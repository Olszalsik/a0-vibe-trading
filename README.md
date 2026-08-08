# Vibe-Trading (Agent Zero plugin)

Brings the [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) finance-research workspace into [Agent Zero](https://github.com/agent0ai/agent-zero) as a first-class plugin.

* **MCP server** — registers `vibe-trading-mcp` with Agent Zero's MCP client, exposing the upstream's 54 research-only tools (`backtest`, `factor_analysis`, `analyze_options`, `get_market_data`, `run_swarm`, `analyze_trade_journal`, `extract_shadow_strategy`, `scan_shadow_signals`, `web_search`, `read_document`, etc.) to every agent profile.
* **Agent profile** — ships a dedicated `vibe-trader` persona with the full research workflow, Shadow Account loop, Alpha Zoo cheatsheet, and hard safety guardrails.
* **Settings UI** — surfaces MCP toggle, LLM provider, data-source keys, risk tier, and drawdown cap inside the Agent Zero Plugins settings page, with one-click Save → re-sync.
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

## Verify

```bash
# Full health check — runs from the plugin directory
python /a0/usr/plugins/vibe_trading/execute.py
```

Expected tail:

```
{
  "plugin": "vibe_trading",
  "version": "0.1.10",
  "toggle_state": "DEFAULT (enabled)",
  "files_ok": true,
  "manifest_ok": true,
  "install": {"vibe_trading_ai_installed": true, "vibe_trading_ai_version": "0.1.10", ...},
  "hooks_install_result": {"ok": true, "registered": true, ...},
  "mcp_probe": {"probed": true, "tool_count": 54, ...}
}
[vibe_trading] Health check PASSED — 54 tools live.
```

Or hit the REST endpoints from the WebUI:

```
POST /api/plugins/vibe_trading/stats
POST /api/plugins/vibe_trading/tools     # body: {"force": true} to bypass the 15s cache
POST /api/plugins/vibe_trading/sync_mcp  # body: {"overrides": {...}} to persist config
```

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
| `plugin.yaml` | Plugin manifest (`settings_sections: [external, mcp, agent]`) |
| `default_config.yaml` | Lowest-priority settings fallback |
| `hooks.py` | `install` / `pre_update` / `uninstall` lifecycle — registers/removes the MCP server in `/a0/usr/settings.json` |
| `execute.py` | User-triggered health check (run from Plugins UI or terminal) |
| `api/stats.py` | `POST /api/plugins/vibe_trading/stats` — file presence, install state, MCP live probe |
| `api/sync_mcp.py` | `POST /api/plugins/vibe_trading/sync_mcp` — persist overrides + re-register MCP server |
| `api/tools.py` | `POST /api/plugins/vibe_trading/tools` — cached list of live MCP tool names |
| `webui/config.html` | Settings page (Alpine + `plugin-settings-store`) |
| `webui/page.html` | Full info page with live status + tool list |
| `agents/vibe-trader/agent.yaml` | Dedicated agent profile |
| `extensions/python/banners/_10_vibe_trading_discovery.py` | Banner at agent start announcing live tools |
| `extensions/webui/page-head/vibe-trading-head.html` | Theme CSS variables + meta tag for the WebUI head |
| `LICENSE` | MIT |

## License

MIT. This plugin wraps [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT) and respects upstream's license and security notices.
