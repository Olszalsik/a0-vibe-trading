/*
  Vibe-Trading — Dashboard Alpine component.

  Single Alpine root `vibeTradingDashboard()` consumed by webui/dashboard.html.
  All backend calls go to POST /api/plugins/vibe_trading/dashboard with an
  `action` field, so the API contract is one file (api/dashboard.py).

  Single-quote strings throughout (plugin-wide constraint).
  No build step — pure Alpine.js loaded by the Agent Zero WebUI.
*/

function vibeTradingDashboard() {
  return {
    // ----- state -------------------------------------------------
    loading: 0,
    activeTab: 'overview',
    statusMessage: '',
    tabs: [
      { id: 'overview', label: 'Overview', phase: 1 },
      { id: 'markets', label: 'Markets', phase: 1 },
      { id: 'backtest', label: 'Backtest', phase: 1 },
      // shadow / alphas / swarm / connectors are link-out tabs to the full
      // dedicated pages (v0.2.0 shipped those) — no 'soon' tag anymore.
      { id: 'shadow', label: 'Shadow', phase: 1 },
      { id: 'alphas', label: 'Alphas', phase: 1 },
      { id: 'swarm', label: 'Swarm', phase: 1 },
      { id: 'connectors', label: 'Connectors', phase: 1 },
      { id: 'settings', label: 'Settings', phase: 1 }
    ],
    sourceOptions: ['auto', 'yfinance', 'okx', 'tushare', 'akshare', 'baostock', 'ccxt'],

    versionLabel: 'v0.1.14', // follows the installed upstream vibe-trading-ai via version_sync auto-sync (AGENTS.md invariant 13)
    overview: {},

    markets: {
      codesText: 'AAPL.US, 600519.SH',
      source: 'auto',
      loading: 0,
      error: '',
      quotes: []
    },

    backtest: {
      runDir: '',
      loading: 0,
      error: '',
      result: null
    },

    patterns: {
      loading: 0,
      error: '',
      result: null,
      cached: false
    },

    // ----- lifecycle --------------------------------------------
    init() {
      const meta = document.querySelector('meta[name="vibe-trading-plugin"]');
      if (meta && meta.getAttribute('content')) {
        const m = meta.getAttribute('content').match(/v(\d+\.\d+\.\d+)/);
        if (m) this.versionLabel = 'v' + m[1];
      }
      this.refresh();
    },

    // ----- backend helper ---------------------------------------
    async callApi(action, payload) {
      const body = Object.assign({ action }, payload || {});
      let res, txt;
      try {
        res = await fetch('/api/plugins/vibe_trading/dashboard', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': this.getCsrf() || ''
          },
          body: JSON.stringify(body)
        });
        txt = await res.text();
      } catch (e) {
        return { success: 0, error: 'network error: ' + (e && e.message ? e.message : e) };
      }
      try {
        return JSON.parse(txt);
      } catch (e) {
        return { success: 0, error: 'bad JSON from server: ' + (txt || '').slice(0, 200) };
      }
    },

    getCsrf() {
      const meta = document.querySelector('meta[name="csrf-token"]');
      if (meta) return meta.getAttribute('content');
      const cookie = document.cookie.split('; ').find(c => c.startsWith('csrf_token='));
      return cookie ? cookie.split('=')[1] : '';
    },

    // ----- actions ----------------------------------------------
    async refresh() {
      if (this.loading) return;
      this.loading = true;
      this.statusMessage = '';
      try {
        const res = await this.callApi('snapshot', {});
        if (res && res.success) {
          this.overview = {
            stats: res.stats || {},
            tools: res.tools || {}
          };
        } else {
          this.statusMessage = 'Snapshot failed: ' + (res && res.error ? res.error : 'unknown error');
        }
      } finally {
        this.loading = 0;
      }
    },

    async fetchQuote() {
      const raw = (this.markets.codesText || '').split(',').map(s => s.trim()).filter(Boolean);
      if (!raw.length) {
        this.markets.error = 'enter at least one symbol';
        return;
      }
      this.markets.loading = true;
      this.markets.error = '';
      try {
        const res = await this.callApi('quote', { codes: raw, source: this.markets.source });
        if (!res || !res.success) {
          this.markets.error = (res && res.error) || 'quote failed';
          this.markets.quotes = [];
          return;
        }
        const payload = res.data || res.raw;
        this.markets.quotes = this.normaliseQuotes(payload);
      } finally {
        this.markets.loading = 0;
      }
    },

    async runBacktest() {
      if (!this.backtest.runDir) {
        this.backtest.error = 'run_dir is required';
        return;
      }
      this.backtest.loading = true;
      this.backtest.error = '';
      try {
        const res = await this.callApi('backtest', { run_dir: this.backtest.runDir });
        if (!res || !res.success) {
          this.backtest.error = (res && res.error) || 'backtest failed';
          this.backtest.result = null;
          return;
        }
        this.backtest.result = res.data || res.raw || null;
      } finally {
        this.backtest.loading = 0;
      }
    },

    async detectPatterns() {
      const runDir = (this.backtest.runDir || '').trim();
      if (!runDir) {
        this.patterns.error = 'enter a run_dir first (patterns read run_dir/artifacts/ohlcv_*.csv)';
        return;
      }
      this.patterns.loading = true;
      this.patterns.error = '';
      this.patterns.result = null;
      try {
        const res = await this.callApi('patterns', { run_dir: runDir });
        if (!res || !res.success) {
          this.patterns.error = (res && res.error) || 'pattern recognition failed';
          return;
        }
        this.patterns.result = res.data || res.raw || null;
        this.patterns.cached = !!res.cached;
      } finally {
        this.patterns.loading = 0;
      }
    },

    openSettings() {
      const store = window.Alpine && window.Alpine.store ? window.Alpine.store('pluginSettingsPrototype') : null;
      if (store && typeof store.openConfig === 'function') {
        store.openConfig('vibe_trading');
        return;
      }
      // fallback: navigate to the plugin settings page directly
      window.location.href = '/usr/plugins/vibe_trading/webui/config.html';
    },

    // ----- formatting -------------------------------------------
    get patternsResultText() {
      const r = this.patterns.result;
      if (r == null) return '';
      if (typeof r === 'string') return r;
      try { return JSON.stringify(r, null, 2); } catch (e) { return String(r); }
    },
    normaliseQuotes(payload) {
      let bars = [];
      if (Array.isArray(payload)) bars = payload;
      else if (payload && Array.isArray(payload.bars)) bars = payload.bars;
      else if (payload && typeof payload === 'object') {
        // { SYMBOL: [ {date,close}, ... ] }
        for (const k of Object.keys(payload)) {
          if (Array.isArray(payload[k])) {
            return Object.keys(payload).map(code => this.summariseSeries(code, payload[code]));
          }
        }
      }
      if (!bars.length || !bars[0]) return [];
      const codes = (this.markets.codesText || '').split(',').map(s => s.trim()).filter(Boolean);
      if (bars.length === 1 && codes.length === 1) {
        return [this.summariseSeries(codes[0], bars[0])];
      }
      return bars.map((row, i) => {
        if (row && typeof row === 'object' && ('close' in row || 'last' in row || 'code' in row)) {
          return {
            code: row.code || codes[i] || ('#' + i),
            last: row.last != null ? row.last : row.close,
            change_pct: row.change_pct != null ? row.change_pct : (row.change != null ? row.change : 0),
            spark: row.spark || [row.last != null ? row.last : row.close]
          };
        }
        return null;
      }).filter(Boolean);
    },

    summariseSeries(code, rows) {
      const close = (rows || []).map(r => (r && (r.close != null ? r.close : r.last)));
      const valid = close.filter(v => typeof v === 'number');
      const first = valid[0];
      const last = valid[valid.length - 1];
      const change = first ? ((last - first) / first) * 100 : 0;
      return {
        code: code,
        last: last != null ? last : (rows[rows.length - 1] || {}).close,
        change_pct: change,
        spark: valid
      };
    },

    sparklinePoints(series) {
      const arr = (series || []).filter(v => typeof v === 'number');
      if (arr.length < 2) return '';
      const min = Math.min.apply(null, arr);
      const max = Math.max.apply(null, arr);
      const span = (max - min) || 1;
      const W = 100, H = 30;
      return arr.map((v, i) => {
        const x = (i / (arr.length - 1)) * W;
        const y = H - ((v - min) / span) * H;
        return x.toFixed(2) + ',' + y.toFixed(2);
      }).join(' ');
    },

    formatPrice(v) {
      if (typeof v !== 'number') return '—';
      if (Math.abs(v) >= 1000) return v.toFixed(2);
      if (Math.abs(v) >= 1) return v.toFixed(3);
      return v.toFixed(6);
    },

    formatPct(v) {
      if (typeof v !== 'number') return '—';
      return v.toFixed(2) + '%';
    }
  };
}

// expose for non-module loader (Agent Zero WebUI injects inline scripts)
window.vibeTradingDashboard = vibeTradingDashboard;
