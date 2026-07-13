"""Config-artifact extractors: .env files, docker-compose, Dockerfiles,
GitHub Actions workflows, Kubernetes manifests, pyproject/package.json/Makefile
scripts. Only recognized structures are extracted — never generic key scans.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import yaml

from ..models import Anchor, AnchorKind

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_DOCKER_ENV = re.compile(r"^\s*(ENV|ARG)\s+(.+)$", re.IGNORECASE)
_DOCKER_PAIR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:=|\s|$)")
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?!=)")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_env_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return (
        base == ".env"
        or base.startswith(".env.")
        or (base.endswith(".env") and base != ".env")
        or base in (".env.example", ".env.sample", "env.example")
    )


def extract_dotenv(path: str, text: str) -> list[Anchor]:
    anchors = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if m:
            anchors.append(
                Anchor(
                    AnchorKind.ENV_DEF,
                    m.group(1),
                    m.group(1),
                    path,
                    i,
                    "dotenv assignment",
                    {"source": "dotenv"},
                )
            )
    return anchors


def extract_dockerfile(path: str, text: str) -> list[Anchor]:
    anchors = []
    for i, line in enumerate(text.splitlines(), 1):
        m = _DOCKER_ENV.match(line)
        if not m:
            continue
        kind = m.group(1).upper()
        body = m.group(2)
        for pair in _DOCKER_PAIR.finditer(body):
            name = pair.group(1)
            if _ENV_NAME.match(name):
                anchors.append(
                    Anchor(
                        AnchorKind.ENV_DEF,
                        name,
                        name,
                        path,
                        i,
                        f"Dockerfile {kind}",
                        {"source": "dockerfile"},
                    )
                )
            if kind == "ENV" and "=" not in body:
                break  # legacy `ENV KEY value` defines only the first token
    return anchors


def _yaml_load(text: str) -> Any:
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    return docs


class _LineFinder:
    """Best-effort line lookup for a key name inside a YAML/JSON source."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()

    def find(self, token: str, after: int = 0) -> int:
        for i in range(after, len(self.lines)):
            if token in self.lines[i]:
                return i + 1
        return 1


def extract_compose(path: str, text: str) -> list[Anchor]:
    docs = _yaml_load(text)
    if not docs:
        return []
    finder = _LineFinder(text)
    anchors: list[Anchor] = []
    for doc in docs:
        if not isinstance(doc, dict) or "services" not in doc:
            continue
        services = doc.get("services")
        if not isinstance(services, dict):
            continue
        for sname, svc in sorted(services.items()):
            if not isinstance(svc, dict):
                continue
            for section in ("environment", "build"):
                block = svc.get(section)
                if section == "build":
                    block = block.get("args") if isinstance(block, dict) else None
                names: list[str] = []
                if isinstance(block, dict):
                    names = [str(k) for k in block]
                elif isinstance(block, list):
                    for item in block:
                        if isinstance(item, str):
                            names.append(item.split("=", 1)[0])
                for name in names:
                    if _ENV_NAME.match(name):
                        anchors.append(
                            Anchor(
                                AnchorKind.ENV_DEF,
                                name,
                                name,
                                path,
                                finder.find(name),
                                f"docker-compose service '{sname}' {section}",
                                {"source": "compose"},
                            )
                        )
    return anchors


def extract_k8s(path: str, text: str) -> list[Anchor]:
    docs = _yaml_load(text)
    if not docs:
        return []
    finder = _LineFinder(text)
    anchors: list[Anchor] = []
    for doc in docs:
        if not isinstance(doc, dict) or "apiVersion" not in doc or "kind" not in doc:
            continue
        k8s_kind = str(doc.get("kind"))
        if k8s_kind in ("ConfigMap", "Secret"):
            data = doc.get("data") or {}
            if isinstance(data, dict):
                for name in data:
                    if isinstance(name, str) and _ENV_NAME.match(name):
                        anchors.append(
                            Anchor(
                                AnchorKind.ENV_DEF,
                                name,
                                name,
                                path,
                                finder.find(name),
                                f"kubernetes {k8s_kind} data key",
                                {"source": "k8s"},
                            )
                        )
            continue
        for env_entry in _iter_k8s_env(doc):
            name = env_entry.get("name")
            if isinstance(name, str) and _ENV_NAME.match(name):
                anchors.append(
                    Anchor(
                        AnchorKind.ENV_DEF,
                        name,
                        name,
                        path,
                        finder.find(name),
                        f"kubernetes {k8s_kind} container env",
                        {"source": "k8s"},
                    )
                )
    return anchors


