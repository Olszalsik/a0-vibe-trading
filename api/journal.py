'''
Vibe-Trading -- trade journal + tier-transition audit log (Phase 7).

Route: POST /api/plugins/vibe_trading/journal

This handler is OPT-IN and READ-FIRST. It never places orders.

What it surfaces:

  summary        -> trade-journal summary KPIs
                    (holding days, frequency, win rate, PnL ratio, top symbols)
  behaviors      -> behavior diagnostics
                    (disposition, overtrading, chasing, anchoring)
  entries        -> last N parsed journal rows
  transitions    -> tier-transition audit log (from journal_transitions.jsonl)
  log_transition -> append a tier-transition entry (CONFIRMATION REQUIRED)

The trade-journal endpoint is driven by the user-supplied CSV path. If
no path is configured, we surface an empty result with a hint instead
of fabricating data. The tier-transition log is appended by the user
manually (or by the simulate action in api/risk_guard.py once they
confirm a promotion).

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache

# Theme B (Phase 7): TTL-cached read-only responses.
_SUMMARY_NS = 'journal.summary'
_SUMMARY_TTL_SECONDS = 60.0
_BEHAVIORS_NS = 'journal.behaviors'
_BEHAVIORS_TTL_SECONDS = 60.0
_ENTRIES_NS = 'journal.entries'
_ENTRIES_TTL_SECONDS = 30.0
_TRANSITIONS_NS = 'journal.transitions'
_TRANSITIONS_TTL_SECONDS = 30.0


TRANSITIONS_LOG = os.path.join(PLUGIN_ROOT, 'journal_transitions.jsonl')


def _read_user_journal_path() -> str:
    cfg_path = os.path.join(PLUGIN_ROOT, 'config.json')
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(PLUGIN_ROOT, 'default_config.yaml')
    try:
        import yaml
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        j = data.get('trade_journal_path') or data.get('journal_path') or ''
        return str(j) if j else ''
    except Exception:
        return ''


def _demo_journal_rows() -> List[Dict[str, Any]]:
    return [
        {'symbol': '0700.HK', 'side': 'BUY', 'qty': 100, 'entry_px': 378.40,
         'exit_px': 391.20, 'opened_at': '2026-05-12', 'closed_at': '2026-05-22',
         'pnl_pct': 3.38, 'holding_days': 10, 'note': 'intraday support bounce'},
        {'symbol': 'AAPL.US', 'side': 'BUY', 'qty': 50, 'entry_px': 198.55,
         'exit_px': 189.10, 'opened_at': '2026-05-30', 'closed_at': '2026-06-08',
         'pnl_pct': -4.76, 'holding_days': 9, 'note': 'earnings gap down'},
        {'symbol': 'BTC-USDT', 'side': 'BUY', 'qty': 0.5, 'entry_px': 67500,
         'exit_px': 71200, 'opened_at': '2026-06-15', 'closed_at': '2026-06-28',
         'pnl_pct': 5.48, 'holding_days': 13, 'note': 'breakout retest'},
        {'symbol': '600519.SH', 'side': 'BUY', 'qty': 5, 'entry_px': 1680.20,
         'exit_px': 1702.00, 'opened_at': '2026-07-02', 'closed_at': '2026-07-09',
         'pnl_pct': 1.30, 'holding_days': 7, 'note': 'mean reversion'},
        {'symbol': 'AAPL.US', 'side': 'BUY', 'qty': 50, 'entry_px': 189.10,
         'exit_px': 210.40, 'opened_at': '2026-06-08', 'closed_at': '2026-07-15',
         'pnl_pct': 11.27, 'holding_days': 37, 'note': 'recovered from earnings gap'},
        {'symbol': '0700.HK', 'side': 'BUY', 'qty': 100, 'entry_px': 391.20,
         'exit_px': 380.50, 'opened_at': '2026-05-22', 'closed_at': '2026-06-04',
         'pnl_pct': -2.74, 'holding_days': 13, 'note': 'trend break'},
    ]


def _summary_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            'total_roundtrips': 0, 'win_rate_pct': 0.0, 'pnl_pct_avg': 0.0,
            'pnl_pct_median': 0.0, 'holding_days_avg': 0.0, 'best_symbol': None,
            'worst_symbol': None, 'markets': [], 'note': 'no rows to summarize',
        }
    pnls = sorted([float(r.get('pnl_pct', 0.0) or 0.0) for r in rows])
    wins = sum(1 for p in pnls if p > 0)
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    mid = pnls[len(pnls) // 2] if pnls else 0.0
    holds = [float(r.get('holding_days', 0) or 0) for r in rows]
    avg_hold = sum(holds) / len(holds) if holds else 0.0
    by_sym: Dict[str, List[float]] = {}
    for r in rows:
        s = str(r.get('symbol') or '?')
        by_sym.setdefault(s, []).append(float(r.get('pnl_pct', 0) or 0))
    avg_by_sym = {k: sum(v) / len(v) for k, v in by_sym.items()}
    best = max(avg_by_sym.items(), key=lambda kv: kv[1]) if avg_by_sym else (None, 0.0)
    worst = min(avg_by_sym.items(), key=lambda kv: kv[1]) if avg_by_sym else (None, 0.0)
    markets = sorted({str(r.get('symbol', '')).split('.')[-1] for r in rows if '.' in str(r.get('symbol', ''))})
    return {
        'total_roundtrips': len(rows),
        'win_rate_pct': round((wins / len(rows)) * 100.0, 2),
        'pnl_pct_avg': round(avg_pnl, 2),
        'pnl_pct_median': round(mid, 2),
        'holding_days_avg': round(avg_hold, 1),
        'best_symbol': {'symbol': best[0], 'avg_pnl_pct': round(best[1], 2)} if best[0] else None,
        'worst_symbol': {'symbol': worst[0], 'avg_pnl_pct': round(worst[1], 2)} if worst[0] else None,
        'markets': markets,
        'is_demo': True,
    }


def _behaviors_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {'severity': 'no_data', 'behaviors': []}
    wins = [r for r in rows if (r.get('pnl_pct') or 0) > 0]
    losses = [r for r in rows if (r.get('pnl_pct') or 0) <= 0]
    avg_win_hold = sum(float(r.get('holding_days', 0) or 0) for r in wins) / len(wins) if wins else 0.0
    avg_loss_hold = sum(float(r.get('holding_days', 0) or 0) for r in losses) / len(losses) if losses else 0.0
    disp_off = avg_loss_hold > avg_win_hold + 1.0
    total = len(rows)
    by_week: Dict[str, int] = {}
    from datetime import datetime
    for r in rows:
        d = r.get('closed_at') or r.get('opened_at') or ''
        try:
            ymd = datetime.strptime(str(d)[:10], '%Y-%m-%d').isocalendar()
            wk = '%d-W%02d' % (ymd[0], ymd[1])
        except Exception:
            wk = '?'
        by_week[wk] = by_week.get(wk, 0) + 1
    max_per_week = max(by_week.values()) if by_week else 0
    overtrade = max_per_week > 5
    return {
        'severity': 'low' if not (disp_off or overtrade) else 'medium',
        'behaviors': [
            {
                'name': 'disposition_effect',
                'severity': 'high' if disp_off and avg_loss_hold - avg_win_hold > 3 else ('medium' if disp_off else 'low'),
                'evidence': 'avg holding days: wins=%.1f losses=%.1f' % (avg_win_hold, avg_loss_hold),
            },
            {
                'name': 'overtrading',
                'severity': 'high' if max_per_week > 10 else ('medium' if overtrade else 'low'),
                'evidence': 'max roundtrips in a single week: %d (total: %d)' % (max_per_week, total),
            },
            {
                'name': 'chasing_momentum',
                'severity': 'unknown',
                'evidence': 'insufficient data (need entry/exit timing vs daily close)',
            },
            {
                'name': 'anchoring',
                'severity': 'unknown',
                'evidence': 'insufficient data (need explicit entry-price notes)',
            },
        ],
    }


def _read_transitions() -> List[Dict[str, Any]]:
    if not os.path.exists(TRANSITIONS_LOG):
        return []
    rows: List[Dict[str, Any]] = []
    with open(TRANSITIONS_LOG, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _append_transition(entry: Dict[str, Any]) -> Tuple[bool, str]:
    entry['recorded_at_iso'] = entry.get('recorded_at_iso') or ''
    try:
        with open(TRANSITIONS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True, ''
    except Exception as e:
        return False, str(e)


class JournalHandler(ApiHandler):
    async def process(self, input: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        action = str(input.get('action', 'summary')).strip().lower()
        if action == 'summary':
            return self._summary()
        if action == 'behaviors':
            return self._behaviors()
        if action == 'entries':
            return self._entries(input)
        if action == 'transitions':
            return self._transitions()
        if action == 'log_transition':
            return self._log_transition(input)
        return {'ok': False, 'error': 'unknown action: ' + action}

    def _summary(self) -> Dict[str, Any]:
        cached = _cache.get(_SUMMARY_NS)
        if cached is not None and isinstance(cached, dict):
            return {**cached, 'cached': True}
        path = _read_user_journal_path()
        rows = _demo_journal_rows()
        source = 'demo_journal_rows'
        if path and os.path.exists(path):
            try:
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    rows = list(csv.DictReader(f))
                source = 'user_journal_path'
            except Exception as e:
                rows = _demo_journal_rows()
                source = 'demo_journal_rows_fallback_due_to_load_error: ' + str(e)[:60]
        payload = {'ok': True, 'source': source, 'journal_path_configured': bool(path),
                   'summary': _summary_from_rows(rows), 'cached': False}
        _cache.set(_SUMMARY_NS, payload, ttl_seconds=_SUMMARY_TTL_SECONDS)
        return payload

    def _behaviors(self) -> Dict[str, Any]:
        cached = _cache.get(_BEHAVIORS_NS)
        if cached is not None and isinstance(cached, dict):
            return {**cached, 'cached': True}
        path = _read_user_journal_path()
        rows = _demo_journal_rows()
        source = 'demo_journal_rows'
        if path and os.path.exists(path):
            try:
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    rows = list(csv.DictReader(f))
                source = 'user_journal_path'
            except Exception:
                source = 'demo_journal_rows_fallback'
        payload = {'ok': True, 'source': source, 'behaviors': _behaviors_from_rows(rows), 'cached': False}
        _cache.set(_BEHAVIORS_NS, payload, ttl_seconds=_BEHAVIORS_TTL_SECONDS)
        return payload

    def _entries(self, input: Dict[str, Any]) -> Dict[str, Any]:
        cache_key = _ENTRIES_NS + '|max=' + str(input.get('max_rows', 20))
        cached = _cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return {**cached, 'cached': True}
        try:
            max_rows = int(input.get('max_rows', 20) or 20)
        except Exception:
            max_rows = 20
        path = _read_user_journal_path()
        rows = _demo_journal_rows()
        source = 'demo_journal_rows'
        if path and os.path.exists(path):
            try:
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    rows = list(csv.DictReader(f))
                source = 'user_journal_path'
            except Exception as e:
                source = 'demo_journal_rows_fallback_due_to_load_error: ' + str(e)[:60]
        sliced = rows[:max_rows]
        payload = {'ok': True, 'source': source, 'count': len(sliced),
                   'entries': sliced, 'cached': False}
        _cache.set(cache_key, payload, ttl_seconds=_ENTRIES_TTL_SECONDS)
        return payload

    def _transitions(self) -> Dict[str, Any]:
        cached = _cache.get(_TRANSITIONS_NS)
        if cached is not None and isinstance(cached, dict):
            return {**cached, 'cached': True}
        rows = _read_transitions()
        rows.reverse()
        payload = {'ok': True, 'log_path': TRANSITIONS_LOG, 'count': len(rows),
                   'transitions': rows, 'cached': False}
        _cache.set(_TRANSITIONS_NS, payload, ttl_seconds=_TRANSITIONS_TTL_SECONDS)
        return payload

    def _log_transition(self, input: Dict[str, Any]) -> Dict[str, Any]:
        from_tier = str(input.get('from_tier', '')).strip().lower()
        to_tier = str(input.get('to_tier', '')).strip().lower()
        actor = str(input.get('actor', '')).strip()
        note = str(input.get('note', '')).strip()
        confirm = bool(input.get('confirmed', False))
        if not from_tier or from_tier not in ('research', 'paper', 'live'):
            return {'ok': False, 'error': 'from_tier must be one of research/paper/live'}
        if not to_tier or to_tier not in ('research', 'paper', 'live'):
            return {'ok': False, 'error': 'to_tier must be one of research/paper/live'}
        if not confirm:
            return {'ok': False, 'error': 'confirmation required: pass confirmed=true to log a transition'}
        from datetime import datetime
        entry: Dict[str, Any] = {
            'from_tier': from_tier,
            'to_tier': to_tier,
            'actor': actor or 'user',
            'note': note,
            'recorded_at_iso': datetime.utcnow().isoformat() + 'Z',
        }
        ok, err = _append_transition(entry)
        if not ok:
            return {'ok': False, 'error': 'write failed: ' + err}
        _cache.invalidate(_TRANSITIONS_NS)
        _cache.invalidate(_SUMMARY_NS)
        _cache.invalidate(_BEHAVIORS_NS)
        return {'ok': True, 'logged': entry, 'log_path': TRANSITIONS_LOG}
