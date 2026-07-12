"""CLI entry point: ``seamgraph index | map | for <ref> | impact <range> | check | serve``.

All commands output JSON by default (``--json``), or human-readable tables.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import api


def _json_out(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _table_out(rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    """Simple table printer."""
    if not rows:
        print("(no results)")
        return
    if columns is None:
        columns = list(rows[0].keys())
    widths = {c: max(len(c), max(len(str(r.get(c, ""))[:60]) for r in rows)) for c in columns}
    header = " | ".join(c.ljust(widths[c]) for c in columns)
    print(header)
    print("-+-".join("-" * widths[c] for c in columns))
    for r in rows:
        print(" | ".join(str(r.get(c, ""))[:60].ljust(widths[c]) for c in columns))


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
            print(f"  [{s['kind']}] {s['key']} — {s.get('impact_side', '?')}")
            print(f"    use: {s['use_path']}:{s['use_line']}")
            print(f"    def: {s['def_path']}:{s['def_line']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = api.check(root)
    if args.json:
        _json_out(result)
    else:
        stats = result["stats"]
        print(
            f"Indexed {stats['files_scanned']} files,"
            f" {stats['anchors']} anchors, {stats['seams']} seams"
        )
        warns = result["warnings"]
        if warns:
            print(f"\nWARN {len(warns)} warnings:")
            for w in warns:
                print(f"  {w['problem']:30s}  {w['key']:30s}  {w['path']}:{w['line']}")
        else:
            print("OK No warnings")
    return 1 if result["warning_count"] > 0 else 0


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
                status = "WARN uncalled"
            else:
                status = "WARN unmatched"
            print(f"  {status} {entry['route']}")
            for d in defs:
                method = f" [{d.get('method', '')}]" if d.get("method") else ""
                print(f"      def: {d['path']}:{d['line']}{method}")
            for c in calls:
                method = f" [{c.get('method', '')}]" if c.get("method") else ""
                print(f"      call: {c['path']}:{c['line']}{method}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from .mcp_server import run_server
    except ImportError:
        print("MCP support requires the 'mcp' extra: pip install seamgraph[mcp]", file=sys.stderr)
        return 1
    run_server(Path(args.root).resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seamgraph",
        description="Cross-artifact seam graph for coding agents.",
    )
    p.add_argument("--root", default=".", help="Repository root (default: current directory)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    sub = p.add_subparsers(dest="command", required=True)

    # index
    idx = sub.add_parser("index", help="Index the repository")
    idx.add_argument("--full", action="store_true", help="Force full re-index")

    # map
    mp = sub.add_parser("map", help="Show the seam map")
    mp.add_argument("--kind", help="Filter by seam kind (env, route, template, ...)")

    # for
    fr = sub.add_parser("for", help="Find seams for a reference")
    fr.add_argument("ref", help="Reference string (env var name, route path, file path, ...)")
    fr.add_argument("--kind", help="Filter by seam kind")

    # impact
    imp = sub.add_parser("impact", help="Impact analysis for changed files")
    imp.add_argument("paths", nargs="+", help="Changed file paths (repo-relative)")

    # check
    sub.add_parser("check", help="Index + report warnings (CI-friendly)")

    # env
    sub.add_parser("env", help="Show env variable table")

    # routes
    sub.add_parser("routes", help="Show route table")

    # serve
    sub.add_parser("serve", help="Start MCP stdio server")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "index": cmd_index,
        "map": cmd_map,
        "for": cmd_for,
        "impact": cmd_impact,
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
