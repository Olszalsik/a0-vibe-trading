# Vibe-Trading plugin — User Manual

This document is the end-user manual for the Vibe-Trading Agent Zero plugin. It covers quick-start, usage patterns, keyboard shortcuts, settings, troubleshooting, and safety.

**Plugin version:** 0.1.10 (Phase 9 complete; version follows the upstream `vibe-trading-ai` package via hooks auto-sync — all three version files stay in lockstep). See `README.md` for the capability matrix, install instructions, and file index.

## Table of contents

1. [Quick start](#quick-start)
2. [How to use](#how-to-use)
3. [Keyboard shortcuts](#keyboard-shortcuts)
4. [Settings reference](#settings-reference)
5. [Cache & persistence](#cache--persistence)
6. [Troubleshooting](#troubleshooting)
7. [Safety guardrails](#safety-guardrails)
8. [Roadmap](#roadmap)

---

## Quick start

```bash
# 1) Install the upstream package into Agent Zero's venv
pip install vibe-trading-ai

# 2) Drop the plugin into the user plugins directory
cp -r usr/plugins/vibe_trading /a0/usr/plugins/

# 3) Restart Agent Zero — hooks.py auto-registers the MCP server on first boot
```

Open one of these in your browser:

| URL | Purpose |
|-----|---------|
| `/usr/plugins/vibe_trading/webui/dashboard.html` | 8-tab research console |
| `/usr/plugins/vibe_trading/webui/deepdive.html` | Single-symbol aggregator |
| `/usr/plugins/vibe_trading/webui/skills.html` | 79-skill browser |
| `/usr/plugins/vibe_trading/webui/risk.html` | Risk-tier guard + connector reads |
| `/usr/plugins/vibe_trading/webui/journal.html` | Trade journal, CSV upload, tier-transition audit log |
| `/usr/plugins/vibe_trading/webui/main.html` | Live tool list + status |

NOTE: only files under `webui/` (and `extensions/webui/`) are served — a
root-level `/usr/plugins/vibe_trading/<anything>.html` URL 403s.

Verify the install:

```bash
cd /a0/usr/plugins/vibe_trading && python3 execute.py
```

Expected tail at v0.5.1:

```json
{
  "plugin": "vibe_trading",
  "version": "0.5.1",
  "v22_contract_ok": true,
  "files_ok": true,
  "manifest_ok": true,
  "hooks_install_result": {"ok": true, "mcp_enabled": true, "registered": true},
  "mcp_probe": {"tool_count": 54}
}
```

---

## How to use

Three access methods. Pick whichever fits the moment.

### Method 1 — Chat with the `vibe-trader` agent

Select the `vibe-trader` profile from the **Agent profile** dropdown in any chat. The agent already has the full Vibe-Trading research playbook baked in — including the Shadow Account loop, the 30 swarm presets, the 452 alpha formulas, and the read-only safety guardrails.

Example prompts:

```
Backtest a 20/50-day SMA crossover on BTC-USDT for 2024.
Run the factor "KMID" across the 20 largest A-shares for 2024.
Analyse my trade journal at /path/to/journal.csv and give me 3-5 rules I keep breaking.
Run the investment_committee swarm on AAPL.US with a 7-day horizon.
```

The agent handles tool selection, caching, source citation, and the research-goal audit trail automatically.

### Method 2 — Dashboard UI (visual console)

The dashboard has 8 tabs:

| Tab | Purpose |
|-----|---------|
| **Overview** | Health snapshot: install state, MCP probe, recent research goals, recent swarm runs |
| **Markets** | Live quotes across 13 data loaders (yfinance, akshare, OKX, tencent, baostock, tushare, finnhub, alphavantage, fmp, fred, eastmoney, mootdx, ccxt) |
| **Backtest** | Run a backtest via `run_dir` |
| **Shadow** | 5-step Shadow Account loop — analyse journal, extract rules, backtest, render report, scan signals |
| **Alphas** | Browse 452 alphas (qlib158, alpha101, gtja191, academic), benchmark a sample set |
| **Swarm** | List 30 multi-agent team presets, start a run, poll status |
| **Connectors** | Read-only views into opt-in broker connectors (IBKR / Futu / Robinhood / Trading 212) |
| **Settings** | UI preferences, keyboard shortcut help, plugin settings link |

### Method 3 — REST API (programmatic)

Each handler is a `POST /api/plugins/vibe_trading/<handler>` endpoint with body `{"action": "<name>", ...args}`.

```bash
# Live health snapshot
curl -X POST http://localhost:50001/api/plugins/vibe_trading/dashboard \
  -H 'Content-Type: application/json' -d '{"action": "snapshot"}'

# Quote a symbol
curl -X POST http://localhost:50001/api/plugins/vibe_trading/dashboard \
  -H 'Content-Type: application/json' \
  -d '{"action": "quote", "ticker": "AAPL.US", "source": "yfinance"}'

# List 88 finance skills
curl -X POST http://localhost:50001/api/plugins/vibe_trading/skills \
  -H 'Content-Type: application/json' -d '{"action": "list"}'

# Deep dive one symbol
curl -X POST http://localhost:50001/api/plugins/vibe_trading/deep_dive \
  -H 'Content-Type: application/json' -d '{"symbol": "600519.SH"}'

# List 30 swarm presets
curl -X POST http://localhost:50001/api/plugins/vibe_trading/swarms \
  -H 'Content-Type: application/json' -d '{"action": "list_presets"}'
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

---

## Keyboard shortcuts

Every page that loads `webui/shared.js` (Dashboard, Skills, Deep Dive, Risk Guard, Journal) responds to these chord shortcuts. Press `?` on any page to open the in-app help modal.

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
| `g rg` | Journal | **Risk Guard** page |
| `g j` | Risk Guard | **Journal** page |

Chord shortcuts use the `g` mnemonic (for "go to"). Press `g`, release, then press the second key within 1.5 seconds.

### Persistence keys

These persist across reloads via `localStorage` under the `vibe_trading_ui.` prefix. The **Settings → UI preferences → Export** button bundles them into a single JSON file you can back up or share:

| Key | Restores | Where |
|-----|----------|-------|
| `dashboard.lastTab` | Last active dashboard tab | Dashboard |
| `skills.query` | Last search query | Skills |
| `skills.activeCat` | Last selected category chip | Skills |
| `deepdive.lastSymbol` | Last symbol entered | Deep Dive (when no `?symbol=` URL param) |
| `journal.maxRows` | Journal entries page size | Journal |
| `risk.simTarget` | Last simulated target tier | Risk Guard |

### Tip: backup your preferences

1. Open Dashboard → Settings tab
2. Click **Export preferences**
3. A JSON file `vibe_trading_prefs_<date>.json` downloads
4. To restore on another machine: open the same tab, click **Import preferences**, pick the file

---

## Journal page (Phase 7/8/9)

The Journal page combines three features:

1. **KPIs + behaviours** — win rate, avg P&L, holding period and behavioural diagnostics (disposition effect, overtrading, chasing, anchoring), computed from the active journal source.
2. **CSV upload** — pick any broker-exported CSV (max 5 MB, must parse with a header row + at least one data row). Files are stored at `journal_uploads/<UTC-timestamp>_<name>.csv` at the plugin root. Upload auto-invalidates the journal cache and refreshes KPIs/entries immediately.
3. **Tier-transition audit log** — an append-only `journal_transitions.jsonl` recording `from_tier -> to_tier` changes (research/paper/live) with actor, note and UTC timestamp. Logging requires an explicit confirmation checkbox.

**Auto-load (Phase 9):** row resolution order is: configured `trade_journal_path` (config.json) > newest `journal_uploads/*.csv` by mtime (if `auto_load_uploads` is true, the default) > built-in demo rows. The `source` line under Recent entries shows which file was used, e.g. `auto_loaded_upload (20260818T124001Z_mytrades.csv)`.

**Safety:** the journal is read/append-only. Uploads are validated (extension, size, base64 integrity, CSV parse) and never executed; the audit log can only be appended to, never edited from the UI.

## Settings reference

All settings live in `default_config.yaml` (lowest priority). Override from **Settings → Developer / External / MCP** in the WebUI; the override persists to `usr/plugins/vibe_trading/config.json` and re-pushes into Agent Zero's `mcp_servers` setting on Save.

| Field | Default | Purpose |
|---|---|---|
| `mcp_enabled` | `true` | Master switch for MCP server registration |
| `mcp_command` | `vibe-trading-mcp` | Console script from `pip install vibe-trading-ai` |
| `mcp_args` | `[]` | Optional JSON-array of extra args |
| `llm_provider` | `openrouter` | Only used by `run_swarm` |
| `llm_model` | `deepseek/deepseek-v4-pro` | Free-form model id |
| `temperature` | `0.0` | Upstream default |
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

---

## Cache & persistence

The plugin uses two cache layers:

### 1. Server-side TTL cache (`helpers/cache.py`)

| Action | TTL | Cache key | Force-bypass |
|--------|-----|-----------|--------------|
| `dashboard.quote` | 5 s | `dashboard.quote|<ticker>|<source>` | via different params |
| `dashboard.snapshot` | 15 s | `dashboard.snapshot` | via different params |
| `dashboard.backtest` | 24 h | `dashboard.backtest|<run_dir>` | `force: true` (caller-supplied) |
| `dashboard.factor` | 24 h | `dashboard.factor|<sha256(sorted_params)[:16]>` | n/a (param change → new slot) |
| `loader_health.probe` | 30 s | `loader_health.probe` | `force: true` |
| `connectors.list` | 300 s | `connectors.list` | n/a |
| `connectors.account` | 60 s | `connectors.account|<args>` | n/a |
| `connectors.positions` | 30 s | `connectors.positions|<args>` | n/a |
| `deep_dive.fetch` | 60 s | `deep_dive.fetch|<symbol>` | `force: true` |
| `skills.list` | 5 min | `skills.list` | n/a |
| `skills.load` | 30 s | `skills.load|<name>` | n/a |
| `alphazoo.bench` | 24 h | `alphazoo.bench|<sha256(...)[:16]>` | n/a |
| `swarms.list_presets` | 60 s | `swarms.list_presets` | n/a |
| `swarms.list_runs` | 30 s | `swarms.list_runs|<limit>` | n/a |

### 2. Client-side localStorage (via `webui/shared.js`)

See the [Persistence keys](#persistence-keys) table above. Use the Settings → Export preferences button to back these up as JSON.

---

## Troubleshooting

### Plugin shows `Health check PARTIAL — MCP server probe failed: unhandled errors in a TaskGroup`

This is a known stdio-transport flake from `execute.py`'s inline probe. It does not affect runtime — the plugin's own install path still reports `registered: true` and the 54 tools remain reachable through `api/tools.py`. If `tools_count: 54` is missing, restart Agent Zero.

### `version_sync` keeps rewriting `plugin.yaml`

The `version_sync.sync_plugin_version()` function rewrites `plugin.yaml` if it diverges from the installed `vibe-trading-ai` package version. This is intentional (AGENTS.md invariant #13). To pin a specific version, freeze `pip install vibe-trading-ai==X.Y.Z`.

### A specific loader in the **Markets** tab fails

Most free loaders (yfinance, akshare, baostock, OKX) don't require API keys. The premium ones (tushare, finnhub, alphavantage, tiingo, fmp, fred, iwencai) need keys in the Settings → External page. Re-check the loader's health via the **Loader Health** tab (or `POST /api/plugins/vibe_trading/loader_health` with `force: true`).

### A backtest returns `stale cache` and you want a fresh run

Either wait 24 h, change one parameter in your config (different `run_dir` or different factor params), or open the dashboard's Backtest tab and pass `force: true` from the underlying handler.

### Keyboard shortcuts don't work

1. Make sure your browser tab has focus (click anywhere in the page first).
2. Check that `webui/shared.js` loaded — open DevTools console and look for `window.VibeTrading`. If undefined, the script tag injection failed.
3. Press `?` — the help modal should appear. If not, `shared.js` is not loaded.
4. Chord shortcuts need to be pressed within 1.5 s of each other.

---

## Safety guardrails

The plugin is research-only by design:

- The MCP server exposes **zero order-placement tools**. The `trading_*` tools are read-only.
- The `vibe-trader` agent profile enforces five hard rules:
  1. Refuse to place live orders via MCP; redirect to the user's broker.
  2. Confirm before spawning `run_swarm` (LLM cost + latency).
  3. Always cite the data source and timestamp.
  4. Never claim live-trading readiness from a backtest alone.
  5. Respect `risk_tier` and `require_explicit_confirmation`.

For live execution outside this plugin, the upstream Vibe-Trading CLI supports opt-in connector profiles (IBKR local TWS/Gateway, Robinhood MCP OAuth, Futu, Trading 212) — using them is at the user's own risk and is out of scope for this plugin.

---

## Roadmap

| Phase | Status |
|-------|--------|
| Phase 0 — install & v2.2 contract | ✅ Live |
| Phase 0.3 — version auto-sync | ✅ Live |
| Phase 1 — Dashboard MVP | ✅ Live |
| Phase 2 — upstream surfaces | ✅ Live |
| Phase 3 — deep-dive + skills + cache | ✅ Live |
| Phase 4 — MCP result caching | ✅ Live |
| Phase 5 — shared UI helper layer | ✅ Live |
| Phase 5B — page-level wiring | ✅ Live |
| Phase 6 — live-trade risk guard (gated) | ✅ Live |
| Phase 7 — trade journal + tier-transition audit log | ✅ Live |
| Phase 8 — manual journal CSV upload (5 MB, validated) | ✅ Live |
| Phase 9 — auto-load newest upload on read (`auto_load_uploads`) | ✅ Live |

Phase 6 is opt-in: it adds a risk-tier gate and broker connector detection for users who explicitly want to leave `risk_tier: research`. The default `research` tier keeps the plugin read-only. No order-placement tool exists anywhere in the plugin; live promotion requires an explicit config/env change plus an Agent Zero restart, and is recorded in the audit log.
