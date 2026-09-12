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


class TestGlobalFlagPositions:
    """Both `seamgraph --json map` and `seamgraph map --json` must work.

    Regression: the sub-level copies of --root/--json once overwrote a value
    given before the subcommand (argparse ``set_defaults`` mutates ``.default``
    on the shared parent actions).
    """

    def test_json_before_and_after_subcommand(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["--json", "map"]).json is True
        assert parser.parse_args(["map", "--json"]).json is True
        assert parser.parse_args(["map"]).json is False

    def test_root_before_and_after_subcommand(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["--root", "X", "map"]).root == "X"
        assert parser.parse_args(["map", "--root", "X"]).root == "X"
        assert parser.parse_args(["map"]).root == "."

    def test_both_flags_after_subcommand_with_positional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["for", "A", "--json", "--root", "X"])
        assert (args.json, args.root, args.ref) == (True, "X", "A")

    def test_every_subcommand_accepts_global_flags(self) -> None:
        parser = build_parser()
        argv_for = {
            "index": ["index"],
            "map": ["map"],
            "for": ["for", "REF"],
            "impact": ["impact", "a.py"],
            "verify": ["verify", "REF"],
            "check": ["check"],
            "env": ["env"],
            "routes": ["routes"],
            "serve": ["serve"],
        }
        for name, argv in argv_for.items():
            args = parser.parse_args([*argv, "--json"])
            assert args.json is True, name
            assert args.command == name


class TestVerifyCommand:
    def test_verify_parses(self) -> None:
        args = build_parser().parse_args(["verify", "DATABASE_URL"])
        assert args.command == "verify"
        assert args.ref == "DATABASE_URL"
