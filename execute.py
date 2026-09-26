"""
Vibe-Trading — user-triggered health / maintenance script.

Run from the Plugins UI (or directly: `python execute.py`).

Steps:
  1. Verify all required files exist.
  2. Parse + validate plugin.yaml.
  3. Detect `vibe-trading-ai` install + console script availability.
  4. Re-run install() to refresh MCP registration in /a0/usr/settings.json.
  5. Probe the MCP server briefly to surface any obvious startup issues.
  6. Print a structured summary.

Returns 0 on success, non-zero on failure. Never throws on user-facing
errors — they're printed and reflected in the exit code.
"""

from __future__ import annotations

import json
import os
import sys

# Run from plugin dir so the hooks.py import works regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_SCRIPTS = os.path.join(_HERE, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


PLUGIN_NAME = "vibe_trading"
EXPECTED_VERSION = "0.1.15"
# Subcommands: (none) = full health check, "verify-resolver" = two-venv report.
_ARGV = sys.argv[1:]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _check_files() -> bool:
    # Single source of truth: hooks.REQUIRED_FILES + the plugin.yaml webui
    # surface, so this list can no longer drift out of sync with the tree
    # (it previously checked 24 of 60+ shipped files and still reported
    # "all required files present").
    try:
        import hooks as _hooks  # noqa: E402  # local plugin import
        status = _hooks.check_required_files()
    except Exception as e:
        _print(f"[{PLUGIN_NAME}] ERROR: cannot read the shipped-file manifest: {e}")
        return False
    missing = sorted(p for p, ok in status.items() if not ok)
    if missing:
        _print(f"[{PLUGIN_NAME}] ERROR: missing files ({len(missing)} of {len(status)}):")
        for m in missing:
            _print(f"  - {m}")
        return False
    _print(f"[{PLUGIN_NAME}] OK: all {len(status)} required files present")
    return True


def _check_v22_contract() -> bool:
    try:
        from check_v22_contract import main as _v22_main
    except Exception as e:
        _print(f"[{PLUGIN_NAME}] ERROR: cannot import v2.2 contract check: {e}")
        return False
    ok, report = _v22_main()
    fail = [f for f in report if not f["ok"]]
    if fail:
        _print(f"[{PLUGIN_NAME}] FAIL: {len(fail)} v2.2 contract check(s) failed:")
        for f in fail:
            _print(f"  - [{f['check']}] {f['detail']}")
        return False
    _print(f"[{PLUGIN_NAME}] OK: v2.2 contract check passed ({len(report)} checks)")
    return True


def _check_manifest() -> bool:
    path = os.path.join(_HERE, "plugin.yaml")
    try:
        import yaml  # type: ignore
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        _print(f"[{PLUGIN_NAME}] ERROR: plugin.yaml is not valid YAML: {e}")
        return False
    name = (data.get("name") or "").strip()
    version = (data.get("version") or "").strip()
    if name != PLUGIN_NAME:
        _print(f"[{PLUGIN_NAME}] ERROR: plugin name is {name!r}, expected {PLUGIN_NAME!r}")
        return False
    if version == EXPECTED_VERSION:
        _print(f"[{PLUGIN_NAME}] OK: manifest version {version}")
    else:
        # version_sync.py deliberately keeps plugin.yaml tracking the
        # installed vibe-trading-ai version (hooks.install -> sync_plugin_version).
        # That is by design, so treat "manifest == installed package version"
        # as healthy instead of warning on every post-install run.
        synced = None
        try:
            import importlib.metadata as md  # type: ignore
            synced = md.version("vibe-trading-ai")
        except Exception:
            synced = None
        if synced and version == synced:
            _print(f"[{PLUGIN_NAME}] OK: manifest version {version} (auto-synced with vibe-trading-ai)")
        else:
            _print(f"[{PLUGIN_NAME}] WARN: manifest version is {version!r}, expected {EXPECTED_VERSION!r}"
                   + (f" and no auto-sync (vibe-trading-ai is {synced!r})" if synced else ""))
    return True


def _resolve_mcp_command() -> "str | None":
    """Find the vibe-trading-mcp console script.

    Delegates to the shared resolver (vibe_trading_bin) so the health check,
    the API handlers, the discovery banner and hooks.install() all resolve the
    SAME absolute binary. A bare shutil.which() here would resolve in the
    exec shell's context (the interactive venv) and could differ from the app
    process's choice, which is exactly what the two-venv trap caused.
    """
    import vibe_trading_bin as _bin  # noqa: E402
    return _bin.resolve_mcp_command()


def _check_installation() -> dict:
    import shutil
    info = {"vibe_trading_ai_installed": False, "console_script": False, "console_script_path": None}
    try:
        import importlib.metadata as md  # type: ignore
        info["vibe_trading_ai_installed"] = True
        info["vibe_trading_ai_version"] = md.version("vibe-trading-ai")
    except Exception:
        info["vibe_trading_ai_version"] = None
    cmd_path = _resolve_mcp_command()
    info["console_script"] = cmd_path is not None
    info["console_script_path"] = cmd_path
    if not info["vibe_trading_ai_installed"]:
        _print(f"[{PLUGIN_NAME}] WARN: vibe-trading-ai package is NOT installed. Run: pip install vibe-trading-ai")
    else:
        _print(f"[{PLUGIN_NAME}] OK: vibe-trading-ai {info['vibe_trading_ai_version']} is installed")
    if not info["console_script"]:
        _print(f"[{PLUGIN_NAME}] WARN: 'vibe-trading-mcp' console script not on PATH. Plugin install may be partial.")
    else:
        _print(f"[{PLUGIN_NAME}] OK: 'vibe-trading-mcp' at {cmd_path}")
    return info


