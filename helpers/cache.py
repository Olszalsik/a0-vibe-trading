'''
Vibe-Trading -- shared TTL cache helper.

A tiny, thread-safe, in-memory cache the API handlers can use to avoid
repeated MCP roundtrips on the same query. Each cache entry stores:
  - fetched_at: epoch seconds when stored
  - value: the cached payload (any picklable type)

API:
  - get(key) -> value | None   (None means expired-or-missing)
  - set(key, value, ttl=30.0)
  - invalidate(key)            (also invalidates key wildcards 'foo.*')
  - flush()                    (drops everything)
  - stats()                    (-> {hits, misses, expired, sets, size})

We deliberately keep this dependency-free (no redis/pickle) so the
plugin stays drop-in and self-contained. Theme B of Phase 3.

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


def set(key: str, value: Any, ttl: float = 30.0, *, now: Optional[float] = None) -> None:
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
