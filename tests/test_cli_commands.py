"""CLI command tests: run every subcommand end-to-end on the fastapi_react
fixture (both human and --json output) and check exit codes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from seamgraph.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli") / "fastapi_react"
    shutil.copytree(FIXTURES / "fastapi_react", root)
    assert main(["--root", str(root), "index"]) == 0
    return root


def _json_run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict]:
    code = main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)


class TestCommands:
    def test_index_json(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "index"])
        assert code == 0
        assert data["files_scanned"] > 0

    def test_map_json(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "map"])
        assert code == 0
        assert data["summary"]["total_seams"] > 0
        assert "env" in data["summary"]["by_kind"]

    def test_map_human(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--root", str(repo), "map"]) == 0
        out = capsys.readouterr().out
        assert "Seam map:" in out

    def test_for_json(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "for", "DATABASE_URL"])
        assert code == 0
        assert data["count"] == 3

    def test_for_human(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--root", str(repo), "for", "REDIS_URL"]) == 0
        out = capsys.readouterr().out
        assert "REDIS_URL" in out

    def test_impact_json(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "impact", "backend/main.py"])
        assert code == 0
        assert data["count"] > 0
        sides = {s["impact_side"] for s in data["impacted_seams"]}
        assert "definition changed" in sides or "use changed" in sides

    def test_check_exits_nonzero_on_warnings(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # fixture contains a deliberate unmatched fetch('/api/v1/settings')
        code = main(["--root", str(repo), "check"])
        out = capsys.readouterr().out
        assert code == 1
        assert "route-call-unmatched" in out

    def test_env_human(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--root", str(repo), "env"]) == 0
        out = capsys.readouterr().out
        assert "DATABASE_URL" in out
        assert "WARN unused" in out  # STRIPE_API_KEY defined but never read

    def test_routes_json(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "routes"])
        assert code == 0
        routes = {r["route"] for r in data["routes"]}
        assert "/api/v1/users" in routes

    def test_routes_human(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--root", str(repo), "routes"]) == 0
        out = capsys.readouterr().out
        assert "/health" in out


class TestCheckReporting:
    """`check` must surface dangling references, not silently drop them.

    Regression: a frontend call to a route with no handler -- the canonical
    case the tool exists to catch -- was invisible in `check` output whenever
    the matcher rated it informational.
    """

    def test_dangling_reference_is_reported(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, data = _json_run(capsys, ["--root", str(repo), "--json", "check"])
        keys = {i["key"] for i in data["infos"]} | {w["key"] for w in data["warnings"]}
        assert "/api/v1/settings" in keys  # deliberate dead call in the fixture
        assert code in (0, 1)

    def test_infos_exclude_non_defects(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, data = _json_run(capsys, ["--root", str(repo), "--json", "check"])
        problems = {i["problem"] for i in data["infos"]}
        # unused definitions and externally-provided env vars are not defects
        assert not any(p.endswith(("-def-unused", "-def-uncalled")) for p in problems)
        assert "env-use-unmatched" not in problems

    def test_dead_call_appears_in_human_output(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["--root", str(repo), "check"])
        out = capsys.readouterr().out
        assert "/api/v1/settings" in out


class TestCheckInfoSeverity:
    """A dead call in a namespace seamgraph cannot vouch for is informational.

    It must still be *shown* (regression: it used to be dropped entirely), and
    --strict must turn it into a build failure.
    """

    BACKEND = """
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/users/{uid}")
async def get_user(uid: int):
    return {}
"""

    FRONTEND = """
export const dead = () => fetch("/api/does-not-exist");
"""

    @pytest.fixture()
    def small_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "backend").mkdir()
        (tmp_path / "frontend").mkdir()
        (tmp_path / "backend" / "main.py").write_text(self.BACKEND, encoding="utf-8")
        (tmp_path / "frontend" / "api.js").write_text(self.FRONTEND, encoding="utf-8")
        return tmp_path

    def test_info_listed_and_not_failing(
        self, small_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--root", str(small_repo), "check"])
        out = capsys.readouterr().out
        assert code == 0
        assert "dangling references" in out
        assert "/api/does-not-exist" in out

    def test_strict_fails_on_the_same_repo(self, small_repo: Path) -> None:
        assert main(["--root", str(small_repo), "check"]) == 0
        assert main(["--root", str(small_repo), "check", "--strict"]) == 1
