"""seamgraph — cross-artifact seam graph for coding agents.

Deterministic graph of a repo's *seams*: the string-typed references
connecting code to configs, templates, frontend calls, CI, and .env.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .models import Anchor, AnchorKind, Discovery, Orphan, Seam, SeamKind

__all__ = [
    "Anchor",
    "AnchorKind",
    "Discovery",
    "Orphan",
    "Seam",
    "SeamKind",
    "__version__",
]
