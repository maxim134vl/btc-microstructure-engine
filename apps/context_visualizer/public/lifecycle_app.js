/**
 * Live View: lifecycle context + paper trade overlays.
 * Visual-only. No trading logic. Cache-busted fetches.
 */

const state = {
  candles: [],
  episodes: [],
  uncertainty: [],
  latest: null,
  visualStatus: null,
  overlays: null,
  openPositions: [],
  closedTrades: [],
  tradeShapes: [],
  tradeResult: null,
  pnlSummary: null,
  controller: null,
  selected: [],
  visibleStart: 0,
  visibleEnd: 0,
  range: "latest500",
  pointer: null,
  dragging: false,
  dragStartX: 0,
  dragStartVisibleStart: 0,
  lastVisualTimestamp: null,
  selectedInspector: null,
  hitTargets: [],
  pollTimer: null,
};

const POLL_INTERVAL_MS = 15_000;
const VISUAL_STALE_SECONDS = 90;
const THEME_STORAGE_KEY = "btcml-context-visual-theme";

const viewerRoot = document.getElementById("viewerRoot");
const errorPanel = document.getElementById("viewerErrorPanel");
const canvas = document.getElementById("lifecycleCanvas");
const statusLine = document.getElementById("statusLine");
const sourceLine = document.getElementById("sourceLine");
const statusChips = document.getElementById("statusChips");
const hoverReadout = document.getElementById("hoverReadout");
const rangeSelect = document.getElementById("rangeSelect");
const themeSelect = document.getElementById("themeSelect");
const sidebarToggle = document.getElementById("sidebarToggle");
const inspectorPanel = document.getElementById("inspectorPanel");
const controllerTimeline = document.getElementById("controllerTimeline");
const paperTradeResultPanel = document.getElementById("paperTradeResultPanel");
const paperPnlPanel = document.getElementById("paperPnlPanel");
const ctx = canvas && typeof canvas.getContext === "function" ? canvas.getContext("2d") : null;

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function chartColors() {
  return {
    positive: cssVar("--accent-positive", "#30d158"),
    negative: cssVar("--accent-negative", "#ff453a"),
    warning: cssVar("--accent-warning", "#ff9f0a"),
    info: cssVar("--accent-info", "#64d2ff"),
    grid: cssVar("--chart-grid", "rgba(255,255,255,0.045)"),
    axis: cssVar("--chart-axis", "#6e7380"),
    longZone: cssVar("--long-zone", "rgba(48, 209, 88, 0.12)"),
    longZoneFaded: cssVar("--long-zone-faded", "rgba(48, 209, 88, 0.07)"),
    shortZone: cssVar("--short-zone", "rgba(255, 69, 58, 0.12)"),
    shortZoneFaded: cssVar("--short-zone-faded", "rgba(255, 69, 58, 0.07)"),
    volumeUp: cssVar("--volume-up", "rgba(48, 209, 88, 0.22)"),
    volumeDown: cssVar("--volume-down", "rgba(255, 69, 58, 0.22)"),
    profitZone: cssVar("--profit-zone", "rgba(48, 209, 88, 0.12)"),
    riskZone: cssVar("--risk-zone", "rgba(255, 69, 58, 0.10)"),
    lossZone: cssVar("--loss-zone", "rgba(255, 69, 58, 0.12)"),
    connector: cssVar("--connector", "rgba(255, 214, 10, 0.55)"),
    markerStroke: cssVar("--marker-stroke", "rgba(255,255,255,0.65)"),
    muted: cssVar("--text-muted", "#6e7380"),
    mono: cssVar("--font-mono", "ui-monospace, SF Mono, Menlo, monospace"),
  };
}

function resolveThemeMode(mode) {
  if (mode === "light" || mode === "dark") return mode;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyThemeMode(mode, persist = true) {
  const safeMode = mode === "light" || mode === "dark" || mode === "system" ? mode : "system";
  const resolved = resolveThemeMode(safeMode);
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, safeMode);
    } catch (_e) {
      /* ignore */
    }
  }
  if (themeSelect) themeSelect.value = safeMode;
  renderChart();
}

function initThemeControls() {
  let mode = "system";
  try {
    mode = localStorage.getItem(THEME_STORAGE_KEY) || "system";
  } catch (_e) {
    mode = "system";
  }
  applyThemeMode(mode, false);
  if (themeSelect) {
    themeSelect.value = mode;
    themeSelect.addEventListener("change", () => applyThemeMode(themeSelect.value, true));
  }
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onScheme = () => {
    let current = "system";
    try {
      current = localStorage.getItem(THEME_STORAGE_KEY) || "system";
    } catch (_e) {
      current = "system";
    }
    if (current === "system") applyThemeMode("system", false);
  };
  if (typeof media.addEventListener === "function") media.addEventListener("change", onScheme);
  else if (typeof media.addListener === "function") media.addListener(onScheme);

  if (sidebarToggle && viewerRoot) {
    sidebarToggle.addEventListener("click", () => {
      const collapsed = viewerRoot.classList.toggle("sidebar-collapsed");
      sidebarToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      renderChart();
    });
  }
}

