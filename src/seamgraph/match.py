"""Kind-specific anchor matching: build seams and detect orphans.

Each SeamKind has a dedicated matcher that knows how to compare use-side
anchors to definition-side anchors. The matchers produce Seam edges
(with optional ambiguity notes) and Orphan records for unmatched endpoints.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Anchor, AnchorKind, Orphan, Seam, SeamKind
from .routes import RoutePattern, match_route

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _exact_match(
    uses: list[Anchor],
    defs: list[Anchor],
    seam_kind: SeamKind,
    use_unmatched_severity: str | None = None,
) -> tuple[list[Seam], list[Orphan]]:
    """Match anchors on exact key equality. Handles N:M with ambiguity notes.

    ``use_unmatched_severity``: severity for use-side orphans. Defaults to the
    evidence-gated policy: "warn" only when the repo has at least one
    definition-side anchor of this kind (so we know the definition store is
    visible to us), otherwise "info".
    """
    defs_by_key: dict[str, list[Anchor]] = defaultdict(list)
    for d in defs:
        defs_by_key[d.key].append(d)

    if use_unmatched_severity is None:
        use_unmatched_severity = "warn" if defs else "info"

    used_keys: set[str] = set()
    seams: list[Seam] = []
    orphans: list[Orphan] = []

    for u in uses:
        candidates = defs_by_key.get(u.key)
        if not candidates:
            orphans.append(Orphan(u, f"{seam_kind.value}-use-unmatched", use_unmatched_severity))
            continue
        used_keys.add(u.key)
        note = f"ambiguous ({len(candidates)} definitions)" if len(candidates) > 1 else ""
        for d in candidates:
            seams.append(Seam(seam_kind, u.key, u, d, note=note))

    for d in defs:
        if d.key not in used_keys:
            orphans.append(Orphan(d, f"{seam_kind.value}-def-unused", "info"))

    return seams, orphans


# ---------------------------------------------------------------------------
# Env matcher
# ---------------------------------------------------------------------------


def match_env(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    reads = [a for a in anchors if a.kind is AnchorKind.ENV_READ]
    defs = [a for a in anchors if a.kind is AnchorKind.ENV_DEF]
    # env reads with no in-repo definition are "info", never "warn": variables
    # legitimately come from the deployment environment, not the repo
    return _exact_match(reads, defs, SeamKind.ENV, use_unmatched_severity="info")


# ---------------------------------------------------------------------------
# Route matcher
# ---------------------------------------------------------------------------


def match_routes(
    anchors: list[Anchor],
    strip_prefixes: tuple[str, ...] = (),
) -> tuple[list[Seam], list[Orphan]]:
    """Match route calls against route definitions using path-template normalization."""
    calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
    defs = [a for a in anchors if a.kind is AnchorKind.ROUTE_DEF]
    seams: list[Seam] = []
    orphans: list[Orphan] = []

    # first literal segment of every definition ("api", "v2", ...): an
    # unmatched call only warns when the repo defines routes in the same
    # family — a call to a service the repo doesn't implement is not a defect
    def_families = {
        seg for d in defs for seg in d.key.strip("/").split("/")[:1] if seg not in ("*", "**")
    }

    matched_call_keys: set[int] = set()

    for call in calls:
        call_pattern = RoutePattern(tuple(call.key.strip("/").split("/")))
        best_score: int | None = None
        best_defs: list[Anchor] = []

        for defn in defs:
            def_pattern = RoutePattern(tuple(defn.key.strip("/").split("/")))
            allow_prefix = defn.maybe_prefixed
            score = match_route(call_pattern, def_pattern, allow_def_prefix=allow_prefix)
            if score is None:
                continue
            # method compatibility: if both specify, they must overlap
            if call.method and defn.method:
                call_methods = set(call.method.split(","))
                def_methods = set(defn.method.split(","))
                if not call_methods & def_methods:
                    continue
            if best_score is None or score > best_score:
                best_score = score
                best_defs = [defn]
            elif score == best_score:
                best_defs.append(defn)

        if not best_defs:
            family = call.key.strip("/").split("/")[:1]
            severity = "warn" if family and family[0] in def_families else "info"
            orphans.append(Orphan(call, "route-call-unmatched", severity))
        else:
            matched_call_keys.add(id(call))
            note = f"ambiguous ({len(best_defs)} definitions)" if len(best_defs) > 1 else ""
            for d in best_defs:
                seams.append(Seam(SeamKind.ROUTE, call.key, call, d, note=note))

    # orphan definitions: route defs not matched by any call
    matched_def_ids = {id(s.definition) for s in seams}
    for d in defs:
        if id(d) not in matched_def_ids:
            orphans.append(Orphan(d, "route-def-uncalled", "info"))

    return seams, orphans


# ---------------------------------------------------------------------------
# Template matcher
# ---------------------------------------------------------------------------


def match_templates(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    """Match template references against template files on disk.

    Template keys may be relative paths. We do suffix matching:
    ``"checkout.html"`` matches ``"shop/checkout.html"`` on disk.
    """
    refs = [a for a in anchors if a.kind is AnchorKind.TEMPLATE_REF]
    files = [a for a in anchors if a.kind is AnchorKind.TEMPLATE_FILE]

    files_by_key: dict[str, list[Anchor]] = defaultdict(list)
    files_by_basename: dict[str, list[Anchor]] = defaultdict(list)
    for f in files:
        files_by_key[f.key].append(f)
        basename = f.key.rsplit("/", 1)[-1]
        files_by_basename[basename].append(f)

    seams: list[Seam] = []
    orphans: list[Orphan] = []
    matched_file_keys: set[str] = set()

    for ref in refs:
        # try exact match first
        candidates = files_by_key.get(ref.key)
        if candidates is None:
            # try suffix match: "checkout.html" matches "shop/checkout.html"
            candidates = [f for f in files if f.key.endswith("/" + ref.key) or f.key == ref.key]
        if not candidates:
            # try basename match
            basename = ref.key.rsplit("/", 1)[-1]
            candidates = files_by_basename.get(basename)

        if not candidates:
            orphans.append(Orphan(ref, "template-ref-missing", "warn" if files else "info"))
            continue

        note = f"ambiguous ({len(candidates)} files)" if len(candidates) > 1 else ""
        for f in candidates:
            matched_file_keys.add(f.key)
            seams.append(Seam(SeamKind.TEMPLATE, ref.key, ref, f, note=note))

    # template files never referenced
    for f in files:
        if f.key not in matched_file_keys:
            # base templates and layouts are commonly only extended, which we catch.
            # Only warn for truly unreferenced templates.
            orphans.append(Orphan(f, "template-file-unreferenced", "info"))

    return seams, orphans


# ---------------------------------------------------------------------------
# URL-name matcher
# ---------------------------------------------------------------------------


#: framework-provided endpoint/url names that never have an in-repo definition
_BUILTIN_URLNAMES = frozenset({"static", "media", "admin:index"})


def match_urlnames(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    refs = [
        a for a in anchors if a.kind is AnchorKind.URLNAME_REF and a.key not in _BUILTIN_URLNAMES
    ]
    defs = [a for a in anchors if a.kind is AnchorKind.URLNAME_DEF]
    return _exact_match(refs, defs, SeamKind.URLNAME)


# ---------------------------------------------------------------------------
# Task matcher
# ---------------------------------------------------------------------------


def match_tasks(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    """Match Celery task calls to definitions.

    Task names are dotted module paths. We try exact match first, then
    suffix match (``module.function`` matches ``pkg.module.function``).
    """
    calls = [a for a in anchors if a.kind is AnchorKind.TASK_CALL]
    defs = [a for a in anchors if a.kind is AnchorKind.TASK_DEF]

    defs_by_key: dict[str, list[Anchor]] = defaultdict(list)
    for d in defs:
        defs_by_key[d.key].append(d)

    seams: list[Seam] = []
    orphans: list[Orphan] = []
    matched_def_keys: set[str] = set()

    for c in calls:
        candidates = defs_by_key.get(c.key)
        if not candidates:
            # suffix match
            candidates = [
                d for d in defs if d.key.endswith("." + c.key) or c.key.endswith("." + d.key)
            ]
        if not candidates:
            orphans.append(Orphan(c, "task-call-unmatched", "warn" if defs else "info"))
            continue
        matched_def_keys.update(d.key for d in candidates)
        note = f"ambiguous ({len(candidates)} definitions)" if len(candidates) > 1 else ""
        for d in candidates:
            seams.append(Seam(SeamKind.TASK, c.key, c, d, note=note))

    for d in defs:
        if d.key not in matched_def_keys:
            orphans.append(Orphan(d, "task-def-uncalled", "info"))

    return seams, orphans


# ---------------------------------------------------------------------------
# Script matcher
# ---------------------------------------------------------------------------


def match_scripts(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    """Match script uses to definitions *within the same script type*.

    ``make build`` must only match a Makefile target, ``npm run build`` only a
    package.json script, and a bare command token only a pyproject entry point.
    Unmatched bare tokens are dropped silently (every CLI tool on a runner
    would otherwise be an orphan); unmatched ``make X`` / ``npm run X`` are
    real references into a definition store and warrant a warning when that
    store exists in the repo.
    """
    uses = [a for a in anchors if a.kind is AnchorKind.SCRIPT_USE]
    defs = [a for a in anchors if a.kind is AnchorKind.SCRIPT_DEF]

    defs_by_type_key: dict[tuple[str, str], list[Anchor]] = defaultdict(list)
    def_types: set[str] = set()
    for d in defs:
        stype = d.extra.get("script_type", "")
        defs_by_type_key[(stype, d.key)].append(d)
        def_types.add(stype)

    seams: list[Seam] = []
    orphans: list[Orphan] = []
    matched_def_ids: set[int] = set()

    for u in uses:
        stype = u.extra.get("script_type", "")
        candidates = defs_by_type_key.get((stype, u.key))
        if candidates:
            note = f"ambiguous ({len(candidates)} definitions)" if len(candidates) > 1 else ""
            for d in candidates:
                matched_def_ids.add(id(d))
                seams.append(Seam(SeamKind.SCRIPT, u.key, u, d, note=note))
        elif stype in ("makefile", "package.json"):
            severity = "warn" if stype in def_types else "info"
            orphans.append(Orphan(u, "script-use-unmatched", severity))
        # bare-token (pyproject-type) uses that match nothing: dropped

    for d in defs:
        if id(d) not in matched_def_ids:
            orphans.append(Orphan(d, "script-def-unused", "info"))

    return seams, orphans


# ---------------------------------------------------------------------------
# Settings matcher
# ---------------------------------------------------------------------------


def match_settings(anchors: list[Anchor]) -> tuple[list[Seam], list[Orphan]]:
    reads = [a for a in anchors if a.kind is AnchorKind.SETTING_READ]
    defs = [a for a in anchors if a.kind is AnchorKind.SETTING_DEF]
    # reads of Django's own default settings (never overridden in settings.py)
    # are legitimate, so unmatched reads are informational only
    return _exact_match(reads, defs, SeamKind.SETTING, use_unmatched_severity="info")


# ---------------------------------------------------------------------------
# Combined matcher
# ---------------------------------------------------------------------------


def match_all(
    anchors: list[Anchor],
    strip_prefixes: tuple[str, ...] = (),
) -> tuple[list[Seam], list[Orphan]]:
    """Run all kind-specific matchers and return combined results."""
    all_seams: list[Seam] = []
    all_orphans: list[Orphan] = []

    for matcher in (
        match_env,
        lambda a: match_routes(a, strip_prefixes=strip_prefixes),
        match_templates,
        match_urlnames,
        match_tasks,
        match_scripts,
        match_settings,
    ):
        seams, orphans = matcher(anchors)
        all_seams.extend(seams)
        all_orphans.extend(orphans)

    return all_seams, all_orphans
