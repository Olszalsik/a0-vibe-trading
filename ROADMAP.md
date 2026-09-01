# Vibe-Trading plugin — implementation roadmap

Started 2026-09-01. Goal: complete ALL items. Order below is execution order —
work them one at a time, verify + commit + push each before starting the next.

Ground rules (from AGENTS.md): handlers NEVER import plugin-local modules via
`from helpers import ...` (framework shadows `helpers`); use plugin-root
top-level modules (`import vibe_trading_cache as _cache` after
`sys.path.insert(0, PLUGIN_ROOT)`). WebUI pages are served RAW — full-document
shell, Alpine include LAST (`/vendor/alpine/alpine.min.js`). All endpoints
`/api/plugins/vibe_trading/<handler>`. Graceful degradation everywhere: probe
the live tool list and return a clear "needs upstream >= X" message instead of
a raw error (pattern established in `api/portfolio.py`).

## 1. Swarm Run Manager — runs history / status / retry  [task #7]

Upstream tools (all present at 0.1.10): `list_runs`, `get_swarm_status`,
`get_run_result`, `reap_stale_runs`, `retry_run`, `list_swarm_presets`.

- `api/swarms.py`: new actions `runs`, `run_status`, `run_result`, `reap`,
  `retry` proxying the five status/history tools (bounded MCP round-trip via
  `api.dashboard._call_tool`); reads TTL-cached, mutations invalidate.
- `webui/swarms.html`: "Runs" card — table (run id, preset, state, started,
  elapsed), ↻ refresh, per-run "Open result", "Retry" for failed runs,
  "Reap stale" button. Poll status only on demand (no background polling —
  memory: usr plugin polling cadence).

## 2. Shadow Account pipeline page  [task #8]

Upstream tools (present at 0.1.10): `extract_shadow_strategy`,
`run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`.

- `api/shadow.py`: actions `extract`, `backtest`, `report`, `scan` (report
  returns the generated HTML path + sections; long outer timeout — upstream
  renders HTML/PDF, can take minutes).
- `webui/shadow.html`: replace link-out stub with the real 4-step workflow:
  1. Extract rules (from journal roundtrips) → shows extracted if-then rules
  2. Backtest extracted rules → delta-PnL attribution summary
  3. Render report → surfaces the produced HTML artifact path (link)
  4. Scan today's signals → matching symbols list
  Each step shows live status; steps 2-3 enabled after 1 succeeds.

## 3. Research Goals board  [task #9]

Upstream tools (present at 0.1.10): `start_research_goal`,
`get_research_goal`, `add_goal_evidence`, `update_research_goal_status`.

- `api/research_goals.py`: new handler, actions `start`, `get`, `add_evidence`,
  `update_status` (+ `list` if upstream supports enumeration; else get-by-id
  only and the page keeps its own id list in localStorage).
- `webui/goals.html`: goal cards (question, status, evidence count), create
  form, evidence composer, status transition buttons. Link from
  `dashboard.html` settings tab, `page.html`, `HANDOFF.md`.

## 4. Pattern recognition in Deep Dive  [task #10]

Upstream tool `pattern_recognition` (present at 0.1.10): chart patterns
(head-and-shoulders, double top/bottom, triangles, wedges, channels).

- `api/deep_dive.py`: `fetch` action additionally calls `pattern_recognition`
  for the symbol (bounded, cacheable 15-30min) and returns a `patterns`
  section.
- `webui/deepdive.html`: "Patterns" card — name, direction (bullish/bearish),
  confidence/status if provided; hidden cleanly when the tool is absent.

## 5. Upgrade vibe-trading-ai in the container  [task #11]

`pip install -U vibe-trading-ai` inside the A0 container (0.1.10 → latest,
expect v0.1.14 / 74 tools), restart A0 so `hooks.py` re-registers and the MCP
server respawns with the new tool set. Then, per invariant 13 lockstep:
bump `version_sync.py:FALLBACK`, `execute.py:EXPECTED_VERSION`,
`webui/dashboard.js versionLabel`, `webui/page.html` h1, and the
`vibe-trading-head.html` meta to the new installed version.

Post-upgrade sanity: dashboard overview tile shows the new version; tool
count reflects 74; `execute.py` health check passes.