def _run_install_hook() -> dict:
    try:
        import hooks  # type: ignore  # noqa: E402
        result = hooks.install()
        _print(f"[{PLUGIN_NAME}] OK: hooks.install() returned {json.dumps(result, ensure_ascii=False)}")
        return result
    except Exception as e:
        _print(f"[{PLUGIN_NAME}] ERROR: hooks.install() raised: {e}")
        return {"ok": False, "error": str(e)}


def _probe_mcp_server() -> dict:
    """Best-effort: send initialize + tools/list to the MCP server."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import asyncio
    except Exception as e:
        return {"probed": False, "error": f"mcp client not importable: {e}"}

    async def _run():
        cmd = _resolve_mcp_command()
        if not cmd:
            return {"probed": False, "error": "vibe-trading-mcp not on PATH"}
        params = StdioServerParameters(command=cmd, args=[], env=None)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Cold start is 8-25s (AGENTS.md invariant 1); 10s lost
                    # that race intermittently. Same budgets as api/tools.py.
                    await asyncio.wait_for(session.initialize(), timeout=25)
                    res = await asyncio.wait_for(session.list_tools(), timeout=15)
                    names = sorted([t.name for t in (res.tools or [])])
                    return {"probed": True, "tool_count": len(names), "sample_tools": names[:10]}
        except Exception as e:
            return {"probed": False, "error": str(e)[:300]}

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=45))
    except Exception as e:
        return {"probed": False, "error": str(e)[:300]}


def verify_resolver() -> dict:
    """Two-venv diagnostic: is every path pointing at the SAME install?

    The failure this catches is subtle and was live on 2026-09-26: the app
    process's PATH resolves vibe-trading-mcp to /opt/venv-a0/bin while
    config.json pins the registered server to /opt/venv/bin, so the WebUI
    panels quietly probe a different binary than the agent uses. `ok` is
    False whenever the two disagree, or the pin points at a missing file.
    """
    try:
        import hooks as _hooks  # noqa: E402  # local plugin import
        import vibe_trading_bin as _bin  # noqa: E402
    except Exception as e:
        return {"ok": False, "error": f"cannot import plugin modules: {e}"}

    snap = _hooks._status_snapshot()
    resolved = _bin.resolve_or_none()
    mcp = resolved.get("mcp_command")
    registered = snap.get("mcp_registered_command")

    checks = {
        "mcp_command_resolved": bool(mcp),
        "cli_command_resolved": bool(resolved.get("cli_command")),
        "server_registered": bool(snap.get("mcp_registered_in_settings")),
        # The load-bearing one: probes and the live server must agree.
        "probe_matches_registered": bool(mcp and registered and mcp == registered),
    }
    same_venv = bool(
        mcp
        and resolved.get("cli_command")
        and os.path.dirname(mcp) == os.path.dirname(resolved["cli_command"])
    )
    checks["mcp_and_cli_same_venv"] = same_venv

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "resolved": resolved,
        "registered_command": registered,
        "mcp_client_init_timeout_note": (
            "settings mcp_client_init_timeout must be >= 30s (AGENTS.md invariant 1)"
        ),
    }


def main() -> int:
    _print(f"[{PLUGIN_NAME}] Plugin dir: {_HERE}")
    ok_v22 = _check_v22_contract()
    ok_files = _check_files()
    ok_manifest = _check_manifest()
    install_info = _check_installation()
    install_result = _run_install_hook()
    probe = _probe_mcp_server()

    toggle_on = os.path.isfile(os.path.join(_HERE, ".toggle-1"))
    toggle_off = os.path.isfile(os.path.join(_HERE, ".toggle-0"))
    if toggle_on:
        state = "ON"
    elif toggle_off:
        state = "OFF"
    else:
        state = "DEFAULT (enabled)"
    _print(f"[{PLUGIN_NAME}] Toggle state: {state}")

    summary = {
        "plugin": PLUGIN_NAME,
        "version": EXPECTED_VERSION,
        "toggle_state": state,
        "v22_contract_ok": ok_v22,
        "files_ok": ok_files,
        "manifest_ok": ok_manifest,
        "install": install_info,
        "hooks_install_result": install_result,
        "mcp_probe": probe,
    }
    _print("")
    _print(json.dumps(summary, indent=2, ensure_ascii=False))
    _print("")
    # Subcommand dispatch. Guard the index: the Plugins-UI runner imports this
    # module and calls main() with no argv, so `_ARGV` can legitimately be empty.
    if _ARGV and _ARGV[0] == "verify-resolver":
        print(json.dumps(verify_resolver(), indent=1))
        return 0

    if not ok_v22:
        _print(f"[{PLUGIN_NAME}] Health check FAILED — v2.2 contract check failed.")
        return 2
    if not (ok_files and ok_manifest):
        _print(f"[{PLUGIN_NAME}] Health check FAILED.")
        return 2
    if not install_info.get("vibe_trading_ai_installed"):
        _print(f"[{PLUGIN_NAME}] Health check PARTIAL — pip install vibe-trading-ai to finish.")
        return 1
    if not probe.get("probed"):
        _print(f"[{PLUGIN_NAME}] Health check PARTIAL — MCP server probe failed: {probe.get('error')}")
        return 1
    _print(f"[{PLUGIN_NAME}] Health check PASSED — {probe.get('tool_count', 0)} tools live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