function shortId(value, keep = 10) {
  const text = String(value || "");
  if (!text || text === "—") return "—";
  if (text.length <= keep + 4) return text;
  return `${text.slice(0, keep)}…`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function chipHtml(label, className = "", title = "") {
  const cls = className ? ` lifecycle-chip ${className}` : " lifecycle-chip";
  return `<span class="${cls.trim()}" title="${escapeHtml(title || label)}">${escapeHtml(label)}</span>`;
}

function kvRow(label, value, opts = {}) {
  const classes = ["v"];
  if (opts.mono) classes.push("mono");
  if (opts.pos) classes.push("pos");
  if (opts.neg) classes.push("neg");
  return `<div class="k">${escapeHtml(label)}</div><div class="${classes.join(" ")}" title="${escapeHtml(opts.title || value)}">${value}</div>`;
}

function copyableId(value) {
  const full = String(value || "—");
  const short = shortId(full, 14);
  return `<span class="lifecycle-id-row"><span class="lifecycle-mono" title="${escapeHtml(full)}">${escapeHtml(short)}</span><button type="button" data-copy="${escapeHtml(full)}" title="Copy full id">Copy</button></span>`;
}

function bindCopyButtons(root) {
  if (!root) return;
  root.querySelectorAll("button[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const text = btn.getAttribute("data-copy") || "";
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "Copied";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      } catch (_e) {
        btn.textContent = "Fail";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  });
}

function showViewerError(message) {
  const text = String(message || "Unknown viewer error");
  if (errorPanel) {
    errorPanel.textContent = text;
    errorPanel.classList.remove("hidden");
  }
  if (statusLine) statusLine.textContent = text;
  if (viewerRoot) viewerRoot.setAttribute("data-viewer-error", "1");
  console.error("[lifecycle viewer]", text);
}

function clearViewerError() {
  if (errorPanel) {
    errorPanel.textContent = "";
    errorPanel.classList.add("hidden");
  }
  if (viewerRoot) viewerRoot.removeAttribute("data-viewer-error");
}

window.addEventListener("error", (event) => {
  const detail = event?.error?.message || event?.message || "Script error";
  showViewerError(`Viewer runtime error: ${detail}`);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event?.reason;
  const detail = reason?.message || String(reason || "Unhandled promise rejection");
  showViewerError(`Viewer promise error: ${detail}`);
});

function ensureRefreshLine() {
  let refreshLine = document.getElementById("refreshLine");
  if (refreshLine) return refreshLine;
  const meta = document.querySelector(".lifecycle-status-meta");
  refreshLine = document.createElement("span");
  refreshLine.id = "refreshLine";
  refreshLine.className = "lifecycle-refresh-line";
  refreshLine.textContent = "AUTO-REFRESH";
  if (meta) meta.insertBefore(refreshLine, meta.firstChild);
  return refreshLine;
}

