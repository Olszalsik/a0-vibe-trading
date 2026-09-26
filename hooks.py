"""
Vibe-Trading — lifecycle hooks.

install() is called by the framework immediately after the plugin lands in
usr/plugins/. We:

  1. Detect whether `vibe-trading-ai` is importable (we do NOT auto-pip-install
     on every agent start — that's noisy and slow. The user runs `execute.py`
     once or the install docs tell them to pip install separately).
  2. Build the MCP server config from plugin defaults + the user-overridden
     config.json (priority order per the plugin router skill).
  3. Merge it into the framework's `mcp_servers` setting (a JSON string) so
     Agent Zero's MCP client starts the Vibe-Trading server on next reload.

uninstall() removes the MCP server entry. The pip package is intentionally
left in place so other consumers (e.g. an external TUI) keep working.

pre_update() re-merges after a plugin update in case defaults shifted.

All three are idempotent: safe to call repeatedly. Failures are logged but
never raised, because a broken plugin install must not break framework boot.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)

PLUGIN_NAME = "vibe_trading"
PLUGIN_TITLE = "Vibe-Trading"
from version_sync import read_plugin_yaml_version, sync_plugin_version, FALLBACK as _VS_FALLBACK
# Single source of truth for locating the upstream binaries (the two-venv
# trap). hooks, the API handlers, execute.py and the discovery banner all
# resolve through this module, so a probe can never target a different
# install than the one registered here.
import vibe_trading_bin as _bin
PLUGIN_VERSION = read_plugin_yaml_version() or _VS_FALLBACK
MCP_SERVER_KEY = "vibe-trading"  # the key inside mcpServers


def _plugin_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _read_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:  # pragma: no cover
        log.warning("[%s] failed to read %s: %s", PLUGIN_NAME, path, e)
        return {}


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:  # pragma: no cover
        log.warning("[%s] failed to read %s: %s", PLUGIN_NAME, path, e)
        return {}


def _merge_configs() -> Dict[str, Any]:
    """Return the effective plugin config.

    Priority (lowest first):
      plugins/<name>/default_config.yaml
      usr/plugins/<name>/config.json
    """
    cfg: Dict[str, Any] = {}
    cfg.update(_read_yaml(os.path.join(_plugin_root(), "default_config.yaml")))
    user_cfg_path = os.path.join(
        "/a0", "usr", "plugins", PLUGIN_NAME, "config.json"
    )
    cfg.update(_read_json(user_cfg_path))
    return cfg


def _set_settings_delta(delta: Dict[str, Any]) -> None:
    """Best-effort call into Agent Zero's settings helper.

    If the helper isn't importable (e.g. plugin is being installed during a
    framework cold-boot before helpers are ready), we fall back to a direct
    write into /a0/usr/settings.json so the MCP server is still registered
    for the next session.
    """
    try:
        from helpers.settings import set_settings_delta  # type: ignore
        set_settings_delta(delta)
        return
    except Exception as e:  # pragma: no cover
        log.debug("[%s] set_settings_delta via helper failed: %s; falling back to direct write", PLUGIN_NAME, e)

    # Direct write fallback — must preserve the rest of the file.
    settings_path = "/a0/usr/settings.json"
    if not os.path.isfile(settings_path):
        log.warning("[%s] %s missing; cannot fallback-write", PLUGIN_NAME, settings_path)
        return
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            current = json.load(f) or {}
    except Exception:
        current = {}
    current.update(delta)
    tmp = settings_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, settings_path)


def _get_current_mcp_servers() -> Dict[str, Any]:
    """Return the current mcpServers dict (may be empty)."""
    try:
        from helpers import settings as _settings  # type: ignore
        raw = _settings.get_settings().get("mcp_servers", "")
    except Exception:
        try:
            with open("/a0/usr/settings.json", "r", encoding="utf-8") as f:
                raw = (json.load(f) or {}).get("mcp_servers", "")
        except Exception:
            raw = ""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    servers = parsed.get("mcpServers", {})
    return servers if isinstance(servers, dict) else {}


def _set_current_mcp_servers(servers: Dict[str, Any]) -> None:
    payload = json.dumps({"mcpServers": servers}, ensure_ascii=False)
    _set_settings_delta({"mcp_servers": payload})


def _build_mcp_entry(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Translate plugin config → a single MCP server entry."""
    raw_command = str(cfg.get("mcp_command") or "vibe-trading-mcp")
    # Resolve to an absolute path so the MCP client can spawn the server
    # even when its PATH does not include the venv where vibe-trading-ai was
    # installed. The container runs two venvs (/opt/venv for the interactive
    # CLI, /opt/venv-a0 for the A0 app process), and this hook runs INSIDE the
    # app -- so a bare PATH lookup here would bake the app venv into the
    # registration while the user installed into the other one. The shared
    # resolver applies the config pin, then usr/settings.json, then PATH, then
    # the well-known venv bin dirs, so this and every in-plugin probe agree.
    # An absolute path already in the config is trusted as-is.
    if os.path.isabs(raw_command):
        command = raw_command
    else:
        command = _bin.resolve_mcp_command() or raw_command
    args = cfg.get("mcp_args") or []
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = []
    if not isinstance(args, list):
        args = []

    env: Dict[str, str] = {}

    # LLM provider used by run_swarm.
    #
    # Upstream HKUDS/Vibe-Trading read `LANGCHAIN_PROVIDER` and `LLM_MODEL`
    # (no LANGCHAIN_ prefix on the model). The legacy names are kept as
    # fall-throughs so older upstream builds that still look for
    # `LANGCHAIN_MODEL_NAME` keep working too. Same for the temperature and
    # timeout knobs which moved between the v1 and current variants.
    if cfg.get("llm_provider"):
        env["LANGCHAIN_PROVIDER"] = str(cfg["llm_provider"])
    if cfg.get("llm_model"):
        model = str(cfg["llm_model"])
        env["LLM_MODEL"] = model
        env["LANGCHAIN_MODEL_NAME"] = model  # legacy
    if cfg.get("temperature") not in (None, ""):
        env["LANGCHAIN_TEMPERATURE"] = str(cfg["temperature"])
    if cfg.get("timeout_seconds") not in (None, ""):
        env["TIMEOUT_SECONDS"] = str(cfg["timeout_seconds"])

    # Data sources
    for src_key, env_key in [
        ("tushare_token", "TUSHARE_TOKEN"),
        ("finnhub_api_key", "FINNHUB_API_KEY"),
        ("alphavantage_api_key", "ALPHAVANTAGE_API_KEY"),
        ("tiingo_api_key", "TIINGO_API_KEY"),
        ("fmp_api_key", "FMP_API_KEY"),
        ("fred_api_key", "FRED_API_KEY"),
        ("iwencai_key", "VIBE_TRADING_IWENCAI_KEY"),
        ("qveris_api_key", "QVERIS_API_KEY"),
        ("qveris_base_url", "QVERIS_BASE_URL"),
        ("gildata_token", "GILDATA_TOKEN"),
        ("gildata_base_url", "GILDATA_BASE_URL"),
    ]:
        val = cfg.get(src_key)
        if val:
            env[env_key] = str(val)

    if str(cfg.get("data_cache") or "") in {"1", "true", "True", "yes", "on"}:
        env["VIBE_TRADING_DATA_CACHE"] = "1"

    # Per-market data-source priority (upstream 0.1.15+). The plugin config
    # carries a JSON object mapping market -> comma-separated source order;
    # each entry becomes MARKET_DATA_ORDER_<MARKET> in the server env. Only
    # the 13 markets upstream's env schema declares are passed through;
    # anything else is dropped rather than sent.
    known_order_markets = {
        "A_SHARE", "US_EQUITY", "HK_EQUITY", "INDIA_EQUITY", "KR_EQUITY",
        "CA_EQUITY", "VIETNAM_EQUITY", "CRYPTO", "FUTURES", "FUND",
        "MACRO", "FOREX", "INDEX",
    }
    order_raw = cfg.get("market_data_order_json")
    if order_raw:
        try:
            orders = json.loads(order_raw) if isinstance(order_raw, str) else order_raw
        except Exception:
            orders = None
        if isinstance(orders, dict):
            for market, order in orders.items():
                market_name = str(market or "").strip().upper().replace("-", "_")
                value = str(order or "").strip()
                if market_name in known_order_markets and value:
                    env["MARKET_DATA_ORDER_" + market_name] = value

    # Risk tier is a soft policy surfaced in the agent persona, not a server
    # flag, but we stash it in env for downstream logging / connector checks.
    if cfg.get("risk_tier"):
        env["VIBE_TRADING_RISK_TIER"] = str(cfg["risk_tier"])

    entry: Dict[str, Any] = {"command": command, "args": list(args)}
    if env:
        entry["env"] = env
    entry["disabled"] = False
    # Per-server MCP timeouts. The framework's `mcp_client_init_timeout` default
    # is 10s, which is shorter than `vibe-trading-ai`'s cold-start import
    # (`vibe_trading_ai` + numpy + pydantic + aiohttp client). Raising the
    # per-server override lets the framework pick the higher value here
    # without affecting other MCP servers in `settings.json`. Values are
    # consistent with `helpers/mcp_handler.py:MCPClientBase.update_tools`.
    entry["init_timeout"] = 30
    entry["tool_timeout"] = 300
    return entry


