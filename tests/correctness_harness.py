"""Real-world correctness harness.

Unit tests only prove the tool handles cases its author already imagined.
This harness runs seamgraph against mature third-party repositories and, for
each one, *seeds scenarios from facts taken out of that repository itself*:

- **True positive (env)** - read an environment variable the repo really
  defines, from a new file. seamgraph must link the read to the real
  definition.
- **True negative (env)** - read a variable that provably appears nowhere in
  the repo. seamgraph must not invent a definition for it.
- **True positive (route)** - call an HTTP route the repo really defines.
  seamgraph must link the call to the real handler.
- **True negative (route)** - call a path that provably matches no handler.
  seamgraph must not fabricate a seam for it.

Every CLI entry point is also run against each repo to confirm it neither
crashes nor emits malformed JSON.

Usage:
    python tests/correctness_harness.py [--repos DIR] [--only NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seamgraph.config import Config
from seamgraph.extract.configs import extract_config_file
from seamgraph.extract.file_routes import extract_file_routes
from seamgraph.extract.js_ts import extract_js_ts
from seamgraph.extract.python_code import extract_python, resolve_routes
from seamgraph.extract.templates import (
    extract_template_file,
    extract_template_refs,
)
from seamgraph.fswalk import list_files, read_text
from seamgraph.match import match_all
from seamgraph.models import Anchor, AnchorKind, SeamKind

PROBE_DIR = "seamgraph_probe"
ABSENT_VAR = "SEAMGRAPH_PROBE_VAR_THAT_DOES_NOT_EXIST"
ABSENT_ROUTE = "/seamgraph-probe/definitely-not-a-route/xyzzy"
CLI_COMMANDS = [
    ["index"],
    ["map", "--json"],
    ["env", "--json"],
    ["routes", "--json"],
    ["check", "--json"],
    ["for", "PATH", "--json"],
    ["impact", "README.md", "--json"],
]


@dataclass
class RepoResult:
    name: str
    files: int = 0
    anchors: int = 0
    seams: int = 0
    checks: dict[str, str] = field(default_factory=dict)
    crashes: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.crashes) or any(v.startswith("FAIL") for v in self.checks.values())


def extract_all(root: Path) -> list[Anchor]:
    anchors: list[Anchor] = []
    py: dict[str, object] = {}
    for rel in list_files(root, exclude=Config().exclude):
        text = read_text(root, rel)
        if text is None:
            continue
        if rel.endswith(".py"):
            py[rel] = extract_python(rel, text)
        else:
            anchors += extract_js_ts(rel, text)
            anchors += extract_config_file(rel, text)
            anchors += extract_file_routes(rel, text)
            anchors += extract_template_file(rel)
            anchors += extract_template_refs(rel, text)
    anchors += resolve_routes(py)  # type: ignore[arg-type]
    return anchors


def pick_real_env(anchors: list[Anchor]) -> str | None:
    """An env var the repo really defines, preferring dotenv/compose sources."""
    defs = [a for a in anchors if a.kind is AnchorKind.ENV_DEF]
    for source in ("dotenv", "compose", "dockerfile", "k8s", "actions"):
        for a in sorted(defs, key=lambda x: x.key):
            if a.extra.get("source") == source and len(a.key) > 3:
                return a.key
    return sorted(defs, key=lambda x: x.key)[0].key if defs else None


#: Value substituted for a path parameter when probing a parameterized route.
PARAM_VALUE = "4242"


def pick_real_route(anchors: list[Anchor]) -> tuple[str, str] | None:
    """Pick a route the repo really defines, and a URL that must reach it.

    Prefers a fully literal route, where the probe URL is the route itself.
    Falls back to a parameterized one with a concrete value substituted for
    each ``*`` segment, so repos whose routes are all parameterized still get
    a true-positive case instead of being skipped. Returns
    ``(definition_key, probe_url)``.
    """
    defs = [a for a in anchors if a.kind is AnchorKind.ROUTE_DEF]
    usable = [a for a in defs if "**" not in a.key and a.key.count("/") >= 2 and len(a.key) > 5]

    def literal(a: Anchor) -> bool:
        return "*" not in a.key

    # Prefer a route mounted at a known absolute path over a suffix-matchable
    # one (Django/DRF register everything through include(), so on those repos
    # only the last tier exists), and a literal path over a parameterized one.
    tiers = [
        [a for a in usable if literal(a) and not a.maybe_prefixed],
        [a for a in usable if not literal(a) and not a.maybe_prefixed],
        [a for a in usable if literal(a) and a.maybe_prefixed],
        [a for a in usable if not literal(a) and a.maybe_prefixed],
    ]
    for tier in tiers:
        if not tier:
            continue
        key = sorted(tier, key=lambda x: x.key)[0].key
        probe = "/".join(PARAM_VALUE if seg == "*" else seg for seg in key.split("/"))
        return key, probe
    return None


def seed_probes(root: Path, real_env: str | None, probe_url: str | None) -> None:
    d = root / PROBE_DIR
    d.mkdir(exist_ok=True)
    lines = ["import os", "", 'absent = os.environ["' + ABSENT_VAR + '"]']
    if real_env:
        lines.append('present = os.environ["' + real_env + '"]')
    (d / "probe.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    js = ['export const absent = () => fetch("' + ABSENT_ROUTE + '");']
    if probe_url:
        js.append('export const present = () => fetch("' + probe_url + '");')
    (d / "probe.js").write_text("\n".join(js) + "\n", encoding="utf-8")


def run_cli(root: Path, argv: list[str]) -> str | None:
    """Run one CLI command; return an error string on crash or malformed JSON."""
    repo_root = Path(__file__).parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "seamgraph.cli", "--root", str(root), *argv],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(repo_root),
        env=env,
    )
    # `check` and `verify` exit 1 to report findings; that is a result, not a crash.
    if proc.returncode not in (0, 1):
        return f"{' '.join(argv)} exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    if "--json" in argv and proc.stdout.strip():
        try:
            json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            return f"{' '.join(argv)} emitted invalid JSON: {e}"
    return None


def check_repo(root: Path, name: str) -> RepoResult:
    res = RepoResult(name=name)
    base = extract_all(root)
    res.files = len(list_files(root, exclude=Config().exclude))
    real_env = pick_real_env(base)
    picked = pick_real_route(base)
    real_route, probe_url = picked if picked else (None, None)

    seed_probes(root, real_env, probe_url)
    try:
        anchors = extract_all(root)
        seams, orphans = match_all(anchors)
        res.anchors, res.seams = len(anchors), len(seams)
        probe_py = PROBE_DIR + "/probe.py"
        probe_js = PROBE_DIR + "/probe.js"

        # true positive: env read of a variable the repo really defines
        if real_env:
            hit = [
                s
                for s in seams
                if s.kind is SeamKind.ENV and s.key == real_env and s.use.path == probe_py
            ]
            res.checks["TP-env"] = (
                f"PASS ({real_env} -> {hit[0].definition.path})"
                if hit
                else f"FAIL (no seam for real var {real_env})"
            )
        else:
            res.checks["TP-env"] = "SKIP (repo defines no env vars)"

        # true negative: env read of a variable that exists nowhere
        bogus = [s for s in seams if s.key == ABSENT_VAR]
        orph = [o for o in orphans if o.anchor.key == ABSENT_VAR]
        res.checks["TN-env"] = (
            "PASS (no seam invented)"
            if not bogus and orph
            else f"FAIL (seams={len(bogus)} orphans={len(orph)})"
        )

        # true positive: call to a route the repo really defines
        if real_route and probe_url:
            hit = [
                s
                for s in seams
                if s.kind is SeamKind.ROUTE
                and s.use.path == probe_js
                and s.definition.key == real_route
            ]
            note = "" if probe_url == real_route else f" via {probe_url}"
            res.checks["TP-route"] = (
                f"PASS ({real_route}{note} -> {hit[0].definition.path})"
                if hit
                else f"FAIL (no seam for real route {real_route} probed as {probe_url})"
            )
        else:
            res.checks["TP-route"] = "SKIP (repo defines no unambiguous route)"

        # true negative: call to a path that matches no handler
        bogus_r = [s for s in seams if s.use.path == probe_js and ABSENT_ROUTE in s.use.raw]
        orph_r = [o for o in orphans if ABSENT_ROUTE in o.anchor.raw]
        res.checks["TN-route"] = (
            "PASS (no seam invented)"
            if not bogus_r and orph_r
            else f"FAIL (seams={len(bogus_r)} orphans={len(orph_r)})"
        )

        # every CLI entry point runs without crashing
        for argv in CLI_COMMANDS:
            err = run_cli(root, argv)
            if err:
                res.crashes.append(err)
        res.checks["CLI"] = f"PASS ({len(CLI_COMMANDS)} commands)" if not res.crashes else "FAIL"
    finally:
        shutil.rmtree(root / PROBE_DIR, ignore_errors=True)
        shutil.rmtree(root / ".seamgraph", ignore_errors=True)
    return res


def _mark(result: RepoResult, key: str) -> str:
    value = result.checks.get(key, "?")
    return {"P": " ok  ", "F": " FAIL", "S": " skip"}.get(value[0], "  ?  ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default="bench-repos")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    base = Path(args.repos)
    repos = sorted(p for p in base.iterdir() if p.is_dir() and (p / ".git").exists())
    if args.only:
        repos = [p for p in repos if p.name == args.only]

    results: list[RepoResult] = []
    for r in repos:
        print(f"--- {r.name}", flush=True)
        try:
            res = check_repo(r, r.name)
        except Exception as e:  # the harness reports failures, it must not die
            res = RepoResult(name=r.name, crashes=[f"harness error: {type(e).__name__}: {e}"])
        results.append(res)
        for k, v in res.checks.items():
            print(f"      {k:9s} {v}", flush=True)
        for c in res.crashes:
            print(f"      CRASH   {c}", flush=True)

    print("\n" + "=" * 78)
    print(
        f"{'repo':22s} {'files':>6s} {'anchors':>8s} {'seams':>7s}  TP-env TN-env TP-rt  TN-rt  CLI"
    )
    ok = True
    for r in results:
        print(
            f"{r.name:22s} {r.files:6d} {r.anchors:8d} {r.seams:7d}  "
            f"{_mark(r, 'TP-env')} {_mark(r, 'TN-env')} {_mark(r, 'TP-route')} "
            f"{_mark(r, 'TN-route')} {_mark(r, 'CLI')}"
        )
        ok &= not r.failed
    print("=" * 78)
    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
