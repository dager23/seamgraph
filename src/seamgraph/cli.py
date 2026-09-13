"""CLI entry point: ``seamgraph index | map | for <ref> | impact <paths> | check | serve``.

Human-readable output by default; ``--json`` for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import api

#: Human-readable output truncates long finding lists; --json always has all.
_MAX_LISTED = 25


def _json_out(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _print_findings(findings: list[dict[str, Any]]) -> None:
    for f in findings[:_MAX_LISTED]:
        print(f"  {f['problem']:30s}  {f['key']:30s}  {f['path']}:{f['line']}")
    if len(findings) > _MAX_LISTED:
        rest = len(findings) - _MAX_LISTED
        print(f"  ... and {rest} more (use --json for the full list)")


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    stats = api.index(root, full=args.full)
    if args.json:
        _json_out(stats)
    else:
        print(f"Indexed {stats['files_scanned']} files ({stats['files_changed']} changed)")
        print(f"  Anchors: {stats['anchors']}")
        print(f"  Seams:   {stats['seams']}")
        print(f"  Orphans: {stats['orphans']}")
        print(f"  Discoveries: {stats['discoveries']}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.seam_map(root, kind=args.kind)
    if args.json:
        _json_out(result)
    else:
        summary = result["summary"]
        print(
            f"Seam map: {summary['total_seams']} seams,"
            f" {summary['total_orphans']} orphans,"
            f" {summary['total_discoveries']} discoveries"
        )
        if summary.get("by_kind"):
            by_kind = sorted(summary["by_kind"].items())
            print("  By kind:", ", ".join(f"{k}={v}" for k, v in by_kind))
        if summary.get("by_grade"):
            by_grade = sorted(summary["by_grade"].items())
            print("  By grade:", ", ".join(f"{k}={v}" for k, v in by_grade))
        print()
        if result["seams"]:
            for s in result["seams"][:50]:
                grade_tag = f" [{s['grade']}]" if s["grade"] != "anchored" else ""
                note_tag = f" ({s['note']})" if s.get("note") else ""
                print(f"  {s['kind']:10s} {s['key'][:50]:50s}{grade_tag}{note_tag}")
                print(f"    use: {s['use_path']}:{s['use_line']}  <- {s['use_detail']}")
                print(f"    def: {s['def_path']}:{s['def_line']}  <- {s['def_detail']}")
            if len(result["seams"]) > 50:
                print(f"  ... and {len(result['seams']) - 50} more (use --json for full output)")
    return 0


def cmd_for(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.seams_for(root, ref=args.ref, kind=args.kind)
    if args.json:
        _json_out(result)
    else:
        print(f"Seams for '{args.ref}': {result['count']} found")
        for s in result["seams"]:
            print(f"  [{s['kind']}] {s['key']}")
            print(f"    use: {s['use_path']}:{s['use_line']}")
            print(f"    def: {s['def_path']}:{s['def_line']}")
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.impact(root, paths=args.paths)
    if args.json:
        _json_out(result)
    else:
        print(f"Impact analysis: {result['count']} seams cross the change boundary")
        for s in result["impacted_seams"]:
            print(f"  [{s['kind']}] {s['key']} - {s.get('impact_side', '?')}")
            print(f"    use: {s['use_path']}:{s['use_line']}")
            print(f"    def: {s['def_path']}:{s['def_line']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.check(root, strict=args.strict)
    if args.json:
        _json_out(result)
    else:
        stats = result["stats"]
        print(
            f"Indexed {stats['files_scanned']} files,"
            f" {stats['anchors']} anchors, {stats['seams']} seams"
        )
        warns = result["warnings"]
        infos = result["infos"]
        if warns:
            print(f"\nWARN {len(warns)} warnings:")
            _print_findings(warns)
        if infos:
            label = "failing (--strict)" if result["strict"] else "not failing"
            print(f"\nINFO {len(infos)} dangling references [{label}]:")
            _print_findings(infos)
            if not result["strict"]:
                print("  (seamgraph could not find the definition side of these")
                print("   namespaces, so it will not fail the build on them;")
                print("   re-run with --strict to treat them as errors)")
        if not warns and not infos:
            print("OK No warnings")
    return 1 if result["failing_count"] > 0 else 0


def cmd_env(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.env_table(root)
    if args.json:
        _json_out(result)
    else:
        print(f"Env variables: {result['count']}")
        for entry in result["env_vars"]:
            defs = entry.get("definitions", [])
            reads = entry.get("reads", [])
            if defs and reads:
                status = "OK"
            elif defs:
                status = "WARN unused"
            else:
                status = "WARN undefined"
            print(f"  {status} {entry['name']}")
            for d in defs:
                print(f"      def: {d['path']}:{d['line']} ({d.get('source', d['detail'])})")
            for r in reads:
                print(f"      use: {r['path']}:{r['line']} ({r.get('source', r['detail'])})")
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.route_table(root)
    if args.json:
        _json_out(result)
    else:
        print(f"Routes: {result['count']}")
        for entry in result["routes"]:
            defs = entry.get("definitions", [])
            calls = entry.get("calls", [])
            if defs and calls:
                status = "OK"
            elif defs:
                status = "uncalled"
            else:
                # unmatched calls carry the severity the matcher assigned
                worst = "info"
                for c in calls:
                    if c.get("severity") == "warn":
                        worst = "warn"
                status = "WARN no-handler" if worst == "warn" else "info no-handler"
            print(f"  {status} {entry['route']}")
            for d in defs:
                method = f" [{d.get('method', '')}]" if d.get("method") else ""
                print(f"      def: {d['path']}:{d['line']}{method}")
            for c in calls:
                method = f" [{c.get('method', '')}]" if c.get("method") else ""
                url = f" {c['url']}" if c.get("url") else ""
                print(f"      call: {c['path']}:{c['line']}{method}{url}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.verify(root, ref=args.ref)
    if args.json:
        _json_out(result)
    else:
        state = "connected" if result["connected"] else "NOT connected"
        print(f"'{args.ref}': {state} ({len(result['seams'])} seam(s))")
        for s in result["seams"]:
            print(f"  [{s['kind']}] {s['key']}")
            print(f"    use: {s['use_path']}:{s['use_line']}")
            print(f"    def: {s['def_path']}:{s['def_line']}")
        for o in result["orphans"]:
            print(f"  unmatched: {o['problem']} {o['key']} @ {o['path']}:{o['line']}")
    return 0 if result["connected"] else 1


def cmd_serve(args: argparse.Namespace) -> int:
    # Imported lazily so other commands never pay for loading the MCP SDK.
    # Importing this module succeeds even without the SDK (the server class is
    # resolved at runtime), so availability must be checked explicitly -- and
    # before indexing, which would otherwise run only to end in a traceback.
    from .mcp_server import HAS_MCP, run_server

    if not HAS_MCP:
        print(
            "seamgraph serve needs the MCP SDK: pip install 'seamgraph[mcp]'",
            file=sys.stderr,
        )
        return 1
    run_server(Path(args.root).resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Global flags are accepted on both sides of the subcommand, so both
    # `seamgraph --json map` and the more conventional `seamgraph map --json`
    # work. The sub-level copies use SUPPRESS so that omitting them does not
    # overwrite a value already given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        default=argparse.SUPPRESS,
        help="Repository root (default: current directory)",
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Output JSON",
    )

    # NB: the top-level flags are defined directly (not via ``parents``) and
    # carry the real defaults. ``set_defaults`` must not be used here: it
    # mutates ``.default`` on the shared parent actions, which would make the
    # subparser copies overwrite a value given before the subcommand.
    p = argparse.ArgumentParser(
        prog="seamgraph",
        description="Cross-artifact seam graph for coding agents.",
    )
    p.add_argument("--root", default=".", help="Repository root (default: current directory)")
    p.add_argument("--json", action="store_true", default=False, help="Output JSON")
    sub = p.add_subparsers(dest="command", required=True)

    # index
    idx = sub.add_parser("index", help="Index the repository", parents=[common])
    idx.add_argument("--full", action="store_true", help="Force full re-index")

    # map
    mp = sub.add_parser("map", help="Show the seam map", parents=[common])
    mp.add_argument("--kind", help="Filter by seam kind (env, route, template, ...)")

    # for
    fr = sub.add_parser("for", help="Find seams for a reference", parents=[common])
    fr.add_argument("ref", help="Reference string (env var name, route path, file path, ...)")
    fr.add_argument("--kind", help="Filter by seam kind")

    # impact
    imp = sub.add_parser("impact", help="Impact analysis for changed files", parents=[common])
    imp.add_argument("paths", nargs="+", help="Changed file paths (repo-relative)")

    # verify
    vf = sub.add_parser("verify", help="Check whether a reference is connected", parents=[common])
    vf.add_argument("ref", help="Reference to verify")

    # check
    chk = sub.add_parser("check", help="Index + report warnings (CI-friendly)", parents=[common])
    chk.add_argument(
        "--strict",
        action="store_true",
        help="Also fail on informational dangling references",
    )

    # env
    sub.add_parser("env", help="Show env variable table", parents=[common])

    # routes
    sub.add_parser("routes", help="Show route table", parents=[common])

    # serve
    sub.add_parser("serve", help="Start MCP stdio server", parents=[common])

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "index": cmd_index,
        "map": cmd_map,
        "for": cmd_for,
        "impact": cmd_impact,
        "verify": cmd_verify,
        "check": cmd_check,
        "env": cmd_env,
        "routes": cmd_routes,
        "serve": cmd_serve,
    }
    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
