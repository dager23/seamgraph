"""Route path normalization and matching.

Backend route patterns (FastAPI ``{id}``, Flask ``<int:id>``, Django ``<int:pk>``,
Express ``:id``) and frontend URL literals (including ``${expr}`` template-literal
holes and concatenation tails) are normalized to segment tuples:

- literal segments stay as written
- parameter segments become ``*`` (matches exactly one segment)
- an unresolved tail (string concatenation / f-string suffix) becomes ``**``
  (matches one or more trailing segments)

Matching is deterministic and conservative: a call matches a definition only if
segments align and at least one non-trivial literal segment matches exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARAM = "*"
TAIL = "**"

_FASTAPI_PARAM = re.compile(r"^\{[^{}]+\}$")
_FLASK_PARAM = re.compile(r"^<[^<>]+>$")
_EXPRESS_PARAM = re.compile(r"^:[A-Za-z_][A-Za-z0-9_]*\??$")
_JS_HOLE = re.compile(r"\$\{[^}]*\}")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class RoutePattern:
    segments: tuple[str, ...]

    def display(self) -> str:
        return "/" + "/".join(self.segments)


def _strip_host(url: str) -> str | None:
    """Drop scheme+host from absolute URLs; return path part or None if hostless-relative."""
    if _SCHEME.match(url):
        rest = _SCHEME.sub("", url, count=1)
        slash = rest.find("/")
        return rest[slash:] if slash >= 0 else "/"
    return url


def _split(path: str) -> list[str]:
    path = path.split("?", 1)[0].split("#", 1)[0]
    return [seg for seg in path.split("/") if seg != ""]


def normalize_backend(path: str, framework: str) -> RoutePattern:
    """Normalize a backend route path. ``framework``: fastapi|flask|django|express."""
    segs: list[str] = []
    for seg in _split(path):
        if (
            framework in ("fastapi", "flask", "django")
            and (_FASTAPI_PARAM.match(seg) or _FLASK_PARAM.match(seg))
        ) or (framework == "express" and _EXPRESS_PARAM.match(seg)):
            segs.append(PARAM)
        elif ("{" in seg and "}" in seg) or ("<" in seg and ">" in seg):
            # mixed segment like "v{version}" or "item-<id>"
            segs.append(PARAM)
        else:
            segs.append(seg)
    return RoutePattern(tuple(segs))


def normalize_call(
    url: str,
    strip_prefixes: tuple[str, ...] = (),
    open_tail: bool = False,
) -> RoutePattern | None:
    """Normalize a frontend/client URL literal.

    Returns None for URLs that cannot map to an in-repo route (external hosts are
    kept — host is stripped — but mailto:, data:, etc. are rejected).
    ``open_tail`` marks a URL built by concatenation: ``fetch("/api/users/" + id)``.
    """
    url = url.strip()
    if url.startswith(("mailto:", "data:", "javascript:", "ws:", "wss:", "//")):
        return None
    for prefix in strip_prefixes:
        if prefix and url.startswith(prefix):
            url = url[len(prefix) :] or "/"
            break
    path = _strip_host(url)
    if path is None:
        return None
    segs: list[str] = []
    for seg in _split(path):
        if _JS_HOLE.search(seg):
            segs.append(PARAM)
        else:
            segs.append(seg)
    if open_tail:
        # trailing concatenation: last written segment may be a prefix of a longer path
        segs.append(TAIL)
    if not segs:
        return None
    return RoutePattern(tuple(segs))


def _literal(seg: str) -> bool:
    return seg not in (PARAM, TAIL)


def match_route(
    call: RoutePattern,
    definition: RoutePattern,
    allow_def_prefix: bool = False,
) -> int | None:
    """Match a call pattern against a definition pattern.

    Returns a score (count of exactly-matched literal segments) or None.
    ``allow_def_prefix`` permits the call to carry extra *leading* segments not
    present in the definition (Django include()/unresolved router prefixes):
    the definition is then matched as a suffix of the call.
    """
    best: int | None = None
    offsets = range(0, len(call.segments) + 1) if allow_def_prefix else range(0, 1)
    for off in offsets:
        score = _match_from(call.segments[off:], definition.segments)
        if score is not None and (best is None or score > best):
            best = score
    if best is None:
        return None
    # require at least one non-trivial literal overlap to avoid "/*"-style matches
    return best if best >= 1 else None


def _match_from(call: tuple[str, ...], defn: tuple[str, ...]) -> int | None:
    """Segment alignment; TAIL in call consumes 1+ remaining definition segments."""
    ci, di, score = 0, 0, 0
    while ci < len(call) and di < len(defn):
        c, d = call[ci], defn[di]
        if c == TAIL:
            # consumes the rest of the definition (must be at least one segment)
            return score if len(defn) - di >= 1 else None
        if _literal(c) and _literal(d):
            if c != d:
                return None
            if len(c) >= 2 and not c.isdigit():
                score += 1
        # PARAM on either side matches any single segment
        ci += 1
        di += 1
    if ci == len(call) and di == len(defn):
        return score
    # allow a single trailing TAIL left over on the call side matching nothing? No:
    # TAIL requires >=1 segment, handled above. Trailing-slash asymmetry is handled
    # by _split dropping empty segments.
    return None
