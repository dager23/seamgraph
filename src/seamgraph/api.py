"""Query API for the seam graph.

High-level functions that agents (and the CLI) call. Each returns
JSON-serializable dicts with evidence fields for every claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_config
from .graph import SeamGraph


def _graph(root: Path, auto_index: bool = True) -> SeamGraph:
    """Open the graph for ``root``.

    Query entry points pass ``auto_index=True`` so a first query on a repo that
    was never indexed returns real data instead of an empty graph. ``index()``
    passes False -- it is about to index anyway, and auto-indexing first would
    do the work twice and then report "0 changed" on a first run.
    """
    g = SeamGraph(root, load_config(root))
    if auto_index and not g.db_path.exists():
        g.index()
    return g


def index(root: Path, full: bool = False) -> dict[str, Any]:
    """Index the repository and return stats."""
    return _graph(root, auto_index=False).index(full=full)


def seam_map(root: Path, kind: str | None = None) -> dict[str, Any]:
    """Return a compact map of all seams, optionally filtered by kind."""
    g = _graph(root)
    seams = g.query_seams(kind=kind)
    orphans = g.query_orphans()
    discoveries = g.query_discoveries()
    return {
        "seams": seams,
        "orphans": orphans,
        "discoveries": discoveries,
        "summary": {
            "total_seams": len(seams),
            "total_orphans": len(orphans),
            "total_discoveries": len(discoveries),
            "by_kind": _count_by(seams, "kind"),
            "by_grade": _count_by(seams, "grade"),
        },
    }


def seams_for(
    root: Path,
    ref: str,
    kind: str | None = None,
) -> dict[str, Any]:
    """Return seams matching a reference string (key substring or file path)."""
    g = _graph(root)
    # Try as key substring first
    results = g.query_seams(kind=kind, key=ref)
    if not results:
        # Try as file path
        results = g.query_seams(kind=kind, path=ref)
    return {
        "query": ref,
        "seams": results,
        "count": len(results),
    }


def impact(root: Path, paths: list[str]) -> dict[str, Any]:
    """Given a set of changed files, find all seams that cross the boundary.

    Returns seams where one side is in the change set and the other is not —
    these are the seams an agent should check for breakage.
    """
    g = _graph(root)
    # accept Windows-style separators; the graph stores posix paths
    change_set = {p.replace("\\", "/") for p in paths}
    all_seams = g.query_seams()

    impacted: list[dict[str, Any]] = []
    for s in all_seams:
        use_in = s["use_path"] in change_set
        def_in = s["def_path"] in change_set
        if use_in != def_in:  # exactly one side changed
            s["impact_side"] = "use changed" if use_in else "definition changed"
            impacted.append(s)

    return {
        "changed_files": paths,
        "impacted_seams": impacted,
        "count": len(impacted),
    }


def env_table(root: Path) -> dict[str, Any]:
    """Return a comprehensive env-variable table."""
    g = _graph(root)
    table = g.query_env_table()
    return {"env_vars": table, "count": len(table)}


def route_table(root: Path) -> dict[str, Any]:
    """Return a comprehensive route table."""
    g = _graph(root)
    table = g.query_route_table()
    return {"routes": table, "count": len(table)}


def orphans(root: Path, severity: str | None = None) -> dict[str, Any]:
    """Return orphaned anchors (unmatched endpoints)."""
    g = _graph(root)
    result = g.query_orphans(severity=severity)
    return {
        "orphans": result,
        "count": len(result),
        "by_problem": _count_by(result, "problem"),
    }


#: Dangling-reference problems worth showing even at informational severity.
#: A reference with no resolvable target is actionable; an unused *definition*
#: is not a defect, and env/setting reads legitimately come from outside the
#: repo, so neither class appears here.
DANGLING_PROBLEMS = (
    "route-call-unmatched",
    "template-ref-missing",
    "task-call-unmatched",
    "urlname-use-unmatched",
    "script-use-unmatched",
)


def check(root: Path, strict: bool = False) -> dict[str, Any]:
    """Run a check: index, then report warnings and dangling references.

    ``warnings`` are findings seamgraph is confident about (the repo visibly
    serves the namespace the reference points into). ``infos`` are dangling
    references it cannot be confident about -- usually because the definition
    side of that namespace was never extracted -- so they are reported but do
    not fail the run unless ``strict`` is set.
    """
    g = _graph(root, auto_index=False)
    stats = g.index()
    warns = g.query_orphans(severity="warn")
    infos = [o for o in g.query_orphans(severity="info") if o["problem"] in DANGLING_PROBLEMS]
    failing = len(warns) + (len(infos) if strict else 0)
    return {
        "stats": stats,
        "warnings": warns,
        "warning_count": len(warns),
        "infos": infos,
        "info_count": len(infos),
        "strict": strict,
        "failing_count": failing,
        "ok": failing == 0,
    }


def verify(root: Path, ref: str) -> dict[str, Any]:
    """Verify a single reference: is it connected on both sides?"""
    g = _graph(root)
    seams = g.query_seams(key=ref)
    orphs = g.query_orphans()
    relevant_orphans = [o for o in orphs if ref in o.get("key", "")]
    return {
        "ref": ref,
        "connected": len(seams) > 0,
        "seams": seams,
        "orphans": relevant_orphans,
    }


def _count_by(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = str(item.get(field, "unknown"))
        counts[val] = counts.get(val, 0) + 1
    return counts
