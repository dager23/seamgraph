"""Tests for the co-change mining module."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from seamgraph.cochange import (
    CochangePair,
    corroborate_seams,
    discover_statistical,
    mine_cochange,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=30,
    )


class TestMine:
    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        _git(tmp_path, "init", "-b", "main")
        (tmp_path / "api.py").write_text("# v0\n")
        (tmp_path / "web.ts").write_text("// v0\n")
        (tmp_path / "other.py").write_text("# v0\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "init")
        # api.py and web.ts co-change three times; other.py changes alone once
        for i in range(1, 4):
            (tmp_path / "api.py").write_text(f"# v{i}\n")
            (tmp_path / "web.ts").write_text(f"// v{i}\n")
            _git(tmp_path, "add", "-A")
            _git(tmp_path, "commit", "-m", f"change {i}")
        (tmp_path / "other.py").write_text("# v1\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "solo change")
        return tmp_path

    def test_mine_real_repo(self, repo: Path) -> None:
        pairs = {(p.path_a, p.path_b): p for p in mine_cochange(repo)}
        assert ("api.py", "web.ts") in pairs
        got = pairs[("api.py", "web.ts")]
        # 3 co-changes + the init commit where all three files appeared
        assert got.support == 4
        assert got.confidence > 0.5

    def test_mine_paths_filter(self, repo: Path) -> None:
        pairs = mine_cochange(repo, paths={"api.py", "web.ts"})
        keys = {(p.path_a, p.path_b) for p in pairs}
        assert keys == {("api.py", "web.ts")}

    def test_mine_non_git_dir(self, tmp_path: Path) -> None:
        assert mine_cochange(tmp_path) == []


class TestCorroborate:
    def test_corroboration(self) -> None:
        seam_pairs = {("app.py", "frontend.js")}
        cochange = [
            CochangePair("app.py", "frontend.js", support=5, confidence=0.4),
            CochangePair("app.py", "config.py", support=2, confidence=0.1),
        ]
        result = corroborate_seams(seam_pairs, cochange, min_support=3, min_confidence=0.25)
        assert ("app.py", "frontend.js") in result
        assert result[("app.py", "frontend.js")].support == 5

    def test_below_threshold(self) -> None:
        seam_pairs = {("a.py", "b.py")}
        cochange = [
            CochangePair("a.py", "b.py", support=1, confidence=0.1),
        ]
        result = corroborate_seams(seam_pairs, cochange, min_support=3, min_confidence=0.25)
        assert len(result) == 0

    def test_pair_normalization(self) -> None:
        # Pass pair in reverse order
        seam_pairs = {("z.py", "a.py")}
        cochange = [
            CochangePair("a.py", "z.py", support=5, confidence=0.5),
        ]
        result = corroborate_seams(seam_pairs, cochange, min_support=3, min_confidence=0.25)
        assert ("a.py", "z.py") in result


class TestDiscover:
    def test_discover_statistical(self) -> None:
        seam_pairs = {("a.py", "b.yml")}  # this pair has a static seam
        cochange = [
            CochangePair("a.py", "b.yml", support=10, confidence=0.8),
            CochangePair("c.py", "d.yml", support=8, confidence=0.6),  # no static seam
            CochangePair("e.py", "f.yml", support=2, confidence=0.1),  # below threshold
        ]
        result = discover_statistical(cochange, seam_pairs, min_support=5, min_confidence=0.5)
        assert len(result) == 1
        assert result[0].path_a == "c.py"
        assert result[0].path_b == "d.yml"

    def test_discover_skips_same_artifact_class(self) -> None:
        # two Python files co-changing is ordinary import coupling, not a seam;
        # same for two JS/TS files — these stay invisible by design
        cochange = [
            CochangePair("c.py", "d.py", support=8, confidence=0.6),
            CochangePair("app.js", "util.ts", support=8, confidence=0.6),
        ]
        result = discover_statistical(cochange, set(), min_support=5, min_confidence=0.5)
        assert result == []

    def test_discover_cross_artifact_kept(self) -> None:
        cochange = [CochangePair("api.py", "web/app.ts", support=6, confidence=0.55)]
        result = discover_statistical(cochange, set(), min_support=5, min_confidence=0.5)
        assert len(result) == 1
