'''
Vibe-Trading -- canonical MCP/CLI binary resolver (the two-venv fix).

WHY THIS FILE EXISTS (incident 2026-09-22, AGENTS.md "the two-venv trap"):

The container has TWO installs of vibe-trading-ai:

    /opt/venv      3.13  interactive/CLI venv
    /opt/venv-a0   3.12  the A0 APP PROCESS's venv

The A0 app process runs with PATH=/opt/venv-a0/bin:... and nothing else, so a
bare `shutil.which('vibe-trading-mcp')` evaluated inside the app resolves to
/opt/venv-a0/bin/vibe-trading-mcp. Meanwhile config.json pins the REGISTERED
MCP entry to the absolute /opt/venv/bin/vibe-trading-mcp. Before this module
the two halves disagreed: `hooks.py` and `execute.py` honoured the pin, but
every API handler and the discovery banner called `shutil.which` directly --
so the WebUI panels spawned a DIFFERENT binary than the one the agent's MCP
client uses. That is the exact split the pin exists to prevent.

RESOLUTION ORDER (first hit wins):

    1. the plugin config `mcp_command` / `cli_command` when it is absolute
       AND the file exists -- this is the pin, and it is what hooks.py
       registers, so probes and the live server always agree;
    2. a registered MCP entry already in usr/settings.json (read-only
       introspection, so we agree with whatever the boot hook last wrote);
    3. `shutil.which` (correct when the caller's PATH does own the venv);
    4. well-known venv bin dirs, preferring /opt/venv (the pinned venv).

Never returns a bare name: an unresolvable command is a clear error, not a
FileNotFoundError surfacing from deep inside the MCP client.

Dependency-free, and side-effect-free on import. Single-quote literals only.
'''

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional

PLUGIN_NAME = 'vibe_trading'
PLUGIN_ROOT = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER_KEY = 'vibe-trading'

# Ordered by preference. /opt/venv comes first because that is the venv the
# plugin config pins; /opt/venv-a0 is the app venv and is the correct fallback
# when no pin exists. /usr/local/bin covers a non-container install.
VENV_BIN_DIRS = ('/opt/venv/bin', '/opt/venv-a0/bin', '/usr/local/bin')
MCP_INIT_TIMEOUT_S = 25.0


def call_budget(outer: float, inner: float) -> float:
    '''Keep total deadline long enough for cold init plus one bounded call.'''
    try:
        requested = max(0.0, float(outer))
        tool = max(0.0, float(inner))
    except (TypeError, ValueError, OverflowError):
        requested, tool = 30.0, 15.0
    return max(requested, MCP_INIT_TIMEOUT_S + tool + 1.0)

_SETTINGS_PATH = '/a0/usr/settings.json'
_config_cache: Dict[str, Any] = {}


def _read_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_json(path: str) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _config_paths() -> List[str]:
    return [
        os.path.join(PLUGIN_ROOT, 'default_config.yaml'),
        os.path.join(PLUGIN_ROOT, 'config.json'),
    ]


def effective_config() -> Dict[str, Any]:
    '''default_config.yaml overlaid with usr/plugins/<name>/config.json.

    Mirrors hooks._merge_configs() precedence. Memoised on file mtime/size so
    repeated handler calls do not re-parse YAML on every request.
    '''
    paths = _config_paths()
    stamps: List[Any] = []
    for p in paths:
        try:
            st = os.stat(p)
            stamps.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            stamps.append((p, None, None))
    key = tuple(stamps)
    if _config_cache.get('key') == key:
        return _config_cache['cfg']

    cfg: Dict[str, Any] = {}
    for p in paths:
        cfg.update(_read_yaml(p) if p.endswith(('.yaml', '.yml')) else _read_json(p))
    _config_cache['key'] = key
    _config_cache['cfg'] = cfg
    return cfg



def registered_mcp_command() -> Optional[str]:
    '''The command hooks.install() last wrote into usr/settings.json.

    Best-effort read-only introspection. Keeps probes aligned with the live
    server even if the user edits the pin after boot.
    '''
    settings = _read_json(_SETTINGS_PATH)
    if not isinstance(settings, dict):
        return None
    raw = settings.get('mcp_servers')
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    servers = raw.get('mcpServers')
    if not isinstance(servers, dict):
        return None
    entry = servers.get(MCP_SERVER_KEY)
    if not isinstance(entry, dict):
        return None
    cmd = entry.get('command')
    cmd = str(cmd).strip() if isinstance(cmd, str) else ''
    return cmd or None


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _probe_venv_dirs(basename: str) -> Optional[str]:
    for d in VENV_BIN_DIRS:
        candidate = os.path.join(d, basename)
        if _executable(candidate):
            return candidate
    return None


def _resolve(basename: str, config_keys, *, consult_settings: bool) -> Optional[str]:
    cfg = effective_config()
    for key in config_keys:
        raw = str(cfg.get(key) or '').strip()
        if not raw:
            continue
        if os.path.isabs(raw):
            # An absolute pin is trusted only when it actually exists, so a
            # config carried across machines degrades to the next resolution
            # step instead of failing every probe.
            if _executable(raw):
                return raw
            continue
        # A bare `mcp_command` is the shipped default, not an install pin.
        # Defer it until after usr/settings.json, whose absolute command is
        # what hooks.install() actually registered. Otherwise the A0 process
        # PATH can win first and silently select the other venv.
        if key != 'mcp_command' or raw != basename:
            found = shutil.which(raw)
            if found:
                return found

    if consult_settings:
        registered = registered_mcp_command()
        if registered and _executable(registered):
            return registered

    if not consult_settings:
        # The CLI ships alongside the MCP console script in the same venv.
        # Resolve the MCP pin FIRST and prefer its sibling: the app process's
        # PATH owns the app venv, so a bare which() here would hand the CLI a
        # different install than the one the MCP tools actually use.
        mcp = resolve_mcp_command()
        if mcp:
            sibling = os.path.join(os.path.dirname(mcp), basename)
            if _executable(sibling):
                return sibling

    found = shutil.which(basename)
    if found:
        return found

    return _probe_venv_dirs(basename)


def resolve_mcp_command() -> Optional[str]:
    '''Absolute path to the vibe-trading-mcp console script, or None.'''
    return _resolve('vibe-trading-mcp', ('mcp_command',), consult_settings=True)


def resolve_cli_command() -> Optional[str]:
    '''Absolute path to the upstream `vibe-trading` CLI, or None.

    Same precedence as the MCP resolver, so `vibe-trading portfolio show` runs
    from the same venv that serves the MCP tools.
    '''
    return _resolve('vibe-trading', ('cli_command',), consult_settings=False)


def resolve_or_none() -> Dict[str, Any]:
    '''Resolver report for the health / snapshot surfaces.'''
    mcp = resolve_mcp_command()
    cli = resolve_cli_command()
    return {
        'mcp_command': mcp,
        'mcp_command_exists': mcp is not None,
        'cli_command': cli,
        'cli_command_exists': cli is not None,
    }