function cacheBust(path) {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}v=${Date.now()}`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatTime(unixSeconds) {
  if (!unixSeconds) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(unixSeconds * 1000));
}

function actionLabel(allowed) {
  return allowed ? "action enabled" : "action disabled";
}

function updateRefreshLine() {
  const refreshLine = ensureRefreshLine();
  if (!refreshLine) return;
  const vs = state.visualStatus || {};
  const status = vs.visual_data_status || "UNKNOWN";
  const sourceLag = vs.source_lag_minutes;
  const visualAge = vs.visual_refresh_age_seconds;
  const lastRefresh = vs.last_visual_refresh_ts || "—";
  const liveTs = vs.latest_live_feed_ts || "—";
  let mode = "FRESH";
  let staleClass = false;
  let waitingClass = false;
  if (status === "VISUAL_DATA_STALE") {
    mode = "STALE";
    staleClass = true;
  } else if (status === "SOURCE_WAITING_NO_NEW_BAR" || status === "SOURCE_WAITING") {
    mode = "SOURCE WAITING";
    waitingClass = true;
  } else if (status === "DEGRADED_LAST_GOOD_DATA") {
    mode = "DEGRADED";
    staleClass = true;
  } else if (status === "LIVE_OK") {
    mode = "FRESH";
  }
  const lagText = sourceLag == null ? "—" : `${Number(sourceLag).toFixed(1)}m`;
  const ageText = visualAge == null ? "—" : `${Number(visualAge).toFixed(0)}s`;
  refreshLine.textContent = `${mode} · age ${ageText} · lag ${lagText}`;
  refreshLine.title = `${status} · visual age ${ageText} · source lag ${lagText} · refresh ${lastRefresh} · live ${liveTs}`;
  refreshLine.classList.toggle("is-stale", staleClass);
  refreshLine.classList.toggle("is-live", !staleClass && !waitingClass);
  refreshLine.classList.toggle("is-waiting", waitingClass);
}

function contextChipClass(context) {
  const c = String(context || "OBSERVE").toUpperCase();
  if (c.includes("LONG")) return "is-long";
  if (c.includes("SHORT")) return "is-short";
  return "is-observe";
}

function lifecycleChipClass(lifecycle) {
  const l = String(lifecycle || "").toUpperCase();
  if (l.includes("CHALLENGED")) return "is-challenged";
  if (l.includes("ACTIVE") || l.includes("CONFIRMED")) return "is-fresh";
  return "is-idle";
}

function renderStatusChips() {
  if (!statusChips) return;
  const latest = state.latest || {};
  const vs = state.visualStatus || {};
  const context = latest.active_market_context || "OBSERVE";
  const lifecycle = latest.lifecycle_state || "NO_ACTIVE_CONTEXT";
  const status = vs.visual_data_status || "UNKNOWN";
  let sourceChip = "SOURCE";
  let sourceClass = "is-info";
  if (status === "LIVE_OK") {
    sourceChip = "FRESH";
    sourceClass = "is-fresh";
  } else if (status === "SOURCE_WAITING_NO_NEW_BAR" || status === "SOURCE_WAITING") {
    sourceChip = "SOURCE WAITING";
    sourceClass = "is-waiting";
  } else if (status === "VISUAL_DATA_STALE" || status === "DEGRADED_LAST_GOOD_DATA") {
    sourceChip = "STALE";
    sourceClass = "is-stale";
  }
  const contextLabel = String(context).includes("LONG")
    ? "LONG"
    : String(context).includes("SHORT")
      ? "SHORT"
      : "OBSERVE";
  statusChips.innerHTML = [
    chipHtml(contextLabel, contextChipClass(context), context),
    chipHtml(lifecycle, lifecycleChipClass(lifecycle), lifecycle),
    chipHtml("PAPER ONLY", "is-accent", "Paper trading only"),
    chipHtml("EXECUTION OFF", "is-idle", "No real execution"),
    chipHtml(sourceChip, sourceClass, status),
  ].join("");
}

function updateStatusLine() {
  if (!statusLine || !sourceLine) return;
  const latest = state.latest || {};
  const context = latest.active_market_context || "OBSERVE";
  const lifecycle = latest.lifecycle_state || "NO_ACTIVE_CONTEXT";
  const age = latest.active_context_age_bars;
  if (context === "OBSERVE") {
    statusLine.textContent = "Current context";
    statusLine.title = `${context} · ${lifecycle} · ${actionLabel(Boolean(latest.action_allowed))}`;
  } else {
    statusLine.textContent = "Current context";
    statusLine.title = `${context} · ${lifecycle} · age ${age ?? 0} bars · ${actionLabel(Boolean(latest.action_allowed))}`;
  }
  const vs = state.visualStatus || {};
  const oc = state.overlays?.counts || {};
  const entries = vs.entries_count ?? oc.entry_markers ?? 0;
  const exits = vs.exits_count ?? oc.exit_markers ?? 0;
  const openN = vs.open_positions_count ?? (state.openPositions || []).length;
  const closedN = vs.closed_trades_count ?? (state.closedTrades || []).length;
  const lastId = vs.last_trade_id || state.overlays?.last_trade_id || "—";
  const lastRes = vs.last_trade_result || state.overlays?.last_trade_result || "—";
  sourceLine.textContent = `entries ${entries} · exits ${exits} · open ${openN} · closed ${closedN} · last ${lastId} · ${lastRes}`;
  sourceLine.title = sourceLine.textContent;
  renderStatusChips();
  updateRefreshLine();
  renderControllerTimeline();
  renderTradeResultPanel();
  renderPnlPanel();
}

function renderTradeResultPanel() {
  if (!paperTradeResultPanel) return;
  const tr = state.tradeResult;
  if (!tr || !tr.has_closed_trade) {
    paperTradeResultPanel.innerHTML = `<p class="lifecycle-empty">No closed paper trade yet.</p>`;
    return;
  }
  const result = String(tr.result || "—").toUpperCase();
  const side = String(tr.side || "—").toUpperCase();
  const pnl = Number(tr.realized_pnl_usd);
  const pnlClass = Number.isFinite(pnl) ? (pnl >= 0 ? "pos" : "neg") : "";
  paperTradeResultPanel.innerHTML = `
    <div class="lifecycle-inline-chips">
      ${chipHtml(side, contextChipClass(side))}
      ${chipHtml(result, result === "WIN" ? "is-win" : result === "LOSS" ? "is-loss" : "is-idle")}
      ${chipHtml(tr.status || "CLOSED", "is-accent")}
    </div>
    <div class="lifecycle-kv">
      ${kvRow("trade id", copyableId(tr.trade_id), { title: tr.trade_id })}
      ${kvRow("position", copyableId(tr.position_id), { title: tr.position_id })}
      ${kvRow("entry → exit", `${formatNumber(tr.entry_price)} → ${formatNumber(tr.exit_price)}`)}
      ${kvRow("times", `${tr.entry_time || "—"} → ${tr.exit_time || "—"}`)}
      ${kvRow("exit reason", escapeHtml(tr.exit_reason || "—"), { title: tr.exit_reason })}
      ${kvRow("pnl usd", formatNumber(tr.realized_pnl_usd), { pos: pnlClass === "pos", neg: pnlClass === "neg" })}
      ${kvRow("pnl bps", formatNumber(tr.realized_pnl_bps, 2))}
      ${kvRow("fees", formatNumber(tr.fees))}
      ${kvRow("context", `${tr.context_entry || "—"} → ${tr.context_exit || "—"}`)}
      ${kvRow("lifecycle", `${tr.lifecycle_entry || "—"} → ${tr.lifecycle_exit || "—"}`)}
    </div>`;
  bindCopyButtons(paperTradeResultPanel);
}

function renderPnlPanel() {
  if (!paperPnlPanel) return;
  const p = state.pnlSummary || {};
  const total = Number(p.total_pnl_usd);
  paperPnlPanel.innerHTML = `
    <div class="lifecycle-kv">
      ${kvRow("initial capital", formatNumber(p.initial_capital, 2), { title: p.initial_capital_source || "" })}
      ${kvRow("current equity", formatNumber(p.current_paper_equity, 2))}
      ${kvRow("total pnl", formatNumber(p.total_pnl_usd, 2), { pos: total >= 0, neg: total < 0 })}
      ${kvRow("total pnl %", `${formatNumber(p.total_pnl_pct, 4)}%`)}
      ${kvRow("annualized %", `${formatNumber(p.annualized_return_pct, 4)}%`)}
      ${kvRow("closed trades", String(p.closed_trades_count ?? 0))}
      ${kvRow("win / loss", `${p.win_count ?? 0} / ${p.loss_count ?? 0}`)}
      ${kvRow("open positions", String(p.open_positions_count ?? 0))}
    </div>`;
}

function renderControllerTimeline() {
  if (!controllerTimeline) return;
  const actions = state.controller?.actions || [];
  const cycles = state.controller?.cycles || [];
  const recentCycles = cycles.slice(-8).reverse();
  const lines = [];
  if (actions.length) {
    actions.slice().reverse().slice(0, 12).forEach((a) => {
      const reason = a.reason || "";
      lines.push(
        `<div class="tl-row" data-kind="action" data-id="${escapeHtml(a.action_id || "")}">
          ${chipHtml(a.action_type || "ACTION", "is-info")}
          <div>
            <div class="lifecycle-mono">${escapeHtml(a.action_ts || "")}</div>
            <div>${escapeHtml(a.side || "")} @ ${formatNumber(a.price, 2)}</div>
          </div>
          <div class="tl-meta" title="${escapeHtml(reason)}">${escapeHtml(reason)}</div>
        </div>`
      );
    });
  }
  recentCycles.forEach((c) => {
    const reason = `${c.context || ""} / ${c.lifecycle_state || ""}`;
    lines.push(
      `<div class="tl-row" data-kind="cycle" data-id="${escapeHtml(c.cycle_id || "")}">
        ${chipHtml(c.action_taken || "CYCLE", "is-idle")}
        <div>
          <div class="lifecycle-mono">${escapeHtml(c.cycle_ts || "")}</div>
          <div>${escapeHtml(reason)}</div>
        </div>
        <div class="tl-meta" title="${escapeHtml(reason)}">${escapeHtml(reason)}</div>
      </div>`
    );
  });
  controllerTimeline.innerHTML = lines.join("") || `<div class="tl-empty">No controller actions yet.</div>`;
}

function setInspector(payload) {
  state.selectedInspector = payload || null;
  if (!inspectorPanel) return;
  if (!payload) {
    inspectorPanel.innerHTML = `<p class="lifecycle-empty">Click an entry/exit marker or trade shape.</p>`;
    return;
  }
  const side = String(payload.side || "").toUpperCase();
  const result = String(payload.result_status || payload.result || payload.status || "").toUpperCase();
  inspectorPanel.innerHTML = `
    <div class="lifecycle-inline-chips">
      ${side ? chipHtml(side, contextChipClass(side)) : ""}
      ${result ? chipHtml(result, result === "WIN" ? "is-win" : result === "LOSS" ? "is-loss" : "is-accent") : ""}
    </div>
    <pre class="lifecycle-inspector">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
}

