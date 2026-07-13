"""JavaScript/TypeScript extractor (anchored regex, v0.1).

Extracted, all anchored on call syntax — never bare string scans:
- ``fetch("...")`` / ``fetch(`...`)`` and axios/apiClient-style calls -> ROUTE_CALL
- ``process.env.X`` / ``process.env["X"]`` / ``import.meta.env.X`` -> ENV_READ
- Express ``app.get("/path", ...)`` style definitions -> ROUTE_DEF
"""

from __future__ import annotations

import re

from ..models import Anchor, AnchorKind
from ..routes import HTTP_METHODS, normalize_backend, normalize_call

_JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")

_FETCH = re.compile(r"""\bfetch\s*\(\s*(['"`])""")
_AXIOS_VERB = re.compile(
    r"""\b([\w$.]*(?:axios|api|client|http|request|fetcher)[\w$]*)\s*"""
    r"""\.\s*(get|post|put|patch|delete|head|options|request)\s*\(\s*(['"`])""",
    re.IGNORECASE,
)
_ENV_READS = re.compile(
    r"""\b(?:process\.env|import\.meta\.env)(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*['"]([^'"\]]+)['"]\s*\])"""
)
_ENV_DESTRUCTURE = re.compile(
    r"""(?:const|let|var)\s*\{([^}]+)\}\s*=\s*(?:process\.env|import\.meta\.env)\b"""
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*")
_EXPRESS_DEF = re.compile(
    r"""\b(app|router|server|api)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*(['"`])(/[^'"`\n]*)\3"""
)
# app.use("/api", subrouter) / hono app.route("/api/v2", subapp): a mounted
# sub-application serves everything below the prefix. The trailing comma
# requires a second argument, excluding express's chaining .route("/x").get()
_EXPRESS_MOUNT = re.compile(
    r"""\b(app|router|server|api)\s*\.\s*(use|route)\s*\(\s*(['"`])(/[^'"`\n]*)\3\s*,"""
)
_METHOD_OPT = re.compile(r"""method\s*:\s*['"`](\w+)['"`]""", re.IGNORECASE)
_VITE_STYLE_ENV = frozenset({"MODE", "BASE_URL", "PROD", "DEV", "SSR"})


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _read_string(text: str, start: int, quote: str) -> tuple[str, bool, int] | None:
    """Read a JS string starting after its opening quote.

    Returns (value, open_tail, end_index) where ``end_index`` points just past
    the closing quote. Template-literal ``${...}`` holes become ``${x}``;
    a closing quote followed by ``+`` marks concatenation (open tail).
    """
    out: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == quote:
            rest = text[i + 1 : i + 24].lstrip()
            open_tail = rest.startswith("+")
            return "".join(out), open_tail, i + 1
        if quote == "`" and ch == "$" and text[i : i + 2] == "${":
            depth = 1
            j = i + 2
            while j < len(text) and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            out.append("${x}")
            i = j
            continue
        if ch == "\n":
            return None  # unterminated ordinary string
        out.append(ch)
        i += 1
    return None


def _method_in_call(text: str, after_string: int) -> str:
    """Find a ``method: "X"`` option inside the *current* call's argument list.

    Scans from just past the URL string to the call's closing paren (tracking
    paren depth and skipping strings) so an option from a *later* call can
    never be picked up.
    """
    i = after_string
    depth = 0
    in_str: str | None = None
    while i < len(text) and i < after_string + 2000:
        ch = text[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "'\"`":
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        i += 1
    m = _METHOD_OPT.search(text, after_string, i)
    return m.group(1).upper() if m else ""


def _looks_minified(text: str) -> bool:
    lines = text.splitlines() or [""]
    return max(len(ln) for ln in lines) > 5000


def _route_call_anchor(
    path: str,
    text: str,
    url: str,
    open_tail: bool,
    pos: int,
    detail: str,
    method: str,
    strip_prefixes: tuple[str, ...],
) -> Anchor | None:
    if not url or url.startswith(("mailto:", "data:", "javascript:", "#", "?")):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.IGNORECASE).split("/")[0]
        hostname = host.split("@")[-1].split(":")[0].lower()
        if hostname not in ("localhost", "127.0.0.1", "0.0.0.0") and "${x}" not in host:
            return None  # external API call, not an in-repo seam
    elif not url.startswith("/") and not url.startswith("${x}"):
        return None  # relative-to-page URLs are ambiguous; skip
    pattern = normalize_call(url, strip_prefixes=strip_prefixes, open_tail=open_tail)
    if pattern is None or not pattern.segments:
        return None
    if all(seg in ("*", "**") for seg in pattern.segments):
        return None  # nothing literal to match on
    if not _METHOD_OPT_ALLOWED.match(method):
        method = ""
    return Anchor(
        AnchorKind.ROUTE_CALL,
        pattern.display(),
        url,
        path,
        _line_of(text, pos),
        detail,
        {"method": method, "client": "js"},
    )


_METHOD_OPT_ALLOWED = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|)$")


