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

from seamgraph.api import DANGLING_PROBLEMS
from seamgraph.cochange import corroborate_seams, discover_statistical, mine_cochange
from seamgraph.config import Config
from seamgraph.extract.configs import extract_config_file
from seamgraph.extract.file_routes import extract_file_routes
from seamgraph.extract.js_ts import extract_js_ts
from seamgraph.extract.python_code import PyFileFacts, extract_python, resolve_routes
from seamgraph.extract.templates import extract_template_file, extract_template_refs
from seamgraph.fswalk import list_files, read_text
from seamgraph.match import match_all
from seamgraph.models import Anchor, Seam

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
    total_discoveries: int = 0
    warnings: int = 0
    infos_dangling: int = 0
    error: str | None = None


def clone_repo(repo: dict[str, str], bench_dir: Path) -> Path | None:
    """Clone a repo with 300 commits of history but no historical blobs.

    ``--filter=blob:none`` keeps the clone small while ``git log --name-only``
    (all the co-change miner needs) still works over the 300-commit window.
    """
    dest = bench_dir / repo["name"]
    if dest.exists():
        return dest
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=300",
                "--single-branch",
                "--filter=blob:none",
                repo["url"],
                str(dest),
            ],
            capture_output=True,
            timeout=600,
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
                all_anchors.extend(extract_file_routes(rel, text))
                all_anchors.extend(extract_template_file(rel))
                all_anchors.extend(extract_template_refs(rel, text))

        # Resolve cross-file routes
        all_anchors.extend(resolve_routes(py_facts))

        # Match
        seams, orphans = match_all(all_anchors)

        # Co-change grading over the cloned history window
        anchor_paths = {a.path for a in all_anchors}
        cochange = mine_cochange(
            root,
            max_commits=config.max_commits,
            max_files_per_commit=config.max_files_per_commit,
            paths=anchor_paths,
        )
        seam_file_pairs = {
            (min(s.use.path, s.definition.path), max(s.use.path, s.definition.path))
            for s in seams
            if s.use.path != s.definition.path
        }
        corroborated = corroborate_seams(
            seam_file_pairs,
            cochange,
            min_support=config.corroborate_support,
            min_confidence=config.corroborate_confidence,
        )
        graded: list[Seam] = []
        for s in seams:
            pair = (min(s.use.path, s.definition.path), max(s.use.path, s.definition.path))
            if pair in corroborated:
                cc = corroborated[pair]
                graded.append(
                    Seam(
                        s.kind,
                        s.key,
                        s.use,
                        s.definition,
                        grade="corroborated",
                        cochange_support=cc.support,
                        cochange_confidence=cc.confidence,
                        note=s.note,
                    )
                )
            else:
                graded.append(s)
        seams = graded
        discoveries = discover_statistical(
            cochange,
            seam_file_pairs,
            min_support=config.discover_support,
            min_confidence=config.discover_confidence,
        )

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
        warn_count = 0
        info_dangling = 0
        for o in orphans:
            orphans_by_problem[o.problem] = orphans_by_problem.get(o.problem, 0) + 1
            if o.severity == "warn":
                warn_count += 1
            elif o.problem in DANGLING_PROBLEMS:
                info_dangling += 1

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
            total_discoveries=len(discoveries),
            warnings=warn_count,
            infos_dangling=info_dangling,
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        return BenchmarkResult(
            name=name,
            desc=desc,
            files_scanned=0,
            time_seconds=round(elapsed, 2),
            anchors_by_kind={},
            seams_by_kind={},
            seams_by_grade={},
            orphans_by_problem={},
            total_anchors=0,
            total_seams=0,
            total_orphans=0,
            error=str(e),
        )


def run_benchmarks(keep: bool = False) -> list[BenchmarkResult]:
    bench_dir = Path(__file__).parent.parent / "bench-repos"
    bench_dir.mkdir(exist_ok=True)
    results: list[BenchmarkResult] = []

    for repo in REPOS:
        print(f"\n{'=' * 60}")
        print(f"  {repo['name']}: {repo['desc']}")
        print(f"{'=' * 60}")

        root = clone_repo(repo, bench_dir)
        if root is None:
            results.append(
                BenchmarkResult(
                    name=repo["name"],
                    desc=repo["desc"],
                    files_scanned=0,
                    time_seconds=0,
                    anchors_by_kind={},
                    seams_by_kind={},
                    seams_by_grade={},
                    orphans_by_problem={},
                    total_anchors=0,
                    total_seams=0,
                    total_orphans=0,
                    error="clone failed",
                )
            )
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
        "## Methodology",
        "",
        "- Each repo is cloned with `--depth=300 --single-branch --filter=blob:none`:",
        "  the working tree plus 300 commits of history (no historical blobs), which",
        "  is all the co-change miner needs.",
        "- *Anchors* are pattern-anchored reference endpoints; *seams* are matched",
        "  edges; *corroborated* seams additionally have co-change support >= 3 with",
        "  directional confidence >= 0.25 in the 300-commit window; *discoveries* are",
        "  cross-artifact file pairs with high co-change but no static seam.",
        "- Numbers are produced by `python tests/benchmark_real_repos.py --keep` and",
        "  are fully deterministic for a given set of clone heads.",
        "- **Warn** counts findings seamgraph is confident about: a reference that",
        "  resolves to nothing in a namespace the repo visibly serves. **Info**",
        "  counts dangling references whose definition side was never extracted, so",
        "  they are reported but do not fail a build without `--strict`.",
        "- Sampled warnings were hand-verified as either genuine dead references",
        "  (papermark's frontend calls `/api/teams/{id}/billing/manage`, which has",
        "  no handler in the repo) or extraction gaps that were fixed and re-run",
        "  before these numbers were published.",
        "",
        "## Summary Table",
        "",
        "| Repo | Description | Files | Anchors | Seams | Corrob. | Warn | Info | Time (s) |",
        "|------|-------------|------:|--------:|------:|--------:|-----:|-----:|---------:|",
    ]
    totals = {
        "files": 0,
        "anchors": 0,
        "seams": 0,
        "corroborated": 0,
        "discoveries": 0,
        "warnings": 0,
        "infos": 0,
    }
    for r in results:
        if r.error:
            lines.append(f"| {r.name} | {r.desc} | — | — | — | — | — | — | X {r.error} |")
        else:
            corroborated = r.seams_by_grade.get("corroborated", 0)
            lines.append(
                f"| {r.name} | {r.desc} | {r.files_scanned:,} | {r.total_anchors:,} | "
                f"{r.total_seams:,} | {corroborated:,} | {r.warnings:,} | "
                f"{r.infos_dangling:,} | {r.time_seconds} |"
            )
            totals["files"] += r.files_scanned
            totals["anchors"] += r.total_anchors
            totals["seams"] += r.total_seams
            totals["corroborated"] += corroborated
            totals["discoveries"] += r.total_discoveries
            totals["warnings"] += r.warnings
            totals["infos"] += r.infos_dangling

    lines.extend(
        [
            f"| **Total** | | **{totals['files']:,}** | **{totals['anchors']:,}** | "
            f"**{totals['seams']:,}** | **{totals['corroborated']:,}** | "
            f"**{totals['warnings']:,}** | **{totals['infos']:,}** | |",
            "",
            "## Seams by Kind (aggregated)",
            "",
        ]
    )

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
                    "total_discoveries": r.total_discoveries,
                    "warnings": r.warnings,
                    "infos_dangling": r.infos_dangling,
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
