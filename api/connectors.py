'''
Vibe-Trading -- trading connector proxy (read-only).

Route: POST /api/plugins/vibe_trading/connectors

All actions delegate to the MCP trading_* tools. NONE of these actions
may place a live order -- there is no order-placement MCP tool exposed
by the upstream server, and this plugin will never add one.

Actions:
    list      -> trading_connections()                         action 'list'
    select    -> trading_select_connection(connection)        action 'select'
    check     -> trading_check(connection, ...)                action 'check'
    account   -> trading_account(connection, ...)              action 'account'
    positions -> trading_positions(connection, ...)            action 'positions'
    orders    -> trading_orders(connection, account, ie)        action 'orders'
    quote     -> trading_quote(symbol, connection, ...)        action 'quote'
    history   -> trading_history(symbol, connection, ...)      action 'history'

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from typing import Any, Dict

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# Theme B: cached read-only responses (list / account / positions).
# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache

# Theme B: per-action TTL for connector read-only responses.
_LIST_NS = 'connectors.list'
_LIST_TTL_SECONDS = 300.0
_ACCOUNT_NS = 'connectors.account'
_ACCOUNT_TTL_SECONDS = 60.0
_POSITIONS_NS = 'connectors.positions'
_POSITIONS_TTL_SECONDS = 30.0


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


def _connection_opt(payload: Dict[str, Any]) -> str:
    conn = payload.get('connection') or ''
    return conn if isinstance(conn, str) else ''


def _populate(arguments: Dict[str, Any], payload: Dict[str, Any], keys) -> Dict[str, Any]:
    for k in keys:
        v = payload.get(k)
        if v is not None and v != '':
            arguments[k] = v
    return arguments


async def _dispatch(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cmd = shutil.which('vibe-trading-mcp')
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH'}

    if action == 'list':
        hit = _cache.get(_LIST_NS)
        if hit is not None:
            return {'ok': True, 'data': hit, 'cached': True}
        res = await _call_tool(cmd, 'trading_connections', {}, 15.0, 10.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(_LIST_NS, res.get('data'), ttl=_LIST_TTL_SECONDS)
        return res

    if action == 'select':
        connection = _connection_opt(payload)
        if not connection:
            return {'ok': False, 'error': 'connection is required for select'}
        return await _call_tool(cmd, 'trading_select_connection', {'connection': connection}, 15.0, 10.0)

    if action == 'check':
        arguments: Dict[str, Any] = {}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account'))
        if not arguments:
            return {'ok': False, 'error': 'at least one of (connection, host, port, client_id, account) is required for check'}
        return await _call_tool(cmd, 'trading_check', arguments, 15.0, 10.0)

    if action == 'account':
        arguments = {}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account'))
        _account_key = _ACCOUNT_NS + '|' + '|'.join('{}="{}"'.format(k, v) for k, v in sorted(arguments.items()))
        hit = _cache.get(_account_key)
        if hit is not None:
            return {'ok': True, 'data': hit, 'cached': True}
        res = await _call_tool(cmd, 'trading_account', arguments, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(_account_key, res.get('data'), ttl=_ACCOUNT_TTL_SECONDS)
        return res

    if action == 'positions':
        arguments = {}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account'))
        _positions_key = _POSITIONS_NS + '|' + '|'.join('{}="{}"'.format(k, v) for k, v in sorted(arguments.items()))
        hit = _cache.get(_positions_key)
        if hit is not None:
            return {'ok': True, 'data': hit, 'cached': True}
        res = await _call_tool(cmd, 'trading_positions', arguments, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(_positions_key, res.get('data'), ttl=_POSITIONS_TTL_SECONDS)
        return res

    if action == 'orders':
        arguments: Dict[str, Any] = {'include_executions': bool(payload.get('include_executions', False))}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account'))
        return await _call_tool(cmd, 'trading_orders', arguments, 20.0, 15.0)

    if action == 'quote':
        symbol = str(payload.get('symbol') or '').strip()
        if not symbol:
            return {'ok': False, 'error': 'symbol is required for quote'}
        arguments: Dict[str, Any] = {'symbol': symbol}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account', 'exchange', 'currency', 'sec_type'))
        return await _call_tool(cmd, 'trading_quote', arguments, 20.0, 15.0)

    if action == 'history':
        symbol = str(payload.get('symbol') or '').strip()
        if not symbol:
            return {'ok': False, 'error': 'symbol is required for history'}
        arguments: Dict[str, Any] = {'symbol': symbol}
        _populate(arguments, payload, ('connection', 'host', 'port', 'client_id', 'account', 'exchange', 'currency', 'sec_type', 'duration', 'bar_size', 'what_to_show', 'use_rth'))
        return await _call_tool(cmd, 'trading_history', arguments, 30.0, 25.0)

    return {'ok': False, 'error': 'unknown connector action: ' + repr(action)}


class Connectors(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or '').strip().lower()
        if not action:
            return {
                'success': False,
                'error': "missing 'action' (one of: list, select, check, account, positions, orders, quote, history)",
            }

        res = await _dispatch(action, input_data)
        ok = bool(res.get('ok'))
        return {'success': ok, 'action': action, **res}