def _is_vibe_trading_installed() -> Tuple[bool, Optional[str]]:
    try:
        import importlib.metadata as md  # type: ignore
        ver = md.version("vibe-trading-ai")
        return True, ver
    except Exception:
        return False, None


def _status_snapshot() -> Dict[str, Any]:
    cfg = _merge_configs()
    installed, version = _is_vibe_trading_installed()
    # Resolve through the shared resolver: the reported path must be the same
    # absolute binary install() registers, not a bare PATH lookup that in the
    # app process resolves to the OTHER venv (the two-venv trap).
    resolved = _bin.resolve_or_none()
    servers = _get_current_mcp_servers()
    registered = MCP_SERVER_KEY in servers
    registered_cmd = (servers.get(MCP_SERVER_KEY) or {}).get("command") if registered else None
    risk = cfg.get("risk_tier", "research")
    return {
        "plugin": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "vibe_trading_ai_installed": installed,
        "vibe_trading_ai_version": version,
        "mcp_command": resolved["mcp_command"],
        "mcp_command_exists": resolved["mcp_command_exists"],
        "cli_command": resolved["cli_command"],
        "cli_command_exists": resolved["cli_command_exists"],
        "mcp_registered_command": registered_cmd,
        # True when the live server and every in-plugin probe point at the
        # same file. False means the two-venv split is live again.
        "mcp_command_matches_registered": bool(
            registered_cmd and resolved["mcp_command"] == registered_cmd
        ),
        "mcp_enabled_in_config": bool(cfg.get("mcp_enabled", True)),
        "mcp_registered_in_settings": registered,
        "risk_tier": risk,
        "llm_provider": cfg.get("llm_provider"),
        "llm_model": cfg.get("llm_model"),
        "data_cache": bool(str(cfg.get("data_cache") or "") in {"1", "true", "yes", "on"}),
    }


