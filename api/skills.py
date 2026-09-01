'''
Vibe-Trading -- finance knowledge-skill browser.

Route: POST /api/plugins/vibe_trading/skills

Two actions:
  - list   -> proxies MCP list_skills, grouped by category, with a per-skill
              preview title (single-line summary of the description).
              Cached for 5 minutes.
  - load   -> proxies MCP load_skill for one skill name and returns its full
              SKILL.md body as markdown text. Cached 30s. force=true skips.

The page (skills.html) uses this for the searchable skill browser.

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


_LIST_TTL = 300.0
_LOAD_TTL = 30.0
_OUTER_TIMEOUT = 25.0
_INNER_TIMEOUT = 15.0
_INIT_TIMEOUT = 10.0


_CATEGORY_KEYWORDS = [
    ('options', ['option', 'put', 'call', 'greeks', 'volatility', 'iv']),
    ('factor', ['factor', 'alpha', 'quant', 'ic ', 'ir ']),
    ('macro', ['macro', 'fed', 'treasury', 'cpi', 'gdp', 'rate']),
    ('technical', ['candle', 'elliott', 'ichimoku', 'smc', 'fibonacci', 'harmonic', 'pattern']),
    ('risk', ['risk', 'drawdown', 'var', 'cvar', 'sharpe']),
    ('crypto', ['crypto', 'bitcoin', 'btc', 'eth', 'okx']),
    ('journal', ['journal', 'trade diary', 'behaviour', 'behavior']),
    ('research', ['report', 'research', 'analyst', 'swarm', 'sec', 'filing']),
    ('screening', ['screen', 'filter', 'rank', 'scan']),
    ('execution', ['order', 'execution', 'broker', 'connect']),
    ('ml', ['ml', 'model', 'lstm', 'transformer', 'neural']),
]


def _categorize(name: str, description: str) -> str:
    blob = (name + ' ' + (description or '')).lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in blob:
                return cat
    return 'general'


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
                    return {'ok': True, 'data': parsed, 'raw': joined[:6000]}
                return {'ok': True, 'raw': joined[:6000]}

    try:
        return await asyncio.wait_for(_run(), timeout=_OUTER_TIMEOUT)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


async def _list_skills() -> Dict[str, Any]:
    cmd = _mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp binary not on PATH'}

    res = await _call_tool(cmd, 'list_skills', {})
    if not res.get('ok'):
        return res

    payload = res.get('data', res.get('raw', ''))
    rows: List[Dict[str, Any]] = []

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                nm = str(item.get('name') or item.get('id') or '').strip()
                desc = str(item.get('description') or '').strip()
                if nm:
                    rows.append({
                        'name': nm,
                        'description': desc,
                        'category': _categorize(nm, desc),
                    })
            elif isinstance(item, str):
                rows.append({
                    'name': item.strip(),
                    'description': '',
                    'category': 'general',
                })
    elif isinstance(payload, dict):
        inner = payload.get('skills') or payload.get('data') or payload.get('items')
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    nm = str(item.get('name') or item.get('id') or '').strip()
                    desc = str(item.get('description') or '').strip()
                    if nm:
                        rows.append({
                            'name': nm,
                            'description': desc,
                            'category': _categorize(nm, desc),
                        })

    if not rows and isinstance(payload, str):
        text = payload
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                left, _, right = line.partition(':')
                nm = left.strip().lstrip('-').strip()
                desc = right.strip()
                if nm and ' ' not in nm and '.' not in nm[:1]:
                    rows.append({
                        'name': nm,
                        'description': desc,
                        'category': _categorize(nm, desc),
                    })

    rows.sort(key=lambda r: (r['category'], r['name']))
    by_cat: Dict[str, int] = {}
    for r in rows:
        by_cat[r['category']] = by_cat.get(r['category'], 0) + 1
    return {
        'ok': True,
        'fetched_at': int(time.time()),
        'total': len(rows),
        'categories': by_cat,
        'skills': rows,
    }


async def _load_skill(skill_name: str) -> Dict[str, Any]:
    cmd = _mcp_cmd()
    if not cmd:
        return {'ok': False, 'error': 'vibe-trading-mcp binary not on PATH'}
    res = await _call_tool(cmd, 'load_skill', {'name': skill_name})
    if not res.get('ok'):
        return res
    data = res.get('data', res.get('raw', ''))
    body: str = ''
    if isinstance(data, dict):
        body = str(data.get('body') or data.get('text') or data.get('content') or '')
    elif isinstance(data, str):
        body = data
    if not body and res.get('raw'):
        body = str(res.get('raw', ''))
    return {
        'ok': True,
        'name': skill_name,
        'body': body[:60000],
    }


class Skills(ApiHandler):
    async def process(self, payload: Dict[str, Any], request: Any = None) -> Dict[str, Any]:
        # NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
        # helpers package shadows the plugin's, and its cache API is (area, key)-shaped
        # with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
        import vibe_trading_cache as _cache

        action = (payload or {}).get('action') or 'list'
        force = bool((payload or {}).get('force'))

        if action == 'list':
            cache_key = 'skills.list'
            if not force:
                hit = _cache.get(cache_key)
                if hit is not None:
                    return {
                        'ok': True,
                        'action': 'list',
                        'cached': True,
                        'data': hit,
                    }
            rows = await _list_skills()
            if rows.get('ok'):
                _cache.set(cache_key, rows, ttl=_LIST_TTL)
            return {
                'ok': bool(rows.get('ok')),
                'action': 'list',
                'cached': False,
                'data': rows,
            }

        if action == 'load':
            skill_name = (payload or {}).get('name') or ''
            skill_name = skill_name.strip()
            if not skill_name:
                return {'ok': False, 'error': 'name is required for action=load'}
            cache_key = 'skills.load.' + skill_name
            if not force:
                hit = _cache.get(cache_key)
                if hit is not None:
                    return {
                        'ok': True,
                        'action': 'load',
                        'cached': True,
                        'data': hit,
                    }
            body = await _load_skill(skill_name)
            if body.get('ok'):
                _cache.set(cache_key, body, ttl=_LOAD_TTL)
            return {
                'ok': bool(body.get('ok')),
                'action': 'load',
                'cached': False,
                'data': body,
            }

        return {
            'ok': False,
            'error': 'unknown action: ' + str(action),
            'supported': ['list', 'load'],
        }
