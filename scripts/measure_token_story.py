"""Measure the token story: grep+read bytes vs one seams_for response.

For each of the busiest env vars and routes in a repo, compare:

- **grep+read cost**: the total size of all files an agent would open after
  grepping for the literal (the standard agent workflow today: Grep -> Read
  each matching file). This is the charitable version — one read per matching
  file, no re-reads.
- **seamgraph cost**: the size of the single ``seams_for --json`` response.

Bytes are converted to approximate tokens at 4 bytes/token. Deterministic:
no LLM calls, no sampling.

Usage:
    python scripts/measure_token_story.py <repo_root> [top_n]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seamgraph.api import seams_for
from seamgraph.fswalk import list_files, read_text
from seamgraph.graph import SeamGraph


def grep_read_bytes(root: Path, needle: str, files: list[str]) -> tuple[int, int]:
    """Total size of files containing the needle (agent Grep -> Read workflow)."""
    total = 0
    hits = 0
    for rel in files:
        text = read_text(root, rel)
        if text and needle in text:
            hits += 1
            total += len(text.encode("utf-8", errors="replace"))
    return total, hits


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    g = SeamGraph(root)
    g.index()
    files = list_files(root, exclude=g.config.exclude)

    # busiest env vars and routes = those with the most seams
    seams = g.query_seams()
    counts: dict[tuple[str, str], int] = {}
    for s in seams:
        if s["kind"] in ("env", "route"):
            key = (s["kind"], s["key"])
            counts[key] = counts.get(key, 0) + 1
    busiest = sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]

    ratios: list[float] = []
    rows: list[dict[str, object]] = []
    for (kind, key), n_seams in busiest:
        needle = key if kind == "env" else key.replace("/*", "/").rstrip("/") or key
        grep_bytes, n_files = grep_read_bytes(root, needle.strip("/") or needle, files)
        response = seams_for(root, ref=key, kind=kind)
        seam_bytes = len(json.dumps(response).encode("utf-8"))
        if grep_bytes == 0 or seam_bytes == 0:
            continue
        ratio = grep_bytes / seam_bytes
        ratios.append(ratio)
        rows.append(
            {
                "kind": kind,
                "key": key,
                "seams": n_seams,
                "files_agent_would_read": n_files,
                "grep_read_tokens": grep_bytes // 4,
                "seams_for_tokens": seam_bytes // 4,
                "reduction": f"{ratio:.1f}x",
            }
        )

    print(json.dumps(rows, indent=2))
    if ratios:
        print(
            f"\nmedian reduction: {statistics.median(ratios):.1f}x "
            f"(n={len(ratios)}, min={min(ratios):.1f}x, max={max(ratios):.1f}x)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
