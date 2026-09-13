"""MCP stdio server for seamgraph (optional extra ``seamgraph[mcp]``).

Exposes seven tools:

- ``seam_map``: the full seam map (an agent's starting point)
- ``seams_for``: seams related to one reference
- ``impact``: seams crossing a change boundary
- ``verify``: whether a reference is connected on both sides
- ``env_table``: env-variable cross-reference
- ``route_table``: route cross-reference
- ``check``: re-index and report findings

The high-level server class was renamed between SDK generations -- ``FastMCP``
in ``mcp`` 1.x, ``MCPServer`` in 2.x -- so both names are tried here. The tool
surface is identical across the two, so nothing else has to branch.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

#: Where each SDK generation keeps the high-level server class, newest first.
_SERVER_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("mcp.server.mcpserver", "MCPServer"),  # mcp >= 2.0
    ("mcp.server.fastmcp", "FastMCP"),  # mcp 1.2 - 1.x
)


def _resolve_server_class() -> Any:
    """Return the installed SDK's high-level server class, or None.

    Resolved dynamically on purpose. Static ``from mcp.server import ...``
    statements make type checking depend on which SDK generation is installed:
    a suppression one generation needs is reported as unused under the other,
    so no single source file could pass strict mypy against both.
    """
    for module_name, attr in _SERVER_LOCATIONS:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        cls = getattr(module, attr, None)
        if cls is not None:
            return cls
    return None


#: The high-level server class, under whichever name this SDK generation uses.
_Server: Any = _resolve_server_class()

HAS_MCP = _Server is not None

from . import api  # noqa: E402


def create_server(root: Path) -> Any:
    """Build the MCP server, with every tool bound to ``root``."""
    if not HAS_MCP:
        raise ImportError("MCP support requires: pip install 'seamgraph[mcp]'")

    server = _Server(
        name="seamgraph",
        instructions=(
            "seamgraph indexes the string-typed seams of this repository: the "
            "references that connect code to configs, templates, frontend HTTP "
            "calls, CI scripts and .env files. Use seams_for instead of grepping "
            "when you need to know what a route, env var or template name is "
            "connected to, and impact before finishing a change."
        ),
    )

    @server.tool()  # type: ignore[untyped-decorator]
    def seam_map(kind: str | None = None) -> dict[str, Any]:
        """Get every cross-artifact seam in this repo, with a summary by kind and grade.

        Start here to understand what is connected. Optionally filter by kind:
        env, route, template, urlname, task, script, setting.
        """
        return api.seam_map(root, kind=kind)

    @server.tool()  # type: ignore[untyped-decorator]
    def seams_for(ref: str, kind: str | None = None) -> dict[str, Any]:
        """Find what a reference is connected to, with file:line evidence on both sides.

        Use this instead of grep. ``ref`` can be an env var name
        (DATABASE_URL), a route path (/api/users), a template name
        (checkout.html) or a file path.
        """
        return api.seams_for(root, ref=ref, kind=kind)

    @server.tool()  # type: ignore[untyped-decorator]
    def impact(paths: list[str]) -> dict[str, Any]:
        """Given changed files, list the seams that cross the change boundary.

        These are the connections where one side moved and the other did not,
        so they are what to re-check before calling a change done.
        """
        return api.impact(root, paths=paths)

    @server.tool()  # type: ignore[untyped-decorator]
    def verify(ref: str) -> dict[str, Any]:
        """Check whether one reference resolves on both sides.

        Use after editing a route, env var or template name to confirm the
        other side still matches.
        """
        return api.verify(root, ref=ref)

    @server.tool()  # type: ignore[untyped-decorator]
    def env_table() -> dict[str, Any]:
        """Cross-reference every environment variable: where each is defined and read.

        Covers .env files, docker-compose, Dockerfile, Kubernetes manifests,
        CI workflow env blocks, and reads in Python and JS/TS.
        """
        return api.env_table(root)

    @server.tool()  # type: ignore[untyped-decorator]
    def route_table() -> dict[str, Any]:
        """Cross-reference every HTTP route: handlers and the calls that reach them.

        Calls are grouped under the handler they actually matched; calls with
        no handler are listed on their own with the severity seamgraph
        assigned them.
        """
        return api.route_table(root)

    @server.tool()  # type: ignore[untyped-decorator]
    def check(strict: bool = False) -> dict[str, Any]:
        """Re-index and report findings: warnings plus informational dangling references.

        Warnings are references seamgraph is confident are broken.
        Informational findings are references whose definition side it never
        extracted. ``strict`` counts the informational ones as failures too.
        """
        return api.check(root, strict=strict)

    return server


def run_server(root: Path) -> None:
    """Run the MCP server on stdio.

    The repository is indexed (incrementally) at startup so the first tool call
    answers from a real graph instead of an empty one.
    """
    api.index(root)
    create_server(root).run()
