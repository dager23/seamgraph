"""Co-change mining from ``git log``.

Mines file-pair co-occurrence across commits (how often two files change
together), yielding support (absolute count) and confidence: the fraction of
the less-frequently-changed file's commits that also touched the other file
(``support / min(changes_a, changes_b)`` — directional confidence, as in the
change-coupling literature). Jaccard was rejected: hub files with huge change
counts (settings.py) would drown genuine coupling in the union term.

Usage:
- *Corroboration*: anchored seams with co-change support above threshold get
  upgraded from ``anchored`` to ``corroborated``.
- *Discovery*: file pairs with high co-change but no static seam are surfaced
  as ``Discovery`` objects (statistical-only edges).
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CochangePair:
    """A pair of files that co-changed."""

    path_a: str  # lexicographically first
    path_b: str
    support: int  # number of commits both appeared in
    confidence: float  # directional: support / min(changes_a, changes_b)


def mine_cochange(
    root: Path,
    max_commits: int = 2000,
    max_files_per_commit: int = 40,
    paths: set[str] | None = None,
) -> list[CochangePair]:
    """Mine co-change pairs from git history.

    ``paths``: if provided, only consider pairs where both files are in this set
    (the set of files with anchors, typically).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--name-only",
                "--pretty=format:",
                f"-{max_commits}",
                "--no-renames",
                "--diff-filter=ACMR",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    # Parse git log output: commits are separated by blank lines
    commits: list[list[str]] = []
    current: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                commits.append(current)
                current = []
        else:
            current.append(stripped)
    if current:
        commits.append(current)

    # Count file occurrences and co-occurrences
    file_count: dict[str, int] = defaultdict(int)
    pair_count: dict[tuple[str, str], int] = defaultdict(int)

    for files in commits:
        if len(files) > max_files_per_commit:
            continue  # skip bulk commits (merges, reformats, etc.)

        # filter to relevant files if path set provided
        relevant = sorted(set(files))
        if paths is not None:
            relevant = [f for f in relevant if f in paths]

        for f in relevant:
            file_count[f] += 1

        # all pairs (sorted to canonicalize)
        for i in range(len(relevant)):
            for j in range(i + 1, len(relevant)):
                a, b = relevant[i], relevant[j]
                if a > b:
                    a, b = b, a
                pair_count[(a, b)] += 1

    # Build results with directional confidence
    results: list[CochangePair] = []
    for (a, b), support in sorted(pair_count.items()):
        smaller = min(file_count[a], file_count[b])
        confidence = support / smaller if smaller > 0 else 0.0
        results.append(CochangePair(a, b, support, round(confidence, 4)))

    return results


def corroborate_seams(
    seam_file_pairs: set[tuple[str, str]],
    cochange: list[CochangePair],
    min_support: int = 3,
    min_confidence: float = 0.25,
) -> dict[tuple[str, str], CochangePair]:
    """Find co-change evidence for static seam file pairs.

    Returns a dict mapping (path_a, path_b) → CochangePair for pairs that
    pass the corroboration threshold.
    """
    cochange_index: dict[tuple[str, str], CochangePair] = {}
    for cc in cochange:
        cochange_index[(cc.path_a, cc.path_b)] = cc

    result: dict[tuple[str, str], CochangePair] = {}
    for pair in seam_file_pairs:
        a, b = pair
        if a > b:
            a, b = b, a
        found = cochange_index.get((a, b))
        if found and found.support >= min_support and found.confidence >= min_confidence:
            result[(a, b)] = found

    return result


_ARTIFACT_CLASSES: dict[str, str] = {
    ".py": "python",
    ".js": "js",
    ".jsx": "js",
    ".ts": "js",
    ".tsx": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".vue": "js",
    ".svelte": "js",
    ".yml": "config",
    ".yaml": "config",
    ".toml": "config",
    ".json": "config",
    ".ini": "config",
    ".cfg": "config",
    ".env": "config",
    ".html": "template",
    ".htm": "template",
    ".jinja": "template",
    ".jinja2": "template",
    ".j2": "template",
}


def artifact_class(path: str) -> str:
    base = path.rsplit("/", 1)[-1].lower()
    if base == "dockerfile" or base.startswith((".env", "dockerfile.")) or base == "makefile":
        return "config"
    ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    return _ARTIFACT_CLASSES.get(ext, "other")


def discover_statistical(
    cochange: list[CochangePair],
    seam_file_pairs: set[tuple[str, str]],
    min_support: int = 5,
    min_confidence: float = 0.5,
) -> list[CochangePair]:
    """Find high-cochange file pairs that have NO static seam between them.

    These are the statistical-only discoveries — files that suspiciously
    co-change but have no anchored connection we can see. Only *cross-artifact*
    pairs are surfaced: same-class pairs (two Python files, two JS files) are
    ordinary import coupling, visible to LSP/code-graph tools, and would drown
    the signal seamgraph exists to provide.
    """
    # Normalize seam pairs
    normalized_seam_pairs: set[tuple[str, str]] = set()
    for a, b in seam_file_pairs:
        if a > b:
            a, b = b, a
        normalized_seam_pairs.add((a, b))

    return [
        cc
        for cc in cochange
        if cc.support >= min_support
        and cc.confidence >= min_confidence
        and (cc.path_a, cc.path_b) not in normalized_seam_pairs
        and artifact_class(cc.path_a) != artifact_class(cc.path_b)
    ]
