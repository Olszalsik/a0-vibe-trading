# Vibe-Trading (Agent Zero plugin)

Brings the [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) finance-research workspace into [Agent Zero](https://github.com/agent0ai/agent-zero) as a first-class plugin.

* **MCP server** — registers `vibe-trading-mcp` with Agent Zero's MCP client, exposing the upstream's 54 research-only tools (`backtest`, `factor_analysis`, `analyze_options`, `get_market_data`, `run_swarm`, `analyze_trade_journal`, `extract_shadow_strategy`, `scan_shadow_signals`, `web_search`, `read_document`, etc.) to every agent profile.
* **Agent profile** — ships a dedicated `vibe-trader` persona with the full research workflow, Shadow Account loop, Alpha Zoo cheatsheet, and hard safety guardrails.
* **Settings UI** — surfaces MCP toggle, LLM provider, data-source keys, risk tier, and drawdown cap inside the Agent Zero Plugins settings page, with one-click Save → re-sync.
* **Dashboard** — 8-tab research console with overview, markets, backtest, shadow, alphas, swarm, connectors, settings. Plus standalone Deep Dive and Skills browser pages.
* **Cache layer** — TTL-cached MCP responses for expensive calls (backtest 24h, factor 24h, alpha bench 24h, connector reads 30-300s, market data 5-30s). Dashboard reloads in milliseconds on second hit.
* **UX layer** — keyboard chord shortcuts (`?` for help, `Esc` to dismiss, `g o` / `g m` / `g b` for tab switching, `r` to refresh, `g dd` / `g s` for cross-page nav). State persists across reloads via localStorage. Toast notifications on async actions. Export/import button pair for backup of all preferences.
* **Live status panel** — `webui/page.html` shows install state, MCP server reachability, and the live tool list.
* **Zero-touch keys** — HK / US / crypto research and the free A-share fallback chain (akshare, baostock, sina, eastmoney, mootdx) all run key-free. Only `TUSHARE_TOKEN` (optional) and an LLM key for `run_swarm` are needed.

## What you get from Vibe-Trading

| Capability | Tools | Notes |
|---|---|---|
| **Backtest** (7 engines) | `backtest` | ChinaA · GlobalEquity · Crypto · ChinaFutures · GlobalFutures · Forex + options portfolio |
| **Factor / Alpha** | `factor_analysis` + 452 alphas | qlib158, alpha101, gtja191, academic — IC/IR/alive-reversed-dead one-line CLI bench |
| **Multi-agent swarms** (29) | `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result` | Investment Committee, Global Equities Desk, Crypto Trading Desk, Earnings Research, Macro/Rates/FX, Quant Strategy, Risk Committee |
| **Market data** (18 sources) | `get_market_data` + 10 read-only tool family | yfinance, stooq, yahoo, OKX, akshare, baostock, tencent, sina, eastmoney, mootdx, futu, tushare, finnhub, alphavantage, tiingo, fmp, local CSV/Parquet/DuckDB |
| **Fundamentals & flow** | `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_sec_filings`, `get_financial_statements`, `get_stock_profile`, `get_options_chain`, `get_stock_news` | A-share + US + HK + crypto |
| **Options & patterns** | `analyze_options`, `get_options_chain`, `pattern_recognition` | Black-Scholes + Greeks, H&S / double-top / triangle / flag |
| **Research goals** | `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status` | Auditable lifecycle per research question |
| **Shadow Account** | `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals` | Behavioural diagnostics + 3-5 distilled if-then rules + delta-PnL |
| **Macro & search** | `get_macro_series`, `iwencai_search`, `web_search`, `read_url`, `read_document` | FRED, iWenCai NL, DuckDuckGo, PDF/DOCX/XLSX/PPTX/image OCR |
| **Trading connector reads** | `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `trading_connections`, `trading_select_connection`, `trading_check` | Read-only; opt-in connector profiles (IBKR local TWS/Gateway, Robinhood MCP OAuth, Futu, Trading 212) — **no order placement via MCP** |
| **Skills knowledge base** (79) | `list_skills`, `load_skill` | Candlestick, Elliott wave, Ichimoku, SMC, harmonic, chanlun, factor research, ML strategy, pair trading, VaR/CVaR, hedging, SEC filings, crypto trading desk, behavioural finance, … |

## Install

```bash
# 1) Install the upstream package into Agent Zero's venv
pip install vibe-trading-ai

# 2) Drop the plugin into the user plugins directory
cp -r usr/plugins/vibe_trading /a0/usr/plugins/

# 3) Restart Agent Zero (the plugin's hooks.py auto-registers the MCP server on first boot)
```

After Agent Zero restarts, the agent profile `vibe-trader` appears in the **Agent profile** dropdown, the settings page shows a new **Vibe-Trading** section, and any agent can call the 54 tools by their upstream names (e.g. `backtest`, `get_market_data`, `run_swarm`).

## How to use this plugin

The plugin ships **3 ways** to interact with the upstream research workspace. Pick whichever fits the moment.

### 1. Chat with the `vibe-trader` agent (quickest)

Select the `vibe-trader` profile from the **Agent profile** dropdown in any chat. The agent already has the full Vibe-Trading research playbook baked in — including the Shadow Account loop, the 29 swarm presets, the 452 alpha formulas, and the read-only safety guardrails.

Just ask, for example:

```
Backtest a 20/50-day SMA crossover on BTC-USDT for 2024 and show Sharpe, max drawdown, and the equity curve.

Run the factor "KMID" across the 20 largest A-shares for 2024 and tell me which quintile wins.

Analyse my trade journal at /path/to/journal.csv and give me 3-5 rules I keep breaking.

Run the investment_committee swarm on AAPL.US with a 7-day horizon.
```

The agent handles tool selection, caching, source citation, and the research goal audit trail automatically.

### 2. Dashboard UI (visual research console)

Open `http://localhost:50001/usr/plugins/vibe_trading/dashboard.html` (or click the **Vibe-Trading** link in the sidebar). Eight tabs:

| Tab | Purpose | Best for |
|-----|---------|----------|
| **Overview** | Health snapshot: install state, MCP probe, recent research goals, recent swarm runs | Daily check that everything's alive |
| **Markets** | Live quotes for any symbol across 13 data loaders (yfinance, akshare, OKX, tencent, baostock, tushare, finnhub, alphavantage, fmp, fred, eastmoney, mootdx, ccxt) | "What's AAPL at right now?" |
| **Backtest** | Run a backtest via `run_dir` (the upstream-configured backtest directory) | Re-running existing configs |
| **Shadow** | 5-step Shadow Account loop — analyse journal, extract rules, backtest, render report, scan signals | Trading behaviour diagnostics |
| **Alphas** | Browse 452 alphas (qlib158, alpha101, gtja191, academic), benchmark a sample set | Factor library exploration |
| **Swarm** | List 29 multi-agent team presets, start a run, poll status | Investment committee / quant desk workflows |
| **Connectors** | Read-only views into opt-in broker connectors (IBKR / Futu / Robinhood / Trading 212) | "What's my account look like?" |
| **Settings** | UI preferences, keyboard shortcut help, plugin settings link | Theme + shortcut reference |

Two **standalone pages** also ship:

| URL | Purpose |
|-----|---------|
| `/usr/plugins/vibe_trading/webui/deepdive.html` | Single-symbol aggregator: profile card + financials + news + chart — one shot |
| `/usr/plugins/vibe_trading/webui/skills.html` | Browse 79 finance skills (candlestick, Elliott wave, Ichimoku, SMC, factor research, …), load any one into the chat |

### 3. REST API (programmatic / scripted)

Each page tab maps to a `POST /api/plugins/vibe_trading/<handler>` endpoint. Body shape: `{"action": "<name>", ...args}`. Examples:

```bash
# Live health snapshot
curl -X POST http://localhost:50001/api/plugins/vibe_trading/dashboard \
  -H 'Content-Type: application/json' -d '{"action": "snapshot"}'

# Quote a symbol
curl -X POST http://localhost:50001/api/plugins/vibe_trading/dashboard \
  -H 'Content-Type: application/json' \
  -d '{"action": "quote", "ticker": "AAPL.US", "source": "yfinance"}'

# List 79 finance skills
curl -X POST http://localhost:50001/api/plugins/vibe_trading/skills \
  -H 'Content-Type: application/json' -d '{"action": "list"}'

# Deep dive one symbol
curl -X POST http://localhost:50001/api/plugins/vibe_trading/deep_dive \
  -H 'Content-Type: application/json' -d '{"symbol": "600519.SH"}'

# List 29 swarm presets
curl -X POST http://localhost:50001/api/plugins/vibe_trading/swarms \
  -H 'Content-Type: application/json' -d '{"action": "list_presets"}'

# Run a backtest
curl -X POST http://localhost:50001/api/plugins/vibe_trading/dashboard \
  -H 'Content-Type: application/json' \
  -d '{"action": "backtest", "run_dir": "/path/to/backtest/run"}'
```

Full endpoint list (12 handlers):

| Handler | Actions |
|---------|---------|
| `stats` | (none) — returns install + MCP probe snapshot |
| `sync_mcp` | `{"action": "sync", "overrides": {...}}` — persist config and re-register MCP |
| `tools` | `{"action": "list", "force": true}` — list live MCP tools (15s cache) |
| `dashboard` | `snapshot`, `quote`, `backtest`, `factor` |
| `loader_health` | `probe` (with optional `force: true`) |
| `swarms` | `list_presets`, `start_run`, `get_run`, `list_runs`, `retry_run`, `reap_stale_runs` |
| `shadow` | `run_loop` (5-step orchestrator) |
| `alphazoo` | `list`, `bench` |
| `connectors` | `list`, `select`, `account`, `positions`, `orders`, `quote`, `history` |
| `deep_dive` | `fetch` (with `symbol`, optional `force`) |
| `skills` | `list`, `load` (with `name`) |

## Keyboard shortcuts

Every page that loads `webui/shared.js` (Dashboard, Skills, Deep Dive) responds to these chord shortcuts. Press `?` on any page to open the in-app help modal that lists the active shortcuts.

### Global (work everywhere)

| Key | Effect |
|-----|--------|
| `?` | Open the help modal — lists all shortcuts registered on the current page |
| `Esc` | Dismiss all toasts + close the help modal |

### Dashboard navigation

| Chord | Effect |
|-------|--------|
| `g o` | Switch to **Overview** tab |
| `g m` | Switch to **Markets** tab |
| `g b` | Switch to **Backtest** tab |
| `g sh` | Switch to **Shadow** tab |
| `g al` | Switch to **Alphas** tab |
| `g sw` | Switch to **Swarm** tab |
| `g c` | Switch to **Connectors** tab |
| `g st` | Switch to **Settings** tab |
| `r` | Refresh current view |

### Cross-page navigation

| Chord | From | To |
|-------|------|-----|
| `g s` | Dashboard / Deep Dive | **Skills** page |
| `g dd` | Dashboard | **Deep Dive** page |
| `g d` | Skills / Deep Dive | **Dashboard** |

Chord shortcuts use the `g` mnemonic (for "go to"). Press `g`, release, then press the second key within 1.5 seconds.

### Persistence keys

These persist across reloads via `localStorage` under the `vibe_trading_ui.` prefix. The **Settings → UI preferences → Export** button bundles them into a single JSON file you can back up or share:

| Key | Restores | Where |
|-----|----------|-------|
| `dashboard.lastTab` | Last active dashboard tab | Dashboard |
| `skills.query` | Last search query | Skills |
| `skills.activeCat` | Last selected category chip | Skills |
| `deepdive.lastSymbol` | Last symbol entered | Deep Dive (when no `?symbol=` URL param) |

## Verify

```bash
# Full health check — runs from the plugin directory
python /a0/usr/plugins/vibe_trading/execute.py
```

Expected tail at v0.5.1:

```json
{
  "plugin": "vibe_trading",
  "version": "0.5.1",
  "toggle_state": "ON",
  "v22_contract_ok": true,
  "files_ok": true,
  "manifest_ok": true,
  "install": {"vibe_trading_ai_installed": true, "console_script": true, ...},
  "hooks_install_result": {"ok": true, "mcp_enabled": true, "registered": true, ...},
  "mcp_probe": {"probed": true, "tool_count": 54, ...}
}
[vibe_trading] Health check PASSED — 54 tools live.
```

A `PARTIAL` health check with `mcp_probe.error = "unhandled errors in a TaskGroup (1 sub-exception)"` is a known stdio-transport flake from `execute.py`'s inline probe and does not affect runtime — the plugin's own install path still reports `registered: true` and the 54 tools remain reachable through `api/tools.py`.

## Configuration

All settings live in `default_config.yaml` (lowest priority). The user can override any field from the **Settings → Developer / External / MCP** pages in the WebUI; the override is persisted to `usr/plugins/vibe_trading/config.json` and re-pushed into Agent Zero's `mcp_servers` setting on Save.

| Field | Default | Purpose |
|---|---|---|
| `mcp_enabled` | `true` | Master switch for MCP server registration |
| `mcp_command` | `vibe-trading-mcp` | Console script from `pip install vibe-trading-ai` |
| `mcp_args` | `[]` | Optional JSON-array of extra args |
| `llm_provider` | `openrouter` | Only used by `run_swarm` |
| `llm_model` | `deepseek/deepseek-v4-pro` | Free-form model id |
| `temperature` | `0.0` | Upstream default; MiniMax requires > 0 |
| `timeout_seconds` | `120` | Per-LLM-call cap |
| `tushare_token` | `""` | Optional premium A-share data |
| `finnhub_api_key` | `""` | Optional US fallback |
| `alphavantage_api_key` | `""` | Optional US fallback |
| `tiingo_api_key` | `""` | Optional US fallback |
| `fmp_api_key` | `""` | Optional US fallback |
| `fred_api_key` | `""` | Macro series |
| `iwencai_key` | `""` | A-share NL research |
| `data_cache` | `0` | Opt-in local OHLCV cache |
| `risk_tier` | `research` | `research` \| `paper` \| `live` |
| `max_drawdown_pct` | `20` | Soft cap surfaced to the agent |
| `require_explicit_confirmation` | `true` | Force per-action confirmation before any live order |

## Safety

Vibe-Trading is research-only by design: the MCP server **exposes zero order-placement tools**. The `trading_*` tools are read-only (`trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`). For live execution, the upstream Vibe-Trading CLI supports opt-in connector profiles (IBKR local TWS/Gateway, Robinhood MCP OAuth, Futu, Trading 212) — using them is at the user's own risk and is out of scope for this plugin.

The `vibe-trader` agent profile enforces five hard rules:
1. Refuse to place live orders via MCP; redirect to the user's broker.
2. Confirm before spawning `run_swarm` (LLM cost + latency).
3. Always cite the data source and timestamp.
4. Never claim live-trading readiness from a backtest alone.
5. Respect the `risk_tier` and `require_explicit_confirmation` settings.

## Files

| File | Purpose |
|---|---|
| `plugin.yaml` | Plugin manifest (`settings_sections: [external, mcp, agent]`), `webui:` list |
| `default_config.yaml` | Lowest-priority settings fallback |
| `hooks.py` | `install` / `pre_update` / `uninstall` lifecycle — registers/removes the MCP server in `/a0/usr/settings.json` |
| `execute.py` | User-triggered health check (run from Plugins UI or terminal) |
| `version_sync.py` | Auto-syncs `plugin.yaml` version with installed `vibe-trading-ai` package |
| `api/stats.py` | `POST /api/plugins/vibe_trading/stats` — file presence, install state, MCP live probe |
| `api/sync_mcp.py` | `POST /api/plugins/vibe_trading/sync_mcp` — persist overrides + re-register MCP server |
| `api/tools.py` | `POST /api/plugins/vibe_trading/tools` — cached list of live MCP tool names |
| `api/dashboard.py` | `POST /api/plugins/vibe_trading/dashboard` — `snapshot`, `quote`, `backtest`, `factor` (TTL-cached) |
| `api/loader_health.py` | `POST /api/plugins/vibe_trading/loader_health` — probe all 13 data loaders (TTL-cached) |
| `api/swarms.py` | `POST /api/plugins/vibe_trading/swarms` — `list_presets`, `start_run`, `get_run`, `list_runs`, etc. |
| `api/shadow.py` | `POST /api/plugins/vibe_trading/shadow` — 5-step Shadow Account orchestrator |
| `api/alphazoo.py` | `POST /api/plugins/vibe_trading/alphazoo` — `list`, `bench` (TTL-cached) |
| `api/connectors.py` | `POST /api/plugins/vibe_trading/connectors` — `list`, `select`, `account`, `positions`, `orders`, `quote`, `history` |
| `api/deep_dive.py` | `POST /api/plugins/vibe_trading/deep_dive` — `fetch` (aggregates profile + financials + news + quote) |
| `api/skills.py` | `POST /api/plugins/vibe_trading/skills` — `list` (79 skills, categorised), `load` |
| `helpers/cache.py` | Shared thread-safe TTL cache (used by 7 read-heavy handlers) |
| `webui/main.html` | Standalone plugin page with live tool list |
| `webui/page.html` | Full info page with live status + tool list |
| `webui/config.html` | Settings page (Alpine + `plugin-settings-store`) |
| `webui/dashboard.html` | 8-tab dashboard (Overview / Markets / Backtest / Shadow / Alphas / Swarm / Connectors / Settings) |
| `webui/dashboard.css` | Dashboard styles |
| `webui/dashboard.js` | Dashboard Alpine component |
| `webui/deepdive.html` | Single-symbol deep-dive page |
| `webui/skills.html` | 79-skill browser |
| `webui/alphazoo.html` | Alpha zoo browser (452 alphas across 4 zoos) |
| `webui/swarms.html` | Swarm preset browser + run manager |
| `webui/shadow.html` | Shadow Account launcher + journal upload |
| `webui/shared.js` | Shared UI namespace: `window.VibeTrading` — toast, persist, shortcuts, help, prefs |
| `agents/vibe-trader/agent.yaml` | Dedicated agent profile |
| `extensions/python/banners/_10_vibe_trading_discovery.py` | Banner at agent start announcing live tools |
| `extensions/webui/page-head/vibe-trading-head.html` | Theme CSS variables + meta tag for the WebUI head |
| `extensions/webui/sidebar-start/vibe-trading-nav.html` | Three sidebar links: VT Dashboard / Deep Dive / Skills |
| `LICENSE` | MIT |

## License

MIT. This plugin wraps [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT) and respects upstream's license and security notices.