function applyRange(resetViewport = true) {
  const candleRows = Array.isArray(state.candles) ? state.candles : [];
  const rows = candleRows.filter((row) => row && row.time && row.open != null);
  if (!rows.length) {
    state.selected = [];
    state.visibleStart = 0;
    state.visibleEnd = 0;
    return;
  }
  const latest = rows[rows.length - 1];
  const range = state.range;
  if (range === "latest100") state.selected = rows.slice(-100);
  else if (range === "latest500") state.selected = rows.slice(-500);
  else if (range === "latest1000") state.selected = rows.slice(-1000);
  else if (range === "last7d") state.selected = rows.filter((row) => row.time >= latest.time - 7 * 86400);
  else if (range === "last14d") state.selected = rows.filter((row) => row.time >= latest.time - 14 * 86400);
  else state.selected = rows.slice();

  if (resetViewport) {
    state.visibleStart = 0;
    state.visibleEnd = state.selected.length;
  } else {
    constrainViewport();
  }
}

function constrainViewport() {
  const total = state.selected.length;
  const count = Math.max(24, state.visibleEnd - state.visibleStart);
  if (count >= total) {
    state.visibleStart = 0;
    state.visibleEnd = total;
    return;
  }
  state.visibleStart = clamp(state.visibleStart, 0, total - count);
  state.visibleEnd = state.visibleStart + count;
}

function getBounds(width, height) {
  const left = 12;
  const right = width - 58;
  const top = 18;
  const bottom = height - 28;
  const volumeHeight = 42;
  const volumeBottom = bottom;
  const volumeTop = volumeBottom - volumeHeight;
  return {
    left,
    right,
    top,
    bottom,
    width: right - left,
    priceTop: top + 8,
    priceBottom: volumeTop - 8,
    volumeTop,
    volumeBottom,
  };
}

function fillHatch(x, y, w, h, color) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = color.replace(/[\d.]+\)$/, "0.35)");
  ctx.lineWidth = 1;
  const step = 7;
  for (let offset = -h; offset < w + h; offset += step) {
    ctx.beginPath();
    ctx.moveTo(x + offset, y);
    ctx.lineTo(x + offset + h, y + h);
    ctx.stroke();
  }
  ctx.restore();
}

function episodeFill(episode) {
  const colors = chartColors();
  const challenged = Number(episode.challenge_ratio || 0) > 0.5
    || String(episode.dominant_lifecycle_state || "").toUpperCase() === "CHALLENGED";
  if (episode.context === "LONG_CONTEXT") {
    return challenged
      ? { mode: "hatch", color: colors.longZoneFaded }
      : { mode: "solid", color: colors.longZone };
  }
  if (episode.context === "SHORT_CONTEXT") {
    return challenged
      ? { mode: "hatch", color: colors.shortZoneFaded }
      : { mode: "solid", color: colors.shortZone };
  }
  return null;
}