def install() -> Dict[str, Any]:
    """Framework hook: called after the plugin is placed in usr/plugins/."""
    try:
        # Auto-keep plugin.yaml in sync with the installed vibe-trading-ai package.
        sync_plugin_version()
        cfg = _merge_configs()
        installed, version = _is_vibe_trading_installed()
        log.info(
            "[%s] install() v%s — vibe-trading-ai %s",
            PLUGIN_NAME,
            PLUGIN_VERSION,
            f"installed ({version})" if installed else "NOT INSTALLED — run `pip install vibe-trading-ai`",
        )

        if not cfg.get("mcp_enabled", True):
            # User wants the plugin files but not the MCP server.
            # Make sure we don't leave a stale entry behind.
            servers = _get_current_mcp_servers()
            if MCP_SERVER_KEY in servers:
                servers.pop(MCP_SERVER_KEY, None)
                _set_current_mcp_servers(servers)
                log.info("[%s] removed stale MCP entry (mcp_enabled=false)", PLUGIN_NAME)
            return {"ok": True, "mcp_enabled": False, "installed": installed, "version": version}

        # Build & register.
        servers = _get_current_mcp_servers()
        servers[MCP_SERVER_KEY] = _build_mcp_entry(cfg)
        _set_current_mcp_servers(servers)
        log.info(
            "[%s] registered MCP server '%s' (command=%s, args=%s)",
            PLUGIN_NAME,
            MCP_SERVER_KEY,
            servers[MCP_SERVER_KEY].get("command"),
            servers[MCP_SERVER_KEY].get("args"),
        )
        return {
            "ok": True,
            "mcp_enabled": True,
            "installed": installed,
            "version": version,
            "registered": True,
        }
    except Exception as e:  # pragma: no cover
        log.exception("[%s] install() failed: %s", PLUGIN_NAME, e)
        return {"ok": False, "error": str(e)}


def pre_update() -> Dict[str, Any]:
    """Framework hook: called before the updater pulls new code."""
    try:
        return install()  # re-register with current config + new defaults
    except Exception as e:  # pragma: no cover
        log.exception("[%s] pre_update() failed: %s", PLUGIN_NAME, e)
        return {"ok": False, "error": str(e)}


