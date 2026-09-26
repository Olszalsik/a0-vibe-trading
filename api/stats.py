"""
Vibe-Trading — backend stats / health endpoint.

Route: POST /api/plugins/vibe_trading/stats

Returns:
  - plugin version + toggle state
  - file presence (required files)
  - vibe-trading-ai install status + version
  - console script path
  - MCP server entry status (registered / disabled / not registered)
  - live MCP server probe (shared with api/tools.py, cached 15s, bounded 45s)

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

# Two-venv trap: shared canonical binary resolver (plugin root, shadow-proof).
import vibe_trading_bin as _bin


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
        # Use the shared, 15s-cached probe from api/tools.py so the WebUI pages
        # that call /stats and /tools together trigger at most ONE cold stdio
        # boot (they used to race two, each under a 12s timer — see AGENTS.md
        # invariant 7). Raises nothing; the handler returns probed=False +
        # error on probe failure.
        cmd = _bin.resolve_mcp_command()
        if not cmd:
            return {"probed": False, "error": "vibe-trading-mcp not found (checked the "
                                              "pinned mcp_command, usr/settings.json, "
                                              "PATH and the well-known venv bin dirs)"}
        try:
            from api import tools as _api_tools  # type: ignore  # local plugin import
            res = await _api_tools._get_tools(force=False)
        except Exception as e:  # pragma: no cover
            return {"probed": False, "error": str(e)[:300]}
        if res.get("error"):
            return {"probed": False, "error": str(res.get("error"))[:300]}
        names: List[str] = sorted(res.get("tools") or [])
        return {"probed": True, "tool_count": len(names), "tools": names}
