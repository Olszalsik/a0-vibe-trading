'''
Vibe-Trading -- research goals proxy (traceable research to-do board).

Route: POST /api/plugins/vibe_trading/research_goals

Proxies the upstream research-goal tools (present since 0.1.10):
    start_research_goal(...)        -> action 'start'
    get_research_goal(goal_id)      -> action 'get'
    add_goal_evidence(goal_id, ...) -> action 'add_evidence'
    update_research_goal_status(..) -> action 'update_status'
    list_research_goals(...)        -> action 'list'   (optional; older
                                       builds may not expose it -- the page
                                       degrades to its own localStorage ids)

Reads are TTL-cached; start/add_evidence/update_status are pass-through
mutations and invalidate the read caches.

Single-quote string literals only.
'''

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from typing import Any, Dict, List

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache

_LIST_NS = 'research_goals.list'
_LIST_TTL_SECONDS = 30.0
_GOAL_NS_PREFIX = 'research_goals.goal|'
_GOAL_TTL_SECONDS = 30.0

_VALID_STATUS = ('draft', 'active', 'paused', 'complete', 'abandoned')


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
                    return {'ok': True, 'data': parsed, 'raw': joined[:12000]}
                return {'ok': True, 'raw': joined[:12000]}

    try:
        return await asyncio.wait_for(_run(), timeout=outer)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:400]}


def _invalidate_goal_caches(goal_id: str = '') -> None:
    _cache.invalidate(_LIST_NS)
    _cache.invalidate(_GOAL_NS_PREFIX + '*')
    if goal_id:
        _cache.invalidate(_GOAL_NS_PREFIX + goal_id)


async def _goals_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cmd = shutil.which('vibe-trading-mcp')
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp not on PATH'}

    if action == 'list':
        hit = _cache.get(_LIST_NS)
        if hit is not None:
            return {'ok': True, 'cached': True, **hit}
        res = await _call_tool(cmd, 'list_research_goals', {}, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(_LIST_NS, res, ttl=_LIST_TTL_SECONDS)
        return res

    if action == 'start':
        question = str(payload.get('question') or '').strip()
        if not question:
            return {'ok': False, 'error': 'question is required'}
        arguments: Dict[str, Any] = {'question': question}
        hypothesis = str(payload.get('hypothesis') or '').strip()
        if hypothesis:
            arguments['hypothesis'] = hypothesis
        res = await _call_tool(cmd, 'start_research_goal', arguments, 30.0, 25.0)
        if res.get('ok'):
            _invalidate_goal_caches()
        return res

    if action == 'get':
        goal_id = str(payload.get('goal_id') or '').strip()
        if not goal_id:
            return {'ok': False, 'error': 'goal_id is required'}
        key = _GOAL_NS_PREFIX + goal_id
        hit = _cache.get(key)
        if hit is not None:
            return {'ok': True, 'cached': True, **hit}
        res = await _call_tool(cmd, 'get_research_goal', {'goal_id': goal_id}, 20.0, 15.0)
        if res.get('ok') and isinstance(res.get('data'), (list, dict)):
            _cache.set(key, res, ttl=_GOAL_TTL_SECONDS)
        return res

    if action == 'add_evidence':
        goal_id = str(payload.get('goal_id') or '').strip()
        if not goal_id:
            return {'ok': False, 'error': 'goal_id is required'}
        evidence = str(payload.get('evidence') or payload.get('text') or '').strip()
        if not evidence:
            return {'ok': False, 'error': 'evidence is required'}
        arguments: Dict[str, Any] = {'goal_id': goal_id, 'evidence': evidence}
        # optional extras the upstream tool accepts; pass through when given
        for src, dst in (('source', 'source'), ('url', 'url'), ('symbol', 'symbol'),
                         ('sentiment', 'sentiment'), ('confidence', 'confidence')):
            v = payload.get(src)
            if v not in (None, ''):
                arguments[dst] = v
        res = await _call_tool(cmd, 'add_goal_evidence', arguments, 30.0, 25.0)
        if res.get('ok'):
            _invalidate_goal_caches(goal_id)
        return res

    if action == 'update_status':
        goal_id = str(payload.get('goal_id') or '').strip()
        status = str(payload.get('status') or '').strip().lower()
        if not goal_id:
            return {'ok': False, 'error': 'goal_id is required'}
        if status not in _VALID_STATUS:
            return {'ok': False, 'error': 'status must be one of: ' + ', '.join(_VALID_STATUS)}
        arguments: Dict[str, Any] = {'goal_id': goal_id, 'status': status}
        note = str(payload.get('note') or '').strip()
        if note:
            arguments['note'] = note
        res = await _call_tool(cmd, 'update_research_goal_status', arguments, 30.0, 25.0)
        if res.get('ok'):
            _invalidate_goal_caches(goal_id)
        return res

    return {'ok': False, 'error': 'unknown research-goal action: ' + repr(action)}


class ResearchGoals(ApiHandler):
    async def process(self, input_data: Dict[str, Any], request) -> Dict[str, Any]:
        action = str(input_data.get('action') or '').strip().lower()
        if not action:
            return {'success': False, 'error': "missing 'action' (one of: list, start, get, add_evidence, update_status)"}

        res = await _goals_action(action, input_data)
        ok = bool(res.get('ok'))
        return {'success': ok, 'action': action, **res}