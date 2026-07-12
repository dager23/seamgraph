"""MCP stdio server for seamgraph (optional extra ``seamgraph[mcp]``).

Exposes tools:
- ``seam_map``: Get the full seam map (overview for an agent starting a task)
- ``seams_for``: Find seams related to a specific reference
- ``impact``: Find seams crossing a change boundary
- ``verify``: Check if a reference is connected on both sides
- ``env_table``: Get the env-variable cross-reference table
- ``route_table``: Get the route cross-reference table
- ``check``: Index + report warnings (CI integration)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from . import api


def _result(data: Any) -> list[Any]:
    """Wrap API result as MCP TextContent."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def create_server(root: Path) -> Any:
    if not HAS_MCP:
        raise ImportError("MCP support requires: pip install seamgraph[mcp]")

    server = Server("seamgraph")

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="seam_map",
                description=(
                    "Get the seam map: all cross-artifact seams in this repo "
                    "(env chains, route links, template refs, url-names, tasks, scripts). "
                    "Use this first to understand what's connected."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "description": (
                                "Filter by seam kind: env, route,"
                                " template, urlname, task, script, setting"
                            ),
                        },
                    },
                },
            ),
            Tool(
                name="seams_for",
                description=(
                    "Find seams related to a specific reference (env var name, route path, "
                    "template name, file path). Returns the exact connections with evidence — "
                    "use this instead of grep when you need to find what's connected."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": (
                                "Reference to search for"
                                " (e.g. 'DATABASE_URL',"
                                " '/api/users', 'base.html')"
                            ),
                        },
                        "kind": {
                            "type": "string",
                            "description": "Filter by seam kind",
                        },
                    },
                    "required": ["ref"],
                },
            ),
            Tool(
                name="impact",
                description=(
                    "Given changed files, find seams that cross the change boundary. "
                    "These are the connections where one side changed and the other didn't — "
                    "the seams you need to verify won't break."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of changed file paths (repo-relative)",
                        },
                    },
                    "required": ["paths"],
                },
            ),
            Tool(
                name="verify",
                description=(
                    "Verify a single reference: is it connected on both sides? "
                    "Use after making a change to confirm nothing is broken."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": "Reference to verify",
                        },
                    },
                    "required": ["ref"],
                },
            ),
            Tool(
                name="env_table",
                description=(
                    "Get a comprehensive env-variable cross-reference table: "
                    "where each variable is defined and read, across .env, compose, "
                    "Dockerfile, k8s, CI, and code."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="route_table",
                description=(
                    "Get a route cross-reference table: backend definitions and "
                    "frontend/test client calls for each route path."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="check",
                description=(
                    "Re-index and report warnings: unmatched route calls, undefined "
                    "env vars, missing templates. CI-friendly."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        if name == "seam_map":
            return _result(api.seam_map(root, kind=arguments.get("kind")))
        elif name == "seams_for":
            return _result(api.seams_for(root, ref=arguments["ref"], kind=arguments.get("kind")))
        elif name == "impact":
            return _result(api.impact(root, paths=arguments["paths"]))
        elif name == "verify":
            return _result(api.verify(root, ref=arguments["ref"]))
        elif name == "env_table":
            return _result(api.env_table(root))
        elif name == "route_table":
            return _result(api.route_table(root))
        elif name == "check":
            return _result(api.check(root))
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


def run_server(root: Path) -> None:
    """Run the MCP server on stdio."""
    import asyncio

    server = create_server(root)

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
