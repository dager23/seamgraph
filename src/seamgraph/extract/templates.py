"""Jinja2/Django template extractor.

Extracts from template files (*.html, *.jinja*, *.j2, *.xml):
- ``{{ var }}`` context-variable references (informational, not linked as seams for now)
- ``{% url 'name' %}`` → URLNAME_REF
- ``{% include "x.html" %}`` / ``{% extends "base.html" %}`` → TEMPLATE_REF
- Template files themselves → TEMPLATE_FILE (by existence)
"""

from __future__ import annotations

import re

from ..models import Anchor, AnchorKind

_TEMPLATE_EXTS = frozenset({".html", ".htm", ".jinja", ".jinja2", ".j2", ".xml", ".txt", ".svg"})
_TEMPLATE_DIRS = ("templates", "template", "partials", "layouts", "emails")

_URL_TAG = re.compile(
    r"""\{%[-\s]+url\s+['"]([^'"]+)['"]""",
)
_INCLUDE_TAG = re.compile(
    r"""\{%[-\s]+(?:include|extends)\s+['"]([^'"]+)['"]""",
)
_BLOCK_TAG = re.compile(
    r"""\{%[-\s]+block\s+(\w+)""",
)


def _is_template_path(path: str) -> bool:
    """Heuristic: file lives in a templates dir or has a template extension."""
    base = path.rsplit("/", 1)[-1].lower()
    ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    if ext not in _TEMPLATE_EXTS:
        return False
    parts = path.lower().split("/")
    return any(p in _TEMPLATE_DIRS for p in parts[:-1]) or ext in (
        ".jinja",
        ".jinja2",
        ".j2",
    )


def _template_key(path: str) -> str:
    """Normalize template path to the relative key used for matching.

    Django/Flask templates are typically referenced relative to the templates/
    directory. We strip the leading templates/ prefix if present.
    """
    parts = path.split("/")
    for i, p in enumerate(parts):
        if p.lower() in _TEMPLATE_DIRS:
            return "/".join(parts[i + 1 :])
    return parts[-1]


def extract_template_file(path: str) -> list[Anchor]:
    """Emit a TEMPLATE_FILE anchor if path looks like a template."""
    if not _is_template_path(path):
        return []
    key = _template_key(path)
    return [
        Anchor(
            AnchorKind.TEMPLATE_FILE,
            key,
            key,
            path,
            1,
            "template file on disk",
        )
    ]


def extract_template_refs(path: str, text: str) -> list[Anchor]:
    """Extract URLNAME_REF ({% url %}) and TEMPLATE_REF ({% include/extends %}) from templates."""
    if not _is_template_path(path):
        return []
    anchors: list[Anchor] = []

    for m in _URL_TAG.finditer(text):
        name = m.group(1).strip()
        # url names may be namespaced: "app:detail" → key = "detail"
        key = name.split(":")[-1]
        line = text.count("\n", 0, m.start()) + 1
        anchors.append(
            Anchor(
                AnchorKind.URLNAME_REF,
                key,
                name,
                path,
                line,
                '{% url "..." %}',
            )
        )

    for m in _INCLUDE_TAG.finditer(text):
        ref = m.group(1).strip()
        line = text.count("\n", 0, m.start()) + 1
        anchors.append(
            Anchor(
                AnchorKind.TEMPLATE_REF,
                ref,
                ref,
                path,
                line,
                "{% include/extends %}",
            )
        )

    return anchors
