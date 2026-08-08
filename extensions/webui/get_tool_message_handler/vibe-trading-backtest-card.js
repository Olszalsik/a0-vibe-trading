/**
 * Vibe-Trading plugin — enhanced message renderer for backtest / factor /
 * options / shadow results.
 *
 * Extension point: get_tool_message_handler (v2.2; still supported in v2.5)
 *
 * The MCP server returns a JSON envelope with a top-level "status" field
 * (always "ok" on success) and a tool-specific payload. For backtest
 * results the payload is a metrics dict (total_return, sharpe, max_drawdown,
 * win_rate, trade_count, …) — exactly the fields a finance user wants to
 * see at a glance instead of as a wall of JSON.
 *
 * This handler intercepts four tool names and replaces the default raw-JSON
 * rendering with a stat-tile card. Anything that doesn't look like a
 * metrics object is left alone so we never break unrelated tools.
 *
 * v2.5 compatibility note: action buttons are built with
 * `createActionButton(icon, text, handler)` from
 * `/components/messages/action-buttons/simple-action-buttons.js` so they
 * integrate with the framework's standard action-button pipeline. The
 * v2.2-era `action: "open-plugin-config:<name>"` string protocol is
 * no longer dispatched in v2.5; we now call
 * `$store.pluginSettingsPrototype.openConfig("<name>")` directly.
 */

import { cleanStepTitle, drawProcessStep } from "/js/messages.js";
import { createActionButton } from "/components/messages/action-buttons/simple-action-buttons.js";

const HANDLED_TOOLS = new Set([
  "backtest",
  "factor_analysis",
  "analyze_options",
  "analyze_trade_journal",
  "run_shadow_backtest",
]);

const TOOL_CODE = {
  backtest: "BT",
  factor_analysis: "FA",
  analyze_options: "OPT",
  analyze_trade_journal: "TJ",
  run_shadow_backtest: "SH",
};

export default async function registerVibeTradingToolHandler(extData) {
  const name = extData?.tool_name;
  if (typeof name === "string" && HANDLED_TOOLS.has(name)) {
    extData.handler = drawVibeTradingToolCard;
  }
}

function _tryParse(content) {
  if (typeof content !== "string") return null;
  // The MCP server wraps every successful response in
  // {"status":"ok", "tool_specific_field": ...} as a JSON string.
  // Tolerate leading/trailing whitespace and accidental fences.
  const trimmed = content.trim().replace(/^```(?:json)?\s*|\s*```$/g, "");
  try {
    const obj = JSON.parse(trimmed);
    return obj && typeof obj === "object" ? obj : null;
  } catch {
    return null;
  }
}

function _extractMetrics(parsed) {
  if (!parsed) return null;
  // Vibe-Trading's mcp_server.py emits {"status":"ok", ...payload}. Pick the
  // first dict-like payload that contains any of the canonical keys.
  const candidate = parsed.status === "ok" && parsed.metrics
    ? parsed.metrics
    : parsed;
  if (!candidate || typeof candidate !== "object") return null;
  const keys = [
    "total_return", "annual_return", "sharpe", "max_drawdown",
    "win_rate", "trade_count", "ic", "ir", "delta", "gamma",
    "theta", "vega", "price",
  ];
  const hit = keys.some((k) => k in candidate);
  return hit ? candidate : null;
}

function _formatNumber(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return String(v ?? "—");
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(0);
  if (abs >= 10) return v.toFixed(2);
  if (abs >= 1) return v.toFixed(3);
  return v.toFixed(4);
}

function _formatPct(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  // Heuristic: most metrics are decimals (0.123 -> 12.3%). If the value
  // looks already-percentaged (>5 in absolute terms), leave it alone.
  const pct = Math.abs(v) > 5 ? v : v * 100;
  return `${pct.toFixed(2)}%`;
}

