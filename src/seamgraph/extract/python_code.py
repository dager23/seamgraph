"""Python source extractor (stdlib ``ast``): env reads, routes, templates, url
names, Celery tasks, Django settings, and HTTP client calls.

Every anchor is *pattern-anchored*: only literal strings at recognized call
shapes are extracted — never bare string scans.

Route definitions on routers/blueprints need cross-file prefix resolution
(``include_router``/``register_blueprint``), so this module returns per-file
facts; :func:`resolve_routes` combines them into final ROUTE_DEF anchors.
"""

from __future__ import annotations

import ast
import contextlib
import re
import warnings
from dataclasses import dataclass, field

from ..models import Anchor, AnchorKind
from ..routes import HTTP_METHODS, normalize_backend, normalize_call

_TEMPLATE_EXTS = (".html", ".htm", ".jinja", ".jinja2", ".j2", ".xml", ".txt")
_DOTTED_TASK = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")
_HTTP_RECEIVER_HINTS = ("client", "session", "requests", "httpx", "api", "http")
_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
_LOCALHOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "testserver")


@dataclass
class RouterInfo:
    framework: str  # fastapi_app | fastapi_router | flask_app | flask_blueprint
    prefix: str = ""
    line: int = 0


@dataclass
class RawRoute:
    var: str
    path: str
    methods: str  # "" (any) or "GET" or "GET,POST"
    line: int
    framework: str  # fastapi | flask | django
    detail: str


@dataclass
class Include:
    """app.include_router(x.router, prefix=...) / app.register_blueprint(bp, url_prefix=...)."""

    owner_var: str  # the including app/router variable
    target_module: str | None  # local name of module if target was attribute access
    target_attr: str  # variable name of the included router
    prefix: str | None  # None when non-literal (unresolvable)
    line: int


@dataclass
class PyFileFacts:
    anchors: list[Anchor] = field(default_factory=list)
    routes: list[RawRoute] = field(default_factory=list)
    routers: dict[str, RouterInfo] = field(default_factory=dict)
    includes: list[Include] = field(default_factory=list)
    imports: dict[str, str] = field(default_factory=dict)  # local name -> dotted module
    import_froms: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (mod, attr)


