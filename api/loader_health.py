'''
Vibe-Trading -- upstream data-loader health probe.

Route: POST /api/plugins/vibe_trading/loader_health

Lightweight healthcheck that asks the MCP get_market_data tool for one
bar per known loader, measures latency, and reports per-loader status.

Cache: 30 seconds per loader-set. force=true skips the cache. Each loader
probe is bounded by asyncio.wait_for(...) so a slow loader cannot stall
the whole dashboard.

Single-quote string literals only (plugin-wide constraint).
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Theme B: helpers.cache is the canonical TTL cache for the plugin.
from helpers import cache as _cache  # type: ignore


_CACHE_NS = 'loader_health.probe'
_CACHE_TTL_SECONDS = 30.0


_SYMBOL_PLAN: List[Dict[str, str]] = [
    {'loader': 'yfinance',    'code': 'AAPL.US',    'source': 'yfinance'},
    {'loader': 'akshare',     'code': '600519.SH',  'source': 'akshare'},
    {'loader': 'baostock',    'code': 'sh.600000',  'source': 'baostock'},
    {'loader': 'tencent',     'code': '600519.SH',  'source': 'tencent'},
    {'loader': 'eastmoney',   'code': '600519.SH',  'source': 'eastmoney'},
    {'loader': 'mootdx',      'code': '600519.SH',  'source': 'mootdx'},
    {'loader': 'tushare',     'code': '000001.SZ',  'source': 'tushare'},
    {'loader': 'okx',         'code': 'BTC-USDT',   'source': 'okx'},
    {'loader': 'finnhub',     'code': 'AAPL',       'source': 'finnhub'},
    {'loader': 'alphavantage','code': 'AAPL',       'source': 'alphavantage'},
    {'loader': 'fmp',         'code': 'AAPL',       'source': 'fmp'},
    {'loader': 'fred',        'code': 'DGS10',      'source': 'fred'},
    {'loader': 'ccxt',        'code': 'BTC/USDT',   'source': 'ccxt'},
]


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
                    return {'ok': True, 'data': parsed, 'raw': joined[:4000]}
                return {'ok': True, 'raw': joined[:4000]}

    try:
        return await asyncio.wait_for(_run(), timeout=outer)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


async def _probe_one(cmd: str, plan: Dict[str, str]) -> Dict[str, Any]:
    started = time.time()
    today = time.strftime('%Y-%m-%d')
    today_minus_7 = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 7 * 86400))
    res = await _call_tool(
        cmd,
        'get_market_data',
        {
            'codes': [plan['code']],
            'start_date': today_minus_7,
            'end_date': today,
            'source': plan['source'],
            'interval': '1D',
            'max_rows': 2,
        },
        12.0,
        8.0,
    )
    elapsed_ms = int((time.time() - started) * 1000)
    if not res.get('ok'):
        return {
            'loader': plan['loader'],
            'code': plan['code'],
            'source': plan['source'],
            'ok': False,
            'latency_ms': elapsed_ms,
            'error': str(res.get('error', 'unknown error'))[:240],
        }
    raw = res.get('data', res.get('raw'))
    return {
        'loader': plan['loader'],
        'code': plan['code'],
        'source': plan['source'],
        'ok': True,
        'latency_ms': elapsed_ms,
        'rows': 1 if raw else 0,
    }


async def _probe_all(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    cached_payload = _cache.get(_CACHE_NS)
    if not force and cached_payload is not None:
        return {'cached': True, **cached_payload}

    cmd = shutil.which('vibe-trading-mcp')
    if not cmd:
        out = {'mcp_available': False, 'error': 'vibe-trading-mcp not on PATH', 'results': []}
        _cache.set(_CACHE_NS, out, ttl=_CACHE_TTL_SECONDS)
        return out

    out: Dict[str, Any] = {'mcp_available': True, 'results': []}
    sem = asyncio.Semaphore(4)

    async def _guarded(plan: Dict[str, str]):
        async with sem:
            return await _probe_one(cmd, plan)

    try:
        tasks = [asyncio.create_task(_guarded(p)) for p in _SYMBOL_PLAN]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        out['results'] = results
    except Exception as e:
        out['results'] = []
        out['error'] = 'gather failed: ' + str(e)

    out['ok_count'] = sum(1 for r in out['results'] if r.get('ok'))
    out['fail_count'] = sum(1 for r in out['results'] if not r.get('ok'))

    _cache.set(_CACHE_NS, out, ttl=_CACHE_TTL_SECONDS)
    return {'cached': False, **out}


class LoaderHealth(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or 'probe').strip().lower()
        if action != 'probe':
            return {'success': False, 'error': "unknown action: '" + action + "' (expected 'probe')"}
        force = bool(input_data.get('force', False))
        res = await _probe_all(force=force)
        ok = bool(res.get('mcp_available')) and (res.get('error') is None)
        return {'success': ok, 'action': action, **res}
