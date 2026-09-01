'''
Vibe-Trading -- single-symbol deep-dive aggregator.

Route: POST /api/plugins/vibe_trading/deep_dive

Fans out four MCP calls in parallel for one symbol and returns the
joined result ready for the deepdive.html page:
  - get_stock_profile  (analyst targets / earnings trend / ownership)
  - get_financial_statements  (per-period indicators, newest 4 quarters)
  - get_stock_news  (last 10 headlines)
  - get_market_data  (last 1 bar, for current price)

Cache: 60 seconds per symbol (auto-busts when force=true).
Each MCP subcall is bounded by asyncio.wait_for so one slow tool
cannot stall the page.

Single-quote string literals only (plugin-wide constraint).
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


_CACHE_TTL_SECONDS = 60.0
_OUTER_TIMEOUT = 25.0
_INNER_TIMEOUT = 12.0
_INIT_TIMEOUT = 10.0


def _mcp_cmd() -> Optional[str]:
    return shutil.which('vibe-trading-mcp')


async def _call_tool(cmd: str, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:
        return {'ok': False, 'error': 'mcp client not importable: ' + str(e)}

    params = StdioServerParameters(command=cmd, args=[], env=None)

    async def _run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=_INIT_TIMEOUT)
                res = await asyncio.wait_for(
                    session.call_tool(name, arguments), timeout=_INNER_TIMEOUT
                )
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
        return await asyncio.wait_for(_run(), timeout=_OUTER_TIMEOUT)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


async def _gather_deep_dive(symbol: str) -> Dict[str, Any]:
    cmd = _mcp_cmd()
    if not cmd:
        return {
            'ok': False,
            'error': 'vibe-trading-mcp binary not on PATH',
            'symbol': symbol,
        }

    today = time.strftime('%Y-%m-%d')
    year_ago = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 365 * 86400))

    coros = {
        'profile': _call_tool(
            cmd,
            'get_stock_profile',
            {'ticker': symbol},
        ),
        'financials': _call_tool(
            cmd,
            'get_financial_statements',
            {'code': symbol, 'statement': 'indicators', 'period': 'quarter'},
        ),
        'news': _call_tool(
            cmd,
            'get_stock_news',
            {'code': symbol, 'scope': 'stock', 'limit': 10},
        ),
        'price': _call_tool(
            cmd,
            'get_market_data',
            {
                'codes': [symbol],
                'start_date': year_ago,
                'end_date': today,
                'interval': '1D',
                'max_rows': 5,
            },
        ),
    }

    keys = list(coros.keys())
    started = time.time()
    settled = await asyncio.gather(*coros.values(), return_exceptions=True)
    elapsed_ms = int((time.time() - started) * 1000)

    parts: Dict[str, Any] = {}
    all_ok = True
    errs: List[str] = []
    for k, v in zip(keys, settled):
        if isinstance(v, Exception):
            parts[k] = {'ok': False, 'error': str(v)[:240]}
            all_ok = False
            errs.append(k + ': ' + str(v)[:120])
            continue
        if not v.get('ok'):
            parts[k] = v
            all_ok = False
            errs.append(k + ': ' + str(v.get('error', '?'))[:120])
            continue
        d = v.get('data')
        if isinstance(d, dict) and 'raw' in d and 'data' not in d:
            parts[k] = {'ok': True, 'text': d.get('raw', '')[:4000]}
        elif isinstance(d, dict) and 'data' in d:
            inner = d.get('data')
            parts[k] = {
                'ok': True,
                'rows': inner if isinstance(inner, list) else None,
                'object': inner if isinstance(inner, dict) else None,
                'raw': d.get('raw', '')[:4000],
            }
        else:
            parts[k] = {'ok': True, 'raw': v.get('raw', '')[:4000]}

    quote_block = parts.get('price') or {}
    news_block = parts.get('news') or {}
    return {
        'ok': all_ok,
        'symbol': symbol,
        'fetched_at': int(time.time()),
        'elapsed_ms': elapsed_ms,
        'sections': parts,
        'recent_news': (news_block.get('rows') if news_block.get('ok') else None),
        'price_tail': (
            quote_block.get('rows', [None])[0]
            if quote_block.get('ok') and quote_block.get('rows')
            else None
        ),
        'errors': errs,
    }


def _namespace_payload(symbol: str, force: bool, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {'symbol': symbol, 'force': force, 'payload': payload}


class DeepDive(ApiHandler):
    async def process(self, payload: Dict[str, Any], request: Any = None) -> Dict[str, Any]:
        # NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
        # helpers package shadows the plugin's, and its cache API is (area, key)-shaped
        # with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
        import vibe_trading_cache as _cache
        action = (payload or {}).get('action') or 'fetch'
        symbol = (payload or {}).get('symbol') or ''
        force = bool((payload or {}).get('force'))

        if action != 'fetch':
            return {
                'ok': False,
                'error': 'unknown action: ' + str(action),
                'supported': ['fetch'],
            }
        symbol = symbol.strip().upper()
        if not symbol:
            return {'ok': False, 'error': 'symbol is required (e.g. AAPL.US, 600519.SH)'}

        cache_key = 'deep_dive.' + symbol
        if not force:
            hit = _cache.get(cache_key)
            if hit is not None:
                hit['_cached'] = True
                return {
                    'ok': True,
                    'action': 'fetch',
                    'cached': True,
                    'symbol': symbol,
                    'data': hit,
                }

        result = await _gather_deep_dive(symbol)
        if result.get('ok'):
            _cache.set(cache_key, result, ttl=_CACHE_TTL_SECONDS)
        return {
            'ok': bool(result.get('ok')),
            'action': 'fetch',
            'cached': False,
            'symbol': symbol,
            'data': result,
        }
