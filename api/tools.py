"""
Vibe-Trading — list live MCP tools exposed by the Vibe-Trading server.

Route: POST /api/plugins/vibe_trading/tools

Returns the list of MCP tool names currently advertised by `vibe-trading-mcp`.
Caches the result for a few seconds so rapid page refreshes don't spawn a
new stdio MCP client per call. Failure is non-fatal — returns an empty list
with an error message so the UI can show "MCP not running".
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = "vibe_trading"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

_CACHE: Dict[str, Any] = {"tools": [], "fetched_at": 0.0, "error": None}
_CACHE_TTL_SECONDS = 15.0


async def _probe_tools() -> Dict[str, Any]:
    cmd = shutil.which("vibe-trading-mcp")
    if not cmd:
        return {"tools": [], "error": "vibe-trading-mcp not on PATH"}
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:  # pragma: no cover
        return {"tools": [], "error": f"mcp client not importable: {e}"}

    async def _run() -> Dict[str, Any]:
        params = StdioServerParameters(command=cmd, args=[], env=None)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=10)
                    res = await asyncio.wait_for(session.list_tools(), timeout=10)
                    names: List[str] = sorted([t.name for t in (res.tools or [])])
                    return {"tools": names, "error": None}
        except Exception as e:  # pragma: no cover
            return {"tools": [], "error": str(e)[:300]}

    try:
        return await asyncio.wait_for(_run(), timeout=12)
    except Exception as e:  # pragma: no cover
        return {"tools": [], "error": str(e)[:300]}


async def _get_tools(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and (now - _CACHE["fetched_at"]) < _CACHE_TTL_SECONDS:
        return {"tools": _CACHE["tools"], "error": _CACHE["error"], "cached": True}
    res = await _probe_tools()
    _CACHE["tools"] = res.get("tools", [])
    _CACHE["error"] = res.get("error")
    _CACHE["fetched_at"] = now
    return {"tools": _CACHE["tools"], "error": _CACHE["error"], "cached": False}


class Tools(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        force = bool(input_data.get("force", False))
        result = await _get_tools(force=force)
        return {
            "success": result.get("error") is None,
            "tools": result.get("tools", []),
            "count": len(result.get("tools", [])),
            "error": result.get("error"),
            "cached": result.get("cached", False),
        }