function _displayKvps(metrics, toolName) {
  const out = {};
  const put = (label, value) => {
    if (value === undefined || value === null) return;
    out[label] = String(value);
  };

  if (toolName === "backtest" || toolName === "run_shadow_backtest") {
    put("Total return", _formatPct(metrics.total_return));
    put("Annual return", _formatPct(metrics.annual_return));
    put("Sharpe", _formatNumber(metrics.sharpe));
    put("Max drawdown", _formatPct(metrics.max_drawdown));
    put("Win rate", _formatPct(metrics.win_rate));
    put("Trades", metrics.trade_count);
    if (metrics.start_date && metrics.end_date) {
      put("Window", `${metrics.start_date} → ${metrics.end_date}`);
    }
  } else if (toolName === "factor_analysis") {
    put("IC", _formatNumber(metrics.ic));
    put("IR", _formatNumber(metrics.ir));
    put("Top quintile return", _formatPct(metrics.top_return));
    put("Bottom quintile return", _formatPct(metrics.bottom_return));
    put("Universe", metrics.universe || "—");
    put("Period", metrics.period || "—");
  } else if (toolName === "analyze_options") {
    put("Price", _formatNumber(metrics.price));
    put("Delta", _formatNumber(metrics.delta));
    put("Gamma", _formatNumber(metrics.gamma));
    put("Theta", _formatNumber(metrics.theta));
    put("Vega", _formatNumber(metrics.vega));
    put("Spot / Strike", `${metrics.spot ?? "?"} / ${metrics.strike ?? "?"}`);
  } else if (toolName === "analyze_trade_journal") {
    put("Roundtrips", metrics.roundtrips);
    put("Win rate", _formatPct(metrics.win_rate));
    put("Avg hold (days)", _formatNumber(metrics.avg_holding_days));
    put("Disposition effect", metrics.disposition_effect || "—");
    put("Chasing", metrics.chasing || "—");
    put("Overtrading", metrics.overtrading || "—");
  }
  return out;
}

function _buildActionButtons(toolName, parsed) {
  // Post-loop CTA. v2.5 uses createActionButton(icon, text, handler).
  // The handler calls into the plugin settings store directly so the
  // button works without any custom event-bus registration.
  const buttons = [];

  const openConfig = () => {
    const store = window.Alpine?.store?.("pluginSettingsPrototype");
    if (store && typeof store.openConfig === "function") {
      return store.openConfig("vibe_trading");
    }
    // Fallback: navigate to the settings URL directly.
    window.location.href = "/settings#vibe_trading";
  };

  const openPage = () => {
    // Plugin page lives at /usr/plugins/<name>/webui/page.html for user
    // plugins and /plugins/<name>/webui/page.html for built-ins. Try
    // the user-plugins path first, fall through on 404.
    const userUrl = "/usr/plugins/vibe_trading/webui/page.html";
    const builtinUrl = "/plugins/vibe_trading/webui/page.html";
    fetch(userUrl, { method: "HEAD" })
      .then((r) => {
        window.open(r.ok ? userUrl : builtinUrl, "_blank", "noopener");
      })
      .catch(() => window.open(builtinUrl, "_blank", "noopener"));
  };

  if (toolName === "backtest") {
    buttons.push(
      createActionButton(
        "monitoring",
        "Add to Shadow Account",
        () => openConfig(),
      ),
    );
  } else if (toolName === "analyze_trade_journal") {
    buttons.push(
      createActionButton(
        "science",
        "Extract shadow strategy",
        () => openConfig(),
      ),
    );
  } else if (toolName === "factor_analysis") {
    buttons.push(
      createActionButton("insights", "Browse Alpha Zoo", () => openPage()),
    );
  }
  return buttons;
}

function drawVibeTradingToolCard({
  id,
  type,
  heading,
  content,
  kvps,
  timestamp,
  agentno = 0,
  ...additional
}) {
  const args = arguments[0];
  const toolName = args?.tool_name || (kvps && kvps.tool_name) || "";
  const parsed = _tryParse(content);
  const metrics = _extractMetrics(parsed);

  // If we can't recognise the payload, fall back to the framework's default
  // renderer by returning undefined — the v2.2 contract lets us opt out.
  if (!metrics) return undefined;

  const title = cleanStepTitle(heading);
  const displayKvps = _displayKvps(metrics, toolName);
  // Surface any original kvps that aren't already in displayKvps.
  for (const [k, v] of Object.entries(kvps || {})) {
    if (!(k in displayKvps)) displayKvps[k] = String(v);
  }
  const code = TOOL_CODE[toolName] || "VT";
  const actionButtons = _buildActionButtons(toolName, parsed);

  return drawProcessStep({
    id,
    title,
    code,
    classes: "vibe-trading-tool-card",
    kvps: displayKvps,
    content: undefined, // suppress raw JSON dump — card already shows the metrics
    actionButtons,
    log: { ...args, _vt_metrics: metrics, _vt_tool: toolName },
  });
}
