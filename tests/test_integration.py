"""End-to-end integration tests: index fixture repos through SeamGraph and
assert the exact seam sets, orphans, and anchor counts.

These tests use *exact counts* deliberately — they are the regression net for
double-extraction bugs (anchors added twice produce doubled seams) and for
matcher policy changes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from seamgraph.graph import SeamGraph
from seamgraph.models import AnchorKind

FIXTURES = Path(__file__).parent / "fixtures"


def _indexed(tmp_path: Path, fixture: str) -> SeamGraph:
    """Copy a fixture repo to tmp and index it there (keeps repo tree clean)."""
    root = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, root)
    g = SeamGraph(root)
    g.index()
    return g


@pytest.fixture(scope="module")
def fastapi_graph(tmp_path_factory: pytest.TempPathFactory) -> SeamGraph:
    return _indexed(tmp_path_factory.mktemp("fx"), "fastapi_react")


class TestFastapiReact:
    def test_no_anchor_duplication(self, fastapi_graph: SeamGraph) -> None:
        # regression: DATABASE_URL is read exactly once in backend/main.py
        reads = [
            a
            for a in fastapi_graph.query_anchors(kind=AnchorKind.ENV_READ.value)
            if a["key"] == "DATABASE_URL"
        ]
        assert len(reads) == 1
        assert reads[0]["path"] == "backend/main.py"

    def test_env_seams_exact(self, fastapi_graph: SeamGraph) -> None:
        # DATABASE_URL: 1 read x 3 defs (.env, compose api, compose worker)
        seams = [s for s in fastapi_graph.query_seams(kind="env") if s["key"] == "DATABASE_URL"]
        assert len(seams) == 3
        def_paths = sorted(s["def_path"] for s in seams)
        assert def_paths == [".env", "docker-compose.yml", "docker-compose.yml"]

    def test_js_env_read_linked(self, fastapi_graph: SeamGraph) -> None:
        env_seams = fastapi_graph.query_seams(kind="env")
        seams = [s for s in env_seams if s["key"] == "REACT_APP_API_URL"]
        assert len(seams) == 1
        assert seams[0]["use_path"] == "frontend/src/api.js"
        assert seams[0]["def_path"] == ".env"

    def test_route_seams_link_frontend_to_backend(self, fastapi_graph: SeamGraph) -> None:
        route_seams = fastapi_graph.query_seams(kind="route")
        pairs = {(s["use_path"], s["def_path"], s["key"]) for s in route_seams}
        # template-literal fetch matches the {user_id} param route
        assert ("frontend/src/api.js", "backend/main.py", "/api/v1/users/*") in pairs
        assert ("frontend/src/api.js", "backend/main.py", "/api/v1/users") in pairs
        assert ("frontend/src/api.js", "backend/main.py", "/health") in pairs

    def test_route_methods_respected(self, fastapi_graph: SeamGraph) -> None:
        param_seams = [
            s for s in fastapi_graph.query_seams(kind="route") if s["key"] == "/api/v1/users/*"
        ]
        # the method-less fetch legitimately matches BOTH the GET and DELETE
        # defs (2 seams, ambiguous); the explicit DELETE fetch matches only the
        # DELETE def (1 seam). A later call's `method:` option must never leak
        # into an earlier one (regression for the fixed-window bug).
        assert len(param_seams) == 3
        delete_call_seams = [
            s for s in param_seams if "method: 'DELETE'" in s["use_raw"] or s["use_line"] == 20
        ]
        assert len(delete_call_seams) == 1
        assert delete_call_seams[0]["def_detail"].startswith("@router.delete")

    def test_unknown_route_is_orphan_warn(self, fastapi_graph: SeamGraph) -> None:
        orphans = fastapi_graph.query_orphans(severity="warn")
        settings_orphans = [o for o in orphans if o["problem"] == "route-call-unmatched"]
        assert len(settings_orphans) == 1
        assert settings_orphans[0]["key"] == "/api/v1/settings"

    def test_task_seam(self, fastapi_graph: SeamGraph) -> None:
        seams = fastapi_graph.query_seams(kind="task")
        assert len(seams) == 1
        assert seams[0]["key"] == "app.tasks.send_welcome_email"
        assert seams[0]["use_path"] == "backend/worker.py"
        assert seams[0]["def_path"] == "backend/tasks.py"

    def test_unused_env_def_is_info(self, fastapi_graph: SeamGraph) -> None:
        infos = fastapi_graph.query_orphans(severity="info")
        stripe = [o for o in infos if o["key"] == "STRIPE_API_KEY"]
        assert len(stripe) == 1
        assert stripe[0]["problem"] == "env-def-unused"


@pytest.fixture(scope="module")
def flask_graph(tmp_path_factory: pytest.TempPathFactory) -> SeamGraph:
    return _indexed(tmp_path_factory.mktemp("fx"), "flask_app")


class TestFlaskApp:
    def test_template_seams(self, flask_graph: SeamGraph) -> None:
        seams = flask_graph.query_seams(kind="template")
        keys = sorted(s["key"] for s in seams)
        assert keys == ["about.html", "contact.html", "index.html"]
        for s in seams:
            assert s["use_path"] == "app.py"
            assert s["def_path"].startswith("templates/")

    def test_urlname_seam_flask_endpoint(self, flask_graph: SeamGraph) -> None:
        seams = [s for s in flask_graph.query_seams(kind="urlname") if s["key"] == "index"]
        assert len(seams) == 1
        assert seams[0]["use_detail"] == "url_for(...)"

    def test_env_seams(self, flask_graph: SeamGraph) -> None:
        env_keys = {s["key"] for s in flask_graph.query_seams(kind="env")}
        assert env_keys == {"SECRET_KEY", "DATABASE_URL"}


@pytest.fixture(scope="module")
def django_graph(tmp_path_factory: pytest.TempPathFactory) -> SeamGraph:
    return _indexed(tmp_path_factory.mktemp("fx"), "django_app")


class TestDjangoApp:
    def test_urlname_seams(self, django_graph: SeamGraph) -> None:
        seams = django_graph.query_seams(kind="urlname")
        by_key: dict[str, int] = {}
        for s in seams:
            by_key[s["key"]] = by_key.get(s["key"], 0) + 1
        # order-detail: {% url %} in order_list.html + reverse() in views.py
        assert by_key["order-detail"] == 2
        assert by_key["order-invoice"] == 1

    def test_template_seams_include_extends(self, django_graph: SeamGraph) -> None:
        seams = django_graph.query_seams(kind="template")
        base_refs = [s for s in seams if s["key"] == "base.html"]
        # order_list, order_detail, invoice all extend base.html
        assert len(base_refs) == 3
        render_refs = {s["key"] for s in seams if s["use_path"].endswith("views.py")}
        assert render_refs == {
            "shop/order_list.html",
            "shop/order_detail.html",
            "shop/invoice.html",
        }

    def test_setting_seam(self, django_graph: SeamGraph) -> None:
        setting_seams = django_graph.query_seams(kind="setting")
        seams = [s for s in setting_seams if s["key"] == "STRIPE_API_KEY"]
        assert len(seams) == 1
        assert seams[0]["use_path"] == "shop/views.py"
        assert seams[0]["def_path"] == "shop/settings.py"

    def test_django_routes_extracted(self, django_graph: SeamGraph) -> None:
        defs = django_graph.query_anchors(kind=AnchorKind.ROUTE_DEF.value)
        keys = {a["key"] for a in defs}
        assert "/orders" in keys
        assert "/orders/*" in keys


class TestIncremental:
    def test_reindex_unchanged_is_noop(self, tmp_path: Path) -> None:
        root = tmp_path / "fastapi_react"
        shutil.copytree(FIXTURES / "fastapi_react", root)
        g = SeamGraph(root)
        first = g.index()
        assert first["files_changed"] > 0
        second = g.index()
        assert second["files_changed"] == 0

    def test_file_edit_triggers_reindex(self, tmp_path: Path) -> None:
        root = tmp_path / "fastapi_react"
        shutil.copytree(FIXTURES / "fastapi_react", root)
        g = SeamGraph(root)
        g.index()
        env = root / ".env"
        env.write_text(env.read_text(encoding="utf-8") + "NEW_FLAG=1\n", encoding="utf-8")
        stats = g.index()
        assert stats["files_changed"] == 1
        defs = [a for a in g.query_anchors(kind=AnchorKind.ENV_DEF.value) if a["key"] == "NEW_FLAG"]
        assert len(defs) == 1

    def test_file_delete_removes_anchors(self, tmp_path: Path) -> None:
        root = tmp_path / "fastapi_react"
        shutil.copytree(FIXTURES / "fastapi_react", root)
        g = SeamGraph(root)
        g.index()
        (root / "backend" / "worker.py").unlink()
        g.index()
        task_calls = g.query_anchors(kind=AnchorKind.TASK_CALL.value)
        assert task_calls == []
