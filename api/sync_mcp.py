"""
Vibe-Trading — sync plugin config into Agent Zero's MCP settings.

Route: POST /api/plugins/vibe_trading/sync_mcp

Body: optional overrides dict (e.g. {"tushare_token": "...", "risk_tier": "paper"}).
       Any field in the body overrides the corresponding value in
       usr/plugins/vibe_trading/config.json for this sync, then we re-run
       hooks.install() to register/refresh the MCP server entry.

This is the endpoint the WebUI's "Save" button calls.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = "vibe_trading"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


class SyncMcp(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        import hooks  # type: ignore  # local plugin import

        overrides = input_data.get("overrides") or {}
        if not isinstance(overrides, dict):
            return {"success": False, "error": "overrides must be a dict"}

        if overrides:
            # Persist overrides to usr/plugins/vibe_trading/config.json so
            # they survive across reloads.
            user_cfg_path = os.path.join("/a0", "usr", "plugins", PLUGIN_NAME, "config.json")
            try:
                import json
                if os.path.isfile(user_cfg_path):
                    with open(user_cfg_path, "r", encoding="utf-8") as f:
                        current = json.load(f) or {}
                else:
                    current = {}
                if not isinstance(current, dict):
                    current = {}
                current.update({k: v for k, v in overrides.items() if v is not None})
                os.makedirs(os.path.dirname(user_cfg_path), exist_ok=True)
                with open(user_cfg_path, "w", encoding="utf-8") as f:
                    json.dump(current, f, ensure_ascii=False, indent=2)
            except Exception as e:  # pragma: no cover
                return {"success": False, "error": f"failed to persist config: {e}"}

        result = hooks.sync_now()
        snap = hooks.get_status()
        return {"success": bool(result.get("ok")), "hooks_result": result, "status": snap}
