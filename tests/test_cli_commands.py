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