function drawLifecycleBands(bounds, visibleStartTime, visibleEndTime, xForTime) {
  if (!ctx) return;
  const episodes = Array.isArray(state.episodes) ? state.episodes : [];
  episodes.forEach((episode) => {
    const fill = episodeFill(episode);
    if (!fill) return;
    const start = episode.start_time_unix;
    const end = episode.end_time_unix;
    if (end < visibleStartTime || start > visibleEndTime) return;
    const x0 = clamp(xForTime(Math.max(start, visibleStartTime)), bounds.left, bounds.right);
    const x1 = clamp(xForTime(Math.min(end, visibleEndTime)), bounds.left, bounds.right);
    const width = Math.max(1, x1 - x0);
    const y = bounds.priceTop;
    const h = bounds.priceBottom - bounds.priceTop;
    if (fill.mode === "hatch") fillHatch(x0, y, width, h, fill.color);
    else {
      ctx.fillStyle = fill.color;
      ctx.fillRect(x0, y, width, h);
    }
  });
}

function uncertaintyHatchColor(segment) {
  const colors = chartColors();
  const type = String(segment.visual_type || "").toUpperCase();
  if (type !== "CANDIDATE" && type !== "CHALLENGED") return null;
  const direction = String(segment.direction || "OBSERVE").toUpperCase();
  if (direction === "LONG_CONTEXT") return colors.longZoneFaded;
  if (direction === "SHORT_CONTEXT") return colors.shortZoneFaded;
  return null;
}

function drawUncertaintySegments(bounds, visibleStartTime, visibleEndTime, xForTime) {
  if (!ctx) return;
  const segments = Array.isArray(state.uncertainty) ? state.uncertainty : [];
  segments.forEach((segment) => {
    const color = uncertaintyHatchColor(segment);
    if (!color) return;
    const start = Number(segment.start_time_unix);
    const end = Number(segment.end_time_unix);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;
    if (end < visibleStartTime || start > visibleEndTime) return;
    const x0 = clamp(xForTime(Math.max(start, visibleStartTime)), bounds.left, bounds.right);
    const x1 = clamp(xForTime(Math.min(end, visibleEndTime)), bounds.left, bounds.right);
    const width = Math.max(1, x1 - x0);
    fillHatch(x0, bounds.priceTop, width, bounds.priceBottom - bounds.priceTop, color);
  });
}

function drawCandles(bounds, rows, xForTime, yForPrice) {
  if (rows.length < 2) return;
  const colors = chartColors();
  const step = Math.max(1, (rows[1].time - rows[0].time) || 900);
  const candleWidth = Math.max(1.5, (xForTime(rows[0].time + step) - xForTime(rows[0].time)) * 0.7);
  rows.forEach((row) => {
    const x = xForTime(row.time);
    const openY = yForPrice(row.open);
    const closeY = yForPrice(row.close);
    const highY = yForPrice(row.high);
    const lowY = yForPrice(row.low);
    const up = row.close >= row.open;
    const color = up ? colors.positive : colors.negative;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();
    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(1, Math.abs(closeY - openY));
    ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
  });
}

const VOLUME_HIGHLIGHT_EVENTS = new Set(["BUYING_CLIMAX", "SELLING_CLIMAX"]);

function volumeEventOf(row) {
  return typeof row.volume_event === "string" ? row.volume_event.toUpperCase() : "";
}

function drawVolume(bounds, rows, xForTime, volumeMax) {
  if (!rows.length) return;
  const colors = chartColors();
  const step = Math.max(1, (rows[1]?.time || rows[0].time + 900) - rows[0].time);
  const barWidth = Math.max(1, (xForTime(rows[0].time + step) - xForTime(rows[0].time)) * 0.55);
  rows.forEach((row) => {
    const height = ((row.volume || 0) / volumeMax) * (bounds.volumeBottom - bounds.volumeTop);
    const x = xForTime(row.time);
    const up = row.close >= row.open;
    const event = volumeEventOf(row);
    const y = bounds.volumeBottom - height;
    if (VOLUME_HIGHLIGHT_EVENTS.has(event)) {
      const selling = event === "SELLING_CLIMAX";
      ctx.fillStyle = selling ? colors.negative : colors.positive;
      ctx.globalAlpha = 0.7;
      ctx.fillRect(x - barWidth / 2, y, barWidth, height);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = colors.warning;
      ctx.lineWidth = 1.1;
      ctx.strokeRect(x - barWidth / 2, y, barWidth, Math.max(1, height));
    } else {
      ctx.fillStyle = up ? colors.volumeUp : colors.volumeDown;
      ctx.fillRect(x - barWidth / 2, y, barWidth, height);
    }
  });
}

function drawGrid(bounds, priceMin, priceMax) {
  const colors = chartColors();
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 5; i += 1) {
    const y = bounds.priceTop + ((bounds.priceBottom - bounds.priceTop) / 5) * i;
    ctx.moveTo(bounds.left, y);
    ctx.lineTo(bounds.right, y);
  }
  ctx.stroke();

  ctx.fillStyle = colors.axis;
  ctx.font = `11px ${colors.mono}`;
  ctx.textAlign = "left";
  for (let i = 0; i <= 5; i += 1) {
    const price = priceMax - ((priceMax - priceMin) / 5) * i;
    const y = bounds.priceTop + ((bounds.priceBottom - bounds.priceTop) / 5) * i;
    ctx.fillText(formatNumber(price, 0), bounds.right + 6, y + 3);
  }
}

function drawTimeAxis(bounds, rows, xForTime) {
  if (!rows.length) return;
  const colors = chartColors();
  ctx.fillStyle = colors.axis;
  ctx.font = `11px ${colors.mono}`;
  ctx.textAlign = "center";
  const step = Math.max(1, Math.floor(rows.length / 6));
  for (let i = 0; i < rows.length; i += step) {
    const row = rows[i];
    ctx.fillText(formatTime(row.time), xForTime(row.time), bounds.bottom + 14);
  }
}

