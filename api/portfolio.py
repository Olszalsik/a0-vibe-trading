'''
Vibe-Trading -- portfolio roll-up (Phase 9).

Route: POST /api/plugins/vibe_trading/portfolio

READ-ONLY. Surfaces two independent views, both opt-in:

  summary   -> MCP `portfolio_summary` (present in upstream v0.1.13+).
               Never fabricated: if the tool is not in the live server's
               tool list we return a clear hint instead of an error dump.
  account   -> trading_account() via the shared connectors dispatch
               (same shape as the Connectors tab uses).
  positions -> trading_positions() via the shared connectors dispatch.

Caching follows the Theme B convention (helpers.cache, per-action TTL).

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from helpers import cache as _cache  # type: ignore

_SUMMARY_NS = 'portfolio.summary'
_SUMMARY_TTL_SECONDS = 120.0


async def _call_tool(cmd: str, name: str, arguments: Dict[str, Any], outer: float, inner: float) -> Dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:
        return {'ok': False, 'error': 'mcp client not importable: ' + str(e)}

    params = StdioServerParameters(command=cmd, args=[], env=None)

    async def _run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=10)
                res = await asyncio.wait_for(session.call_tool(name, arguments), timeout=inner)
                texts: List[str] = []
                for item in (getattr(res, 'content', None) or []):
                    txt = getattr(item, 'text', None)
                    if txt is not None:
                        texts.append(txt)
                joined = '\n'.join(texts) if texts else ''
                parsed: Any = None
                try:
                    parsed = json.loads(joined)
                except Exception:
                    parsed = None
                if parsed is not None:
                    return {'ok': True, 'data': parsed, 'raw': joined[:6000]}
                return {'ok': True, 'raw': joined[:6000]}

    try:
        return await asyncio.wait_for(_run(), timeout=outer)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


def _connector_payload(input_data: Dict[str, Any]) -> Dict[str, Any]:
    keys = ('connection', 'host', 'port', 'client_id', 'account')
    return {k: input_data[k] for k in keys if input_data.get(k) not in (None, '')}


class Portfolio(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = (input_data.get('action') or '').strip().lower()
        if not action:
            return {'success': False, 'error': "missing 'action' (one of: summary, account, positions)"}

        if action in ('account', 'positions'):
            from api import connectors as _conn
            res = await _conn._dispatch(action, _connector_payload(input_data))
            return {'success': bool(res.get('ok')), 'action': action, **res}

        if action == 'summary':
            cache_k = _SUMMARY_NS
            hit = _cache.get(cache_k)
            if hit is not None:
                return {'success': True, 'action': action, 'cached': True, **hit}

            cmd = shutil.which('vibe-trading-mcp')
            if not cmd:
                return {'success': False, 'action': action, 'error': 'vibe-trading-mcp not on PATH'}

            # Check the tool exists on the live server before calling it --
            # upstream added portfolio_summary in v0.1.13; older installs
            # would surface a confusing raw error.
            from api.tools import _get_tools
            try:
                tools_res = await _get_tools(force=False)
                names = tools_res.get('tools') or []
            except Exception as e:
                return {'success': False, 'action': action, 'error': 'tool list probe failed: ' + str(e)[:200]}
            if names and 'portfolio_summary' not in names:
                return {
                    'success': False,
                    'action': action,
                    'error': 'portfolio_summary is not exposed by the installed vibe-trading-mcp '
                             '(needs upstream >= 0.1.13). Re-run: pip install -U vibe-trading-ai',
                }

            from api.dashboard import _call_tool  # bounded MCP round-trip
            res = await _call_tool(cmd, 'portfolio_summary', {}, outer_timeout=30.0, inner_timeout=25.0)
            if res.get('ok'):
                _cache.set(cache_k, {'data': res.get('data', res.get('raw'))}, ttl=_SUMMARY_TTL_SECONDS)
                return {'success': True, 'action': action, **res}
            return {'success': False, 'action': action, **res}

        return {'success': False, 'error': "unknown action: " + repr(action) + " (expected: summary, account, positions)"}