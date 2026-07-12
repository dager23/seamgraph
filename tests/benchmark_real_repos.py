"""Benchmark seamgraph against real-world OSS repositories.

This script shallow-clones popular full-stack repos and runs seamgraph
extraction + matching on each, reporting:
- Anchors by kind
- Seams by kind and grade
- Orphans by problem type
- Extraction time

Usage:
    python -m tests.benchmark_real_repos [--keep]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seamgraph.config import Config
from seamgraph.extract.configs import extract_config_file
from seamgraph.extract.js_ts import extract_js_ts
from seamgraph.extract.python_code import PyFileFacts, extract_python, resolve_routes
from seamgraph.extract.templates import extract_template_file, extract_template_refs
from seamgraph.fswalk import list_files, read_text
from seamgraph.match import match_all
from seamgraph.models import Anchor

# 20 popular OSS full-stack repos covering diverse frameworks
# (name, github org/repo, description)
_REPO_ROWS: list[tuple[str, str, str]] = [
    (
        "fastapi-full-stack",
        "fastapi/full-stack-fastapi-template",
        "FastAPI+React official template",
    ),
    ("saleor", "saleor/saleor", "Django e-commerce platform"),
    ("saleor-dashboard", "saleor/saleor-dashboard", "React dashboard for Saleor"),
    ("label-studio", "HumanSignal/label-studio", "Django+React data labeling"),
    ("redash", "getredash/redash", "Flask+React dashboards"),
    ("plane", "makeplane/plane", "Django+Next.js project management"),
    ("cal.com", "calcom/cal.com", "Next.js scheduling platform"),
    ("immich", "immich-app/immich", "TS+Svelte photo management"),
    ("listmonk", "knadh/listmonk", "Go+Vue newsletter manager"),
    ("maybe", "maybe-finance/maybe", "Ruby+React finance app"),
    ("documenso", "documenso/documenso", "Next.js document signing"),
    ("rallly", "lukevella/rallly", "Next.js scheduling polls"),
    ("formbricks", "formbricks/formbricks", "Next.js survey platform"),
    ("papermark", "mfts/papermark", "Next.js document sharing"),
    ("dify", "langgenius/dify", "Flask+React LLM app platform"),
    ("open-webui", "open-webui/open-webui", "Svelte+Python chat UI"),
    ("lobe-chat", "lobehub/lobe-chat", "Next.js chat application"),
    ("twenty", "twentyhq/twenty", "TS+React CRM"),
    ("infisical", "Infisical/infisical", "Next.js secret management"),
    ("hoppscotch", "hoppscotch/hoppscotch", "Vue.js API development"),
]

REPOS: list[dict[str, str]] = [
    {"name": name, "url": f"https://github.com/{slug}", "desc": desc}
    for name, slug, desc in _REPO_ROWS
]


@dataclass
class BenchmarkResult:
    name: str
    desc: str
    files_scanned: int
    time_seconds: float
    anchors_by_kind: dict[str, int]
    seams_by_kind: dict[str, int]
    seams_by_grade: dict[str, int]
    orphans_by_problem: dict[str, int]
    total_anchors: int
    total_seams: int
    total_orphans: int
    error: str | None = None


def clone_repo(repo: dict[str, str], bench_dir: Path) -> Path | None:
    """Shallow-clone a repo. Returns path or None on failure."""
    dest = bench_dir / repo["name"]
    if dest.exists():
        return dest
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", repo["url"], str(dest)],
            capture_output=True,
            timeout=120,
            check=True,
        )
        return dest
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  X Clone failed for {repo['name']}: {e}")
        return None


def benchmark_repo(root: Path, name: str, desc: str) -> BenchmarkResult:
    """Run seamgraph extraction and matching on a cloned repo."""
    config = Config()
    t0 = time.monotonic()

    try:
        files = list_files(root, exclude=config.exclude)

        all_anchors: list[Anchor] = []
        py_facts: dict[str, PyFileFacts] = {}

        for rel in files:
            text = read_text(root, rel)
            if text is None:
                continue
            if rel.endswith(".py"):
                # resolve_routes() returns every Python anchor; adding
                # facts.anchors here as well would double-count them
                py_facts[rel] = extract_python(rel, text)
            else:
                all_anchors.extend(extract_js_ts(rel, text))
                all_anchors.extend(extract_config_file(rel, text))
                all_anchors.extend(extract_template_file(rel))
                all_anchors.extend(extract_template_refs(rel, text))

        # Resolve cross-file routes
        all_anchors.extend(resolve_routes(py_facts))

        # Match
        seams, orphans = match_all(all_anchors)

        elapsed = time.monotonic() - t0

        # Aggregate stats
        anchors_by_kind: dict[str, int] = {}
        for a in all_anchors:
            anchors_by_kind[a.kind.value] = anchors_by_kind.get(a.kind.value, 0) + 1

        seams_by_kind: dict[str, int] = {}
        seams_by_grade: dict[str, int] = {}
        for s in seams:
            seams_by_kind[s.kind.value] = seams_by_kind.get(s.kind.value, 0) + 1
            seams_by_grade[s.grade] = seams_by_grade.get(s.grade, 0) + 1

        orphans_by_problem: dict[str, int] = {}
        for o in orphans:
            orphans_by_problem[o.problem] = orphans_by_problem.get(o.problem, 0) + 1

        return BenchmarkResult(
            name=name,
            desc=desc,
            files_scanned=len(files),
            time_seconds=round(elapsed, 2),
            anchors_by_kind=anchors_by_kind,
            seams_by_kind=seams_by_kind,
            seams_by_grade=seams_by_grade,
            orphans_by_problem=orphans_by_problem,
            total_anchors=len(all_anchors),
            total_seams=len(seams),
            total_orphans=len(orphans),
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        return BenchmarkResult(
            name=name, desc=desc, files_scanned=0, time_seconds=round(elapsed, 2),
            anchors_by_kind={}, seams_by_kind={}, seams_by_grade={},
            orphans_by_problem={}, total_anchors=0, total_seams=0, total_orphans=0,
            error=str(e),
        )


def run_benchmarks(keep: bool = False) -> list[BenchmarkResult]:
    bench_dir = Path(__file__).parent.parent / "bench-repos"
    bench_dir.mkdir(exist_ok=True)
    results: list[BenchmarkResult] = []

    for repo in REPOS:
        print(f"\n{'='*60}")
        print(f"  {repo['name']}: {repo['desc']}")
        print(f"{'='*60}")

        root = clone_repo(repo, bench_dir)
        if root is None:
            results.append(BenchmarkResult(
                name=repo["name"], desc=repo["desc"], files_scanned=0,
                time_seconds=0, anchors_by_kind={}, seams_by_kind={},
                seams_by_grade={}, orphans_by_problem={},
                total_anchors=0, total_seams=0, total_orphans=0,
                error="clone failed",
            ))
            continue

        result = benchmark_repo(root, repo["name"], repo["desc"])
        results.append(result)

        if result.error:
            print(f"  X Error: {result.error}")
        else:
            print(f"  Files: {result.files_scanned}")
            print(f"  Anchors: {result.total_anchors}")
            print(f"  Seams: {result.total_seams}")
            print(f"  Orphans: {result.total_orphans}")
            print(f"  Time: {result.time_seconds}s")
            if result.anchors_by_kind:
                print(f"  Anchors by kind: {result.anchors_by_kind}")
            if result.seams_by_kind:
                print(f"  Seams by kind: {result.seams_by_kind}")

    if not keep and bench_dir.exists():
        print(f"\nCleaning up {bench_dir}...")
        shutil.rmtree(bench_dir, ignore_errors=True)

    return results


def write_report(results: list[BenchmarkResult], out_path: Path) -> None:
    """Write a markdown benchmark report."""
    lines = [
        "# seamgraph Benchmark Results",
        "",
        f"Tested against {len(results)} real-world OSS repositories.",
        "",
        "## Summary Table",
        "",
        "| Repo | Description | Files | Anchors | Seams | Orphans | Time (s) |",
        "|------|-------------|------:|--------:|------:|--------:|---------:|",
    ]
    totals = {"files": 0, "anchors": 0, "seams": 0, "orphans": 0}
    for r in results:
        if r.error:
            lines.append(f"| {r.name} | {r.desc} | — | — | — | — | X {r.error} |")
        else:
            lines.append(
                f"| {r.name} | {r.desc} | {r.files_scanned:,} | {r.total_anchors:,} | "
                f"{r.total_seams:,} | {r.total_orphans:,} | {r.time_seconds} |"
            )
            totals["files"] += r.files_scanned
            totals["anchors"] += r.total_anchors
            totals["seams"] += r.total_seams
            totals["orphans"] += r.total_orphans

    lines.extend([
        f"| **Total** | | **{totals['files']:,}** | **{totals['anchors']:,}** | "
        f"**{totals['seams']:,}** | **{totals['orphans']:,}** | |",
        "",
        "## Seams by Kind (aggregated)",
        "",
    ])

    kind_totals: dict[str, int] = {}
    for r in results:
        for k, v in r.seams_by_kind.items():
            kind_totals[k] = kind_totals.get(k, 0) + v

    if kind_totals:
        lines.append("| Kind | Count |")
        lines.append("|------|------:|")
        for k, v in sorted(kind_totals.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v:,} |")
    else:
        lines.append("No seams found across any repositories.")

    lines.extend(["", "## Anchors by Kind (aggregated)", ""])
    anchor_totals: dict[str, int] = {}
    for r in results:
        for k, v in r.anchors_by_kind.items():
            anchor_totals[k] = anchor_totals.get(k, 0) + v

    if anchor_totals:
        lines.append("| Kind | Count |")
        lines.append("|------|------:|")
        for k, v in sorted(anchor_totals.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v:,} |")

    lines.extend(["", "## Orphans by Problem (aggregated)", ""])
    orphan_totals: dict[str, int] = {}
    for r in results:
        for k, v in r.orphans_by_problem.items():
            orphan_totals[k] = orphan_totals.get(k, 0) + v

    if orphan_totals:
        lines.append("| Problem | Count |")
        lines.append("|---------|------:|")
        for k, v in sorted(orphan_totals.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v:,} |")

    lines.extend(["", "## Per-Repo Details", ""])
    for r in results:
        if r.error:
            continue
        lines.append(f"### {r.name}")
        lines.append(f"*{r.desc}*")
        lines.append("")
        if r.anchors_by_kind:
            pairs = sorted(r.anchors_by_kind.items())
            lines.append("**Anchors:** " + ", ".join(f"{k}={v}" for k, v in pairs))
        if r.seams_by_kind:
            pairs = sorted(r.seams_by_kind.items())
            lines.append("**Seams:** " + ", ".join(f"{k}={v}" for k, v in pairs))
        if r.seams_by_grade:
            pairs = sorted(r.seams_by_grade.items())
            lines.append("**Grades:** " + ", ".join(f"{k}={v}" for k, v in pairs))
        if r.orphans_by_problem:
            pairs = sorted(r.orphans_by_problem.items())
            lines.append("**Orphans:** " + ", ".join(f"{k}={v}" for k, v in pairs))
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {out_path}")


def main() -> None:
    keep = "--keep" in sys.argv
    results = run_benchmarks(keep=keep)

    # Write JSON results
    json_path = Path(__file__).parent.parent / "BENCHMARKS.json"
    with open(json_path, "w") as f:
        json.dump(
            [
                {
                    "name": r.name,
                    "desc": r.desc,
                    "files_scanned": r.files_scanned,
                    "time_seconds": r.time_seconds,
                    "total_anchors": r.total_anchors,
                    "total_seams": r.total_seams,
                    "total_orphans": r.total_orphans,
                    "anchors_by_kind": r.anchors_by_kind,
                    "seams_by_kind": r.seams_by_kind,
                    "seams_by_grade": r.seams_by_grade,
                    "orphans_by_problem": r.orphans_by_problem,
                    "error": r.error,
                }
                for r in results
            ],
            f,
            indent=2,
        )

    # Write markdown report
    md_path = Path(__file__).parent.parent / "BENCHMARKS.md"
    write_report(results, md_path)


if __name__ == "__main__":
    main()
