"""Tests for the CLI module."""
from __future__ import annotations

from seamgraph.cli import build_parser


class TestParser:
    def test_index(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["index"])
        assert args.command == "index"

    def test_index_full(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["index", "--full"])
        assert args.full is True

    def test_map(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["map"])
        assert args.command == "map"

    def test_for_ref(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["for", "DATABASE_URL"])
        assert args.command == "for"
        assert args.ref == "DATABASE_URL"

    def test_impact(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["impact", "app.py", "config.py"])
        assert args.command == "impact"
        assert args.paths == ["app.py", "config.py"]

    def test_check(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["check"])
        assert args.command == "check"

    def test_json_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--json", "map"])
        assert args.json is True

    def test_root_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--root", "/some/path", "index"])
        assert args.root == "/some/path"