def extract_js_ts(path: str, text: str, strip_prefixes: tuple[str, ...] = ()) -> list[Anchor]:
    if not path.lower().endswith(_JS_EXTS) or ".min." in path or _looks_minified(text):
        return []
    anchors: list[Anchor] = []

    for m in _FETCH.finditer(text):
        got = _read_string(text, m.end(), m.group(1))
        if got is None:
            continue
        url, open_tail, str_end = got
        method = _method_in_call(text, str_end)
        a = _route_call_anchor(
            path, text, url, open_tail, m.start(), "fetch(...)", method, strip_prefixes
        )
        if a:
            anchors.append(a)

    for m in _AXIOS_VERB.finditer(text):
        receiver, verb, quote = m.group(1), m.group(2).lower(), m.group(3)
        got = _read_string(text, m.end(), quote)
        if got is None:
            continue
        url, open_tail, _ = got
        method = verb.upper() if verb.upper() in HTTP_METHODS else ""
        a = _route_call_anchor(
            path, text, url, open_tail, m.start(), f"{receiver}.{verb}(...)", method, strip_prefixes
        )
        if a:
            anchors.append(a)

    for m in _ENV_READS.finditer(text):
        name = m.group(1) or m.group(2)
        if not name or name in _VITE_STYLE_ENV:
            continue
        anchors.append(
            Anchor(
                AnchorKind.ENV_READ,
                name,
                name,
                path,
                _line_of(text, m.start()),
                "process.env / import.meta.env",
                {"source": "code"},
            )
        )

    for m in _ENV_DESTRUCTURE.finditer(text):
        # const { API_URL, DEBUG: dbg = "0" } = process.env
        for part in m.group(1).split(","):
            ident = _IDENT.match(part.strip())
            if not ident or ident.group(0) in _VITE_STYLE_ENV:
                continue
            anchors.append(
                Anchor(
                    AnchorKind.ENV_READ,
                    ident.group(0),
                    ident.group(0),
                    path,
                    _line_of(text, m.start()),
                    "destructured from process.env",
                    {"source": "code"},
                )
            )

    for m in _EXPRESS_DEF.finditer(text):
        var, verb, url = m.group(1), m.group(2), m.group(4)
        pattern = normalize_backend(url, "express")
        anchors.append(
            Anchor(
                AnchorKind.ROUTE_DEF,
                pattern.display(),
                url,
                path,
                _line_of(text, m.start()),
                f"{var}.{verb}(...) (express-style)",
                {
                    "method": "" if verb == "all" else verb.upper(),
                    "framework": "express",
                    # routers are commonly mounted under a prefix we can't resolve in v0.1
                    "maybe_prefixed": "1" if var != "app" else "",
                },
            )
        )

    for m in _EXPRESS_MOUNT.finditer(text):
        var, verb, url = m.group(1), m.group(2), m.group(4)
        base = url.rstrip("/")
        if not base:
            continue  # app.use("/", ...) mounts everything; no seam evidence
        pattern = normalize_backend(base, "express")
        anchors.append(
            Anchor(
                AnchorKind.ROUTE_DEF,
                pattern.display() + "/**",
                url,
                path,
                _line_of(text, m.start()),
                f"{var}.{verb}(...) (mounted sub-app)",
                {
                    "method": "",
                    "framework": "express",
                    "maybe_prefixed": "1" if var != "app" else "",
                },
            )
        )

    return anchors
