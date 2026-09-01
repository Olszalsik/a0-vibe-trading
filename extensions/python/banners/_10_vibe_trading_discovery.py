"""
Vibe-Trading plugin - welcome-screen discovery banner (v2.2 format).

Appends a dismissible feature card to the welcome screen so the user learns
about the plugin on their first session after enabling it. Modeled on the
ui_loader_optimizer and caveman discovery banners.

Extension point: banners (v2.2)
Reference: /a0/usr/plugins/caveman/extensions/python/banners/_10_caveman_discovery.py

The card only appears when:
  - the plugin is enabled in the Plugins UI (caveman pattern), AND
  - the vibe-trading-ai Python package is importable, AND
  - the vibe-trading-mcp console script is on PATH, AND
  - the MCP server responds to a tools/list probe within ~3 seconds.

That way the card is never shown for a broken / unconfigured install.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import List

from helpers import plugins as plugins_helper  # type: ignore


PLUGIN_NAME = "vibe_trading"
CARD_ID = "vibe_trading_discovery_v1"


def _is_enabled() -> bool:
    try:
        cfg = plugins_helper.get_plugin_config(PLUGIN_NAME) or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        return False
    return cfg.get("enabled") is True or cfg.get("mcp_enabled") is True


def _vibe_trading_ai_installed() -> bool:
    try:
        import importlib.metadata as md
        return md.version("vibe-trading-ai") is not None
    except Exception:
        return False


def _vibe_trading_ai_version() -> str:
    try:
        import importlib.metadata as md
        return md.version("vibe-trading-ai") or ""
    except Exception:
        return ""


def _console_script_exists() -> bool:
    return shutil.which("vibe-trading-mcp") is not None


async def _mcp_live(timeout: float = 3.0) -> bool:
    cmd = shutil.which("vibe-trading-mcp")
    if not cmd:
        return False
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception:
        return False

    async def _run() -> bool:
        params = StdioServerParameters(command=cmd, args=[], env=None)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=timeout)
                    res = await asyncio.wait_for(session.list_tools(), timeout=timeout)
                    return bool(res and res.tools)
        except Exception:
            return False

    try:
        return await asyncio.wait_for(_run(), timeout=timeout + 2)
    except Exception:
        return False


def execute(banners: list, **kwargs):
    """v2.2 banner contract: append a Vibe-Trading discovery card to the list."""
    for existing in banners or []:
        if isinstance(existing, dict) and existing.get("id") == CARD_ID:
            return

    if not _is_enabled():
        return
    if not _vibe_trading_ai_installed():
        return
    if not _console_script_exists():
        return

    # NOTE: run the async probe in its own thread — `execute()` may be invoked
    # while the server's event loop is already running, and asyncio.run() would
    # raise "cannot be called from a running event loop" (previously swallowed
    # here, permanently hiding the banner on healthy installs).
    live = False
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            live = bool(_ex.submit(asyncio.run, _mcp_live(timeout=3.0)).result(timeout=6.0))
    except Exception:
        live = False
    if not live:
        return

    banners.append({
        "id": CARD_ID,
        "type": "feature",
        "priority": 50,
        "title": "Vibe-Trading research tools are live",
        "description": (
            "54 finance-research MCP tools (backtest, factor analysis, options, "
            "shadow account, 452 alphas, 29 swarm teams) are now available. "
            "Pick the 'vibe-trader' agent profile to start, or open the "
            "plugin settings to add Tushare / LLM keys."
        ),
        "icon": "trending-up",
        "cta_text": "Open Vibe-Trading settings",
        # v2.5 `executeBannerAction` only dispatches `open-modal:` and
        # `open-url:`. The v2.2-era `open-plugin-config:<name>` string is
        # not handled by the framework and was a silent no-op.
        "cta_action": "open-modal:/usr/plugins/vibe_trading/webui/config.html",
        "dismissible": True,
        "meta": {
            "plugin": PLUGIN_NAME,
            "mcp_command": shutil.which("vibe-trading-mcp"),
            # Follow the installed upstream package (version_sync policy);
            # the banner only renders when the package IS installed.
            "version": _vibe_trading_ai_version() or "unknown",
        },
    })
