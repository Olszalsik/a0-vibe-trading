'''
Vibe-Trading -- portfolio roll-up (Phase 9 / Tier 4).

Route: POST /api/plugins/vibe_trading/portfolio

READ-ONLY. Surfaces five views, all opt-in:

  summary   -> MCP `portfolio_summary` when the live server exposes it, else
               the upstream CLI (`vibe-trading --no-rich portfolio show`,
               upstream 0.1.15+). portfolio_summary is an upstream-internal
               agent tool and is NOT on the MCP surface (probe-verified
               through 0.1.15), so the CLI path is what actually serves the
               page. Aggregation semantics come from upstream: a source that
               fails to refresh is an error excluded from the totals
               (complete=false), never a carried-forward cache.
  refresh   -> CLI `vibe-trading portfolio refresh` (read-only broker reads),
               then the summary cache is invalidated. Explicit user action.
  sources   -> CLI `vibe-trading portfolio sources` (eligible connections).
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
import subprocess
import sys
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache

_SUMMARY_NS = 'portfolio.summary'
_SUMMARY_TTL_SECONDS = 120.0

# Upstream-CLI fallback: portfolio_summary is an upstream-internal agent tool
# and is NOT exposed over MCP (probe-verified through 0.1.15), so the page's
# aggregation view is served by `vibe-trading portfolio show` when present.
_CLI_SHOW_TIMEOUT_SECONDS = 90.0
_CLI_REFRESH_TIMEOUT_SECONDS = 240.0
_CLI_SOURCES_TIMEOUT_SECONDS = 30.0


def _vibe_cli_path() -> str:
    cli = shutil.which('vibe-trading')
    if cli:
        return cli
    mcp_cmd = shutil.which('vibe-trading-mcp')
    if mcp_cmd:
        sibling = os.path.join(os.path.dirname(mcp_cmd), 'vibe-trading')
        if os.path.isfile(sibling):
            return sibling
    return ''


def _run_cli(cli: str, args: List[str], timeout: float) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [cli, '--no-rich', *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'upstream CLI timed out after ' + str(int(timeout)) + 's'}
    except Exception as e:
        return {'ok': False, 'error': 'upstream CLI failed: ' + str(e)[:200]}
    out = (proc.stdout or '').strip()
    parsed = None
    try:
        parsed = json.loads(out)
    except Exception:
        parsed = None
    if proc.returncode != 0 and not out:
        return {'ok': False, 'error': ((proc.stderr or '').strip()[:300]) or ('upstream CLI exited ' + str(proc.returncode))}
    result: Dict[str, Any] = {'ok': True, 'raw': out[:12000], 'exit_code': proc.returncode}
    if parsed is not None:
        result['data'] = parsed
    stderr = (proc.stderr or '').strip()
    if stderr:
        result['stderr'] = stderr[:300]
    return result


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
            if not bool(input_data.get('force')):
                hit = _cache.get(cache_k)
                if hit is not None:
                    return {'success': True, 'action': action, 'cached': True, **hit}

            cmd = shutil.which('vibe-trading-mcp')
            if not cmd:
                return {'success': False, 'action': action, 'error': 'vibe-trading-mcp not on PATH'}

            # MCP first: only call portfolio_summary when the live server
            # actually exposes it (upstream may add it later; today it is
            # registry-only, probe-verified through 0.1.15).
            names = []
            from api.tools import _get_tools
            try:
                tools_res = await _get_tools(force=False)
                names = tools_res.get('tools') or []
            except Exception:
                names = []
            if names and 'portfolio_summary' in names:
                from api.dashboard import _call_tool  # bounded MCP round-trip
                res = await _call_tool(cmd, 'portfolio_summary', {}, outer_timeout=30.0, inner_timeout=25.0)
                if res.get('ok'):
                    _cache.set(cache_k, {'data': res.get('data', res.get('raw')), 'source': 'mcp'}, ttl=_SUMMARY_TTL_SECONDS)
                    return {'success': True, 'action': action, 'source': 'mcp', **res}

            # Fallback: upstream CLI aggregation (0.1.15+). Read-only broker
            # reads; a source that fails to refresh is an error excluded from
            # the totals upstream-side (complete=false), never a smaller cache.
            cli = _vibe_cli_path()
            if not cli:
                return {
                    'success': False,
                    'action': action,
                    'error': 'portfolio aggregation needs the portfolio_summary MCP tool '
                             '(not exposed by the installed server) or the upstream '
                             'vibe-trading CLI (pip install -U vibe-trading-ai, 0.1.15+)',
                }
            cli_res = _run_cli(cli, ['portfolio', 'show'], _CLI_SHOW_TIMEOUT_SECONDS)
            if not cli_res.get('ok'):
                return {'success': False, 'action': action, 'source': 'cli', 'error': cli_res.get('error')}
            _cache.set(cache_k, {'data': cli_res.get('data'), 'raw': cli_res.get('raw'), 'source': 'cli'}, ttl=_SUMMARY_TTL_SECONDS)
            return {'success': True, 'action': action, 'source': 'cli', **cli_res}

        if action == 'refresh':
            cli = _vibe_cli_path()
            if not cli:
                return {'success': False, 'action': action, 'error': 'upstream vibe-trading CLI not on PATH'}
            cli_res = _run_cli(cli, ['portfolio', 'refresh'], _CLI_REFRESH_TIMEOUT_SECONDS)
            _cache.invalidate(_SUMMARY_NS)
            return {'success': bool(cli_res.get('ok')), 'action': action, **cli_res}

        if action == 'sources':
            cli = _vibe_cli_path()
            if not cli:
                return {'success': False, 'action': action, 'error': 'upstream vibe-trading CLI not on PATH'}
            cli_res = _run_cli(cli, ['portfolio', 'sources'], _CLI_SOURCES_TIMEOUT_SECONDS)
            return {'success': bool(cli_res.get('ok')), 'action': action, **cli_res}

        return {'success': False, 'error': "unknown action: " + repr(action) + " (expected: summary, refresh, sources, account, positions)"}