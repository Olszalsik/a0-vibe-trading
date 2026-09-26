'''
Vibe-Trading -- Shadow Account 5-step orchestrator.

Route: POST /api/plugins/vibe_trading/shadow

Action 'run_loop' drives the full Shadow protocol:
  1. analyze_trade_journal(file_path=..., analysis_type='full')
  2. extract_shadow_strategy(journal_path=..., min_support, max_rules)
  3. run_shadow_backtest(shadow_id, window, markets)
  4. render_shadow_report(shadow_id, include_today_signals=True)
  5. scan_shadow_signals(shadow_id, date=today, per_market=3)

Action 'report_html' reads a previously rendered report artifact
(path returned by run_loop as report_path) and returns its text so the
WebUI can display it. Read-only, size-capped.

Each step is bounded by asyncio.wait_for(...). Failed steps are recorded
in steps[].error and do not abort the chain.

The run cache is keyed by the journal file's CONTENT hash (plus the window
args), mirroring upstream's journal-hash keying: re-running after a new
upload forces a fresh analysis instead of serving the previous diagnosis
from the TTL cache.

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Two-venv trap: shared canonical binary resolver (plugin root, shadow-proof).
import vibe_trading_bin as _bin


_CACHE: Dict[str, Any] = {'fetched_at': 0.0, 'key': None, 'report': None}
_CACHE_TTL_SECONDS = 300.0


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
                    return {'ok': True, 'data': parsed, 'raw': joined[:12000]}
                return {'ok': True, 'raw': joined[:12000]}

    try:
        return await asyncio.wait_for(_run(), timeout=_bin.call_budget(outer, inner))
    except Exception as e:
        return {'ok': False, 'error': str(e)[:400]}


async def _run_loop(payload: Dict[str, Any]) -> Dict[str, Any]:
    cmd = _bin.resolve_mcp_command()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not found; check mcp_command and package installation', 'steps': []}

    journal_path = payload.get('journal_path') or ''
    if not journal_path:
        return {'ok': False, 'error': 'journal_path is required (absolute path to the user upload)', 'steps': []}
    if not os.path.isfile(journal_path):
        return {'ok': False, 'error': 'journal file not found: ' + journal_path, 'steps': []}

    min_support = int(payload.get('min_support') or 3)
    max_rules = int(payload.get('max_rules') or 5)
    markets = payload.get('markets') or ['china_a', 'hk', 'us', 'crypto']
    if isinstance(markets, str):
        markets = [m.strip() for m in markets.split(',') if m.strip()]

    # Key the run cache by the journal file's content hash: the same path with
    # new contents must miss, identical contents re-uploaded under a new name may hit.
    try:
        with open(journal_path, 'rb') as _jf:
            journal_sha = hashlib.sha256(_jf.read()).hexdigest()[:16]
    except OSError:
        journal_sha = 'unreadable'

    cache_key = (journal_path, journal_sha, min_support, max_rules, ','.join(markets))
    now = time.time()
    if not bool(payload.get('force')) and _CACHE['key'] == cache_key \
            and (now - _CACHE['fetched_at']) < _CACHE_TTL_SECONDS:
        return {'ok': True, 'cached': True, **_CACHE['report']}

    today = time.strftime('%Y-%m-%d')
    one_year_ago = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 365 * 86400))

    steps_out: List[Dict[str, Any]] = []
    shadow_id = ''

    journal_analysis = await _call_tool(
        cmd, 'analyze_trade_journal',
        {'file_path': journal_path, 'analysis_type': 'full'},
        30.0, 25.0,
    )
    jdata = journal_analysis.get('data')
    steps_out.append({
        'step': 1,
        'name': 'analyze_trade_journal',
        'ok': bool(journal_analysis.get('ok')),
        'error': journal_analysis.get('error'),
        'preview_keys': list(jdata.keys())[:8] if isinstance(jdata, dict) else None,
    })

    strategy = await _call_tool(
        cmd, 'extract_shadow_strategy',
        {'journal_path': journal_path, 'min_support': min_support, 'max_rules': max_rules},
        60.0, 55.0,
    )
    strategy_data = strategy.get('data') if strategy.get('ok') else None
    if isinstance(strategy_data, dict):
        shadow_id = str(strategy_data.get('shadow_id') or '')
    steps_out.append({
        'step': 2,
        'name': 'extract_shadow_strategy',
        'ok': bool(strategy.get('ok')),
        'error': strategy.get('error'),
        'shadow_id': shadow_id,
        'rules_preview': (strategy_data or {}).get('rules') if isinstance(strategy_data, dict) else None,
    })

    if not shadow_id:
        steps_out.append({'step': 3, 'name': 'run_shadow_backtest', 'ok': False, 'error': 'no shadow_id returned (skipping)'})
        steps_out.append({'step': 4, 'name': 'render_shadow_report', 'ok': False, 'error': 'no shadow_id (skipping)'})
        steps_out.append({'step': 5, 'name': 'scan_shadow_signals', 'ok': False, 'error': 'no shadow_id (skipping)'})
        report = {
            'steps': steps_out,
            'shadow_id': '',
            'warning': 'no shadow_id returned -- earlier steps may have failed',
        }
        _CACHE['key'] = cache_key
        _CACHE['fetched_at'] = now
        _CACHE['report'] = report
        return {'ok': False, 'cached': False, **report}

    backtest = await _call_tool(
        cmd, 'run_shadow_backtest',
        {
            'shadow_id': shadow_id,
            'window_start': one_year_ago,
            'window_end': today,
            'markets': markets,
            'journal_path': journal_path,
        },
        180.0, 170.0,
    )
    bdata = backtest.get('data')
    steps_out.append({
        'step': 3,
        'name': 'run_shadow_backtest',
        'ok': bool(backtest.get('ok')),
        'error': backtest.get('error'),
        'preview_keys': list(bdata.keys())[:8] if isinstance(bdata, dict) else None,
    })

    report_call = await _call_tool(
        cmd, 'render_shadow_report',
        {'shadow_id': shadow_id, 'include_today_signals': True, 'journal_path': journal_path},
        120.0, 110.0,
    )
    report_data = report_call.get('data') if report_call.get('ok') else None
    report_path = ''
    if isinstance(report_data, dict):
        for k in ('report_path', 'html_path', 'output_path', 'path', 'file', 'filename'):
            v = report_data.get(k)
            if isinstance(v, str) and v.strip():
                report_path = v.strip()
                break
    elif isinstance(report_data, str) and report_data.strip():
        report_path = report_data.strip()
    steps_out.append({
        'step': 4,
        'name': 'render_shadow_report',
        'ok': bool(report_call.get('ok')),
        'error': report_call.get('error'),
        'report_path': report_path or None,
    })

    signals = await _call_tool(
        cmd, 'scan_shadow_signals',
        {'shadow_id': shadow_id, 'date': today, 'per_market': 3},
        60.0, 55.0,
    )
    sdata = signals.get('data')
    steps_out.append({
        'step': 5,
        'name': 'scan_shadow_signals',
        'ok': bool(signals.get('ok')),
        'error': signals.get('error'),
        'signal_preview': sdata if isinstance(sdata, list) else None,
    })

    ok_count = sum(1 for s in steps_out if s.get('ok'))
    report = {
        'steps': steps_out,
        'shadow_id': shadow_id,
        'journal_sha256_16': journal_sha,
        'report_path': report_path or None,
        'ok_count': ok_count,
        'summary': 'all 5 steps succeeded' if ok_count == len(steps_out) else str(ok_count) + '/' + str(len(steps_out)) + ' steps succeeded',
    }

    _CACHE['key'] = cache_key
    _CACHE['fetched_at'] = now
    _CACHE['report'] = report
    return {'ok': True, 'cached': False, **report}


_REPORT_MAX_BYTES = 2 * 1024 * 1024


def _read_report_html(path: str) -> Dict[str, Any]:
    p = (path or '').strip()
    if not p:
        return {'ok': False, 'error': 'path is required'}
    if not os.path.isabs(p):
        return {'ok': False, 'error': 'path must be absolute'}
    if not os.path.isfile(p):
        return {'ok': False, 'error': 'report file not found: ' + p}
    try:
        size = os.path.getsize(p)
    except OSError as e:
        return {'ok': False, 'error': 'stat failed: ' + str(e)}
    if size > _REPORT_MAX_BYTES:
        return {'ok': False, 'error': 'report too large to display (' + str(size) + ' bytes)'}
    try:
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except Exception as e:
        return {'ok': False, 'error': 'read failed: ' + str(e)}
    return {'ok': True, 'path': p, 'size_bytes': size, 'html': text}


class Shadow(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or 'run_loop').strip().lower()
        if action == 'report_html':
            return {'success': True, 'action': action, **_read_report_html(str(input_data.get('path') or ''))}

        if action != 'run_loop':
            return {'success': False, 'error': "unknown action: '" + action + "' (expected 'run_loop' or 'report_html')"}

        res = await _run_loop(input_data)
        ok = bool(res.get('ok'))
        return {'success': ok, 'action': action, **res}