function drawTriangle(x, y, up, color) {
  const colors = chartColors();
  const s = 7;
  ctx.beginPath();
  if (up) {
    ctx.moveTo(x, y - s);
    ctx.lineTo(x - s, y + s * 0.6);
    ctx.lineTo(x + s, y + s * 0.6);
  } else {
    ctx.moveTo(x, y + s);
    ctx.lineTo(x - s, y - s * 0.6);
    ctx.lineTo(x + s, y - s * 0.6);
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = colors.markerStroke;
  ctx.lineWidth = 1;
  ctx.stroke();
}

function drawCircleMarker(x, y, color) {
  const colors = chartColors();
  ctx.beginPath();
  ctx.arc(x, y, 4.5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = colors.markerStroke;
  ctx.lineWidth = 1.1;
  ctx.stroke();
}

function drawPaperOverlays(bounds, visibleStartTime, visibleEndTime, xForTime, yForPrice) {
  // Chart geometry only — no trade parameter text labels on canvas.
  const colors = chartColors();
  state.hitTargets = [];
  const shapes = Array.isArray(state.tradeShapes) && state.tradeShapes.length
    ? state.tradeShapes
    : [...(state.closedTrades || []), ...(state.openPositions || [])];

  shapes.forEach((shape) => {
    const entryTs = shape.entry_time_unix ?? (shape.entry_ts ? Math.floor(Date.parse(shape.entry_ts) / 1000) : null);
    let exitTs = shape.exit_time_unix ?? (shape.exit_ts ? Math.floor(Date.parse(shape.exit_ts) / 1000) : null);
    const entryPx = shape.entry_price;
    const exitPx = shape.exit_price;
    const stop = shape.stop_price ?? shape.stop_loss_price;
    const take = shape.take_profit_price;
    const side = String(shape.side || "LONG").toUpperCase();
    const isOpen = String(shape.status || "").toUpperCase() === "OPEN";
    if (entryTs == null || entryPx == null) return;
    if (isOpen) exitTs = visibleEndTime;
    if (exitTs == null) return;

    // Partial visibility: draw if any overlap with visible window.
    if (exitTs < visibleStartTime || entryTs > visibleEndTime) return;

    const xEntryRaw = xForTime(entryTs);
    const xExitRaw = xForTime(exitTs);
    const x0 = clamp(Math.min(xEntryRaw, xExitRaw), bounds.left, bounds.right);
    const x1 = clamp(Math.max(xEntryRaw, xExitRaw), bounds.left, bounds.right);
    const xEntry = clamp(xEntryRaw, bounds.left, bounds.right);
    const xExit = clamp(xExitRaw, bounds.left, bounds.right);
    const yEntry = yForPrice(entryPx);

    // Risk zone: LONG below entry→stop; SHORT above entry→stop.
    if (stop != null) {
      const yStop = yForPrice(stop);
      const top = Math.min(yEntry, yStop);
      const h = Math.max(1, Math.abs(yStop - yEntry));
      ctx.fillStyle = colors.riskZone;
      ctx.fillRect(x0, top, Math.max(1, x1 - x0), h);
    }

    // Realized PnL zone between entry and exit prices (closed only).
    if (!isOpen && exitPx != null) {
      const yExit = yForPrice(exitPx);
      const profitable = side === "SHORT" ? exitPx <= entryPx : exitPx >= entryPx;
      ctx.fillStyle = profitable ? colors.profitZone : colors.lossZone;
      const top = Math.min(yEntry, yExit);
      const h = Math.max(1, Math.abs(yExit - yEntry));
      ctx.fillRect(x0, top, Math.max(1, x1 - x0), h);
    }

    // SL / TP reference lines (no price text on chart).
    if (stop != null) {
      const y = yForPrice(stop);
      ctx.strokeStyle = colors.negative;
      ctx.globalAlpha = 0.75;
      ctx.setLineDash([4, 5]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x1, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
    if (take != null) {
      const y = yForPrice(take);
      ctx.strokeStyle = colors.positive;
      ctx.globalAlpha = 0.75;
      ctx.setLineDash([4, 5]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x1, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // Dashed connector entry → exit (partial from visible edge if needed).
    if (exitPx != null || isOpen) {
      const yExit = yForPrice(isOpen ? entryPx : exitPx);
      ctx.strokeStyle = colors.connector;
      ctx.setLineDash([5, 5]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xEntry, yEntry);
      ctx.lineTo(xExit, isOpen ? yEntry : yExit);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (entryTs >= visibleStartTime && entryTs <= visibleEndTime) {
      drawCircleMarker(xEntry, yEntry, colors.positive);
      state.hitTargets.push({ x: xEntry, y: yEntry, r: 14, payload: shape.inspector || shape });
    }
    if (!isOpen && exitPx != null && exitTs >= visibleStartTime && exitTs <= visibleEndTime) {
      const yExit = yForPrice(exitPx);
      drawCircleMarker(xExit, yExit, colors.warning);
      state.hitTargets.push({ x: xExit, y: yExit, r: 14, payload: shape.inspector || shape });
    }
  });
}

function hitTest(x, y) {
  let best = null;
  let bestDist = Infinity;
  (state.hitTargets || []).forEach((t) => {
    const d = Math.hypot(t.x - x, t.y - y);
    if (d <= t.r && d < bestDist) {
      bestDist = d;
      best = t;
    }
  });
  return best;
}

function rowAtPointer(rows, bounds, xForTime) {
  if (!state.pointer || !rows.length) return null;
  let best = null;
  let bestDist = Infinity;
  rows.forEach((row) => {
    const dist = Math.abs(xForTime(row.time) - state.pointer.x);
    if (dist < bestDist) {
      bestDist = dist;
      best = row;
    }
  });
  if (!best || bestDist > 28) return null;
  return best;
}

function updateHover(rows, bounds, xForTime) {
  if (!hoverReadout) return;
  if (state.pointer) {
    const hit = hitTest(state.pointer.x, state.pointer.y);
    if (hit) {
      hoverReadout.classList.remove("hidden");
      const p = hit.payload || {};
      hoverReadout.textContent = [
        p.side || "TRADE",
        p.status || p.marker_type || "",
        p.entry_price != null ? `entry ${formatNumber(p.entry_price)}` : "",
        p.exit_price != null ? `exit ${formatNumber(p.exit_price)}` : "",
        p.realized_pnl_usd != null ? `rpnl ${formatNumber(p.realized_pnl_usd)}` : "",
        p.unrealized_pnl_usd != null ? `upnl ${formatNumber(p.unrealized_pnl_usd)}` : "",
      ].filter(Boolean).join(" · ");
      return;
    }
  }
  const row = rowAtPointer(rows, bounds, xForTime);
  if (!row) {
    hoverReadout.classList.add("hidden");
    hoverReadout.textContent = "";
    return;
  }
  hoverReadout.classList.remove("hidden");
  const parts = [
    formatTime(row.time),
    `close ${formatNumber(row.close)}`,
    row.active_market_context || "OBSERVE",
    row.lifecycle_state || "—",
  ];
  const event = volumeEventOf(row);
  if (VOLUME_HIGHLIGHT_EVENTS.has(event)) parts.push(event);
  hoverReadout.textContent = parts.join(" · ");
}

function renderChart() {
  if (!canvas || !ctx) {
    showViewerError("Chart canvas unavailable — page shell is still visible.");
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(width * ratio));
  canvas.height = Math.max(1, Math.floor(height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const selected = Array.isArray(state.selected) ? state.selected : [];
  const rows = selected.slice(state.visibleStart, state.visibleEnd);
  if (rows.length < 2) {
    const colors = chartColors();
    ctx.fillStyle = colors.muted;
    ctx.textAlign = "center";
    ctx.font = "14px sans-serif";
    ctx.fillText("No lifecycle candle data. Run visual refresher.", width / 2, height / 2);
    return;
  }

  const bounds = getBounds(width, height);
  const visibleStartTime = rows[0].time;
  const visibleEndTime = rows[rows.length - 1].time;
  const overlayPrices = [];
  const shapes = Array.isArray(state.tradeShapes) ? state.tradeShapes : [];
  shapes.forEach((s) => {
    [s.entry_price, s.exit_price, s.stop_price, s.stop_loss_price, s.take_profit_price].forEach((p) => {
      if (p != null && Number.isFinite(Number(p))) overlayPrices.push(Number(p));
    });
  });
  (state.overlays?.entries || []).forEach((m) => {
    if (m.price != null) overlayPrices.push(m.price);
    if (m.stop_loss_price != null) overlayPrices.push(m.stop_loss_price);
    if (m.take_profit_price != null) overlayPrices.push(m.take_profit_price);
  });
  (state.overlays?.exits || []).forEach((m) => {
    if (m.price != null) overlayPrices.push(m.price);
  });
  (state.openPositions || []).forEach((p) => {
    if (p.entry_price != null) overlayPrices.push(p.entry_price);
    (p.stop_take_lines || []).forEach((l) => { if (l?.price != null) overlayPrices.push(l.price); });
  });
  const prices = rows.flatMap((row) => [row.high, row.low]).concat(overlayPrices).filter((v) => Number.isFinite(v));
  const priceMinRaw = Math.min(...prices);
  const priceMaxRaw = Math.max(...prices);
  const pad = Math.max(8, (priceMaxRaw - priceMinRaw) * 0.08);
  const priceMin = priceMinRaw - pad;
  const priceMax = priceMaxRaw + pad;
  const volumeMax = Math.max(...rows.map((row) => row.volume || 0), 1);

  const xForTime = (unix) => {
    const span = Math.max(1, visibleEndTime - visibleStartTime);
    return bounds.left + ((unix - visibleStartTime) / span) * bounds.width;
  };
  const yForPrice = (price) => {
    const span = Math.max(1, priceMax - priceMin);
    return bounds.priceTop + ((priceMax - price) / span) * (bounds.priceBottom - bounds.priceTop);
  };

  drawGrid(bounds, priceMin, priceMax);
  drawLifecycleBands(bounds, visibleStartTime, visibleEndTime, xForTime);
  drawUncertaintySegments(bounds, visibleStartTime, visibleEndTime, xForTime);
  drawCandles(bounds, rows, xForTime, yForPrice);
  drawVolume(bounds, rows, xForTime, volumeMax);
  drawPaperOverlays(bounds, visibleStartTime, visibleEndTime, xForTime, yForPrice);
  drawTimeAxis(bounds, rows, xForTime);
  updateHover(rows, bounds, xForTime);
}

function onWheel(event) {
  event.preventDefault();
  if (!state.selected.length) return;
  const rect = canvas.getBoundingClientRect();
  const bounds = getBounds(rect.width, rect.height);
  const oldCount = state.visibleEnd - state.visibleStart;
  const zoom = event.deltaY > 0 ? 1.18 : 0.82;
  const newCount = clamp(Math.round(oldCount * zoom), 40, state.selected.length);
  const ratio = clamp((event.clientX - rect.left - bounds.left) / bounds.width, 0, 1);
  const anchor = state.visibleStart + Math.round(oldCount * ratio);
  state.visibleStart = Math.round(anchor - newCount * ratio);
  state.visibleEnd = state.visibleStart + newCount;
  constrainViewport();
  renderChart();
}

function onMouseDown(event) {
  state.dragging = true;
  state.dragStartX = event.clientX;
  state.dragStartVisibleStart = state.visibleStart;
}

function onMouseMove(event) {
  const rect = canvas.getBoundingClientRect();
  state.pointer = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
  if (state.dragging) {
    const visibleCount = state.visibleEnd - state.visibleStart;
    const bounds = getBounds(rect.width, rect.height);
    const candleWidth = bounds.width / Math.max(1, visibleCount);
    const delta = Math.round((state.dragStartX - event.clientX) / Math.max(1, candleWidth));
    state.visibleStart = state.dragStartVisibleStart + delta;
    state.visibleEnd = state.visibleStart + visibleCount;
    constrainViewport();
  }
  renderChart();
}

function onClick(event) {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = hitTest(x, y);
  if (hit) setInspector(hit.payload);
}

async function loadJson(path) {
  const response = await fetch(cacheBust(path), { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return response.json();
}

async function loadOptional(path, fallback) {
  try {
    return await loadJson(path);
  } catch (_e) {
    return fallback;
  }
}

async function loadAllVisualData() {
  const [candlesPayload, episodes, latest] = await Promise.all([
    loadJson("./data/lifecycle_candles.json"),
    loadJson("./data/lifecycle_context_episodes.json"),
    loadJson("./data/lifecycle_latest.json"),
  ]);
  const candleRows = Array.isArray(candlesPayload?.rows)
    ? candlesPayload.rows
    : Array.isArray(candlesPayload)
      ? candlesPayload
      : [];
  state.candles = candleRows;
  state.episodes = Array.isArray(episodes)
    ? episodes
    : Array.isArray(episodes?.episodes)
      ? episodes.episodes
      : [];
  try {
    const uncertainty = await loadJson("./data/lifecycle_uncertainty_segments.json");
    state.uncertainty = Array.isArray(uncertainty)
      ? uncertainty
      : Array.isArray(uncertainty?.segments)
        ? uncertainty.segments
        : [];
  } catch (_error) {
    state.uncertainty = [];
  }
  state.latest = latest && typeof latest === "object" ? latest : {};
  state.visualStatus = await loadOptional("./data/visual_status.json", {});
  state.overlays = await loadOptional("./data/paper_trade_overlays.json", { entries: [], exits: [], counts: {}, trade_shapes: [] });
  const openPayload = await loadOptional("./data/open_positions.json", { open_positions: [] });
  state.openPositions = openPayload.open_positions || state.overlays.open_positions || [];
  const closedPayload = await loadOptional("./data/closed_trades.json", { closed_trades: [] });
  state.closedTrades = closedPayload.closed_trades || state.overlays.closed_trades || [];
  state.tradeShapes = state.overlays.trade_shapes || [...state.closedTrades, ...state.openPositions];
  state.tradeResult = await loadOptional("./data/trade_result_summary.json", null);
  state.pnlSummary = await loadOptional("./data/pnl_summary.json", null);
  state.controller = await loadOptional("./data/controller_cycles.json", { cycles: [], actions: [] });
  await loadOptional("./data/context_visual.json", null);

  if (!state.latest.timestamp && !state.latest.generated_at && !state.latest.as_of) {
    showViewerError("lifecycle_latest.json is missing timestamp fields; chart may still render.");
  } else {
    clearViewerError();
  }
  state.lastVisualTimestamp = state.visualStatus?.last_visual_refresh_ts
    || state.latest.timestamp
    || state.latest.generated_at
    || null;
  updateStatusLine();
  applyRange(false);
  renderChart();
}

async function pollLatest() {
  try {
    const status = await loadOptional("./data/visual_status.json", null);
    const latest = await loadJson("./data/lifecycle_latest.json");
    const nextTs = status?.last_visual_refresh_ts || latest?.timestamp || latest?.generated_at || null;
    if (nextTs && nextTs !== state.lastVisualTimestamp) {
      await loadAllVisualData();
      return;
    }
    if (status) state.visualStatus = status;
    if (latest) state.latest = { ...(state.latest || {}), ...latest };
    updateRefreshLine();
  } catch (_error) {
    // Keep last good chart.
  }
}

function startAutoRefresh() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollLatest, POLL_INTERVAL_MS);
}

async function init() {
  if (!canvas || !ctx) {
    showViewerError("Chart library/canvas not loaded — cannot draw lifecycle chart.");
    return;
  }
  if (!statusLine || !sourceLine) {
    showViewerError("Viewer shell is incomplete — status elements missing.");
    return;
  }
  initThemeControls();
  try {
    await loadAllVisualData();
    applyRange(true);
    renderChart();
    startAutoRefresh();

    if (rangeSelect) {
      rangeSelect.addEventListener("change", () => {
        state.range = rangeSelect.value;
        applyRange(true);
        renderChart();
      });
    }
    window.addEventListener("resize", renderChart);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("click", onClick);
    canvas.addEventListener("mouseleave", () => {
      state.pointer = null;
      state.dragging = false;
      if (hoverReadout) {
        hoverReadout.classList.add("hidden");
        hoverReadout.textContent = "";
      }
      renderChart();
    });
    window.addEventListener("mouseup", () => {
      state.dragging = false;
    });
  } catch (error) {
    const message = error?.message || String(error);
    showViewerError(`Unable to load lifecycle visual data: ${message}`);
    if (sourceLine) sourceLine.textContent = "Run context visual refresher";
    const refreshLine = ensureRefreshLine();
    if (refreshLine) {
      refreshLine.textContent = "STALE · awaiting visual refresher";
      refreshLine.classList.add("is-stale");
    }
  }
}

init();
