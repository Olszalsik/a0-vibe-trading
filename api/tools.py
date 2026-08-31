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
_CACHE_LOCK: Optional[asyncio.Lock] = None


def _cache_lock() -> asyncio.Lock:
    # Created lazily so this module can be imported outside a running loop
    # (Python 3.10+ binds asyncio.Lock to the current loop at construction).
    global _CACHE_LOCK
    if _CACHE_LOCK is None:
        _CACHE_LOCK = asyncio.Lock()
    return _CACHE_LOCK


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
                    # Cold start of the upstream server is 8-25s (it imports 54
                    # tool modules and warms the alpha registry, see AGENTS.md
                    # invariant 1) — a 10s initialize timeout lost that race on
                    # every panel refresh right after an A0 restart. Still
                    # strictly bounded, just generous enough to win the race.
                    await asyncio.wait_for(session.initialize(), timeout=25)
                    res = await asyncio.wait_for(session.list_tools(), timeout=15)
                    names_: List[str] = sorted([t.name for t in (res.tools or [])])
                    return {"tools": names_, "error": None}
        except Exception as e:  # pragma: no cover
            return {"tools": [], "error": str(e)[:300]}

    try:
        return await asyncio.wait_for(_run(), timeout=45)
    except Exception as e:  # pragma: no cover
        return {"tools": [], "error": str(e)[:300]}


async def _get_tools(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and (now - _CACHE["fetched_at"]) < _CACHE_TTL_SECONDS:
        return {"tools": _CACHE["tools"], "error": _CACHE["error"], "cached": True}
    # Lock so the WebUI pages that call /stats and /tools in parallel share a
    # single stdio probe instead of racing two cold server boots.
    async with _cache_lock():
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
