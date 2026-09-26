# Vibe-Trading plugin — implementation roadmap

Started 2026-09-01. Goal: complete ALL items. Order below is execution order —
work them one at a time, verify + commit + push each before starting the next.

**STATUS: ALL 5 ITEMS COMPLETE (2026-09-01).** Commits: 1→e8d703e, 2→0378b97,
3→9e19fc6, 4→93bfdb4 (pivoted to the backtest flow — upstream
`pattern_recognition(run_dir)` reads `run_dir/artifacts/ohlcv_*.csv`, not a
symbol; Deep Dive got a pointer card instead), 5→f019e2b. Item 5 fallout:
the upgrade pulled langchain 1.3.18 which broke framework imports — fixed in
the parent repo (01be5461 helpers/, 75b21eeb plugins/_memory +
_document_query) and `langchain-classic` installed in both container venvs.

Ground rules (from AGENTS.md): handlers NEVER import plugin-local modules via
`from helpers import ...` (framework shadows `helpers`); use plugin-root
top-level modules (`import vibe_trading_cache as _cache` after
`sys.path.insert(0, PLUGIN_ROOT)`). WebUI pages are served RAW — full-document
shell, Alpine include LAST (`/vendor/alpine/alpine.min.js`). All endpoints
`/api/plugins/vibe_trading/<handler>`. Graceful degradation everywhere: probe
the live tool list and return a clear "needs upstream >= X" message instead of
a raw error (pattern established in `api/portfolio.py`).

## Tier 4 — upstream 0.1.15 upgrade (2026-09-20)

