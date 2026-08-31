'''
Vibe-Trading -- market watch alerts (Phase 9).

Route: POST /api/plugins/vibe_trading/watch

A lightweight, persisted price-alert watchlist the user manages from the
Market Watch page (webui/watch.html). Rules live in watch_rules.json at
the plugin root (gitignored -- runtime user data, never published).

This handler NEVER places an order. It only reads market data and
compares it against user-set thresholds.

Actions:
    list    -> all persisted watch rules
    add     -> add one rule (symbol, condition, threshold, note?, source?)
    remove  -> remove one rule by id
    check   -> evaluate every rule against the live quote (MCP
               get_market_data via the dashboard quote path) and return
               triggered flags. Also stamps each rule with its last state.

A rule is:
    { id, symbol, source, condition: 'price_above' | 'price_below',
      threshold: float, note: str, created: iso8601,
      last_triggered: bool }

Evaluation is on-demand (page refresh or "Check now"), never a background
worker -- the plugin registers no scheduled tasks (AGENTS.md contract).

Single-quote string literals only.
'''

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, List, Optional

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Runtime user data -- gitignored, never publish (see .gitignore).
WATCH_FILE = os.path.join(PLUGIN_ROOT, 'watch_rules.json')

CONDITIONS = ('price_above', 'price_below')

_CLOSE_KEYS = ('close', 'Close', 'close_price', 'last', 'price')
_ROW_KEYS = ('data', 'rows', 'bars', 'items', 'records')


def _read_watches() -> List[Dict[str, Any]]:
    try:
        with open(WATCH_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return [w for w in data if isinstance(w, dict)]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    except Exception:
        pass
    return []


def _write_watches(watches: List[Dict[str, Any]]) -> bool:
    tmp = WATCH_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(watches, f, indent=2, ensure_ascii=False)
        os.replace(tmp, WATCH_FILE)
        return True
    except Exception:
        return False


def _clean_symbol(symbol: Any) -> str:
    return str(symbol or '').replace(' ', '').strip()


def time_now_iso() -> str:
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def extract_last_close(res: Dict[str, Any]) -> Optional[float]:
    '''Best-effort: pull the most recent close price out of a get_market_data
    response envelope. The upstream payload shape varies by loader; handle
    the common shapes and otherwise give up gracefully (None).'''
    data = res.get('data')

    def _row_close(row: Any) -> Optional[float]:
        if not isinstance(row, dict):
            return None
        for ck in _CLOSE_KEYS:
            v = row.get(ck)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        return None

    if isinstance(data, dict):
        for ck in _CLOSE_KEYS:
            v = data.get(ck)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)

    rows: List[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for rk in _ROW_KEYS:
            inner = data.get(rk)
            if isinstance(inner, list):
                rows = inner
                break
        if not rows:
            # {symbol: [rows]} or {symbol: {close: ...}} keyed maps
            for v in data.values():
                if isinstance(v, list):
                    rows = v
                    break
                if isinstance(v, dict):
                    for ck in _CLOSE_KEYS:
                        v2 = v.get(ck)
                        if isinstance(v2, (int, float)) and v2 > 0:
                            return float(v2)

    if isinstance(data, dict) and not rows:
        for symbol_rows in data.values():
            if isinstance(symbol_rows, list):
                rows = symbol_rows
                break

    for row in reversed(rows):
        close = _row_close(row)
        if close is not None:
            return close
    return None


def _evaluate(rule: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        'id': rule.get('id'),
        'symbol': rule.get('symbol'),
        'condition': rule.get('condition'),
        'threshold': rule.get('threshold'),
        'note': rule.get('note') or '',
        'last_close': None,
        'triggered': False,
        'error': None,
    }
    if not res.get('ok'):
        out['error'] = str(res.get('error') or 'quote failed')[:200]
        return out
    close = extract_last_close(res)
    if close is None:
        out['error'] = 'no close price found in quote payload'
        return out
    out['last_close'] = close
    try:
        threshold = float(rule.get('threshold'))
    except (TypeError, ValueError):
        out['error'] = 'rule has invalid threshold'
        return out
    if rule.get('condition') == 'price_above':
        out['triggered'] = close >= threshold
    elif rule.get('condition') == 'price_below':
        out['triggered'] = close <= threshold
    return out


class Watch(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = (input_data.get('action') or '').strip().lower()

        if action == 'list':
            return {'success': True, 'watches': _read_watches()}

        if action == 'add':
            symbol = _clean_symbol(input_data.get('symbol'))
            condition = (input_data.get('condition') or '').strip().lower()
            try:
                threshold = float(input_data.get('threshold'))
            except (TypeError, ValueError):
                return {'success': False, 'error': 'threshold must be a number'}
            if not symbol:
                return {'success': False, 'error': 'symbol is required'}
            if not re.match(r'^[\w./:^=-]+$', symbol):
                return {'success': False, 'error': 'symbol contains invalid characters'}
            if condition not in CONDITIONS:
                return {'success': False, 'error': 'condition must be one of: ' + ', '.join(CONDITIONS)}
            if threshold <= 0:
                return {'success': False, 'error': 'threshold must be > 0'}

            watches = _read_watches()
            rule = {
                'id': _new_id(),
                'symbol': symbol,
                'source': (input_data.get('source') or 'auto').strip() or 'auto',
                'condition': condition,
                'threshold': threshold,
                'note': str(input_data.get('note') or '')[:200],
                'created': time_now_iso(),
            }
            watches.append(rule)
            if not _write_watches(watches):
                return {'success': False, 'error': 'could not write watch_rules.json'}
            return {'success': True, 'watches': watches}

        if action == 'remove':
            rid = str(input_data.get('id') or '').strip()
            watches = _read_watches()
            remaining = [w for w in watches if w.get('id') != rid]
            if len(remaining) == len(watches):
                return {'success': False, 'error': 'no rule with id: ' + repr(rid)}
            _write_watches(remaining)
            return {'success': True, 'watches': remaining}

        if action == 'check':
            return await _check()

        return {'success': False, 'error': "missing or unknown 'action' (one of: list, add, remove, check)"}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


async def _check() -> Dict[str, Any]:
    watches = _read_watches()
    if not watches:
        return {'success': True, 'checked_at': time_now_iso(), 'results': [], 'triggered': 0}

    from api import dashboard as _db  # reuse the cached quote path

    results: List[Dict[str, Any]] = []
    for rule in watches:
        res = await _db._quote(codes=[rule.get('symbol') or ''], source=rule.get('source') or 'auto')
        results.append(_evaluate(rule, res))

    # Stamp last-triggered state so the page can colour rules after a
    # reload too. A storage failure never fails the request.
    prev = sorted(w.get('id') for w in watches if w.get('last_triggered'))
    now = sorted(r['id'] for r in results if r.get('triggered'))
    if prev != now:
        ids_now = set(now)
        for w in watches:
            w['last_triggered'] = w.get('id') in ids_now
        _write_watches(watches)

    return {
        'success': True,
        'checked_at': time_now_iso(),
        'results': results,
        'triggered': sum(1 for r in results if r.get('triggered')),
    }