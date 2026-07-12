"""Tests for file-convention route extraction (Next.js / SvelteKit / Nuxt)."""

from __future__ import annotations

from seamgraph.extract.file_routes import extract_file_routes


def _one(path: str, text: str = ""):
    anchors = extract_file_routes(path, text)
    assert len(anchors) == 1, f"{path}: {anchors}"
    return anchors[0]


class TestNextPages:
    def test_simple(self) -> None:
        a = _one("pages/api/users.ts")
        assert a.key == "/api/users"
        assert a.extra["framework"] == "nextjs"

    def test_param(self) -> None:
        assert _one("pages/api/users/[id].ts").key == "/api/users/*"

    def test_index(self) -> None:
        assert _one("pages/api/users/index.ts").key == "/api/users"

    def test_catch_all(self) -> None:
        assert _one("pages/api/auth/[...nextauth].ts").key == "/api/auth/**"

    def test_src_prefix(self) -> None:
        assert _one("src/pages/api/health.js").key == "/api/health"

    def test_non_api_page_ignored(self) -> None:
        assert extract_file_routes("pages/about.tsx", "") == []

    def test_non_code_ext_ignored(self) -> None:
        assert extract_file_routes("pages/api/readme.md", "") == []


class TestNextApp:
    def test_route_ts(self) -> None:
        text = "export async function GET(req) {}\nexport const POST = handler\n"
        a = _one("app/api/users/[id]/route.ts", text)
        assert a.key == "/api/users/*"
        assert a.extra["method"] == "GET,POST"

    def test_route_group_dropped(self) -> None:
        a = _one("src/app/(dashboard)/api/stats/route.ts", "export function GET() {}")
        assert a.key == "/api/stats"
        assert a.extra["method"] == "GET"

    def test_no_exported_methods(self) -> None:
        assert _one("app/api/ping/route.ts", "// TODO").extra["method"] == ""


class TestSvelteKit:
    def test_server_route(self) -> None:
        a = _one("src/routes/api/items/[id]/+server.ts", "export const GET = ...")
        assert a.key == "/api/items/*"
        assert a.extra["framework"] == "sveltekit"
        assert a.extra["method"] == "GET"

    def test_page_not_extracted(self) -> None:
        assert extract_file_routes("src/routes/about/+page.svelte", "") == []


class TestNuxt:
    def test_api_with_method_suffix(self) -> None:
        a = _one("server/api/users/[id].get.ts")
        assert a.key == "/api/users/*"
        assert a.extra["method"] == "GET"
        assert a.extra["framework"] == "nuxt"

    def test_api_no_method(self) -> None:
        a = _one("server/api/health.ts")
        assert a.key == "/api/health"
        assert a.extra["method"] == ""

    def test_server_routes_dir(self) -> None:
        assert _one("server/routes/sitemap.xml.get.ts").key == "/sitemap.xml"


class TestNonRoutes:
    def test_random_ts_file(self) -> None:
        assert extract_file_routes("src/components/Button.tsx", "") == []

    def test_python_file(self) -> None:
        assert extract_file_routes("app/main.py", "") == []
