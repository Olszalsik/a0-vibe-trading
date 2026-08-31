# AGENTS.md — operating contract for `vibe_trading` (Agent Zero plugin)

You are working on an Agent Zero plugin that wires the
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) finance-research workspace into A0 as
a registered MCP server. The plugin exposes 54 research-only tools (backtest, factor analysis,
options, market data, swarm, trade-journal, shadow-account, 79 finance skills, 452 alphas) and a
dedicated `vibe-trader` agent profile. Live order placement is opt-in and gated.

A mistake here causes silent tool absence (MCP `init_timeout` 10s vs cold-start cost of 54 tool
modules), a broken Settings CTA on the welcome banner, an action button that does nothing when
clicked, or the agent falling back to default profiles because the plugin's agent wasn't
discovered. Follow these rules.

## What this plugin is
A self-contained A0 plugin (id `vibe_trading`, version `0.1.11`):

- An MCP server registration — on `install()` the plugin writes a single
  `mcpServers["vibe-trading"]` entry into `usr/settings.json` so A0's MCP client spawns the
  `vibe-trading-mcp` console script on every boot (`hooks.py:install()`).
- Three async API handlers under `api/`: `stats` (file/installation/MCP-live snapshot),
  `sync_mcp` (persist overrides + re-register), and `tools` (cached list of live MCP tool
  names). Each is a class subclassing `helpers.api.ApiHandler` with `async def process(self,
  input_data, request)` (`helpers/api.py:206-272` auto-dispatches the URL).
- A dedicated agent profile at `agents/vibe-trader/agent.yaml` (research-first persona with a
  hard "no live orders" rule and explicit per-action confirmation policy).
- A WebUI settings page at `webui/config.html` (Alpine + `plugin-settings-store`) with a live
  status panel and tool-list grid; a companion `webui/page.html` info page.
- A `get_tool_message_handler` extension that turns backtest / factor / options / trade-journal
  / shadow-backtest JSON envelopes into stat-tile cards with action buttons.
- A `banners` extension that shows a dismissible discovery card on the welcome screen once the
  plugin is fully wired and the MCP server is reachable.
- A `page-head` extension that injects a meta tag and two CSS variables (`--vibe-trading-accent`,
  `--vibe-trading-accent-soft`) for theming.
- A v2.2 contract check (`scripts/check_v22_contract.py`) run from `execute.py` that catches
  regressions to legacy `def announce(` banners or missing toggle.
- A self-check / health script at `execute.py` (file presence, manifest, install state, MCP
  live probe) callable from the Plugins UI or the terminal.

## HARD INVARIANTS — never violate
1. **`mcp_client_init_timeout` must be ≥ 30s.** A0 v2.5 (`helpers/mcp_handler.py:1402`) reads
   the timeout from settings (`mcp_client_init_timeout`, default 10). The upstream
   `vibe-trading-mcp` is a Python stdio server that imports 54 tool modules and warms a 452-alpha
   registry on startup — measured cold start is 8–25s depending on venv state and host FS
   latency. A 10s timeout produces the "McpError: Timed out while waiting for response to
   ClientRequest. Waited 10.0 seconds" warning in `a0 logs`, empties the advertised tool list,
   and silently disables the plugin for the session. The user settings file ships at 30s after
   the 2026-07 fix; do not lower it.
2. **The MCP entry must set `disabled: false`.** `hooks.py:_build_mcp_entry` always emits
   `entry["disabled"] = False`. Removing the field causes A0's MCP config merge to default the
   server to "enabled" but the `_normalize_server` step in `helpers/mcp_handler.py` will treat a
   missing flag as a parse error in some branches. Always emit the field explicitly.
3. **The MCP `command` must be an absolute path or `shutil.which`-resolved.** `hooks.py:148-161`
   resolves `mcp_command` through `shutil.which` so the framework can spawn the server even when
   its PATH is empty (the A0 venv differs from the venv where `pip install vibe-trading-ai`
   landed). Never set `command` to a bare name without resolution — the framework's
   `_create_stdio_transport` will raise `ValueError("Command 'vibe-trading-mcp' not found")`
   (`helpers/mcp_handler.py:1533`).
4. **LLM env vars must be sent under BOTH the legacy and current upstream names.** Upstream
   currently reads `LANGCHAIN_PROVIDER` + `LLM_MODEL` (the model var lost the LANGCHAIN_ prefix
   at some point) but older builds still look for `LANGCHAIN_MODEL_NAME`. `hooks.py` writes
   `LANGCHAIN_PROVIDER`, both `LLM_MODEL` and `LANGCHAIN_MODEL_NAME`, `LANGCHAIN_TEMPERATURE`,
   and `TIMEOUT_SECONDS`. If upstream renames again, ADD the new name — do not delete the old
   one until you've confirmed the new one is in a published release.
