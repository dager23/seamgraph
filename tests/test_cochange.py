"""Tests for the co-change mining module."""
from __future__ import annotations

from seamgraph.cochange import CochangePair, corroborate_seams, discover_statistical


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
