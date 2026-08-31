'''
Vibe-Trading -- shared TTL cache helper (canonical).

WHY THIS FILE EXISTS AT PLUGIN ROOT (not helpers/cache.py):
Inside the running Agent Zero server, `helpers` is ALREADY in sys.modules as
the FRAMEWORK package (/a0/helpers). Any plugin handler doing
`from helpers import cache` therefore gets the framework's cache
(helpers/cache.py: get(area, key, default) -- NO ttl, two positional args),
not the plugin's. That shadowing turned every `get(namespace)` call into
"TypeError: get() missing 1 required positional argument: 'key'" (seen live
on the dashboard snapshot 2026-09-01: helpers/api.py:80 -> Dashboard.process).
A top-level module name that the framework does not use cannot be shadowed.

A tiny, thread-safe, in-memory TTL cache the API handlers use to avoid
repeated MCP roundtrips on the same query. Each entry stores:
  - stored-at epoch seconds
  - value: anything

API:
  - get(key) -> value | None   (None means expired-or-missing)
  - set(key, value, ttl=30.0)  (ttl_seconds= accepted as an alias)
  - invalidate(key)            (also invalidates 'foo.*' wildcards)
  - flush()                    (drops everything)
  - stats()                    (-> {hits, misses, expired, sets, size})

Dependency-free on purpose (no redis/pickle) so the plugin stays drop-in.

Single-quote string literals only (plugin-wide constraint).
'''

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


_lock = threading.RLock()
_store: Dict[str, Tuple[float, Any, float]] = {}
_stats = {'hits': 0, 'misses': 0, 'expired': 0, 'sets': 0, 'size': 0}


def get(key: str, *, now: Optional[float] = None) -> Any:
    now_ts = now if now is not None else time.time()
    with _lock:
        rec = _store.get(key)
        if rec is None:
            _stats['misses'] += 1
            return None
        stored_at, value, ttl = rec
        if (now_ts - stored_at) >= ttl:
            _store.pop(key, None)
            _stats['expired'] += 1
            _stats['size'] = max(0, _stats['size'] - 1)
            return None
        _stats['hits'] += 1
        return value


def set(key: str, value: Any, ttl: float = 30.0, *, now: Optional[float] = None,
        ttl_seconds: Optional[float] = None) -> None:
    # `ttl_seconds` is an accepted alias: the Phase 6/7 handlers (risk_guard,
    # journal) were written against this kwarg and call sites predate the
    # unified helper (Theme B). One alias here beats seven call-site edits.
    if ttl_seconds is not None:
        ttl = float(ttl_seconds)
    now_ts = now if now is not None else time.time()
    with _lock:
        existing = _store.pop(key, None) is not None
        _store[key] = (now_ts, value, float(ttl))
        if not existing:
            _stats['size'] += 1
        _stats['sets'] += 1


def invalidate(key: str) -> int:
    with _lock:
        removed = 0
        for k in list(_store.keys()):
            if k == key or ('.' in k and key.endswith('.*') and k.startswith(key[:-2])):
                _store.pop(k, None)
                removed += 1
                _stats['size'] = max(0, _stats['size'] - 1)
        return removed


def flush() -> int:
    with _lock:
        n = len(_store)
        _store.clear()
        _stats['size'] = 0
        return n


def stats() -> Dict[str, int]:
    with _lock:
        return dict(_stats)


def fresh(key_prefix: str, ttl: float, loader):
    '''Convenience: get-or-fetch with bounded TTL.

    loader must be a zero-arg callable returning the fresh value.
    Returns (value, cached_bool).
    '''
    val = get(key_prefix)
    if val is not None:
        return val, True
    fresh_val = loader()
    set(key_prefix, fresh_val, ttl=ttl)
    return fresh_val, False