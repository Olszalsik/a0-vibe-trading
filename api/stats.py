"""
Vibe-Trading — backend stats / health endpoint.

Route: POST /api/plugins/vibe_trading/stats

Returns:
  - plugin version + toggle state
  - file presence (required files)
  - vibe-trading-ai install status + version
  - console script path
  - MCP server entry status (registered / disabled / not registered)
  - live MCP server probe (initialize + list_tools, ~10s)

Light enough to call from the WebUI on demand, e.g. from a refresh button
in webui/config.html.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = "vibe_trading"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


class Stats(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        import hooks  # type: ignore  # local plugin import

        snap = hooks.self_check()
        snap["mcp_live_probe"] = await self._probe_mcp_server()
        snap["toggle_state"] = self._toggle_state()
        return snap

    @staticmethod
    def _toggle_state() -> str:
        if os.path.isfile(os.path.join(PLUGIN_ROOT, ".toggle-1")):
            return "on"
        if os.path.isfile(os.path.join(PLUGIN_ROOT, ".toggle-0")):
            return "off"
        return "default"

    @staticmethod
    async def _probe_mcp_server() -> Dict[str, Any]:
        cmd = shutil.which("vibe-trading-mcp")
        if not cmd:
            return {"probed": False, "error": "vibe-trading-mcp not on PATH"}
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as e:  # pragma: no cover
            return {"probed": False, "error": f"mcp client not importable: {e}"}

        async def _run() -> Dict[str, Any]:
            params = StdioServerParameters(command=cmd, args=[], env=None)
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=10)
                        res = await asyncio.wait_for(session.list_tools(), timeout=10)
                        names: List[str] = sorted([t.name for t in (res.tools or [])])
                        return {"probed": True, "tool_count": len(names), "tools": names}
            except Exception as e:  # pragma: no cover
                return {"probed": False, "error": str(e)[:300]}

        try:
            return await asyncio.wait_for(_run(), timeout=12)
        except Exception as e:  # pragma: no cover
            return {"probed": False, "error": str(e)[:300]}
