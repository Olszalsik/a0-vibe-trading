
'''
Vibe-Trading — dashboard backend endpoint.

Route: POST /api/plugins/vibe_trading/dashboard

Single ApiHandler with multiple actions so the WebUI dashboard can issue
one round-trip per action rather than mounting every upstream surface as a
separate endpoint.

Actions (selected via input_data["action"]):
    snapshot  — one-shot bundle for the Overview tab:
                  plugin stats (hooks.self_check) + MCP tool list + recent
                  swarm runs + loader-health probe summary. 15s cache.
    quote     — proxy to MCP `get_market_data` with the smallest useful
                  window (1D, max_rows=5). 5s cache. Designed for marquee
                  tickers in the Markets tab.
    backtest  — proxy to MCP `backtest(run_dir=...)`. Caller supplies a
                  fully-built run_dir (config.json + code/signal_engine.py).
                  No caching — every call runs a fresh backtest.
    patterns  — proxy to MCP `pattern_recognition(run_dir=...)`: chart-pattern
                  detection over run_dir/artifacts/ohlcv_*.csv. 30min cache
                  (patterns derive from stored CSVs, not live data).
    factor    — proxy to MCP `factor_analysis(codes=[...], factor_name=...,
                  start_date=..., end_date=..., source="auto", top_n=10,
                  bottom_n=10)`. No caching.

Every MCP round-trip is bounded by `asyncio.wait_for(...)` so a hung
vibe-trading-mcp cannot freeze the dashboard frame. The base pattern is
copied from api/tools.py:55-58 and api/stats.py:75-78.

Single-quote string literals only (plugin-wide constraint).
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Theme B: replaced inline dict caches with the shared helpers.cache module.
# Per-action TTL preserved. helpers.cache is thread-safe.
# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache

_QUOTE_NS = 'dashboard.quote'
_QUOTE_TTL_SECONDS = 5.0

_SNAPSHOT_NS = 'dashboard.snapshot'
_SNAPSHOT_TTL_SECONDS = 15.0

# Phase 4: cache for expensive MCP calls (backtest + factor).
import hashlib

_BACKTEST_NS = 'dashboard.backtest'
_BACKTEST_TTL_SECONDS = 86400.0  # 24h

_FACTOR_NS = 'dashboard.factor'
_FACTOR_TTL_SECONDS = 86400.0  # 24h

_PATTERNS_NS = 'dashboard.patterns'
_PATTERNS_TTL_SECONDS = 1800.0  # 30min -- patterns derive from stored OHLCV CSVs


def _factor_cache_key(payload: Dict[str, Any]) -> str:
    key_data = {
        'codes': sorted(payload.get('codes') or []),
        'factor_name': str(payload.get('factor_name') or '').strip(),
        'start_date': str(payload.get('start_date') or '').strip(),
        'end_date': str(payload.get('end_date') or '').strip(),
        'source': str(payload.get('source') or 'auto').strip(),
        'top_n': int(payload.get('top_n') or 10),
        'bottom_n': int(payload.get('bottom_n') or 10),
    }
    h = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode('utf-8')).hexdigest()
    return _FACTOR_NS + '|' + h[:16]


def _resolve_mcp_cmd() -> Optional[str]:
    return shutil.which('vibe-trading-mcp')


async def _call_tool(cmd: str, name: str, arguments: Dict[str, Any], outer_timeout: float = 30.0, inner_timeout: float = 25.0) -> Dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:
        return {'ok': False, 'error': f'mcp client not importable: {e}'}

    params = StdioServerParameters(command=cmd, args=[], env=None)

    async def _run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=10)
                res = await asyncio.wait_for(session.call_tool(name, arguments), timeout=inner_timeout)
                payload = getattr(res, 'content', None)
                if payload is None:
                    return {'ok': True, 'raw': str(res)[:2000]}
                texts: List[str] = []
                for item in payload:
                    txt = getattr(item, 'text', None)
                    if txt is not None:
                        texts.append(txt)
                joined = '\n'.join(texts) if texts else str(payload)
                parsed: Any = None
                try:
                    parsed = json.loads(joined)
                except Exception:
                    parsed = None
                if parsed is not None:
                    return {'ok': True, 'data': parsed}
                return {'ok': True, 'raw': joined[:8000]}

    try:
        return await asyncio.wait_for(_run(), timeout=outer_timeout)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


def _quote_cache_key(codes: List[str], source: str) -> str:
    return _QUOTE_NS + '|' + ','.join(sorted(set(codes))) + '|' + (source or 'auto')


async def _quote(codes: List[str], source: str = 'auto') -> Dict[str, Any]:
    cmd = _resolve_mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH', 'cached': False}

    today = time.strftime('%Y-%m-%d')
    cache_k = _quote_cache_key(codes, source)
    hit = _cache.get(cache_k)
    if hit is not None:
        return {'ok': True, 'cached': True, **hit}

    res = await _call_tool(
        cmd,
        'get_market_data',
        {
            'codes': codes,
            'start_date': today,
            'end_date': today,
            'source': source,
            'interval': '1D',
            'max_rows': 5,
        },
        outer_timeout=15.0,
        inner_timeout=10.0,
    )
    if res.get('ok'):
        # Cache the shape the WebUI expects ({data: ...}) so a cached hit and a
        # fresh hit are the same payload.
        _cache.set(cache_k, {'data': res.get('data', res.get('raw'))}, ttl=_QUOTE_TTL_SECONDS)
    res['cached'] = False
    return res


async def _backtest(run_dir: str) -> Dict[str, Any]:
    cmd = _resolve_mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH'}
    cache_k = _BACKTEST_NS + '|' + run_dir
    hit = _cache.get(cache_k)
    if hit is not None:
        return {'ok': True, 'cached': True, **hit}
    res = await _call_tool(cmd, 'backtest', {'run_dir': run_dir}, outer_timeout=120.0, inner_timeout=110.0)
    if res.get('ok') and not res.get('cached'):
        _cache.set(cache_k, res, ttl=_BACKTEST_TTL_SECONDS)
    return res


async def _patterns(run_dir: str) -> Dict[str, Any]:
    """Chart-pattern detection over a backtest run's OHLCV artifacts.

    Upstream `pattern_recognition` reads run_dir/artifacts/ohlcv_*.csv, so
    this complements a backtest run rather than a bare symbol lookup.
    """
    run_dir = (run_dir or '').strip()
    if not run_dir:
        return {'ok': False, 'error': 'run_dir is required (path to a backtest run directory containing artifacts/ohlcv_*.csv)'}
    cmd = _resolve_mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH'}
    # Older upstream builds (< 0.1.10) lack the tool; surface a clear message.
    try:
        from api.tools import _get_tools
        tools_res = await _get_tools(force=False)
        names = tools_res.get('tools') or []
        if names and 'pattern_recognition' not in names:
            return {
                'ok': False,
                'error': 'pattern_recognition is not exposed by the installed vibe-trading-mcp '
                         '(needs upstream >= 0.1.10). Re-run: pip install -U vibe-trading-ai',
            }
    except Exception:
        pass  # probe is best-effort; the direct call will error if the tool is missing

    cache_k = _PATTERNS_NS + '|' + run_dir
    hit = _cache.get(cache_k)
    if hit is not None:
        return {'ok': True, 'cached': True, **hit}
    res = await _call_tool(cmd, 'pattern_recognition', {'run_dir': run_dir}, outer_timeout=90.0, inner_timeout=80.0)
    if res.get('ok'):
        _cache.set(cache_k, {'data': res.get('data', res.get('raw'))}, ttl=_PATTERNS_TTL_SECONDS)
    return res


async def _factor(payload: Dict[str, Any]) -> Dict[str, Any]:
    codes = payload.get('codes') or []
    factor_name = payload.get('factor_name') or ''
    if not codes or not factor_name:
        return {'ok': False, 'error': 'codes (list) and factor_name (str) are required'}
    cmd = _resolve_mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH'}
    arguments = {
        'codes': codes,
        'factor_name': factor_name,
        'start_date': payload.get('start_date') or '',
        'end_date': payload.get('end_date') or '',
        'source': payload.get('source') or 'auto',
        'top_n': int(payload.get('top_n') or 10),
        'bottom_n': int(payload.get('bottom_n') or 10),
    }
    cache_k = _factor_cache_key(payload)
    hit = _cache.get(cache_k)
    if hit is not None:
        return {'ok': True, 'cached': True, **hit}
    res = await _call_tool(cmd, 'factor_analysis', arguments, outer_timeout=90.0, inner_timeout=80.0)
    if res.get('ok') and not res.get('cached'):
        _cache.set(cache_k, res, ttl=_FACTOR_TTL_SECONDS)
    return res


async def _snapshot(force: bool = False) -> Dict[str, Any]:
    if not force:
        hit = _cache.get(_SNAPSHOT_NS)
        if hit is not None:
            return {'ok': True, 'cached': True, **hit}

    out: Dict[str, Any] = {}
    try:
        import hooks  # type: ignore  # local plugin import
        out['stats'] = hooks.self_check()
    except Exception as e:
        out['stats'] = {'error': f'hooks.self_check failed: {e}'}

    from api.tools import _get_tools  # type: ignore  # reuse cache
    try:
        t = await _get_tools(force=force)
        out['tools'] = {
            'names': t.get('tools', []),
            'count': len(t.get('tools', [])),
            'error': t.get('error'),
            'cached': t.get('cached', False),
        }
    except Exception as e:
        out['tools'] = {'names': [], 'count': 0, 'error': str(e)[:200]}

    _cache.set(_SNAPSHOT_NS, out, ttl=_SNAPSHOT_TTL_SECONDS)
    return {'ok': True, 'cached': False, **out}


class Dashboard(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = (input_data.get('action') or '').strip().lower()
        if not action:
            return {'success': False, 'error': "missing 'action' in body (one of: snapshot, quote, backtest, factor)"}

        if action == 'snapshot':
            force = bool(input_data.get('force', False))
            res = await _snapshot(force=force)
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        if action == 'quote':
            codes = input_data.get('codes') or []
            if isinstance(codes, str):
                codes = [c.strip() for c in codes.split(',') if c.strip()]
            if not codes or not isinstance(codes, list):
                return {'success': False, 'action': action, 'error': 'codes (list of symbols) is required'}
            source = input_data.get('source') or 'auto'
            res = await _quote(codes=codes, source=source)
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        if action == 'backtest':
            run_dir = input_data.get('run_dir') or ''
            res = await _backtest(run_dir=run_dir)
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        if action == 'patterns':
            res = await _patterns(input_data.get('run_dir') or '')
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        if action == 'factor':
            res = await _factor(input_data)
            ok = bool(res.get('ok'))
            return {'success': ok, 'action': action, **res}

        return {'success': False, 'error': f"unknown action: {action!r} (expected one of: snapshot, quote, backtest, factor, patterns)"}
