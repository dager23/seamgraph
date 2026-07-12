"""Tests for the config module."""

from __future__ import annotations

from pathlib import Path

from seamgraph.config import Config, load_config


class TestConfig:
    def test_defaults(self) -> None:
        cfg = Config()
        assert cfg.max_commits == 2000
        assert cfg.corroborate_support == 3
        assert cfg.exclude == ()

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg.max_commits == 2000  # defaults

    def test_load_seamgraph_toml(self, tmp_path: Path) -> None:
        (tmp_path / "seamgraph.toml").write_text('max_commits = 500\nexclude = ["vendor"]\n')
        cfg = load_config(tmp_path)
        assert cfg.max_commits == 500
        assert cfg.exclude == ("vendor",)

    def test_load_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.seamgraph]\nmax_commits = 100\n")
        cfg = load_config(tmp_path)
        assert cfg.max_commits == 100

    def test_seamgraph_toml_takes_precedence(self, tmp_path: Path) -> None:
        (tmp_path / "seamgraph.toml").write_text("max_commits = 999\n")
        (tmp_path / "pyproject.toml").write_text("[tool.seamgraph]\nmax_commits = 111\n")
        cfg = load_config(tmp_path)
        assert cfg.max_commits == 999
