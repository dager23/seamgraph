"""Repository file discovery.

Prefers ``git ls-files`` (tracked + untracked-not-ignored) so results honor
.gitignore; falls back to a filtered os.walk for non-git directories.
All paths are repo-relative posix strings, deterministically sorted.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".seamgraph",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "coverage",
    "htmlcov",
    "vendor",
    "third_party",
}

_MAX_FILE_BYTES = 2_000_000  # skip anything larger (bundles, data dumps)


def _git_list(root: Path) -> list[str] | None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            timeout=60,
            check=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    names: set[str] = set()
    for out in (tracked.stdout, untracked.stdout):
        for raw in out.split(b"\x00"):
            if raw:
                try:
                    names.add(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
    return sorted(names)


def _walk_list(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS)
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for name in sorted(filenames):
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            found.append(rel)
    return found


def list_files(root: Path, exclude: tuple[str, ...] = ()) -> list[str]:
    """List candidate files, repo-relative posix, sorted. ``exclude`` are path prefixes."""
    names = _git_list(root)
    if names is None:
        names = _walk_list(root)
    result: list[str] = []
    for rel in names:
        parts = rel.split("/")
        if any(p in DEFAULT_EXCLUDE_DIRS for p in parts[:-1]):
            continue
        if any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in exclude):
            continue
        full = root / rel
        try:
            if not full.is_file() or full.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        result.append(rel)
    return result


def read_text(root: Path, rel: str) -> str | None:
    """Read a file as UTF-8 (errors replaced); None for undecodable/binary-ish files."""
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")