def uninstall() -> Dict[str, Any]:
    """Framework hook: called before the plugin directory is deleted."""
    try:
        servers = _get_current_mcp_servers()
        if MCP_SERVER_KEY in servers:
            servers.pop(MCP_SERVER_KEY, None)
            _set_current_mcp_servers(servers)
            log.info("[%s] removed MCP server entry on uninstall", PLUGIN_NAME)
        return {"ok": True, "removed": True}
    except Exception as e:  # pragma: no cover
        log.exception("[%s] uninstall() failed: %s", PLUGIN_NAME, e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Public helpers used by the REST API handlers and execute.py
# ---------------------------------------------------------------------------


def get_status() -> Dict[str, Any]:
    return _status_snapshot()


# ---------------------------------------------------------------------------
# Shipped-file manifest -- single source of truth for the health check.
# execute.py, hooks.self_check() and the unit tests all read this, so the
# list cannot drift between them the way the old copy-pasted pair did.
# ---------------------------------------------------------------------------

REQUIRED_FILES: Tuple[str, ...] = (
    "plugin.yaml",
    "default_config.yaml",
    "hooks.py",
    "execute.py",
    "version_sync.py",
    "vibe_trading_cache.py",
    "vibe_trading_bin.py",
    "scripts/check_v22_contract.py",
    "LICENSE",
    "README.md",
    "agents/vibe-trader/agent.yaml",
    "api/stats.py",
    "api/sync_mcp.py",
    "api/tools.py",
    "api/dashboard.py",
    "api/loader_health.py",
    "api/swarms.py",
    "api/shadow.py",
    "api/alphazoo.py",
    "api/connectors.py",
    "api/deep_dive.py",
    "api/skills.py",
    "api/watch.py",
    "api/portfolio.py",
    "api/risk_guard.py",
    "api/journal.py",
    "api/journal_upload.py",
    "api/research_goals.py",
    "webui/main.html",
    "webui/page.html",
    "webui/config.html",
    "webui/dashboard.html",
    "webui/dashboard.css",
    "webui/dashboard.js",
    "webui/shared.js",
    "webui/thumbnail.png",
    "webui/alphazoo.html",
    "webui/swarms.html",
    "webui/shadow.html",
    "webui/deepdive.html",
    "webui/skills.html",
    "webui/risk.html",
    "webui/journal.html",
    "webui/goals.html",
    "webui/watch.html",
    "webui/portfolio.html",
    "extensions/python/banners/_10_vibe_trading_discovery.py",
    "extensions/webui/page-head/vibe-trading-head.html",
    "extensions/webui/chat-input-bottom-actions-end/vibe-trading-btn.html",
    "extensions/webui/get_tool_message_handler/vibe-trading-backtest-card.js",
    "tests/test_plugin_internals.py",
)

# Every handler the AGENTS.md contract advertises. Kept explicit so a renamed
# or accidentally dropped api/<name>.py is a health-check failure.
API_HANDLERS: Tuple[str, ...] = (
    "stats", "sync_mcp", "tools", "dashboard", "loader_health", "swarms",
    "shadow", "alphazoo", "connectors", "deep_dive", "skills", "watch",
    "portfolio", "risk_guard", "journal", "journal_upload", "research_goals",
)


def check_required_files() -> Dict[str, bool]:
    """Presence map for every shipped file, cross-checked against plugin.yaml.

    The manifest-declared `webui` entries are added so a file listed in
    plugin.yaml but missing on disk is reported (it renders as a dead tab in
    the Plugins UI) instead of silently passing.
    """
    here = _plugin_root()
    status = {p: os.path.isfile(os.path.join(here, p)) for p in REQUIRED_FILES}
    for entry in _read_yaml(os.path.join(here, "plugin.yaml")).get("webui") or []:
        name = str(entry).strip().lstrip("/")
        if not name:
            continue
        rel = name if name.startswith("webui/") else "webui/" + name
        status[rel] = os.path.isfile(os.path.join(here, rel))
    return status


def sync_now() -> Dict[str, Any]:
    """Force a re-sync from current plugin config to settings.json."""
    return install()


def self_check() -> Dict[str, Any]:
    """Lightweight file & import probe for the Plugins UI / health endpoint."""
    here = _plugin_root()
    files_status = check_required_files()
    snap = _status_snapshot()
    snap["files"] = files_status
    snap["files_ok"] = all(files_status.values())
    snap["missing_files"] = sorted(k for k, v in files_status.items() if not v)
    snap["api_handlers"] = list(API_HANDLERS)
    snap["plugin_root"] = here
    return snap
