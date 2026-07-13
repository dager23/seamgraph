"""Configuration: read [tool.seamgraph] from pyproject.toml or seamgraph.toml."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class Config:
    #: path prefixes to skip entirely
    exclude: tuple[str, ...] = ()
    #: URL prefixes stripped from frontend call URLs before matching,
    #: e.g. ["http://localhost:8000", "/backend"]
    strip_url_prefixes: tuple[str, ...] = ()
    #: co-change mining bounds
    max_commits: int = 2000
    max_files_per_commit: int = 40
    #: grading thresholds
    corroborate_support: int = 3
    corroborate_confidence: float = 0.25
    #: statistical discovery thresholds
    discover_support: int = 5
    discover_confidence: float = 0.5


def _coerce(cfg: Config, data: dict[str, Any]) -> Config:
    for key in (
        "max_commits",
        "max_files_per_commit",
        "corroborate_support",
        "discover_support",
    ):
        val = data.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            setattr(cfg, key, val)
    for key in ("corroborate_confidence", "discover_confidence"):
        val = data.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            setattr(cfg, key, float(val))
    for key, attr in (("exclude", "exclude"), ("strip_url_prefixes", "strip_url_prefixes")):
        val = data.get(key)
        if isinstance(val, list) and all(isinstance(v, str) for v in val):
            setattr(cfg, attr, tuple(val))
    return cfg


def load_config(root: Path) -> Config:
    cfg = Config()
    for name, table_path in (("seamgraph.toml", ()), ("pyproject.toml", ("tool", "seamgraph"))):
        f = root / name
        if not f.is_file():
            continue
        try:
            data: Any = tomllib.loads(f.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for part in table_path:
            data = data.get(part, {}) if isinstance(data, dict) else {}
        if isinstance(data, dict) and data:
            return _coerce(cfg, data)
    return cfg
