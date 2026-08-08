# Vibe-Trading plugin — handoff for dashboard work

## What is live and verified

- `scripts/check_v22_contract.py` — 5/5 checks pass (toggle, banner_signature, hooks_function x3)
- `execute.py` — wired to call the contract check as step 0
- `plugin.yaml`, banner, execute.py, hooks.py, page-head, webui/page.html all at v0.1.10
- `agent/requirements.txt` upstream — `fastmcp>=3.4.4,<4`
- Health: 54 MCP tools live, hooks idempotent

## What is not done (13 files)

### Phase 0.3 — version auto-sync

1. `version_sync.py` (NEW) — FALLBACK='0.1.10', functions `read_plugin_yaml_version`, `write_plugin_yaml_version(new_version)`, `sync_plugin_version()`. Uses `importlib.metadata` to read `vibe-trading-ai` version, compares to plugin.yaml, writes if drifted. Idempotent.
2. `hooks.py` (MODIFY) — replace literal `PLUGIN_VERSION = '0.1.10'` with: `from version_sync import read_plugin_yaml_version, FALLBACK as _VS_FALLBACK` and `PLUGIN_VERSION = read_plugin_yaml_version() or _VS_FALLBACK`. Also call `sync_plugin_version()` in `install()` before `cfg = _merge_configs()`.

### Phase 1 — Dashboard MVP (5 files)

3. `api/dashboard.py` (NEW) — ApiHandler with actions `snapshot` (one-shot bundle: stats + tools + recent goals + recent swarm runs), `quote` (proxy to `get_market_data` with 5s cache), `backtest` (proxy to `backtest` MCP tool), `factor` (proxy to `factor_analysis` MCP tool). Use `stdio_client + ClientSession` (see `api/tools.py` for the exact pattern).
4. `webui/dashboard.html` (NEW) — static HTML with Alpine.js tabs: Overview, Markets, Backtest, Shadow, Alphas, Swarm, Connectors, Settings. Each tab x-data's to the relevant `/api/plugins/vibe_trading/*` endpoint. Re-uses `--vibe-trading-accent` CSS vars.
5. `webui/dashboard.js` (NEW) — single Alpine component `vibeTradingDashboard()`. Methods: `refresh()`, `pickZoo(id)`, `openSettings()`, `backtest()`, `factor()`, `shadow()`. Render simple SVG sparklines + bar charts inline.
6. `webui/dashboard.css` (NEW) — re-uses CSS vars; tab styles, card grid, stat-tile grid.
7. `extensions/webui/sidebar-start/vibe-trading-nav.html` (NEW, mkdir first) — one `<li>` with link to `/plugins/vibe_trading/dashboard.html`, label 'Vibe-Trading'.

### Phase 2 — Upstream surfaces (6 files)

8. `api/loader_health.py` (NEW) — ApiHandler with action `probe`. Tries 1-bar `get_market_data` per loader (akshare, baostock, sina, eastmoney, mootdx, tushare, yfinance, okx, finnhub, alphavantage, fmp, fred). 30s cache.
9. `api/swarms.py` (NEW) — ApiHandler with actions `list_presets`, `get_run`, `start_run`. Proxies to MCP `list_swarm_presets`, `run_swarm`, `get_run_result`.
10. `api/shadow.py` (NEW) — ApiHandler with action `run_loop`. 5-step orchestrator: `analyze_trade_journal` -> `extract_shadow_strategy` -> `run_shadow_backtest` -> `render_shadow_report` -> `scan_shadow_signals`.
11. `api/alphazoo.py` (NEW) — ApiHandler with actions `list`, `bench`. Proxies to MCP `list_alphas`, `bench_alphas`.
12. `api/connectors.py` (NEW) — ApiHandler with actions `list`, `select`, `account`, `positions`, `orders`, `quote`, `history`. All read-only.
13. `plugin.yaml` (MODIFY) — bump version to `0.2.0`; add `webui: [main.html, page.html, config.html, dashboard.html, alphazoo.html, swarms.html, shadow.html]`.

## Reference material in /a0/usr/workdir

- `skillopt-plugin/` — perfect template: helpers/, api/, tools/, webui/, agents/, extensions/ all populated
- `ui-loader-optimizer-repo/` — canonical plugin structure
- `vibe-trading-analysis/Vibe-Trading/agent/mcp_server.py` — the 54 MCP tools
- `vibe-trading-analysis/Vibe-Trading/agent/api_server.py` — upstream REST API
- `verify_plugin.py` — verifier script
- `Markdown 2026-07-17.md` — session notes

## Constraint

Every Python file must use only single-quote string literals. This is the constraint that broke the parent context. Same for HTML/JS where possible.

## Verification

After each Python file:
```
python3 -c "import ast; ast.parse(open('PATH').read()); print('OK PATH')"
```

After all files:
```
cd /a0/usr/plugins/vibe_trading && python execute.py
```

Should print `OK: v2.2 contract check passed (5 checks)` and `Health check PASSED -- 54 tools live.`

## After handoff is consumed

1. Bump `plugin.yaml` to `0.2.0`
2. Run `python execute.py` — confirm green
3. Open `http://localhost:50001/plugins/vibe_trading/dashboard.html`
4. Test Overview, Markets, Backtest tabs
5. Pick up Phase 3 (integrations), 4 (optimisations), 5 (UX polish), 6 (stretch) from prior roadmap
