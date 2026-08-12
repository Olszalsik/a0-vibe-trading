'''
Vibe-Trading -- live-trade risk guard (Phase 6).

Route: POST /api/plugins/vibe_trading/risk_guard

This handler is OPT-IN and GATED. The plugin default `risk_tier` is
`research`, which keeps every code path read-only. This handler surfaces:

  - the current `risk_tier` from plugin config (or environment override)
  - whether the confirmation gate is required
  - which broker connectors are reachable (read-only via MCP)
  - a dry-run of what would change if the user moved from `research` to
    `paper` or `live`
  - a banner message for the dashboard explaining the current gate

This handler NEVER places an order. It only surfaces state.

Actions:
    state         -> risk snapshot + banner           action \'state\'
    connectors    -> trading_connections()            action \'connectors\'
    check_broker  -> trading_check(connection)        action \'check_broker\'
    simulate      -> dry-run promotion path           action \'simulate\'

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from helpers import cache as _cache  # type: ignore

# Theme B (Phase 6): TTL-cached read-only responses.
_STATE_NS = 'risk_guard.state'
_STATE_TTL_SECONDS = 60.0
_CONNECTORS_NS = 'risk_guard.connectors'
_CONNECTORS_TTL_SECONDS = 300.0
_CHECK_NS = 'risk_guard.check'
_CHECK_TTL_SECONDS = 60.0


VALID_TIERS = ['research', 'paper', 'live']
TIER_DESCRIPTIONS = {
    'research': 'Read-only research. All trading_* tools return data; no order placement possible.',
    'paper': 'Paper trading. Trading connectors may execute simulated orders if the broker supports it. No real money at risk.',
    'live': 'Live trading. Real orders, real money. Requires explicit per-action confirmation and a working broker connector.',
}
TIER_BANNER_COLORS = {
    'research': '#2e7d32',
    'paper':    '#f57c00',
    'live':     '#c62828',
}


def _read_plugin_config() -> Dict[str, Any]:
    cfg_path = os.path.join(PLUGIN_ROOT, 'config.json')
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(PLUGIN_ROOT, 'default_config.yaml')
    try:
        import yaml
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_risk_tier() -> str:
    env_tier = os.environ.get('VIBE_TRADING_RISK_TIER', '').strip().lower()
    if env_tier in VALID_TIERS:
        return env_tier
    cfg = _read_plugin_config()
    cfg_tier = str(cfg.get('risk_tier', 'research')).strip().lower()
    return cfg_tier if cfg_tier in VALID_TIERS else 'research'


def _resolve_require_confirmation() -> bool:
    env_val = os.environ.get('VIBE_TRADING_REQUIRE_CONFIRMATION', '').strip().lower()
    if env_val in ('0', 'false', 'no', 'off'):
        return False
    if env_val in ('1', 'true', 'yes', 'on'):
        return True
    cfg = _read_plugin_config()
    val = cfg.get('require_explicit_confirmation', True)
    return bool(val) if isinstance(val, bool) else True


def _build_state_payload(tier: str, require_confirm: bool, connectors_cached: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        'ok': True,
        'risk_tier': tier,
        'risk_tier_description': TIER_DESCRIPTIONS.get(tier, 'unknown'),
        'require_explicit_confirmation': require_confirm,
        'banner_color': TIER_BANNER_COLORS.get(tier, '#666'),
        'valid_tiers': list(VALID_TIERS),
        'is_research_default': (tier == 'research'),
        'order_placement_enabled': (tier in ('paper', 'live')),
        'live_order_enabled': (tier == 'live'),
        'plugin_root': PLUGIN_ROOT,
        'config_resolved_from': (
            'env:VIBE_TRADING_RISK_TIER' if os.environ.get('VIBE_TRADING_RISK_TIER', '') else 'plugin_config'
        ),
    }
    if connectors_cached is not None:
        payload['connectors'] = connectors_cached
    return payload


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
    except asyncio.TimeoutError:
        return {'ok': False, 'error': 'MCP timeout'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


class RiskGuardHandler(ApiHandler):
    async def process(self, input: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        action = str(input.get('action', 'state')).strip().lower()
        if action == 'state':
            return await self._state()
        if action == 'connectors':
            return await self._connectors()
        if action == 'check_broker':
            return await self._check_broker(input)
        if action == 'simulate':
            return await self._simulate(input)
        return {'ok': False, 'error': 'unknown action: ' + action}

    async def _state(self) -> Dict[str, Any]:
        cached = _cache.get(_STATE_NS)
        if cached is not None and isinstance(cached, dict):
            return {**cached, 'cached': True}
        tier = _resolve_risk_tier()
        require_confirm = _resolve_require_confirmation()
        connectors_cached = _cache.get(_CONNECTORS_NS)
        payload = _build_state_payload(tier, require_confirm, connectors_cached if isinstance(connectors_cached, dict) else None)
        _cache.set(_STATE_NS, payload, ttl_seconds=_STATE_TTL_SECONDS)
        return {**payload, 'cached': False}

    async def _connectors(self) -> Dict[str, Any]:
        cached = _cache.get(_CONNECTORS_NS)
        if cached is not None and isinstance(cached, dict):
            return {'ok': True, 'connectors': cached, 'cached': True}
        cmd = shutil.which('vibe-trading-mcp') or 'vibe-trading-mcp'
        res = await _call_tool(cmd, 'trading_connections', {}, outer=15.0, inner=12.0)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error', 'mcp failure')}
        data = res.get('data') or {}
        _cache.set(_CONNECTORS_NS, data, ttl_seconds=_CONNECTORS_TTL_SECONDS)
        return {'ok': True, 'connectors': data, 'cached': False}

    async def _check_broker(self, input: Dict[str, Any]) -> Dict[str, Any]:
        connection = str(input.get('connection', '')).strip()
        if not connection:
            return {'ok': False, 'error': 'connection (broker id) is required'}
        cache_key = _CHECK_NS + '|' + connection
        cached = _cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return {'ok': True, 'result': cached, 'cached': True}
        cmd = shutil.which('vibe-trading-mcp') or 'vibe-trading-mcp'
        res = await _call_tool(cmd, 'trading_check', {'connection': connection}, outer=15.0, inner=12.0)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error', 'mcp failure')}
        data = res.get('data') or res.get('raw') or {}
        _cache.set(cache_key, data, ttl_seconds=_CHECK_TTL_SECONDS)
        return {'ok': True, 'result': data, 'cached': False}

    async def _simulate(self, input: Dict[str, Any]) -> Dict[str, Any]:
        target = str(input.get('target_tier', '')).strip().lower()
        if target not in VALID_TIERS:
            return {'ok': False, 'error': 'target_tier must be one of ' + str(VALID_TIERS)}
        current = _resolve_risk_tier()
        require_confirm = _resolve_require_confirmation()
        actions_to_take: List[str] = []
        if target == current:
            actions_to_take.append('No-op: already at ' + target)
        else:
            actions_to_take.append('Set plugin config risk_tier: ' + current + ' -> ' + target)
            if target in ('paper', 'live') and current == 'research':
                actions_to_take.append('Enable connector profiles (run trading_select_connection + trading_check)')
            if target == 'live':
                actions_to_take.append('Verify require_explicit_confirmation is true (gate blocks live orders until human says OK per action)')
            actions_to_take.append('Restart Agent Zero so hooks.py re-registers the MCP server with new risk_tier')
        return {
            'ok': True,
            'current_tier': current,
            'target_tier': target,
            'require_explicit_confirmation': require_confirm,
            'would_change': (target != current),
            'actions': actions_to_take,
            'note': 'DRY RUN -- nothing was changed. Apply via plugin.yaml / env / Settings UI to actually promote.',
        }
