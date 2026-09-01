'''
Vibe-Trading -- journal CSV upload (Phase 8).

Route: POST /api/plugins/vibe_trading/journal_upload

Accepts a user-picked journal CSV via JSON payload
({filename, content_b64, size_bytes}). Writes it to
`journal_uploads/<timestamp>_<safe_filename>.csv` at the plugin root,
then auto-invalidates the journal.* cache namespace so the dashboard
sees the new file on the next request.

Hard limits:
  - max decoded size: 5 MB
  - filename must end with .csv
  - decoded bytes must parse as CSV with at least a header row

This handler NEVER executes the uploaded data -- it only stores it
for journal.py to consume on the next read.

Actions:
    upload  -> upload a journal CSV     action \\'upload\\'
    list    -> list past uploads         action \\'list\\'
    remove  -> remove a stored upload    action \\'remove\\'

Single-quote string literals only.
'''

from __future__ import annotations

import base64
import csv
import io
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple

from helpers.api import ApiHandler  # type: ignore


PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

# NOTE: NOT `from helpers import cache` -- inside the A0 server the framework
# helpers package shadows the plugin's, and its cache API is (area, key)-shaped
# with no TTL. This plugin-root module is shadow-proof. See vibe_trading_cache.py.
import vibe_trading_cache as _cache


UPLOAD_DIR = os.path.join(PLUGIN_ROOT, 'journal_uploads')
MAX_DECODED_BYTES = 5 * 1024 * 1024  # 5 MB

_SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]')


def _safe_name(name):
    base = os.path.basename(name or 'upload.csv')
    base = _SAFE_NAME_RE.sub('_', base)
    if not base:
        base = 'upload.csv'
    if not base.lower().endswith('.csv'):
        base = base + '.csv'
    return base[:160]


def _now_iso():
    return datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')[:-3] + 'Z'


def _ensure_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _list_uploads():
    _ensure_dir()
    out = []
    for fn in sorted(os.listdir(UPLOAD_DIR)):
        full = os.path.join(UPLOAD_DIR, fn)
        if not os.path.isfile(full):
            continue
        if not fn.lower().endswith('.csv'):
            continue
        try:
            stat = os.stat(full)
        except Exception:
            continue
        out.append({
            'filename': fn,
            'size_bytes': stat.st_size,
            'created_iso': datetime.utcfromtimestamp(stat.st_mtime).isoformat() + 'Z',
            'path': full,
        })
    out.sort(key=lambda d: d.get('created_iso', ''), reverse=True)
    return out


def _validate_csv_text(text):
    if not text or not text.strip():
        return False, 'empty file', 0
    try:
        rdr = csv.reader(io.StringIO(text))
        rows = list(rdr)
    except Exception as e:
        return False, 'csv parse failed: ' + str(e), 0
    if not rows:
        return False, 'no file', 0
    header = rows[0]
    body = rows[1:]
    if not header:
        return False, 'header row is empty', 0
    if not body:
        return False, 'no data rows after header', 0
    return True, '', len(body)


def _invalidate_journal_cache():
    # vibe_trading_cache.invalidate() supports 'foo.*' wildcards; there is no
    # keys() introspection on the cache, so just nuke the journal namespace.
    try:
        _cache.invalidate('journal.*')
    except Exception:
        pass


class JournalUploadHandler(ApiHandler):
    async def process(self, input, request):
        action = str(input.get('action', 'list')).strip().lower()
        if action == 'upload':
            return self._upload(input)
        if action == 'list':
            return self._list()
        if action == 'remove':
            return self._remove(input)
        return {'ok': False, 'error': 'unknown action: ' + action}

    def _upload(self, input):
        filename = str(input.get('filename') or '').strip()
        content_b64 = str(input.get('content_b64') or '').strip()
        size_hint = int(input.get('size_bytes') or 0)
        if not filename:
            return {'ok': False, 'error': 'filename is required'}
        if not content_b64:
            return {'ok': False, 'error': 'content_b64 is required'}
        if not filename.lower().endswith('.csv'):
            return {'ok': False, 'error': 'filename must end with .csv'}
        try:
            raw = base64.b64decode(content_b64, validate=True)
        except Exception as e:
            return {'ok': False, 'error': 'base64 decode failed: ' + str(e)}
        if len(raw) > MAX_DECODED_BYTES:
            return {'ok': False, 'error': 'file too large (max 5 MB)'}
        text = raw.decode('utf-8', errors='replace')
        ok_csv, err, n_rows = _validate_csv_text(text)
        if not ok_csv:
            return {'ok': False, 'error': 'invalid CSV: ' + err}
        _ensure_dir()
        safe = _safe_name(filename)
        stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        target = os.path.join(UPLOAD_DIR, stamp + '_' + safe)
        try:
            with open(target, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
        except Exception as e:
            return {'ok': False, 'error': 'write failed: ' + str(e)}
        _invalidate_journal_cache()
        return {
            'ok': True,
            'stored_path': target,
            'filename': safe,
            'size_bytes': len(raw),
            'data_rows': n_rows,
            'created_iso': _now_iso(),
        }

    def _list(self):
        items = _list_uploads()
        return {'ok': True, 'count': len(items), 'items': items, 'upload_dir': UPLOAD_DIR}

    def _remove(self, input):
        target = str(input.get('filename') or '').strip()
        if not target:
            return {'ok': False, 'error': 'filename is required'}
        safe_target = os.path.join(UPLOAD_DIR, _safe_name(target))
        if not os.path.exists(safe_target):
            return {'ok': False, 'error': 'not found: ' + safe_target}
        try:
            os.remove(safe_target)
        except Exception as e:
            return {'ok': False, 'error': 'remove failed: ' + str(e)}
        _invalidate_journal_cache()
        return {'ok': True, 'removed': safe_target}