5. **Plugin hooks are sync `def install/pre_update/uninstall`.** A0 v2.5 supports both sync
   and async hooks — `helpers/plugins.py:853-881` (`call_plugin_hook`) checks
   `iscoroutinefunction(hook)` and adapts. The vibe-trading hooks do pure file I/O
   (read `default_config.yaml`, write `usr/settings.json` via `set_settings_delta`) which is
   sub-millisecond; making them async would just wrap `asyncio.run` around the same body and
   would NOT improve the event-loop situation. Keep them sync. (Counter-example: `omniroute`'s
   hooks are async because they call into the framework's API handlers — different reason.)
6. **`hooks.install()` is idempotent and non-raising.** A broken plugin install must not break
   framework boot (`hooks.py:install` wraps the body in `try/except` and returns `{"ok": False,
   "error": ...}` instead of raising). Don't tighten this to raise — the user may have an
   unconfigured `vibe-trading-ai` and the rest of A0 should still boot.
7. **API handler MCP probes must wrap stdio in `asyncio.wait_for(...)` and never block
   indefinitely.** `api/tools.py:55-58` and `api/stats.py:75-78` bound the probe to 12s; the
   inner session `initialize()` and `list_tools()` to 10s each. Without these timeouts, a hung
   `vibe-trading-mcp` would block the API handler's event loop indefinitely.
8. **The banner's `cta_action` must use `open-modal:<path>`, not `open-plugin-config:<name>`.**
   v2.5's `welcomeStore.executeBannerAction` (`webui/components/welcome/welcome-store.js:159-172`)
   only dispatches `open-modal:<path>` and `open-url:<url>`. The v2.2-era
   `open-plugin-config:vibe_trading` string is NOT handled and renders as a no-op button. The
   plugin's banner (`extensions/python/banners/_10_vibe_trading_discovery.py`) uses
   `open-modal:/usr/plugins/vibe_trading/webui/config.html`. If you change the modal target,
   change both the file and this rule.
9. **Tool message handler action buttons must use `createActionButton(icon, text, handler)`
   from the v2.5 framework.** The handler at
   `extensions/webui/get_tool_message_handler/vibe-trading-backtest-card.js` imports from
   `/components/messages/action-buttons/simple-action-buttons.js`. The v2.2-era pattern of
   returning `{label, action: "open-plugin-config:<name>"}` objects DOES NOT render in v2.5
   — `drawProcessStep` calls `createActionButton` on each entry and only the 3-arg shape works.
   The handler builds its own `openConfig` / `openPage` closures that call
   `window.Alpine?.store?.("pluginSettingsPrototype")?.openConfig("vibe_trading")` for
   settings, or navigate to the plugin page URL for the Alpha Zoo.
10. **Asset URLs in the WebUI use `/usr/plugins/vibe_trading/...`, not `/plugins/...`.** v2.5's
    asset server (`helpers/ui_server.py:158,164`) serves built-in plugins from
    `/plugins/<name>/<path>` and user plugins from `/usr/plugins/<name>/<path>`. The `vibe-trading`
    plugin lives under `usr/plugins/`, so the user-plugin route is the canonical one. Built-in
    route 404s. Banner `cta_action`, settings links, and the Alpha Zoo button all use
    `/usr/plugins/vibe_trading/webui/...`.
11. **The `banners` discovery card must NEVER be shown for a broken install.** The
    `_10_vibe_trading_discovery.py` card only renders when ALL of: plugin toggle is on,
    `vibe-trading-ai` package is importable, `vibe-trading-mcp` console script is on PATH, AND
    the MCP server actually responds to `initialize`+`list_tools` within 3s. A 3s probe is
    shorter than the main MCP client's 30s init timeout — the banner is a "fully-healthy"
    signal, not a "registered" signal. Don't loosen this without thinking about false-positives.
12. **Risk tier is a soft policy, not an enforcement layer.** The `risk_tier` setting
    (`research` | `paper` | `live`) is surfaced in the agent persona's prompt and in the env
    var `VIBE_TRADING_RISK_TIER`, but the MCP server does not expose order-placement tools at
    all. If you ever add a real enforcement layer, do it as a separate extension
    (`_20_vibe_trading_risk_guard.py`) that intercepts tool calls, not by changing the persona
    prompt.
13. **Plugin version is `0.1.11` everywhere.** `plugin.yaml:version`, `hooks.py:PLUGIN_VERSION`,
    `execute.py:EXPECTED_VERSION`, the `vibe-trading-head.html` meta tag, the banner's `meta`
    dict, and the README's expected output all agree. `scripts/check_v22_contract.py` does not
    enforce this, but `execute.py` prints a WARN if `plugin.yaml` disagrees with
    `EXPECTED_VERSION`. Bump them together.
14. **The plugin does NOT install `vibe-trading-ai`.** `hooks.py` only detects whether the
    package is importable (`_is_vibe_trading_installed`) and logs a one-line INFO; the actual
    `pip install vibe-trading-ai` is documented in README and the user does it. Do not add a
    `pip install` call to `install()` — it would slow every boot, race with the user's venv
    manager, and break air-gapped installs.
15. **The plugin does NOT modify Agent Zero framework code.** No edits to `helpers/`,
    `webui/components/`, `initialize.py`, or any other file outside `usr/plugins/vibe_trading/`.
    If a v2.5 framework contract blocks something the plugin needs (e.g. a new banner action
    verb), the right fix is to add a new action verb and dispatch it from the framework — not
    to monkey-patch the framework from the plugin.

## Build discipline
- **Sync `default_config.yaml` keys with `webui/config.html` inputs.** Every `<input
  x-model="config.<key>">` in `webui/config.html` must have a matching default in
  `default_config.yaml` — otherwise the framework's `get_default_value("vibe_trading__<key>",
  None)` returns `None` and the UI shows an empty input. Use the same key list everywhere:
  `mcp_enabled, mcp_command, mcp_args, llm_provider, llm_model, temperature, timeout_seconds,
  tushare_token, finnhub_api_key, alphavantage_api_key, tiingo_api_key, fmp_api_key,
  fred_api_key, iwencai_key, data_cache, risk_tier, max_drawdown_pct,
  require_explicit_confirmation`.
- **Per change:** run `python -m py_compile` on every `.py` you touched. Verify the plugin's
  WebUI parses by `import`-stripping `webui/config.html` and `webui/page.html` then running
  them through `new Function(src)`. Keep `default_config.yaml` ↔ `webui/config.html` keys in
  sync. Bump `plugin.yaml:version` AND `hooks.py:PLUGIN_VERSION` AND
  `execute.py:EXPECTED_VERSION` together. Re-run `python usr/plugins/vibe_trading/execute.py`
  to confirm the v2.2 contract check still passes and the live MCP probe (if the upstream is
  installed) still discovers the expected tool count.
- **The v2.2 contract check is the floor, not the ceiling.** `scripts/check_v22_contract.py`
  ensures `.toggle-1` exists, every banner file has `def execute(banners, **kwargs)` (no
  legacy `def announce(`), and `hooks.py` defines all three lifecycle hooks. It does NOT
  verify v2.5 compatibility. The audit work for v2.5 is in `AGENTS.md` (this file).
- **Restart-required changes.** Bumping `mcp_client_init_timeout` in `usr/settings.json`
  requires a full A0 restart (the framework caches `MCPConfig` per process). Plugin config
  changes via the Settings UI do NOT require a restart — the `sync_mcp` handler re-writes
  `usr/settings.json` but the in-process `MCPConfig` only refreshes on the next
  `MCPConfig.update(...)` call, which happens on agent-config rebuild.
- **Don't bundle upstream code.** The plugin wraps an installed PyPI package
  (`vibe-trading-ai`) — it does not clone, vendor, or download the upstream repo. The
  `LICENSE` file at the plugin root is the upstream MIT, included for license compliance.

## Knowledge map (one source of truth each — never duplicate)
- **User-facing install / quickstart / FAQ:** `README.md`.
- **Config defaults + inline rationale:** `default_config.yaml` (the canonical key list + meanings).
- **Manifest / version / settings UI surface:** `plugin.yaml`.
- **Lifecycle hooks (MCP register/unregister):** `hooks.py`.
- **v2.2 contract regression check:** `scripts/check_v22_contract.py`.
- **Self-check / maintenance script:** `execute.py` (run from Plugins UI or
  `python /a0/usr/plugins/vibe_trading/execute.py`).
- **API endpoints (one handler per file):** `api/stats.py` (POST `/api/plugins/vibe_trading/stats`),
  `api/sync_mcp.py` (POST `/api/plugins/vibe_trading/sync_mcp`),
  `api/tools.py` (POST `/api/plugins/vibe_trading/tools`).
- **Settings UI:** `webui/config.html` (Alpine + `plugin-settings-store`).
- **Info page:** `webui/page.html` (full tool list + status + upstream links).
- **WebUI injection points:** `extensions/webui/page-head/vibe-trading-head.html` (meta + CSS
  vars), `extensions/python/banners/_10_vibe_trading_discovery.py` (welcome screen discovery
  card), `extensions/webui/get_tool_message_handler/vibe-trading-backtest-card.js` (backtest
  / factor / options / journal / shadow-backtest stat tiles), and
  `extensions/webui/chat-input-bottom-actions-end/vibe-trading-btn.html` (chat-input button).
- **Agent profile:** `agents/vibe-trader/agent.yaml`. The plugin ships exactly ONE profile —
  do not add siblings (the WebUI picker iterates every subdirectory of `agents/` and would
  show broken entries if a sibling lacks `agent.yaml`).
- **MCP server contract:** documented in
  [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT, the project this plugin
  wraps). The `pyproject.toml` `console_scripts` entry installs `vibe-trading-mcp` →
  `mcp_server:main`. The MCP server reads `LANGCHAIN_PROVIDER`, `LLM_MODEL` /
  `LANGCHAIN_MODEL_NAME`, `LANGCHAIN_TEMPERATURE`, `TIMEOUT_SECONDS`, plus data-source tokens
  `TUSHARE_TOKEN`, `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`,
  `FRED_API_KEY`.

## Verified A0 v2.5 mechanics (don't re-derive — confirm against the LIVE instance; versions move)
- API dispatch: `helpers/api.py:206-272` resolves `POST /api/plugins/<name>/<handler>` →
  `usr/plugins/<name>/api/<handler>.py` → instantiates the `ApiHandler` subclass and awaits
  `self.process(input_data, request)`. The handler MUST be `async def process`.
- Asset server: `helpers/ui_server.py:158,164` registers BOTH `/plugins/<name>/<path>` (built-in)
  and `/usr/plugins/<name>/<path>` (user). The path-traversal guard at `helpers/ui_server.py:303-327`
  allows only `webui/` and `extensions/webui/` subdirs. Files at the plugin root (e.g.
  `install.ps1`, `LICENSE`) are NOT served.
- WebUI config injection: `webui/components/plugins/plugin-settings-store.js:434-437` injects
  `<x-component path="/plugins/${name}/webui/config.html">` (or `/usr/plugins/...` for user
  plugins) into the Settings page. The store contract is `init(config, context)`,
  `bindConfig(config)`, `cleanup()`.
- Settings open: `Alpine.store("pluginSettingsPrototype").openConfig("vibe_trading")` is the
  v2.5 public API. There is no `window.openPluginSettings` and no `open-plugin-settings` event.
- Hooks: `helpers/plugins.py:853-881` (`call_plugin_hook`) supports both sync and async hooks;
  the `iscoroutinefunction` branch wraps async ones in `asyncio.run(safe_call(...))`. The
  vibe-trading hooks are deliberately sync (file I/O only).
- MCP `init_timeout`: `helpers/mcp_handler.py:1402` reads `mcp_client_init_timeout` from
  settings. 10s is the default; 30s is the recommended value for this plugin (see Invariant 1).
- Banner `executeBannerAction`: `webui/components/welcome/welcome-store.js:159-172` dispatches
  `open-modal:<path>` and `open-url:<url>` only. The `open-plugin-config:` string is not
  handled and renders as a no-op.
- Action buttons: `webui/components/messages/action-buttons/simple-action-buttons.js:68`
  exports `createActionButton(icon, text, handler)`. `drawProcessStep` (`webui/js/messages.js:342`)
  calls this on each entry in its `actionButtons` array. The v2.2 `{label, action}` object
  shape is not handled.

## What this plugin does NOT do
- Does not install `vibe-trading-ai` via `pip`. The user runs `pip install vibe-trading-ai`
  in their active venv (documented in README).
- Does not start, stop, or manage the upstream service. The upstream is a stdio MCP server
  spawned per-session by A0's MCP client.
- Does not place live orders. The MCP server exposes zero order-placement tools; the
  `trading_*` tools are read-only.
- Does not write outside `usr/plugins/vibe_trading/` (and the single `usr/settings.json`
  entry it manages for the MCP server).
- Does not register scheduled tasks or background workers.
- Does not modify Agent Zero framework code in `helpers/`, `webui/components/`, or `initialize.py`.
- Does not expose API keys, host IPs, or local paths in shipped files. `config.json` and
  `.toggle-*` are gitignored.
