"""Core data model: anchors (extracted reference endpoints) and seams (matched edges)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AnchorKind(str, Enum):
    """What a single extracted reference endpoint is."""

    ENV_DEF = "env_def"  # env var defined (.env, compose, Dockerfile ENV, workflow env:, k8s)
    ENV_READ = "env_read"  # env var read (os.environ, process.env, pydantic settings field)
    ROUTE_DEF = "route_def"  # HTTP route handler (FastAPI/Flask/Django/Express)
    ROUTE_CALL = "route_call"  # HTTP call site (fetch/axios/requests/httpx/test clients)
    TEMPLATE_FILE = "template_file"  # a template file on disk
    TEMPLATE_REF = "template_ref"  # render_template("x.html"), {% include %}, {% extends %}
    URLNAME_DEF = "urlname_def"  # Django path(..., name="x")
    URLNAME_REF = "urlname_ref"  # {% url 'x' %}, reverse("x"), redirect("x")
    TASK_DEF = "task_def"  # Celery task (explicit or derivable dotted name)
    TASK_CALL = "task_call"  # send_task("x"), signature("x"), beat schedule entries
    SCRIPT_DEF = "script_def"  # pyproject [project.scripts], package.json scripts, Makefile target
    SCRIPT_USE = "script_use"  # invocation in CI run: lines
    SETTING_DEF = "setting_def"  # UPPER = ... in Django settings module
    SETTING_READ = "setting_read"  # django.conf settings.UPPER


class SeamKind(str, Enum):
    ENV = "env"
    ROUTE = "route"
    TEMPLATE = "template"
    URLNAME = "urlname"
    TASK = "task"
    SCRIPT = "script"
    SETTING = "setting"


#: AnchorKind pairs (use side, definition side) per seam kind.
SEAM_SIDES: dict[SeamKind, tuple[AnchorKind, AnchorKind]] = {
    SeamKind.ENV: (AnchorKind.ENV_READ, AnchorKind.ENV_DEF),
    SeamKind.ROUTE: (AnchorKind.ROUTE_CALL, AnchorKind.ROUTE_DEF),
    SeamKind.TEMPLATE: (AnchorKind.TEMPLATE_REF, AnchorKind.TEMPLATE_FILE),
    SeamKind.URLNAME: (AnchorKind.URLNAME_REF, AnchorKind.URLNAME_DEF),
    SeamKind.TASK: (AnchorKind.TASK_CALL, AnchorKind.TASK_DEF),
    SeamKind.SCRIPT: (AnchorKind.SCRIPT_USE, AnchorKind.SCRIPT_DEF),
    SeamKind.SETTING: (AnchorKind.SETTING_READ, AnchorKind.SETTING_DEF),
}


@dataclass(frozen=True)
class Anchor:
    """One extracted endpoint of a potential seam.

    ``key`` is the normalized match key (env var name, normalized route path,
    template-relative path, url name, task name, script name, setting name).
    ``raw`` preserves the string exactly as written at the site.
    ``detail`` says which anchored pattern produced it (for evidence output).
    ``extra`` carries kind-specific attributes:
      routes: ``method`` (upper or ""), ``maybe_prefixed`` ("1"/absent), ``framework``
      scripts: ``script_type`` (pyproject|package.json|makefile)
      env: ``source`` (dotenv|compose|dockerfile|actions|k8s|pydantic|code)
    """

    kind: AnchorKind
    key: str
    raw: str
    path: str  # repo-relative posix path
    line: int
    detail: str
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def method(self) -> str:
        return self.extra.get("method", "")

    @property
    def maybe_prefixed(self) -> bool:
        return self.extra.get("maybe_prefixed") == "1"

    def location(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Seam:
    """A matched edge between a use-side anchor and a definition-side anchor."""

    kind: SeamKind
    key: str
    use: Anchor
    definition: Anchor
    grade: str = "anchored"  # anchored | corroborated
    cochange_support: int = 0
    cochange_confidence: float = 0.0
    note: str = ""  # e.g. "ambiguous (3 candidates)", "suffix-match (django include)"


@dataclass(frozen=True)
class Orphan:
    """An anchor whose counterpart could not be found."""

    anchor: Anchor
    problem: str  # e.g. "route-call-unmatched", "template-missing", "env-read-undefined"
    severity: str  # "warn" | "info"


@dataclass(frozen=True)
class Discovery:
    """A statistical (co-change-only) file pair with no static seam between them."""

    path_a: str
    path_b: str
    support: int
    confidence: float