def _iter_k8s_env(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        env = node.get("env")
        if isinstance(env, list):
            out.extend(e for e in env if isinstance(e, dict))
        for v in node.values():
            out.extend(_iter_k8s_env(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_iter_k8s_env(v))
    return out


def extract_actions(path: str, text: str) -> list[Anchor]:
    """GitHub Actions workflows: env: keys (defs) and run: script usages."""
    docs = _yaml_load(text)
    if not docs:
        return []
    finder = _LineFinder(text)
    anchors: list[Anchor] = []

    def walk_env(node: Any) -> None:
        if isinstance(node, dict):
            env = node.get("env")
            if isinstance(env, dict):
                for name in env:
                    if isinstance(name, str) and _ENV_NAME.match(name):
                        anchors.append(
                            Anchor(
                                AnchorKind.ENV_DEF,
                                name,
                                name,
                                path,
                                finder.find(name),
                                "workflow env: block",
                                {"source": "actions"},
                            )
                        )
            for v in node.values():
                walk_env(v)
        elif isinstance(node, list):
            for v in node:
                walk_env(v)

    for doc in docs:
        if isinstance(doc, dict) and ("jobs" in doc or "on" in doc or True in doc):
            walk_env(doc)
    anchors.extend(extract_run_lines(path, text))
    return anchors


def extract_run_lines(path: str, text: str) -> list[Anchor]:
    """SCRIPT_USE anchors from workflow run: lines: `make X`, `npm run X`, first tokens."""
    docs = _yaml_load(text)
    if not docs:
        return []
    finder = _LineFinder(text)
    anchors: list[Anchor] = []
    commands: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            run = node.get("run")
            if isinstance(run, str):
                commands.append(run)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for doc in docs:
        walk(doc)
    for cmd in commands:
        for rawline in cmd.splitlines():
            for part in re.split(r"&&|\|\||;", rawline):
                tokens = part.strip().split()
                if not tokens:
                    continue
                use: tuple[str, str] | None = None  # (key, script_type)
                if tokens[0] == "make" and len(tokens) > 1 and not tokens[1].startswith("-"):
                    use = (tokens[1], "makefile")
                elif tokens[0] in ("npm", "pnpm", "yarn"):
                    rest = tokens[1:]
                    if rest and rest[0] == "run" and len(rest) > 1:
                        use = (rest[1], "package.json")
                    elif tokens[0] == "yarn" and rest and not rest[0].startswith("-"):
                        use = (rest[0], "package.json")
                elif re.match(r"^[a-z][\w-]*$", tokens[0]) and tokens[0] not in _SHELL_BUILTINS:
                    use = (tokens[0], "pyproject")
                if use:
                    key, stype = use
                    anchors.append(
                        Anchor(
                            AnchorKind.SCRIPT_USE,
                            key,
                            part.strip()[:120],
                            path,
                            finder.find(key.split()[0]),
                            "workflow run: line",
                            {"script_type": stype},
                        )
                    )
    return anchors


_SHELL_BUILTINS = frozenset(
    """
    cd ls cp mv rm mkdir echo cat set export source sudo apt apt-get brew curl wget git
    python python3 pip pip3 pipx uv uvx node npx bash sh pwsh powershell docker
    docker-compose kubectl helm terraform aws gcloud az chmod chown touch tar unzip
    zip sleep true false test exit trap eval exec printf read wait env find grep sed
    awk sort head tail tee xargs which go cargo rustc dotnet java mvn gradle ruby gem
    bundle php composer twine hatch poetry tox pre-commit coverage codecov if then fi
    for while do done else elif case esac
    """.split()  # noqa: SIM905
)


def extract_pyproject_scripts(path: str, text: str) -> list[Anchor]:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    finder = _LineFinder(text)
    anchors = []
    scripts = data.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict):
        for name in scripts:
            anchors.append(
                Anchor(
                    AnchorKind.SCRIPT_DEF,
                    str(name),
                    str(name),
                    path,
                    finder.find(str(name)),
                    "[project.scripts] entry point",
                    {"script_type": "pyproject"},
                )
            )
    return anchors


def extract_package_json(path: str, text: str) -> list[Anchor]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    finder = _LineFinder(text)
    anchors = []
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        for name in scripts:
            anchors.append(
                Anchor(
                    AnchorKind.SCRIPT_DEF,
                    str(name),
                    str(name),
                    path,
                    finder.find(f'"{name}"'),
                    "package.json scripts entry",
                    {"script_type": "package.json"},
                )
            )
    return anchors


def extract_makefile(path: str, text: str) -> list[Anchor]:
    anchors = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith(("\t", " ", "#", ".")):
            continue
        m = _MAKE_TARGET.match(line)
        if m and m.group(1) not in ("default",):
            anchors.append(
                Anchor(
                    AnchorKind.SCRIPT_DEF,
                    m.group(1),
                    m.group(1),
                    path,
                    i,
                    "Makefile target",
                    {"script_type": "makefile"},
                )
            )
    return anchors


def extract_config_file(path: str, text: str) -> list[Anchor]:
    """Dispatch by filename/location. Returns [] for unrecognized files."""
    base = path.rsplit("/", 1)[-1].lower()
    if _is_env_file(path):
        return extract_dotenv(path, text)
    if base == "dockerfile" or base.startswith("dockerfile."):
        return extract_dockerfile(path, text)
    if base.startswith(("docker-compose", "compose")) and base.endswith((".yml", ".yaml")):
        return extract_compose(path, text)
    if path.startswith(".github/workflows/") and base.endswith((".yml", ".yaml")):
        return extract_actions(path, text)
    if base.endswith((".yml", ".yaml")) and ("apiVersion:" in text and "kind:" in text):
        return extract_k8s(path, text)
    if base == "pyproject.toml":
        return extract_pyproject_scripts(path, text)
    if base == "package.json":
        return extract_package_json(path, text)
    if base in ("makefile", "gnumakefile") or base.endswith(".mk"):
        return extract_makefile(path, text)
    return []
