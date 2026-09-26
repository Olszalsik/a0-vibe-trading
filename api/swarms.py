'''
Vibe-Trading -- multi-agent swarm proxy.

Route: POST /api/plugins/vibe_trading/swarms

Proxies the MCP swarm tools:
    list_swarm_presets()        -> action 'list_presets'
    run_swarm(preset, vars, s)  -> action 'start_run'
    get_swarm_status(run_id)    -> action 'get_status'
    get_run_result(run_id)      -> action 'get_run'
    list_runs(limit)            -> action 'list_runs'
    retry_run(run_id)           -> action 'retry_run'
    reap_stale_runs()           -> action 'reap_stale_runs'

Swarm runs are intrinsically long -- start_run outer timeout is 1h.
Other actions use 15-30s. Every call uses asyncio.wait_for(...) so a
hung MCP server cannot freeze the API.

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Phase 4: short TTL cache for list_presets (60s) + list_runs (30s) to keep UI snappy.
# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache
# Two-venv trap: shared canonical binary resolver (plugin root, shadow-proof).
import vibe_trading_bin as _bin

_LIST_PRESETS_NS = 'swarms.list_presets'
_LIST_PRESETS_TTL_SECONDS = 60.0

_LIST_RUNS_NS = 'swarms.list_runs'
_LIST_RUNS_TTL_SECONDS = 30.0



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
                await asyncio.wait_for(session.initialize(), timeout=_bin.MCP_INIT_TIMEOUT_S)
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
                    return {'ok': True, 'data': parsed, 'raw': joined[:8000]}
                return {'ok': True, 'raw': joined[:8000]}

    try:
        return await asyncio.wait_for(_run(), timeout=_bin.call_budget(outer, inner))
    except Exception as e:
        return {'ok': False, 'error': str(e)[:400]}


async def _swarm(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cmd = _bin.resolve_mcp_command()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not found; check mcp_command and package installation'}

    if action == 'list_presets':
        hit = _cache.get(_LIST_PRESETS_NS)
        if hit is not None:
            return {'ok': True, 'cached': True, **hit}
        res = await _call_tool(cmd, 'list_swarm_presets', {}, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(_LIST_PRESETS_NS, res, ttl=_LIST_PRESETS_TTL_SECONDS)
        return res

    if action == 'start_run':
        preset_name = payload.get('preset_name') or ''
        if not preset_name:
            return {'ok': False, 'error': 'preset_name is required'}
        variables = payload.get('variables') or {}
        if not isinstance(variables, dict):
            return {'ok': False, 'error': 'variables must be a dict'}
        wait_seconds = int(payload.get('wait_seconds') or 60)
        start_only = bool(payload.get('start_only', False))
        arguments: Dict[str, Any] = {
            'preset_name': preset_name,
            'variables': variables,
            'wait_seconds': wait_seconds,
        }
        if start_only:
            arguments['start_only'] = True
        outer = min(3600.0, wait_seconds + 30.0)
        inner = min(3570.0, wait_seconds)
        return await _call_tool(cmd, 'run_swarm', arguments, outer, inner)

    if action == 'get_status':
        run_id = payload.get('run_id') or ''
        if not run_id:
            return {'ok': False, 'error': 'run_id is required'}
        return await _call_tool(cmd, 'get_swarm_status', {'run_id': run_id}, 15.0, 10.0)

    if action == 'get_run':
        run_id = payload.get('run_id') or ''
        if not run_id:
            return {'ok': False, 'error': 'run_id is required'}
        return await _call_tool(cmd, 'get_run_result', {'run_id': run_id}, 30.0, 25.0)

    if action == 'list_runs':
        limit = int(payload.get('limit') or 20)
        lr_key = _LIST_RUNS_NS + '|limit=' + str(limit)
        hit = _cache.get(lr_key)
        if hit is not None:
            return {'ok': True, 'cached': True, **hit}
        res = await _call_tool(cmd, 'list_runs', {'limit': limit}, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(lr_key, res, ttl=_LIST_RUNS_TTL_SECONDS)
        return res

    if action == 'retry_run':
        run_id = payload.get('run_id') or ''
        if not run_id:
            return {'ok': False, 'error': 'run_id is required'}
        return await _call_tool(cmd, 'retry_run', {'run_id': run_id}, 60.0, 55.0)

    if action == 'reap_stale_runs':
        return await _call_tool(cmd, 'reap_stale_runs', {}, 30.0, 25.0)

    return {'ok': False, 'error': 'unknown swarm action: ' + repr(action)}


class Swarms(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or '').strip().lower()
        if not action:
            return {'success': False, 'error': "missing 'action' (one of: list_presets, start_run, get_status, get_run, list_runs, retry_run, reap_stale_runs)"}

        res = await _swarm(action, input_data)
        ok = bool(res.get('ok'))
        return {'success': ok, 'action': action, **res}
