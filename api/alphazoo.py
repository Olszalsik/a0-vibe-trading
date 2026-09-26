'''
Vibe-Trading -- Alpha Zoo proxy.

Route: POST /api/plugins/vibe_trading/alphazoo

The upstream Alpha Zoo is delivered as a CLI (vibe-trading alpha ...),
not as MCP tools. This handler exposes two actions:

    action 'list'  -> returns the static alpha-zoo manifest
                       (qlib158, alpha101, gtja191, academic,
                        with bundled counts and a representative
                        slice of formula names per zoo).
    action 'bench' -> runs a representative factor_analysis on a few
                       alphas from each zoo and returns per-alpha metrics.

The static manifest is the source of truth for the UI's alpha gallery.
The bench action is best-effort: if any MCP call fails, the row is
reported with ok=False and the loop continues.

Single-quote string literals only.
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

# Phase 4: bench result caching (24h TTL keyed by codes+date+sample_per_zoo).
import hashlib

# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache
# Two-venv trap: shared canonical binary resolver (plugin root, shadow-proof).
import vibe_trading_bin as _bin

_BENCH_NS = 'alphazoo.bench'
_BENCH_TTL_SECONDS = 86400.0  # 24h


def _bench_cache_key(payload: Dict[str, Any]) -> str:
    codes = payload.get('codes') or []
    if isinstance(codes, str):
        codes = [c.strip() for c in codes.split(',') if c.strip()]
    key_data = {
        'codes': sorted(codes),
        'start_date': str(payload.get('start_date') or '').strip(),
        'end_date': str(payload.get('end_date') or '').strip(),
        'sample_per_zoo': int(payload.get('sample_per_zoo') or 3),
    }
    h = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode('utf-8')).hexdigest()
    return _BENCH_NS + '|' + h[:16]


_MANIFEST = {
    'total_alphas': 462,
    'zoos': [
        {
            'id': 'qlib158',
            'name': 'Qlib Alpha158',
            'count': 154,
            'origin': 'Microsoft Qlib Alpha158 feature handler',
            'sample_factors': ['KMID', 'KLEN', 'KMID2', 'KLOW', 'KSFT', 'OPEN0', 'CLOS0', 'HIGH0', 'LOW0', 'VWAP0'],
            'tags': ['cross_sectional', 'price_volume', 'rolling_window'],
        },
        {
            'id': 'alpha101',
            'name': 'Alpha101 (Kakushadze 2015)',
            'count': 101,
            'origin': 'Kakushadze, Serban, Yu (2015), 101 Formulaic Alphas',
            'sample_factors': ['alpha001', 'alpha006', 'alpha012', 'alpha020', 'alpha033', 'alpha054', 'alpha084'],
            'tags': ['cross_sectional', 'factor_research', 'standard_benchmark'],
        },
        {
            'id': 'gtja191',
            'name': 'GTJA Alpha191',
            'count': 191,
            'origin': 'Guotai Junan 191 short-period trading alphas',
            'sample_factors': ['GTJA1', 'GTJA12', 'GTJA27', 'GTJA45', 'GTJA66', 'GTJA99', 'GTJA150'],
            'tags': ['short_period', 'china_market', 'volume_price'],
        },
        {
            'id': 'academic',
            'name': 'Academic',
            'count': 12,
            'origin': 'Fama-French 5 + Carhart momentum plus published anomalies '
                      '(betting-against-beta, 52-week-high, correlation stability, …)',
            'sample_factors': ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'UMD'],
            'tags': ['academic', 'factor_research', 'baseline'],
        },
        {
            'id': 'fundamental',
            'name': 'Fundamental (value / quality)',
            'count': 4,
            'origin': 'Classic value & quality screens: gross profitability, '
                      'earnings yield, ROE, asset growth',
            'sample_factors': ['gross_profitability', 'earnings_yield', 'roe', 'asset_growth'],
            'tags': ['fundamental', 'value', 'quality'],
        },
    ],
}


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
                    return {'ok': True, 'data': parsed, 'raw': joined[:6000]}
                return {'ok': True, 'raw': joined[:6000]}

    try:
        return await asyncio.wait_for(_run(), timeout=_bin.call_budget(outer, inner))
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


async def _bench(payload: Dict[str, Any]) -> Dict[str, Any]:
    cache_k = _bench_cache_key(payload)
    hit = _cache.get(cache_k)
    if hit is not None:
        return {'ok': True, 'cached': True, **hit}

    cmd = _bin.resolve_mcp_command()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not found; check mcp_command and the plugin install', 'rows': []}

    codes = payload.get('codes') or []
    if not codes:
        codes = ['AAPL.US', '600519.SH', '000001.SZ']
    if isinstance(codes, str):
        codes = [c.strip() for c in codes.split(',') if c.strip()]

    end_date = payload.get('end_date') or time.strftime('%Y-%m-%d')
    start_date = payload.get('start_date') or time.strftime('%Y-%m-%d', time.gmtime(time.time() - 365 * 86400))
    sample_per_zoo = int(payload.get('sample_per_zoo') or 3)

    rows: List[Dict[str, Any]] = []
    for zoo in _MANIFEST['zoos']:
        for factor_name in zoo['sample_factors'][:sample_per_zoo]:
            res = await _call_tool(
                cmd, 'factor_analysis',
                {
                    'codes': codes,
                    'factor_name': factor_name,
                    'start_date': start_date,
                    'end_date': end_date,
                    'source': 'auto',
                    'top_n': 5,
                    'bottom_n': 5,
                },
                40.0, 35.0,
            )
            data = res.get('data') if res.get('ok') else None
            ic = None
            ic_ir = None
            spread = None
            if isinstance(data, dict):
                ic = data.get('ic')
                ic_ir = data.get('ir') or data.get('ic_ir')
                spread = data.get('spread') or data.get('long_short_spread')
            rows.append({
                'zoo': zoo['id'],
                'factor_name': factor_name,
                'ok': bool(res.get('ok')),
                'error': res.get('error'),
                'ic': ic,
                'ir': ic_ir,
                'long_short_spread': spread,
            })

    _cache.set(cache_k, {'rows': rows, 'cached': False}, ttl=_BENCH_TTL_SECONDS)

    return {
        'ok': True,
        'rows': rows,
        'ok_count': sum(1 for r in rows if r.get('ok')),
        'fail_count': sum(1 for r in rows if not r.get('ok')),
        'sample_per_zoo': sample_per_zoo,
        'window': {'start': start_date, 'end': end_date},
        'codes': codes,
    }


class Alphazoo(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or '').strip().lower()
        if not action:
            return {'success': False, 'error': "missing 'action' (one of: list, bench)"}

        if action == 'list':
            return {
                'success': True,
                'action': action,
                'manifest': _MANIFEST,
            }
        if action == 'bench':
            res = await _bench(input_data)
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        return {'success': False, 'error': "unknown action: '" + action + "' (expected list|bench)"}
