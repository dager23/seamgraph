"""File-based route definitions: Next.js, SvelteKit, and Nuxt map URLs to
file locations rather than code patterns. Pure path mapping — every anchor is
grounded in the framework's documented routing convention.

- Next.js pages router: ``pages/api/users/[id].ts``  -> ``/api/users/*``
- Next.js app router:   ``app/api/users/[id]/route.ts`` -> ``/api/users/*``
  (HTTP methods read from ``export function GET/POST...`` when present)
- SvelteKit:            ``src/routes/api/users/[id]/+server.ts`` -> ``/api/users/*``
- Nuxt 3:               ``server/api/users/[id].get.ts`` -> ``/api/users/*`` (GET)

``[param]`` segments become ``*``; ``[...rest]`` becomes a ``**`` tail;
``(group)`` segments are dropped (they do not appear in the URL).
"""

from __future__ import annotations

import re

from ..models import Anchor, AnchorKind
from ..routes import HTTP_METHODS

_CODE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_EXPORTED_METHOD = re.compile(
    r"export\s+(?:async\s+function|function|const|let)\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"
)
_NUXT_METHOD_SUFFIX = re.compile(r"\.(get|post|put|patch|delete|head|options)$")


def _url_segment(seg: str) -> str | None:
    """Map a path segment to a URL segment; None means 'drop this segment'."""
    if seg.startswith("(") and seg.endswith(")"):
        return None  # route group, not part of the URL
    if seg.startswith("[...") or seg.startswith("[[..."):
        return "**"
    if seg.startswith("[") and seg.endswith("]"):
        return "*"
    if seg.startswith("@"):
        return None  # Next.js parallel route slot
    return seg


def _to_route(segments: list[str]) -> str | None:
    out: list[str] = []
    for seg in segments:
        mapped = _url_segment(seg)
        if mapped is None:
            continue
        out.append(mapped)
    if out and out[-1] == "index":
        out.pop()
    return "/" + "/".join(out)


def _strip_ext(name: str) -> str | None:
    for ext in _CODE_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return None


def _last_index(dir_parts: list[str], name: str) -> int:
    """Index of the last occurrence of ``name`` in ``dir_parts`` (must exist)."""
    return len(dir_parts) - 1 - dir_parts[::-1].index(name)


def _anchor(path: str, route: str, framework: str, methods: str) -> Anchor:
    return Anchor(
        AnchorKind.ROUTE_DEF,
        route,
        path,
        path,
        1,
        f"{framework} file-based route",
        {"method": methods, "framework": framework},
    )


def extract_file_routes(path: str, text: str) -> list[Anchor]:
    """Emit ROUTE_DEF anchors for framework file-convention routes."""
    parts = path.split("/")
    name = parts[-1]
    stem = _strip_ext(name)
    if stem is None:
        return []

    # --- Next.js app router: **/app/.../route.ts -------------------------
    if stem == "route" and "app" in parts[:-1]:
        app_idx = _last_index(parts[:-1], "app")
        route = _to_route(parts[app_idx + 1 : -1])
        if route is not None:
            found = sorted({m.group(1) for m in _EXPORTED_METHOD.finditer(text)} & HTTP_METHODS)
            return [_anchor(path, route, "nextjs", ",".join(found))]
        return []

    # --- Next.js pages router: **/pages/api/... --------------------------
    if "pages" in parts[:-1]:
        pages_idx = _last_index(parts[:-1], "pages")
        rel = parts[pages_idx + 1 : -1] + [stem]
        if rel and rel[0] == "api":
            route = _to_route(rel)
            if route is not None:
                return [_anchor(path, route, "nextjs", "")]
        return []

    # --- SvelteKit: src/routes/**/+server.ts ------------------------------
    if stem == "+server" and "routes" in parts[:-1]:
        routes_idx = _last_index(parts[:-1], "routes")
        route = _to_route(parts[routes_idx + 1 : -1])
        if route is not None:
            found = sorted({m.group(1) for m in _EXPORTED_METHOD.finditer(text)} & HTTP_METHODS)
            return [_anchor(path, route, "sveltekit", ",".join(found))]
        return []

    # --- Nuxt 3: server/api/** and server/routes/** -----------------------
    if "server" in parts[:-1]:
        server_idx = _last_index(parts[:-1], "server")
        rel = parts[server_idx + 1 : -1]
        if rel[:1] in (["api"], ["routes"]):
            method = ""
            m = _NUXT_METHOD_SUFFIX.search(stem)
            base = stem
            if m:
                method = m.group(1).upper()
                base = stem[: m.start()]
            prefix = ["api"] if rel[0] == "api" else []
            route = _to_route(prefix + rel[1:] + [base])
            if route is not None:
                return [_anchor(path, route, "nuxt", method)]
    return []