**STATUS: ALL 6 ITEMS COMPLETE (2026-09-20).** Upgraded the container's
`vibe-trading-ai` 0.1.14 → 0.1.15 (PyPI available; release "data that says what
it is" — 551 commits / 162 PRs). MCP surface count unchanged at 74
(probe-verified before and after), so all API handlers keep working; the win
is behavior/quality plus new surfaces.

1. Container upgrade: `pip install -U vibe-trading-ai` in `/opt/venv` — zero
   transitive dependency churn this time (fastmcp/mcp/langchain imports all
   satisfied; venv health check passed), A0 restarted so `hooks.py`
   re-registered and the manifest auto-synced to 0.1.15.
2. Version lockstep bumped at all five static sites (`version_sync.FALLBACK`,
   `execute.EXPECTED_VERSION`, `dashboard.js versionLabel`, `page.html` h1,
   `page-head` meta) + `plugin.yaml` description refresh (10 engines, 27
   sources, 90 skills, 462 alphas).
3. Lockstep automation: `scripts/check_v22_contract.py` grew check 4 — the
   five static sites must agree (fail), while plugin.yaml / installed-package
   mismatches are advisory warnings (a package upgrade legitimately lands
   before the static bump).
4. Portfolio page: MCP-first with upstream-CLI fallback (`vibe-trading
   portfolio show`), plus new `refresh` / `sources` actions. Probe-verified
   that `portfolio_summary` is upstream-registry-only (NOT MCP-exposed even
   at 0.1.15), so the CLI path is what actually serves the page.
5. Shadow cache keyed by journal content hash (mirrors upstream's journal-hash
   keying): a re-uploaded CSV forces a fresh analysis instead of a stale TTL hit.
6. Config page + `hooks.py`: opt-in QVeris premium-data keys (`QVERIS_API_KEY`
   / `QVERIS_BASE_URL` — default off, never in auto-fallback; other data modes
   stay CLI-managed) and per-market source-priority JSON → `MARKET_DATA_ORDER_*`
   env (13-market whitelist). Docs drift sweep everywhere: 54→74 tools,
   79→90 skills, 452→462 alphas (5th zoo `fundamental` counted live),
   18→27 sources, 7→10 engines, 4→14 brokers; Alpha Zoo NaN-contract caveat
   on the Alphas page; Watch / Deep Dive market hints (UK `.L`/`.IL`,
   China futures `RB0`/`IF0`).

## Tier 5 — hardening (2026-09-21)

**STATUS: COMPLETE (2026-09-21).** Upstream still at 0.1.15 (PyPI + GitHub
tags verified); `main` is assembling 0.1.16 (Gildata source, Robinhood
read-only portfolio, portfolio valuation v3, grounding-gate rewrite,
24 more alpha fixes). The rerun of the upgrade playbook is ready when it
lands — the lockstep check now fails loudly if the five static sites and
`plugin.yaml` drift apart during it.

1. Hygiene: removed the three dead `api/*.pre_themeb.bak` files; stale
   `execute_record.json` left as-is (written by the Plugins-UI runner).
2. Unit tests: `tests/test_plugin_internals.py` — 30 tests, plain pytest on
   the host venv (README "Tests & Verification" documents the command).
3. Goals persistence: Export/Import buttons on `webui/goals.html` —
   downloads goals + remembered ids as JSON, re-links a browser by merging
   ids from an export (same backup pattern as the settings page).
4. (0.1.16 upgrade playbook — NOT yet executed; run when upstream ships:
   container `pip install -U vibe-trading-ai`, restart A0, bump the five
   static sites + plugin.yaml, add the Gildata config field + A_SHARE
   order-migration hint to `config.html`, Robinhood in broker docs,
   portfolio-v3 history note on `portfolio.html`, Alpha Zoo caveat refresh.)

## Tier 6 — main-branch pre-ship (2026-09-22)

**STATUS: COMPLETE (2026-09-22).** 0.1.16 was NOT released upstream — PyPI and
GitHub tags still top out at v0.1.15 — but `main` carried the complete
0.1.16-pending changeset (Gildata, Robinhood read-only portfolio, portfolio
valuation v3, grounding-gate package rewrite, 24 more alpha fixes, gpt-5.6
responses-API retry, backtest/shadow fixes). Per user request, shipped it
early from a pinned commit.

1. Installed `main@a4821b1e0775302d15afb99f71ca3a44391f4495` into BOTH venvs
   (two-venv rule) via `pip install --force-reinstall --no-deps git+...@<sha>`
   — dry-run first confirmed zero dependency churn; both venvs verified via
   `direct_url.json` (commit pinned) and framework imports.
2. MCP surface unchanged at 74 tools (probe-verified) — handler contracts
   intact; plugin version labels stay 0.1.15 because upstream bumps
   `pyproject.toml` only at release time.
3. A0 restarted; registered command / manifest version / tool count all green.
4. Plugin wiring for the new surfaces: Gildata settings section +
   `default_config.yaml` keys + `hooks.py` env passthrough
   (`GILDATA_TOKEN` / `GILDATA_BASE_URL`), A_SHARE order-migration hint on
   the source-priority field, gpt-5.6 `/v1/responses` note on the model field.
5. Skipped deliberately: portfolio-v3 history note (page copy already
   version-neutral) and Alpha Zoo caveat refresh (the NaN-contract note
   covers the new comparison-gate fixes; will revisit at the real 0.1.16
   release when counts may change).

### Addendum — the two-venv trap (2026-09-22)

Post-restart symptom: the fastmcp banner reported `Vibe-Trading, 0.1.14`.
Root cause: the container has TWO vibe-trading-ai installs — `/opt/venv`
(python3.13, the interactive/CLI venv) and `/opt/venv-a0` (python3.12, the
A0 app process's own venv). `hooks.install()` runs inside the app, whose
PATH resolves `vibe-trading-mcp` to the stale venv-a0 copy, so every boot
re-registered the 0.1.14 binary AND `version_sync` (same context) rewrote
`plugin.yaml` back to 0.1.14. Fixes applied:
- `config.json` pins `"mcp_command": "/opt/venv/bin/vibe-trading-mcp"`
  (absolute, survives any PATH).
- `/opt/venv-a0` upgraded to 0.1.15 as well (zero dep churn; framework
  imports verified) — so even a fallback resolution is correct.
- A0 restarted; boot hook re-registered `/opt/venv/...` from inside the
  app; `plugin.yaml` held at 0.1.15; registered-binary probe: 74 tools.
Post-restart health check MUST therefore verify the registered command and
the manifest version, not just the tool count (execute.py probes the
`shutil.which` binary, which in a bare exec shell is /opt/venv and may
differ from the app's choice — this is exactly what bit us).

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