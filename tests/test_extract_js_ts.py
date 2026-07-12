"""Tests for the JS/TS extractor."""

from __future__ import annotations

from seamgraph.extract.js_ts import extract_js_ts
from seamgraph.models import AnchorKind


class TestFetch:
    def test_fetch_literal(self) -> None:
        src = """const res = await fetch('/api/users');"""
        anchors = extract_js_ts("api.js", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
        assert "/api/users" in calls[0].key

    def test_fetch_template_literal(self) -> None:
        src = """const res = await fetch(`/api/users/${userId}`);"""
        anchors = extract_js_ts("api.js", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
        assert "/api/users" in calls[0].key

    def test_fetch_with_method(self) -> None:
        src = """const res = await fetch('/api/users', { method: 'POST' });"""
        anchors = extract_js_ts("api.js", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
        assert calls[0].extra.get("method") == "POST"

    def test_skip_external_url(self) -> None:
        src = """const res = await fetch('https://api.example.com/data');"""
        anchors = extract_js_ts("api.js", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 0

    def test_keep_localhost_url(self) -> None:
        src = """const res = await fetch('http://localhost:8000/api/health');"""
        anchors = extract_js_ts("api.js", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1


class TestAxios:
    def test_axios_get(self) -> None:
        src = """const res = await axios.get('/api/users');"""
        anchors = extract_js_ts("api.ts", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
        assert calls[0].extra.get("method") == "GET"

    def test_api_client_post(self) -> None:
        src = """const res = await apiClient.post('/api/orders');"""
        anchors = extract_js_ts("api.ts", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1


class TestEnvReads:
    def test_process_env(self) -> None:
        src = """const url = process.env.API_URL;"""
        anchors = extract_js_ts("config.js", src)
        envs = [a for a in anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "API_URL"

    def test_process_env_bracket(self) -> None:
        src = """const url = process.env["API_URL"];"""
        anchors = extract_js_ts("config.js", src)
        envs = [a for a in anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "API_URL"

    def test_import_meta_env(self) -> None:
        src = """const url = import.meta.env.VITE_API_URL;"""
        anchors = extract_js_ts("config.ts", src)
        envs = [a for a in anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "VITE_API_URL"

    def test_skip_builtin_vite_env(self) -> None:
        src = """const mode = import.meta.env.MODE;"""
        anchors = extract_js_ts("config.ts", src)
        envs = [a for a in anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 0  # MODE is a Vite builtin


class TestExpressRoutes:
    def test_express_get(self) -> None:
        src = """app.get('/api/users', handler);"""
        anchors = extract_js_ts("server.js", src)
        defs = [a for a in anchors if a.kind is AnchorKind.ROUTE_DEF]
        assert len(defs) == 1
        assert "/api/users" in defs[0].key

    def test_router_post(self) -> None:
        src = """router.post('/orders', createOrder);"""
        anchors = extract_js_ts("routes.js", src)
        defs = [a for a in anchors if a.kind is AnchorKind.ROUTE_DEF]
        assert len(defs) == 1
        assert defs[0].extra.get("maybe_prefixed") == "1"  # router, not app


class TestEdgeCases:
    def test_skip_minified(self) -> None:
        src = "x" * 6000  # one very long line
        anchors = extract_js_ts("bundle.js", src)
        assert len(anchors) == 0

    def test_skip_min_files(self) -> None:
        src = """const res = await fetch('/api/users');"""
        anchors = extract_js_ts("app.min.js", src)
        assert len(anchors) == 0

    def test_vue_file(self) -> None:
        src = """const res = await fetch('/api/users');"""
        anchors = extract_js_ts("App.vue", src)
        calls = [a for a in anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