def _lit(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _chain(node: ast.AST) -> list[str]:
    """Attribute chain names: self.client.post -> ["self","client","post"]."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return []


def _url_parts(node: ast.AST) -> tuple[str, bool] | None:
    """Literal-or-templated URL from Constant / JoinedStr / leading-literal concat.

    Returns (url_with_${}_holes, open_tail) or None.
    """
    s = _lit(node)
    if s is not None:
        return s, False
    if isinstance(node, ast.JoinedStr):
        out: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append("${x}")
        return "".join(out), False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # fold leftmost literal chain: "/api/x/" + id [+ ...]
        left: ast.AST = node
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add):
            left = left.left
        s = _lit(left)
        if s is not None:
            return s, True
    return None


def _internal_url(url: str) -> bool:
    """Keep relative URLs and localhost-ish absolute URLs; drop external hosts."""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/]*)", url, re.IGNORECASE)
    if not m:
        return url.startswith("/")
    host = m.group(1).split("@")[-1].split(":")[0].lower()
    return host in _LOCALHOSTS or "${x}" in m.group(1)


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str, facts: PyFileFacts, strip_prefixes: tuple[str, ...] = ()) -> None:
        self.path = path
        self.f = facts
        self.strip_prefixes = strip_prefixes
        self._class_stack: list[str] = []

    # -- imports ---------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.f.imports[alias.asname or alias.name.split(".")[0]] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = ("." * node.level) + (node.module or "")
        for alias in node.names:
            local = alias.asname or alias.name
            self.f.import_froms[local] = (mod, alias.name)
            self.f.imports.setdefault(local, f"{mod}.{alias.name}" if mod else alias.name)
        self.generic_visit(node)

    def _from(self, local: str, modules: tuple[str, ...], attr: str | None = None) -> bool:
        got = self.f.import_froms.get(local)
        if not got:
            return False
        mod, name = got
        base = mod.lstrip(".").split(".")[0]
        return base in modules and (attr is None or name == attr)

    # -- assignments: router/app construction ----------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        self._maybe_router(node.targets, node.value)
        self._maybe_setting_def(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._maybe_router([node.target], node.value)
        self.generic_visit(node)

    def _maybe_router(self, targets: list[ast.expr], value: ast.expr) -> None:
        if not isinstance(value, ast.Call):
            return
        names = _chain(value.func)
        if not names:
            return
        ctor = names[-1]
        info: RouterInfo | None = None
        if ctor == "APIRouter":
            info = RouterInfo("fastapi_router", _kw_str(value, "prefix") or "", value.lineno)
        elif ctor == "FastAPI":
            info = RouterInfo("fastapi_app", "", value.lineno)
        elif ctor == "Flask":
            info = RouterInfo("flask_app", "", value.lineno)
        elif ctor == "Blueprint":
            info = RouterInfo("flask_blueprint", _kw_str(value, "url_prefix") or "", value.lineno)
        if info is None:
            return
        for t in targets:
            if isinstance(t, ast.Name):
                self.f.routers[t.id] = info

    def _maybe_setting_def(self, node: ast.Assign) -> None:
        if not _is_settings_module(self.path) or self._class_stack:
            return
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) >= 2:
                self.f.anchors.append(
                    Anchor(
                        AnchorKind.SETTING_DEF,
                        t.id,
                        t.id,
                        self.path,
                        node.lineno,
                        "module-level assignment in settings module",
                    )
                )

    # -- classes: pydantic settings ---------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        base_names = {
            b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases
        }
        if "BaseSettings" in base_names:
            self._pydantic_settings(node)
        self.generic_visit(node)
        self._class_stack.pop()

    def _pydantic_settings(self, node: ast.ClassDef) -> None:
        prefix = ""
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    is_config = isinstance(t, ast.Name) and t.id == "model_config"
                    if is_config and isinstance(stmt.value, ast.Call):
                        prefix = _kw_str(stmt.value, "env_prefix") or ""
            if isinstance(stmt, ast.ClassDef) and stmt.name == "Config":
                for s2 in stmt.body:
                    if isinstance(s2, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "env_prefix" for t in s2.targets
                    ):
                        prefix = _lit(s2.value) or prefix
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            if name.startswith("_") or name == "model_config":
                continue
            explicit = None
            if isinstance(stmt.value, ast.Call) and _chain(stmt.value.func)[-1:] == ["Field"]:
                explicit = (
                    _kw_str(stmt.value, "validation_alias")
                    or _kw_str(stmt.value, "env")
                    or _kw_str(stmt.value, "alias")
                )
            key = (explicit or (prefix + name)).upper()
            self.f.anchors.append(
                Anchor(
                    AnchorKind.ENV_READ,
                    key,
                    name,
                    self.path,
                    stmt.lineno,
                    f"pydantic BaseSettings field in class {node.name}",
                    {"source": "pydantic"},
                )
            )

    # -- subscripts: os.environ["X"] --------------------------------------
    def visit_Subscript(self, node: ast.Subscript) -> None:
        names = _chain(node.value)
        if names[-1:] == ["environ"] and (
            (len(names) == 1 and self._from("environ", ("os",))) or names[-2:] == ["os", "environ"]
        ):
            key = _lit(node.slice)
            if key:
                self.f.anchors.append(
                    Anchor(
                        AnchorKind.ENV_READ,
                        key,
                        key,
                        self.path,
                        node.lineno,
                        "os.environ[...]",
                        {"source": "code"},
                    )
                )
        self.generic_visit(node)

    # -- attribute reads: django settings.X --------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.attr.isupper()
            and len(node.attr) >= 2
            and self._from(node.value.id, ("django",), "settings")
        ):
            self.f.anchors.append(
                Anchor(
                    AnchorKind.SETTING_READ,
                    node.attr,
                    f"settings.{node.attr}",
                    self.path,
                    node.lineno,
                    "django.conf settings attribute",
                )
            )
        self.generic_visit(node)

    # -- calls: the workhorse ----------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        names = _chain(node.func)
        if names:
            self._call_env(node, names)
            self._call_route_client(node, names)
            self._call_template(node, names)
            self._call_urlname(node, names)
            self._call_task(node, names)
            self._call_include(node, names)
            self._call_django_path(node, names)
            self._call_add_resource(node, names)
            self._call_drf_register(node, names)
        self.generic_visit(node)

    def _call_drf_register(self, node: ast.Call, names: list[str]) -> None:
        """Django REST Framework routers: router.register(r"views", ViewSet).

        Anchored on: a .register(...) call whose receiver name contains
        "router", with a string-literal prefix. ViewSets expose list/detail
        routes; we emit both, suffix-matchable since the router's include()
        mount point is elsewhere.
        """
        if names[-1] != "register" or not node.args:
            return
        receiver_hint = any("router" in part.lower() for part in names[:-1])
        if not receiver_hint:
            return
        prefix = _lit(node.args[0])
        if prefix is None or not prefix or prefix.startswith("/"):
            return
        base = "/" + prefix.strip("/")
        detail = f"{'.'.join(names)}({prefix!r}, ...) (DRF ViewSet)"
        for rule in (base, base + "/<pk>"):
            self.f.routes.append(RawRoute("", rule, "", node.lineno, "drf", detail))

    def _call_add_resource(self, node: ast.Call, names: list[str]) -> None:
        """Flask-RESTful style: api.add_resource(Cls, "/path" [, "/path2" ...]).

        Also matches project-specific wrappers like redash's add_org_resource.
        The registering Api object's own prefix is unknown, so routes are
        marked maybe_prefixed (suffix-matchable).
        """
        if names[-1] not in ("add_resource", "add_org_resource"):
            return
        cls_name = ""
        if node.args and isinstance(node.args[0], ast.Name):
            cls_name = node.args[0].id
        for arg in node.args[1:]:
            rule = _lit(arg)
            if rule is None or not rule.startswith("/"):
                continue
            self.f.routes.append(
                RawRoute(
                    "",
                    rule,
                    "",
                    node.lineno,
                    "flask_restful",
                    f"{names[-1]}({cls_name or '...'}, ...)",
                )
            )

    def _call_env(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        anchor: tuple[str, str] | None = None  # (kind-detail, key)
        is_getenv = (len(names) == 1 and self._from("getenv", ("os",))) or names[-2:] == [
            "os",
            "getenv",
        ]
        if tail == "getenv" and is_getenv:
            key = _lit(node.args[0]) if node.args else None
            if key:
                anchor = ("os.getenv(...)", key)
        elif tail in ("get", "setdefault", "pop") and names[-2:-1] == ["environ"]:
            ok = (len(names) == 2 and self._from("environ", ("os",))) or names[-3:-1] == [
                "os",
                "environ",
            ]
            if ok and node.args:
                key = _lit(node.args[0])
                if key:
                    anchor = (f"os.environ.{tail}(...)", key)
        if anchor is None:
            return
        detail, key = anchor
        kind = AnchorKind.ENV_DEF if "setdefault" in detail else AnchorKind.ENV_READ
        self.f.anchors.append(
            Anchor(kind, key, key, self.path, node.lineno, detail, {"source": "code"})
        )

    def _call_route_client(self, node: ast.Call, names: list[str]) -> None:
        verb = names[-1]
        if verb not in _VERBS and verb != "request":
            return
        receiver = names[:-1]
        hinted = any(h in part.lower() for part in receiver for h in _HTTP_RECEIVER_HINTS)
        if not receiver or not hinted:
            return
        if verb == "request":
            method = (_lit(node.args[0]) or "").upper() if node.args else ""
            url_node = node.args[1] if len(node.args) > 1 else None
        else:
            method = verb.upper()
            url_node = node.args[0] if node.args else None
        if url_node is None:
            return
        parts = _url_parts(url_node)
        if parts is None:
            return
        url, open_tail = parts
        if not _internal_url(url):
            return
        pattern = normalize_call(url, strip_prefixes=self.strip_prefixes, open_tail=open_tail)
        if pattern is None:
            return
        self.f.anchors.append(
            Anchor(
                AnchorKind.ROUTE_CALL,
                pattern.display(),
                url,
                self.path,
                node.lineno,
                f"{'.'.join(receiver)}.{verb}(...)",
                {"method": method if method in HTTP_METHODS else "", "client": "python"},
            )
        )

    def _call_template(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        if tail not in (
            "render_template",
            "render",
            "render_to_string",
            "get_template",
            "TemplateResponse",
            "select_template",
        ):
            return
        for arg in node.args[:2]:
            s = _lit(arg)
            if s and s.lower().endswith(_TEMPLATE_EXTS):
                self.f.anchors.append(
                    Anchor(
                        AnchorKind.TEMPLATE_REF,
                        s,
                        s,
                        self.path,
                        node.lineno,
                        f"{tail}(...)",
                    )
                )
                return

    def _call_urlname(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        if tail not in ("reverse", "reverse_lazy", "redirect", "url_for"):
            return
        if not node.args:
            return
        s = _lit(node.args[0])
        if not s or "/" in s or not re.match(r"^[\w.:-]+$", s):
            return
        if tail in ("reverse", "reverse_lazy") and not (
            self._from(tail, ("django",)) or "urls" in str(self.f.import_froms.get(tail, ""))
        ):
            # reverse() from other libs is common; require django import for reverse
            return
        if tail == "url_for":
            # flask endpoint names: function names, keep as urlname too
            pass
        # strip django "app:" namespaces and flask "blueprint." qualifiers
        key = s.split(":")[-1].split(".")[-1]
        self.f.anchors.append(
            Anchor(
                AnchorKind.URLNAME_REF,
                key,
                s,
                self.path,
                node.lineno,
                f"{tail}(...)",
            )
        )

    def _call_task(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        if tail in ("send_task", "signature"):
            s = _lit(node.args[0]) if node.args else None
            if s and _DOTTED_TASK.match(s):
                self.f.anchors.append(
                    Anchor(AnchorKind.TASK_CALL, s, s, self.path, node.lineno, f"{tail}(...)")
                )

    def _call_include(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        if tail not in ("include_router", "register_blueprint") or not node.args:
            return
        owner = names[0] if len(names) >= 2 else ""
        target = node.args[0]
        tmod: str | None = None
        tattr = ""
        if isinstance(target, ast.Name):
            tattr = target.id
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            tmod, tattr = target.value.id, target.attr
        else:
            chain = _chain(target)
            if len(chain) >= 2:
                tmod, tattr = chain[-2], chain[-1]
        if not tattr:
            return
        kwname = "prefix" if tail == "include_router" else "url_prefix"
        has_kw = any(k.arg == kwname for k in node.keywords)
        prefix = _kw_str(node, kwname)
        self.f.includes.append(
            Include(
                owner,
                tmod,
                tattr,
                prefix if (prefix is not None or not has_kw) else None,
                node.lineno,
            )
        )
        if prefix is None and not has_kw:
            # no prefix argument at all -> prefix is ""
            self.f.includes[-1].prefix = ""

    def _call_django_path(self, node: ast.Call, names: list[str]) -> None:
        tail = names[-1]
        if tail not in ("path", "re_path", "url"):
            return
        if not self._from(tail, ("django",)):
            return
        route = _lit(node.args[0]) if node.args else None
        if route is None:
            return
        name = _kw_str(node, "name")
        if name:
            self.f.anchors.append(
                Anchor(
                    AnchorKind.URLNAME_DEF,
                    name,
                    name,
                    self.path,
                    node.lineno,
                    f'{tail}(..., name="{name}")',
                )
            )
        if _is_include_call(node):
            return
        if tail == "path":
            rule: str | None = "/" + route.lstrip("/")
        else:
            # re_path()/url() take a regex; only convert the plainly literal ones
            rule = _regex_to_route(route)
        if rule is not None:
            self.f.routes.append(
                RawRoute("", rule, "", node.lineno, "django", f"django {tail}(...)")
            )

    # -- decorators: routes and celery tasks --------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._decorators(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._decorators(node)
        self.generic_visit(node)

    def _decorators(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                # bare @shared_task
                names = _chain(dec)
                if names and names[-1] in ("shared_task", "task"):
                    self._task_def(node, None, dec)
                continue
            names = _chain(dec.func)
            if not names:
                continue
            tail = names[-1]
            if tail in ("shared_task", "task"):
                self._task_def(node, dec, dec)
                continue
            if len(names) >= 2 and (tail in _VERBS or tail in ("route", "api_route")):
                self._route_def(node, dec, names)

    def _task_def(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        call: ast.Call | None,
        dec: ast.expr,
    ) -> None:
        name = _kw_str(call, "name") if call else None
        if name:
            self.f.anchors.append(
                Anchor(
                    AnchorKind.TASK_DEF,
                    name,
                    name,
                    self.path,
                    dec.lineno,
                    'task decorator with name="..."',
                )
            )
        else:
            # auto-named: dotted module path + function name (filled by resolver)
            self.f.anchors.append(
                Anchor(
                    AnchorKind.TASK_DEF,
                    f"?auto?.{node.name}",
                    node.name,
                    self.path,
                    dec.lineno,
                    "task decorator (auto-named)",
                    {"auto": "1"},
                )
            )

    def _route_def(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        dec: ast.Call,
        names: list[str],
    ) -> None:
        var = names[0]
        tail = names[-1]
        path_arg = _lit(dec.args[0]) if dec.args else _kw_str(dec, "path") or _kw_str(dec, "rule")
        if path_arg is not None and path_arg != "" and not path_arg.startswith("/"):
            # Flask and FastAPI both require absolute rule strings; anything
            # else (@mock.patch("pkg.attr"), cache.get("key")) is not a route
            return
        if path_arg is None:
            # dynamic route path (helper-wrapped rule): the URL is unknowable
            # but the endpoint name is still the view function's name
            if (
                tail == "route"
                or var in self.f.import_froms
                or "flask" in str(self.f.imports.values())
            ):
                self.f.anchors.append(
                    Anchor(
                        AnchorKind.URLNAME_DEF,
                        node.name,
                        node.name,
                        self.path,
                        dec.lineno,
                        f"flask endpoint {node.name} (dynamic rule)",
                    )
                )
            return
        info = self.f.routers.get(var)
        if info is not None:
            framework = "flask" if info.framework.startswith("flask") else "fastapi"
        elif var in self.f.import_froms:
            # router/blueprint imported from another module (the common way
            # large apps split routes); resolve_routes() follows the import
            framework = "imported"
        elif any(m.split(".")[0] == "fastapi" for m in self.f.imports.values()):
            framework = "fastapi"
        elif any(m.split(".")[0] == "flask" for m in self.f.imports.values()):
            framework = "flask"
        elif tail == "route":
            # .route() is the Flask/Blueprint signature even when neither
            # flask nor the router constructor is visible in this file
            framework = "flask"
        else:
            return
        if tail == "route" or tail == "api_route":
            methods = _kw_str_list(dec, "methods")
        else:
            methods = [tail.upper()]
        methods = [m for m in (methods or []) if m.upper() in HTTP_METHODS]
        self.f.routes.append(
            RawRoute(
                var,
                path_arg,
                ",".join(sorted({m.upper() for m in methods})),
                dec.lineno,
                framework,
                f"@{var}.{tail}(...) on {node.name}",
            )
        )
        # flask url_for uses endpoint names == view function names
        if framework in ("flask", "imported"):
            self.f.anchors.append(
                Anchor(
                    AnchorKind.URLNAME_DEF,
                    node.name,
                    node.name,
                    self.path,
                    dec.lineno,
                    f"flask endpoint {node.name}",
                )
            )


def _kw_str(call: ast.Call | None, name: str) -> str | None:
    if call is None:
        return None
    for k in call.keywords:
        if k.arg == name:
            return _lit(k.value)
    return None


def _kw_str_list(call: ast.Call, name: str) -> list[str]:
    for k in call.keywords:
        if k.arg == name and isinstance(k.value, (ast.List, ast.Tuple)):
            return [v for v in (_lit(e) for e in k.value.elts) if v]
    return []


def _is_include_call(node: ast.Call) -> bool:
    return any(isinstance(a, ast.Call) and _chain(a.func)[-1:] == ["include"] for a in node.args)


#: A regex group: named or plain. Multi-segment bodies become a ``**`` tail.
_RE_GROUP = re.compile(r"\((\?P<[^>]+>)?((?:[^()\\]|\\.)*)\)")
#: Regex metacharacters that must not survive conversion to a literal path.
_RE_LEFTOVER = re.compile(r"[\[\]{}()+*?|^$\\]")


def _regex_to_route(pattern: str) -> str | None:
    """Convert a Django ``re_path`` regex to a path pattern, or None.

    Django projects that predate ``path()`` register everything as regexes, so
    skipping them outright leaves whole codebases with no routes at all. Only
    plainly literal patterns are converted -- every capture group becomes a
    parameter segment and anything still carrying regex syntax afterwards is
    rejected rather than guessed at.

    ``r"^plugins/global/(?P<plugin_id>[\\w-]+)/"`` -> ``/plugins/global/*``
    """
    if "(?:" in pattern or "|" in pattern:
        return None  # alternation / optional groups: the URL shape is not one path
    body = pattern
    if body.startswith("^"):
        body = body[1:]
    if body.endswith("$"):
        body = body[:-1]

    def _sub(m: re.Match[str]) -> str:
        inner = m.group(2)
        # `.*` / `.+` can span separators, so the group is a trailing wildcard
        return "\x00\x00" if (".*" in inner or ".+" in inner) else "\x00"

    body = _RE_GROUP.sub(_sub, body)
    # unescape the escapes Django authors actually write in URL regexes
    body = body.replace("\\.", ".").replace("\\-", "-").replace("\\/", "/").replace("\\w", "\x00")
    if _RE_LEFTOVER.search(body):
        return None
    body = body.replace("\x00\x00", "**").replace("\x00", "*")
    segments = [s for s in body.split("/") if s]
    if not segments or all(s in ("*", "**") for s in segments):
        return None  # nothing literal to anchor a match on
    return "/" + "/".join(segments)


def _is_settings_module(path: str) -> bool:
    parts = path.split("/")
    base = parts[-1]
    return (
        base in ("settings.py", "base.py", "local.py", "production.py", "dev.py")
        and ("settings" in parts[:-1] or base == "settings.py")
    ) or (base.startswith("settings") and base.endswith(".py"))


def extract_python(path: str, source: str, strip_prefixes: tuple[str, ...] = ()) -> PyFileFacts:
    facts = PyFileFacts()
    try:
        with warnings.catch_warnings():
            # third-party code full of invalid escape sequences is not our problem
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return facts
    # pathologically nested generated code: keep whatever was extracted
    with contextlib.suppress(RecursionError):
        _Visitor(path, facts, strip_prefixes).visit(tree)
    return facts


# ---------------------------------------------------------------------------
# Cross-file route resolution
# ---------------------------------------------------------------------------


def _module_candidates(path: str) -> list[str]:
    """Dotted module names a file might be imported as."""
    if not path.endswith(".py"):
        return []
    parts = path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    cands = [".".join(parts)]
    for skip in ("src", "lib", "app", "backend", "server"):
        if len(parts) > 1 and parts[0] == skip:
            cands.append(".".join(parts[1:]))
    # suffix module name (from x.y import z resolvable by tail)
    if len(parts) > 1:
        cands.append(parts[-1])
    return cands


def resolve_routes(all_facts: dict[str, PyFileFacts]) -> list[Anchor]:
    """Combine per-file facts into final ROUTE_DEF anchors (and fix auto task names)."""
    module_index: dict[str, str] = {}
    for path in sorted(all_facts):
        for cand in _module_candidates(path):
            module_index.setdefault(cand, path)

    def find_module_file(facts: PyFileFacts, local: str) -> str | None:
        dotted = facts.imports.get(local)
        if dotted:
            d = dotted.lstrip(".")
            # Try full dotted path, then without the last component (the attr
            # itself in a ``from mod import attr``), then just the tail.
            parts = d.split(".")
            candidates = [d]
            if len(parts) > 1:
                candidates.append(".".join(parts[:-1]))
            candidates.append(parts[-1])
            if len(parts) > 1:
                candidates.append(parts[-2])
            for cand in candidates:
                if cand in module_index:
                    return module_index[cand]
        # Also check import_froms for the module path directly
        got = facts.import_froms.get(local)
        if got:
            mod = got[0].lstrip(".")
            if mod in module_index:
                return module_index[mod]
            mod_tail = mod.split(".")[-1]
            if mod_tail in module_index:
                return module_index[mod_tail]
        return module_index.get(local)

    # (path, var) -> list of mount prefixes (composed); "" means mounted at root
    mounts: dict[tuple[str, str], list[str | None]] = {}
    for path, facts in sorted(all_facts.items()):
        for inc in facts.includes:
            target_path: str | None = path
            if inc.target_module is not None:
                target_path = find_module_file(facts, inc.target_module)
            elif inc.target_attr not in facts.routers:
                # from x import router; include_router(router)
                got = facts.import_froms.get(inc.target_attr)
                if got:
                    target_path = find_module_file(facts, inc.target_attr) or path
            if target_path is None:
                continue
            mounts.setdefault((target_path, inc.target_attr), []).append(inc.prefix)

    anchors: list[Anchor] = []
    for path, facts in sorted(all_facts.items()):
        # fix auto-named celery tasks
        for a in facts.anchors:
            if a.kind is AnchorKind.TASK_DEF and a.extra.get("auto") == "1":
                cands = _module_candidates(path)
                dotted = cands[0] if cands else path
                anchors.append(
                    Anchor(a.kind, f"{dotted}.{a.raw}", a.raw, a.path, a.line, a.detail, a.extra)
                )
            else:
                anchors.append(a)
        for r in facts.routes:
            own_prefix = ""
            is_subrouter = False
            framework = r.framework
            info = facts.routers.get(r.var)
            mount_key = (path, r.var)
            if info is None and framework == "imported":
                # follow the import chain (up to 3 hops) to the module that
                # constructs the router/blueprint this decorator hangs off
                seen: set[tuple[str, str]] = set()
                cur_path, cur_var, cur_facts = path, r.var, facts
                for _ in range(3):
                    if (cur_path, cur_var) in seen:
                        break
                    seen.add((cur_path, cur_var))
                    target = find_module_file(cur_facts, cur_var)
                    if target is None or target not in all_facts:
                        break
                    cur_path, cur_facts = target, all_facts[target]
                    resolved_info = cur_facts.routers.get(cur_var)
                    if resolved_info is not None:
                        info = resolved_info
                        mount_key = (cur_path, cur_var)
                        break
                    if cur_var not in cur_facts.import_froms:
                        break
                if info is not None:
                    framework = "flask" if info.framework.startswith("flask") else "fastapi"
                else:
                    # unresolved import: .route() decorators are Flask-style
                    framework = "flask"
            if info is not None:
                own_prefix = info.prefix
                is_subrouter = info.framework in ("fastapi_router", "flask_blueprint")
            mount_prefixes = mounts.get(mount_key, [])
            extra = {"method": r.methods, "framework": framework}
            if r.framework in ("django", "drf"):
                # urls.py routes are mounted via include(); always suffix-matchable
                extra["maybe_prefixed"] = "1"
                full_paths = [r.path]
            elif mount_prefixes:
                full_paths = []
                for mp in sorted({p for p in mount_prefixes if p is not None}):
                    full_paths.append((mp or "") + own_prefix + r.path)
                if any(p is None for p in mount_prefixes):
                    extra["maybe_prefixed"] = "1"
                    if not full_paths:
                        full_paths = [own_prefix + r.path]
            elif is_subrouter or info is None:
                # router never seen mounted (or unknown var): unknown prefix
                extra["maybe_prefixed"] = "1"
                full_paths = [own_prefix + r.path]
            else:
                full_paths = [own_prefix + r.path]
            for fp in full_paths:
                pattern = normalize_backend(fp, framework)
                anchors.append(
                    Anchor(
                        AnchorKind.ROUTE_DEF,
                        pattern.display(),
                        fp,
                        path,
                        r.line,
                        r.detail,
                        dict(extra),
                    )
                )
    return anchors
