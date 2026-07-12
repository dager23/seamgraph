"""End-to-end MCP smoke test: spawn `seamgraph serve` over stdio, list tools,
and call seams_for/impact against the fastapi_react fixture.

Skipped automatically when the optional ``mcp`` extra is not installed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_TOOLS = {
    "seam_map",
    "seams_for",
    "impact",
    "verify",
    "env_table",
    "route_table",
    "check",
}


async def _roundtrip(root: Path) -> tuple[set[str], dict[str, Any], dict[str, Any]]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "seamgraph.cli", "--root", str(root), "serve"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        names = {t.name for t in listed.tools}

        res = await session.call_tool("seams_for", {"ref": "DATABASE_URL"})
        seams_payload = json.loads(res.content[0].text)  # type: ignore[union-attr]

        res2 = await session.call_tool("impact", {"paths": ["backend/main.py"]})
        impact_payload = json.loads(res2.content[0].text)  # type: ignore[union-attr]

        return names, seams_payload, impact_payload


def test_mcp_stdio_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "fastapi_react"
    shutil.copytree(FIXTURES / "fastapi_react", root)

    names, seams_payload, impact_payload = asyncio.run(_roundtrip(root))

    assert names >= EXPECTED_TOOLS
    # server auto-indexed at startup: DATABASE_URL seams are served
    assert seams_payload["count"] >= 1
    keys = {s["key"] for s in seams_payload["seams"]}
    assert "DATABASE_URL" in keys
    # impact of changing the backend: route seams to the frontend cross the boundary
    impacted_kinds = {s["kind"] for s in impact_payload["impacted_seams"]}
    assert "route" in impacted_kinds
