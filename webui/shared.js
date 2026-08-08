/**
 * Vibe-Trading shared UI helpers (Phase 5).
 *
 * Exposes a small namespace window.VibeTrading with:
 *   - persistence: localStorage wrapper (persist / recall / forget / exportPrefs / importPrefs)
 *   - toast: non-blocking notification system (toast / dismissAll)
 *   - shortcuts: chord-based keyboard shortcut dispatcher
 *   - help: lightweight modal listing registered shortcuts
 *   - cacheAge: small helper for cache-freshness CSS classes
 *
 * Designed to be loaded as a separate file from the plugin webui list, then
 * called from each page's existing inline <script> block.
 *
 * Single-quote-friendly (plugin constraint).
 */
(function (root) {
  'use strict';

  var NS = 'vibe_trading_ui.';
  var STORAGE_PREFIX = NS;

  // ============== persistence ==============
  function persist(key, value) {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify({ v: value, t: Date.now() }));
      return 1;
    } catch (e) {
      console.warn('[VibeTrading] persist failed:', e);
      return 0;
    }
  }

  function recall(key, fallback) {
    try {
      var raw = window.localStorage.getItem(STORAGE_PREFIX + key);
      if (!raw) return fallback;
      var parsed = JSON.parse(raw);
      return parsed && Object.prototype.hasOwnProperty.call(parsed, 'v') ? parsed.v : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function forget(key) {
    try { window.localStorage.removeItem(STORAGE_PREFIX + key); return 1; } catch (e) { return 0; }
  }

  function exportPrefs() {
    var out = {};
    try {
      for (var i = 0; i < window.localStorage.length; i++) {
        var k = window.localStorage.key(i);
        if (k && k.indexOf(NS) === 0) {
          var v = window.localStorage.getItem(k);
          out[k.slice(NS.length)] = v;
        }
      }
    } catch (e) {}
    return JSON.stringify(out, null, 2);
  }

  function importPrefs(jsonStr) {
    try {
      var obj = JSON.parse(jsonStr);
      var n = 0;
      Object.keys(obj || {}).forEach(function (k) {
        var v = obj[k];
        try { window.localStorage.setItem(STORAGE_PREFIX + k, v); n++; } catch (e) {}
      });
      return n;
    } catch (e) {
      return 0;
    }
  }

  // ============== toast ==============
  var toastContainer = null;
  function ensureToastContainer() {
    if (toastContainer) return toastContainer;
    var c = document.createElement('div');
    c.id = 'vt-toast-container';
    c.setAttribute('aria-live', 'polite');
    c.style.position = 'fixed';
    c.style.right = '12px';
    c.style.bottom = '12px';
    c.style.zIndex = '9999';
    c.style.display = 'flex';
    c.style.flexDirection = 'column';
    c.style.gap = '8px';
    c.style.maxWidth = '320px';
    document.body.appendChild(c);
    toastContainer = c;
    return c;
  }

  function toast(message, type, durationMs) {
    var c = ensureToastContainer();
    var t = type || 'info';
    var dur = typeof durationMs === 'number' ? durationMs : (t === 'error' ? 6000 : 3000);
    var node = document.createElement('div');
    node.className = 'vt-toast vt-toast-' + t;
    node.style.padding = '10px 14px';
    node.style.borderRadius = '8px';
    node.style.boxShadow = '0 4px 16px rgba(0,0,0,0.18)';
    node.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    node.style.fontSize = '13px';
    node.style.lineHeight = '1.4';
    node.style.cursor = 'pointer';
    node.style.color = '#fff';
    node.textContent = message;
    if (t === 'success') { node.style.background = 'var(--vibe-trading-accent, #4f8cff)'; }
    else if (t === 'error') { node.style.background = '#d9534f'; }
    else if (t === 'warning') { node.style.background = '#f0ad4e'; node.style.color = '#222'; }
    else { node.style.background = '#2b2f33'; }
    node.addEventListener('click', function () { dismiss(node); });
    c.appendChild(node);
    setTimeout(function () { dismiss(node); }, dur);
    return node;
  }

  function dismiss(node) {
    if (!node || !node.parentNode) return;
    node.style.opacity = '0';
    node.style.transition = 'opacity 200ms';
    setTimeout(function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    }, 220);
  }

  function dismissAll() {
    var c = ensureToastContainer();
    while (c.firstChild) c.removeChild(c.firstChild);
  }

  // ============== keyboard shortcuts ==============
  var chordBuffer = [];
  var chordTimer = null;
  var chordTimeoutMs = 900;
  var shortcutMap = {};

  function registerShortcuts(map) {
    Object.keys(map || {}).forEach(function (k) { shortcutMap[k] = map[k]; });
  }

  function unregisterShortcuts(keys) {
    (keys || []).forEach(function (k) { delete shortcutMap[k]; });
  }

  function handleKey(ev) {
    var tag = (ev.target && ev.target.tagName) || '';
    var isEditable = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (ev.target && ev.target.isContentEditable);
    if (isEditable && ev.key !== 'Escape') return;
    var key = ev.key || '';
    if (!key) return;
    if (key === '?') {
      help();
      ev.preventDefault();
      return;
    }
    if (key === 'Escape') {
      dismissAll();
      hideHelp();
      return;
    }
    chordBuffer.push(key);
    if (chordTimer) clearTimeout(chordTimer);
    chordTimer = setTimeout(function () { chordBuffer = []; }, chordTimeoutMs);
    var chord = chordBuffer.join(' ');
    if (shortcutMap[chord]) {
      try { shortcutMap[chord](ev); } catch (e) { console.warn('[VibeTrading] shortcut failed:', e); }
      chordBuffer = [];
      if (chordTimer) { clearTimeout(chordTimer); chordTimer = null; }
      ev.preventDefault();
    }
  }

  document.addEventListener('keydown', handleKey);

  // ============== help modal ==============
  var helpOverlay = null;
  function help() {
    if (helpOverlay) { hideHelp(); }
    var ov = document.createElement('div');
    ov.id = 'vt-help-overlay';
    ov.style.position = 'fixed';
    ov.style.inset = '0';
    ov.style.background = 'rgba(0,0,0,0.55)';
    ov.style.zIndex = '10000';
    ov.style.display = 'flex';
    ov.style.alignItems = 'center';
    ov.style.justifyContent = 'center';
    ov.addEventListener('click', function (e) { if (e.target === ov) hideHelp(); });
    var box = document.createElement('div');
    box.style.background = 'var(--vibe-trading-bg, #1a1d23)';
    box.style.color = 'var(--vibe-trading-text, #e8eaed)';
    box.style.padding = '24px';
    box.style.borderRadius = '12px';
    box.style.maxWidth = '480px';
    box.style.width = '90%';
    box.style.boxShadow = '0 12px 48px rgba(0,0,0,0.5)';
    box.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    box.style.fontSize = '13px';
    var h = document.createElement('h2');
    h.textContent = 'Vibe-Trading -- keyboard shortcuts';
    h.style.margin = '0 0 16px';
    h.style.fontSize = '16px';
    h.style.color = 'var(--vibe-trading-accent, #4f8cff)';
    box.appendChild(h);
    var list = document.createElement('table');
    list.style.width = '100%';
    list.style.borderCollapse = 'collapse';
    var keys = Object.keys(shortcutMap).sort();
    if (keys.length === 0) {
      var empty = document.createElement('div');
      empty.textContent = 'No shortcuts registered on this page.';
      empty.style.color = '#888';
      empty.style.padding = '12px 0';
      box.appendChild(empty);
    } else {
      keys.forEach(function (k) {
        var row = document.createElement('tr');
        var kc = document.createElement('td');
        kc.textContent = k;
        kc.style.padding = '6px 8px';
        kc.style.fontFamily = 'monospace';
        kc.style.color = 'var(--vibe-trading-accent, #4f8cff)';
        kc.style.width = '120px';
        var dc = document.createElement('td');
        dc.style.padding = '6px 8px';
        dc.textContent = (shortcutMap[k] && shortcutMap[k].description) || 'action';
        row.appendChild(kc); row.appendChild(dc);
        list.appendChild(row);
      });
      box.appendChild(list);
    }
    var hint = document.createElement('div');
    hint.textContent = 'Press Escape to close. Single-quote string-literal convention applies.';
    hint.style.marginTop = '14px';
    hint.style.fontSize = '11px';
    hint.style.color = '#888';
    box.appendChild(hint);
    ov.appendChild(box);
    document.body.appendChild(ov);
    helpOverlay = ov;
  }

  function hideHelp() {
    if (helpOverlay && helpOverlay.parentNode) helpOverlay.parentNode.removeChild(helpOverlay);
    helpOverlay = null;
  }

  // ============== cache freshness helper ==============
  function cacheAgeClass(seconds) {
    if (typeof seconds !== 'number' || seconds < 0) return 'vt-cache-fresh';
    if (seconds < 30) return 'vt-cache-fresh';
    if (seconds < 600) return 'vt-cache-warm';
    return 'vt-cache-stale';
  }

  function cacheAgeLabel(seconds) {
    if (typeof seconds !== 'number' || seconds < 0) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm';
    return Math.round(seconds / 3600) + 'h';
  }

  root.VibeTrading = {
    persist: persist,
    recall: recall,
    forget: forget,
    exportPrefs: exportPrefs,
    importPrefs: importPrefs,
    toast: toast,
    dismissAll: dismissAll,
    registerShortcuts: registerShortcuts,
    unregisterShortcuts: unregisterShortcuts,
    help: help,
    hideHelp: hideHelp,
    cacheAgeClass: cacheAgeClass,
    cacheAgeLabel: cacheAgeLabel
  };
})(window);
