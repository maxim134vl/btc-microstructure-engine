/**
 * VIS3C + trade-render fix: standalone ?tf= charts, stable TF_N numbers,
 * TradingView Long/Short position zones (Entry/SL/TP), visible TF context bands.
 * Visual-only. Cache-busted fetches. No global lifecycle strip. No GRID DOM.
 */

const TIMEFRAMES = ["M15", "M30", "H1", "H4"];
const THEME_STORAGE_KEY = "btcml-context-visual-theme";
const POLL_INTERVAL_MS = 15_000;
const DEFAULT_VISIBLE = { M15: 144, M30: 96, H1: 96, H4: null };

function parseStandaloneTf() {
  const params = new URLSearchParams(window.location.search);
  const raw = (params.get("tf") || "M15").toUpperCase();
  return TIMEFRAMES.includes(raw) ? raw : "M15";
}

const state = {
  truth: null,
  activeTf: parseStandaloneTf(),
  range: "latest500",
  charts: {},
  selectedTradeKey: null,
  pollTimer: null,
  activePaperEpochId: null,
};

const statusLine = document.getElementById("statusLine");
const statusChips = document.getElementById("statusChips");
const refreshLine = document.getElementById("refreshLine");
const sourceLine = document.getElementById("sourceLine");
const truthBanner = document.getElementById("truthBanner");
const hoverReadout = document.getElementById("hoverReadout");
const tradeDetailPanel = document.getElementById("tradeDetailPanel");
const rangeSelect = document.getElementById("rangeSelect");
const themeSelect = document.getElementById("themeSelect");
const tfChartHost = document.getElementById("tfChartHost");
const errorPanel = document.getElementById("viewerErrorPanel");
const tfNav = document.getElementById("tfNav");

function activeTimeframes() {
  return [state.activeTf];
}

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
    longZone: cssVar("--long-zone", "rgba(48, 209, 88, 0.22)"),
    shortZone: cssVar("--short-zone", "rgba(255, 69, 58, 0.20)"),
    observeZone: "rgba(100, 210, 255, 0.16)",
    connector: cssVar("--connector", "rgba(255, 214, 10, 0.7)"),
    markerStroke: cssVar("--marker-stroke", "rgba(255,255,255,0.65)"),
    tradeEntry: cssVar("--trade-entry-color", "#0a84ff"),
    tradeExit: cssVar("--trade-exit-color", "#ff9f0a"),
    tradeStop: cssVar("--trade-stop-color", "#ff453a"),
    tradeTake: cssVar("--trade-take-color", "#30d158"),
    riskFill: "rgba(255, 69, 58, 0.18)",
    riskFillSel: "rgba(255, 69, 58, 0.32)",
    rewardFill: "rgba(48, 209, 88, 0.18)",
    rewardFillSel: "rgba(48, 209, 88, 0.32)",
    muted: cssVar("--text-muted", "#6e7380"),
    text: cssVar("--text-primary", "#f5f5f7"),
    mono: cssVar("--font-mono", "ui-monospace, SF Mono, Menlo, monospace"),
    dim: "rgba(127,127,127,0.28)",
  };
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.abs(value) >= 100 ? value.toFixed(2) : value.toFixed(4);
  }
  return String(value);
}

function fmtPnl(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function parseTs(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

function tradeKey(entity) {
  if (!entity) return null;
  return entity.trade_id || entity.position_id || null;
}

function isStableTfNumber(label, tf) {
  if (!label || !tf) return false;
  return new RegExp(`^${String(tf).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}_\\d+$`).test(String(label));
}

/** Never paint hex / UUID / "M15 · e3ee3129" on the canvas. */
function publicNumber(entity, tf) {
  if (!entity) return "";
  const tfName = tf || entity.timeframe || state.activeTf;
  for (const candidate of [entity.public_number, entity.display_label]) {
    if (isStableTfNumber(candidate, tfName)) return String(candidate);
  }
  return "";
}

function fmtPrice(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Stable TF_N when payload still has legacy display_label (e.g. live v2).
 * Same order as adapter assign_tf_ordinals: entry → created_at → id.
 */
function ensureTfOrdinals(tf, tfBlock) {
  if (!tfBlock) return;
  const closed = Array.isArray(tfBlock.closed_trades) ? tfBlock.closed_trades : [];
  const opens = Array.isArray(tfBlock.open_positions) ? tfBlock.open_positions : [];
  const entities = closed.concat(opens);
  if (!entities.length) return;
  if (entities.every((e) => isStableTfNumber(e.public_number, tf))) return;
  const sorted = entities.slice().sort((a, b) => {
    const ka = [
      a.entry_timestamp || "",
      a.created_at || a.entry_timestamp || "",
      a.trade_id || a.position_id || "",
    ].join("\0");
    const kb = [
      b.entry_timestamp || "",
      b.created_at || b.entry_timestamp || "",
      b.trade_id || b.position_id || "",
    ].join("\0");
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  });
  sorted.forEach((entity, idx) => {
    const label = `${tf}_${idx + 1}`;
    entity.ordinal = idx + 1;
    entity.public_number = label;
    entity.display_label = label;
  });
}

function finitePrice(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function resolveTheme(mode) {
  if (mode === "light" || mode === "dark") return mode;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(mode) {
  const resolved = resolveTheme(mode);
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch (_e) {
    /* ignore */
  }
}

function showError(message) {
  if (!errorPanel) return;
  errorPanel.textContent = message;
  errorPanel.classList.toggle("hidden", !message);
}

async function loadJson(path) {
  const url = `${path}${path.includes("?") ? "&" : "?"}t=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function candidateTruthCandidates() {
  const params = new URLSearchParams(window.location.search);
  const override = params.get("chart_truth");
  if (override) return [override];
  // Active workspace only. Candidate recovery archives retain legacy markers and
  // must not be used as fallback once LIVE1B epoch charts are available.
  return ["./data/timeframe_chart_truth.json"];
}

async function loadChartTruth() {
  const errors = [];
  for (const path of candidateTruthCandidates()) {
    try {
      const epochHint = state.activePaperEpochId || "active";
      const url = `${path}${path.includes("?") ? "&" : "?"}epoch=${encodeURIComponent(epochHint)}&schema=v4&t=${Date.now()}`;
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${path} → ${res.status}`);
      const payload = await res.json();
      if (payload && payload.schema_version && payload.timeframes) {
        payload.__loaded_from = path;
        state.activePaperEpochId = payload.active_paper_epoch_id || null;
        // Hard replace trade layers — empty array clears previous markers.
        Object.keys(payload.timeframes || {}).forEach((tf) => {
          const block = payload.timeframes[tf] || {};
          block.closed_trades = filterActiveEpochTrades(block.closed_trades || [], payload.active_paper_epoch_id);
          block.open_positions = filterActiveEpochTrades(block.open_positions || [], payload.active_paper_epoch_id);
          payload.timeframes[tf] = block;
        });
        return payload;
      }
    } catch (err) {
      errors.push(`${path}: ${err.message || err}`);
    }
  }
  throw new Error(`timeframe_chart_truth unavailable\n${errors.join("\n")}`);
}

function filterActiveEpochTrades(rows, activeEpochId) {
  const list = Array.isArray(rows) ? rows : [];
  if (!activeEpochId) {
    // Without an active LIVE1B epoch id on the payload, still drop unmarked legacy
    // rows that lack paper_epoch_id when schema is v4+.
    return list;
  }
  return list.filter((row) => {
    if (!row || typeof row !== "object") return false;
    const eid = String(row.paper_epoch_id || "").trim();
    if (!eid) return false;
    if (eid !== String(activeEpochId)) return false;
    const status = String(row.status || row.void_status || "").toUpperCase();
    if (status === "VOID_PRE_INTRABAR_RULE_CONTRACT" || status.startsWith("VOID_")) return false;
    return true;
  });
}

function selectCandles(candles, range) {
  const rows = Array.isArray(candles) ? candles.filter((c) => c && c.timestamp && c.open != null) : [];
  if (!rows.length) return [];
  const last = rows[rows.length - 1];
  const lastTs = parseTs(last.timestamp);
  if (range === "latest100") return rows.slice(-100);
  if (range === "latest500") return rows.slice(-500);
  if (range === "latest1000") return rows.slice(-1000);
  if (range === "last7d" && lastTs != null) return rows.filter((r) => (parseTs(r.timestamp) || 0) >= lastTs - 7 * 86400);
  if (range === "last14d" && lastTs != null) return rows.filter((r) => (parseTs(r.timestamp) || 0) >= lastTs - 14 * 86400);
  return rows.slice();
}

function defaultSpan(tf, n) {
  const pref = DEFAULT_VISIBLE[tf];
  if (pref == null) return Math.max(1, n);
  return Math.max(20, Math.min(n, pref));
}

function mountStandalonePanel(tf) {
  if (!tfChartHost) return;
  tfChartHost.innerHTML = "";
  tfChartHost.dataset.tf = tf;
  const section = document.createElement("section");
  section.className = "tf-chart-panel";
  section.dataset.tf = tf;
  section.setAttribute("aria-label", `${tf} chart`);
  section.innerHTML = `
    <header class="tf-chart-header" id="header-${tf}"></header>
    <div class="tf-chart-nav">
      <button type="button" data-nav="reset" data-tf="${tf}">Reset</button>
      <button type="button" data-nav="fit" data-tf="${tf}">Fit</button>
      <button type="button" data-nav="latest" data-tf="${tf}">Latest</button>
    </div>
    <div class="tf-chart-body">
      <canvas id="chart-${tf}" class="tf-chart-canvas" data-tf="${tf}" role="img" aria-label="${tf} candlestick chart"></canvas>
      <div class="tf-chart-empty" id="empty-${tf}" hidden>SOURCE_UNAVAILABLE</div>
    </div>
  `;
  tfChartHost.appendChild(section);
}

function syncTfNav(tf) {
  if (!tfNav) return;
  tfNav.querySelectorAll("a[data-tf]").forEach((a) => {
    const active = a.getAttribute("data-tf") === tf;
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function initChartState(tf) {
  const canvas = document.getElementById(`chart-${tf}`);
  const header = document.getElementById(`header-${tf}`);
  const empty = document.getElementById(`empty-${tf}`);
  state.charts[tf] = {
    tf,
    canvas,
    ctx: canvas && canvas.getContext ? canvas.getContext("2d") : null,
    header,
    empty,
    candles: [],
    visible: [],
    visibleStart: 0,
    visibleEnd: 0,
    followLatest: true,
    userAnchored: false,
    dragging: false,
    dragStartX: 0,
    dragStartVisibleStart: 0,
    hitRegions: [],
  };
}

function resizeCanvas(canvas) {
  if (!canvas) return { width: 0, height: 0 };
  const parent = canvas.parentElement;
  const width = Math.max(80, Math.floor(parent.clientWidth || 80));
  const height = Math.max(100, Math.floor(parent.clientHeight || 100));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { width, height };
}

function applyVisibleWindow(chart) {
  const rows = chart.candles;
  if (!rows.length) {
    chart.visible = [];
    chart.visibleStart = 0;
    chart.visibleEnd = 0;
    return;
  }
  let span = Math.max(20, chart.visibleEnd - chart.visibleStart || defaultSpan(chart.tf, rows.length));
  span = Math.min(span, rows.length);
  if (chart.followLatest && !chart.userAnchored) {
    chart.visibleEnd = rows.length;
    chart.visibleStart = Math.max(0, rows.length - span);
  } else {
    const maxStart = Math.max(0, rows.length - span);
    chart.visibleStart = Math.max(0, Math.min(chart.visibleStart, maxStart));
    chart.visibleEnd = Math.min(rows.length, chart.visibleStart + span);
    if (chart.visibleEnd >= rows.length) {
      chart.followLatest = true;
      chart.userAnchored = false;
    }
  }
  chart.visible = rows.slice(chart.visibleStart, chart.visibleEnd);
}

function setDefaultViewport(chart) {
  const n = chart.candles.length;
  const span = defaultSpan(chart.tf, n);
  chart.visibleEnd = n;
  chart.visibleStart = Math.max(0, n - span);
  chart.followLatest = true;
  chart.userAnchored = false;
  applyVisibleWindow(chart);
}

function fitViewport(chart) {
  chart.visibleStart = 0;
  chart.visibleEnd = chart.candles.length;
  chart.followLatest = true;
  chart.userAnchored = false;
  applyVisibleWindow(chart);
}

function goLatest(chart) {
  const span = Math.max(20, chart.visibleEnd - chart.visibleStart || defaultSpan(chart.tf, chart.candles.length));
  chart.visibleEnd = chart.candles.length;
  chart.visibleStart = Math.max(0, chart.candles.length - span);
  chart.followLatest = true;
  chart.userAnchored = false;
  applyVisibleWindow(chart);
}

function geometry(chart, priceExtras) {
  const canvas = chart.canvas;
  const w = canvas.clientWidth || 100;
  const h = canvas.clientHeight || 100;
  const pad = { top: 18, right: 10, bottom: 36, left: 54 };
  const plotW = Math.max(10, w - pad.left - pad.right);
  const plotH = Math.max(10, h - pad.top - pad.bottom);
  const rows = chart.visible;
  let minP = Infinity;
  let maxP = -Infinity;
  rows.forEach((c) => {
    minP = Math.min(minP, c.low, c.open, c.close);
    maxP = Math.max(maxP, c.high, c.open, c.close);
  });
  (priceExtras || []).forEach((p) => {
    const n = finitePrice(p);
    if (n == null) return;
    minP = Math.min(minP, n);
    maxP = Math.max(maxP, n);
  });
  if (!Number.isFinite(minP) || !Number.isFinite(maxP) || minP === maxP) {
    minP = (minP || 0) - 1;
    maxP = (maxP || 0) + 1;
  }
  const padP = (maxP - minP) * 0.08;
  minP -= padP;
  maxP += padP;
  const n = Math.max(1, rows.length);
  return {
    pad,
    plotW,
    plotH,
    minP,
    maxP,
    xAt(i) {
      return pad.left + ((i + 0.5) / n) * plotW;
    },
    yAt(price) {
      return pad.top + ((maxP - price) / (maxP - minP)) * plotH;
    },
    indexAt(x) {
      const rel = (x - pad.left) / plotW;
      return Math.max(0, Math.min(n - 1, Math.floor(rel * n)));
    },
    inPlotY(y) {
      return y >= pad.top - 12 && y <= pad.top + plotH + 16;
    },
  };
}

function collectVisiblePriceExtras(chart, tfBlock) {
  const extras = [];
  const entities = (tfBlock.open_positions || []).concat(tfBlock.closed_trades || []);
  entities.forEach((e) => {
    if ((e.timeframe || chart.tf) !== chart.tf) return;
    extras.push(e.entry_price, e.exit_price, e.stop_price, e.take_profit_price);
  });
  return extras;
}

function timeIndex(rows, ts) {
  if (ts == null || !rows.length) return null;
  let best = null;
  let bestDist = Infinity;
  rows.forEach((c, i) => {
    const t = parseTs(c.timestamp);
    if (t == null) return;
    const dist = Math.abs(t - ts);
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  });
  return best;
}

function drawContextBands(chart, tfBlock, g) {
  const ctx = chart.ctx;
  const colors = chartColors();
  const segments = Array.isArray(tfBlock.context_segments)
    ? tfBlock.context_segments
    : Array.isArray(tfBlock.context_history)
      ? tfBlock.context_history
      : [];
  if (!segments.length || !chart.visible.length) return;
  const firstTs = parseTs(chart.visible[0].timestamp);
  const lastTs = parseTs(chart.visible[chart.visible.length - 1].timestamp);
  if (firstTs == null || lastTs == null || lastTs <= firstTs) return;
  segments.forEach((seg) => {
    if ((seg.timeframe || chart.tf) !== chart.tf) return;
    const s = parseTs(seg.start_timestamp);
    const e = parseTs(seg.end_timestamp) || lastTs;
    if (s == null || e < firstTs || s > lastTs) return;
    const i0 = timeIndex(chart.visible, Math.max(s, firstTs));
    const i1 = timeIndex(chart.visible, Math.min(e, lastTs));
    if (i0 == null || i1 == null) return;
    const x1 = g.xAt(Math.min(i0, i1)) - (g.plotW / chart.visible.length) * 0.5;
    const x2 = g.xAt(Math.max(i0, i1)) + (g.plotW / chart.visible.length) * 0.5;
    const width = Math.max(2, x2 - x1);
    const name = String(seg.directional_state || "").toUpperCase();
    let fill = colors.observeZone;
    let accent = colors.info;
    if (name.includes("LONG")) {
      fill = colors.longZone;
      accent = colors.positive;
    }
    if (name.includes("SHORT")) {
      fill = colors.shortZone;
      accent = colors.negative;
    }
    ctx.fillStyle = fill;
    ctx.fillRect(x1, g.pad.top, width, g.plotH);
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.55;
    ctx.fillRect(x1, g.pad.top, width, 3);
    ctx.globalAlpha = 1;
  });
}

function drawCandles(chart, tfBlock) {
  const ctx = chart.ctx;
  const colors = chartColors();
  if (!ctx || !chart.canvas) return;
  resizeCanvas(chart.canvas);
  const w = chart.canvas.clientWidth;
  const h = chart.canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  const rows = chart.visible;
  if (!rows.length) return;
  const g = geometry(chart, collectVisiblePriceExtras(chart, tfBlock));
  drawContextBands(chart, tfBlock, g);
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = g.pad.top + (g.plotH * i) / 3;
    ctx.beginPath();
    ctx.moveTo(g.pad.left, y);
    ctx.lineTo(g.pad.left + g.plotW, y);
    ctx.stroke();
  }
  ctx.fillStyle = colors.axis;
  ctx.font = `10px ${colors.mono}`;
  ctx.fillText(fmt(g.maxP), 4, g.pad.top + 8);
  ctx.fillText(fmt(g.minP), 4, g.pad.top + g.plotH);
  const first = rows[0];
  const last = rows[rows.length - 1];
  ctx.fillText(`${String(first.timestamp || "").slice(0, 16)}Z`, g.pad.left, h - 8);
  ctx.fillText(`${String(last.timestamp || "").slice(0, 16)}`, g.pad.left + g.plotW - 110, h - 8);
  const candleW = Math.max(1, (g.plotW / rows.length) * 0.6);
  rows.forEach((c, i) => {
    const x = g.xAt(i);
    const yHigh = g.yAt(c.high);
    const yLow = g.yAt(c.low);
    const yOpen = g.yAt(c.open);
    const yClose = g.yAt(c.close);
    const up = c.close >= c.open;
    ctx.strokeStyle = up ? colors.positive : colors.negative;
    ctx.fillStyle = up ? colors.positive : colors.negative;
    ctx.beginPath();
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, yLow);
    ctx.stroke();
    const top = Math.min(yOpen, yClose);
    const body = Math.max(1, Math.abs(yClose - yOpen));
    ctx.fillRect(x - candleW / 2, top, candleW, body);
  });
  return g;
}

function drawLongEntryMarker(ctx, x, yBelow, selected, colors) {
  const size = selected ? 7 : 5;
  ctx.fillStyle = colors.tradeEntry;
  ctx.beginPath();
  ctx.moveTo(x, yBelow - size);
  ctx.lineTo(x - size, yBelow + size);
  ctx.lineTo(x + size, yBelow + size);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = colors.markerStroke;
  ctx.stroke();
}

function drawShortEntryMarker(ctx, x, yAbove, selected, colors) {
  const size = selected ? 7 : 5;
  ctx.fillStyle = colors.negative;
  ctx.beginPath();
  ctx.moveTo(x, yAbove + size);
  ctx.lineTo(x - size, yAbove - size);
  ctx.lineTo(x + size, yAbove - size);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = colors.markerStroke;
  ctx.stroke();
}

function drawExitMarker(ctx, x, y, selected, colors) {
  const size = selected ? 6 : 4;
  ctx.strokeStyle = colors.tradeExit;
  ctx.lineWidth = selected ? 2.5 : 2;
  ctx.beginPath();
  ctx.moveTo(x - size, y - size);
  ctx.lineTo(x + size, y + size);
  ctx.moveTo(x + size, y - size);
  ctx.lineTo(x - size, y + size);
  ctx.stroke();
  ctx.lineWidth = 1;
}

function drawZoneRect(ctx, x1, x2, yA, yB, fill) {
  const top = Math.min(yA, yB);
  const height = Math.max(1, Math.abs(yB - yA));
  ctx.fillStyle = fill;
  ctx.fillRect(x1, top, Math.max(2, x2 - x1), height);
}

function drawOverlays(chart, tfBlock, g) {
  const ctx = chart.ctx;
  const colors = chartColors();
  if (!ctx || !chart.visible.length || !g) return;
  chart.hitRegions = [];
  if (tfBlock.panel_status === "TF_SOURCE_CONTAMINATION") {
    ctx.fillStyle = "rgba(255,69,58,0.12)";
    ctx.fillRect(g.pad.left, g.pad.top, g.plotW, g.plotH);
    ctx.fillStyle = colors.negative;
    ctx.font = `12px ${colors.mono}`;
    ctx.fillText("TF_SOURCE_CONTAMINATION", g.pad.left + 8, g.pad.top + 18);
    return;
  }
  const opens = filterActiveEpochTrades(tfBlock.open_positions || [], state.truth && state.truth.active_paper_epoch_id)
    .filter((p) => (p.timeframe || chart.tf) === chart.tf);
  const closed = filterActiveEpochTrades(tfBlock.closed_trades || [], state.truth && state.truth.active_paper_epoch_id)
    .filter((t) => (t.timeframe || chart.tf) === chart.tf);
  // Empty arrays clear previous hitRegions (already reset above).
  if (!opens.length && !closed.length) {
    return;
  }
  const selected = state.selectedTradeKey;

  const rows = [];
  closed.forEach((entity) => rows.push({ entity, kind: "closed" }));
  opens.forEach((entity) => rows.push({ entity, kind: "open" }));
  rows.sort((a, b) => {
    const aSel = tradeKey(a.entity) === selected ? 1 : 0;
    const bSel = tradeKey(b.entity) === selected ? 1 : 0;
    const aOpen = a.kind === "open" ? 1 : 0;
    const bOpen = b.kind === "open" ? 1 : 0;
    return aSel - bSel || aOpen - bOpen;
  });

  const labelSlots = [];
  const placeCompact = (x, yPreferred, text, color, selectedLabel) => {
    let y = yPreferred;
    let xPos = x;
    let guard = 0;
    while (
      guard < 10
      && labelSlots.some((s) => Math.abs(s.x - xPos) < 42 && Math.abs(s.y - y) < 11)
    ) {
      y += (guard % 2 === 0 ? -12 : 12);
      if (guard > 4) xPos += 8;
      guard += 1;
    }
    labelSlots.push({ x: xPos, y });
    ctx.font = `${selectedLabel ? "bold 11" : "10"}px ${colors.mono}`;
    ctx.textAlign = "center";
    const metrics = ctx.measureText(text);
    const padX = 4;
    const boxW = metrics.width + padX * 2;
    const boxH = selectedLabel ? 14 : 12;
    ctx.fillStyle = selectedLabel ? "rgba(0,0,0,0.45)" : "rgba(0,0,0,0.28)";
    ctx.fillRect(xPos - boxW / 2, y - boxH + 2, boxW, boxH);
    ctx.fillStyle = color;
    ctx.fillText(text, xPos, y);
    ctx.textAlign = "left";
    return { x: xPos, y };
  };

  rows.forEach(({ entity, kind }, rowIdx) => {
    const key = tradeKey(entity);
    const label = publicNumber(entity, chart.tf);
    if (!label) return;
    const isSel = selected && key === selected;
    const dim = selected && !isSel;
    ctx.save();
    ctx.globalAlpha = dim ? 0.2 : 1;

    const entry = finitePrice(entity.entry_fill_price ?? entity.entry_price);
    const stop = finitePrice(entity.stop_loss_price ?? entity.stop_price);
    const take = finitePrice(entity.take_profit_price);
    const exitPx = finitePrice(entity.exit_price);
    const side = String(entity.side || "LONG").toUpperCase();
    const anchorTs = parseTs(entity.bar_anchor_time || entity.entry_fill_timestamp || entity.entry_timestamp);
    const iEntry = timeIndex(chart.visible, anchorTs);
    if (iEntry == null || entry == null) {
      ctx.restore();
      return;
    }
    let iEnd = chart.visible.length - 1;
    if (kind === "closed") {
      const ix = timeIndex(chart.visible, parseTs(entity.exit_timestamp));
      if (ix != null) iEnd = ix;
    }
    const x1 = g.xAt(Math.min(iEntry, iEnd));
    const x2 = g.xAt(Math.max(iEntry, iEnd));
    const xMid = (x1 + x2) / 2;
    const yEntry = g.yAt(entry);
    const entryCandle = chart.visible[iEntry];

    if (take != null) {
      drawZoneRect(ctx, x1, x2, yEntry, g.yAt(take), isSel ? colors.rewardFillSel : colors.rewardFill);
      ctx.strokeStyle = colors.tradeTake;
      ctx.lineWidth = isSel ? 2 : 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, g.yAt(take));
      ctx.lineTo(x2, g.yAt(take));
      ctx.stroke();
      ctx.setLineDash([]);
      if (isSel || !selected) {
        ctx.fillStyle = colors.tradeTake;
        ctx.font = `9px ${colors.mono}`;
        ctx.textAlign = "left";
        ctx.fillText("Цель", x2 + 3, g.yAt(take) + 3);
      }
    }
    if (stop != null) {
      drawZoneRect(ctx, x1, x2, yEntry, g.yAt(stop), isSel ? colors.riskFillSel : colors.riskFill);
      ctx.strokeStyle = colors.tradeStop;
      ctx.lineWidth = isSel ? 2 : 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, g.yAt(stop));
      ctx.lineTo(x2, g.yAt(stop));
      ctx.stroke();
      ctx.setLineDash([]);
      if (isSel || !selected) {
        ctx.fillStyle = colors.tradeStop;
        ctx.font = `9px ${colors.mono}`;
        ctx.textAlign = "left";
        ctx.fillText("Стоп", x2 + 3, g.yAt(stop) + 3);
      }
    }

    ctx.strokeStyle = colors.tradeEntry;
    ctx.lineWidth = isSel ? 2.25 : 1.5;
    ctx.beginPath();
    ctx.moveTo(x1, yEntry);
    ctx.lineTo(x2, yEntry);
    ctx.stroke();
    ctx.lineWidth = 1;
    if (isSel || !selected) {
      ctx.fillStyle = colors.tradeEntry;
      ctx.font = `9px ${colors.mono}`;
      ctx.textAlign = "left";
      ctx.fillText("Вход", x2 + 3, yEntry + 3);
    }

    // Compact entry marker only (no text on marker)
    if (side === "SHORT") {
      drawShortEntryMarker(ctx, x1, g.yAt(entryCandle.high) - 8, isSel, colors);
      chart.hitRegions.push({ key, x: x1, y: g.yAt(entryCandle.high) - 8, entity, kind, role: "entry" });
    } else {
      drawLongEntryMarker(ctx, x1, g.yAt(entryCandle.low) + 8, isSel, colors);
      chart.hitRegions.push({ key, x: x1, y: g.yAt(entryCandle.low) + 8, entity, kind, role: "entry" });
    }

    // Single TF_N label centered on trade span, near entry line (not on candle body)
    const yLabelPreferred = yEntry - 10 - (rowIdx % 3) * 11;
    const placed = placeCompact(
      xMid,
      yLabelPreferred,
      label,
      isSel ? colors.text : colors.tradeEntry,
      isSel,
    );
    chart.hitRegions.push({ key, x: placed.x, y: placed.y, entity, kind, role: "label" });

    if (kind === "closed" && exitPx != null) {
      const yExit = g.yAt(exitPx);
      drawExitMarker(ctx, x2, yExit, isSel, colors);
      chart.hitRegions.push({ key, x: x2, y: yExit, entity, kind, role: "exit" });
    }

    const yTop = Math.min(yEntry, take != null ? g.yAt(take) : yEntry, stop != null ? g.yAt(stop) : yEntry);
    const yBot = Math.max(yEntry, take != null ? g.yAt(take) : yEntry, stop != null ? g.yAt(stop) : yEntry);
    chart.hitRegions.push({
      key,
      x: xMid,
      y: yEntry,
      entity,
      kind,
      role: "zone",
      x1,
      x2,
      yTop,
      yBot,
    });

    ctx.restore();
  });
}

function renderHeader(tf, tfBlock) {
  const chart = state.charts[tf];
  if (!chart || !chart.header) return;
  const st = tfBlock.state || {};
  const perf = tfBlock.performance || {};
  const contract = tfBlock.candle_contract || {};
  const side = st.position_side || "FLAT";
  const pstatus = st.position_status || "FLAT";
  const bar = contract.latest_confirmed_close || "—";
  const barShort = String(bar).replace(/:\d{2}Z$/, "Z");
  const segCount = (tfBlock.context_segments || tfBlock.context_history || []).length;
  chart.header.innerHTML = `
    <span class="tf-name">${tf}</span>
    <span class="tf-context">${fmt(st.directional_state)} · ${fmt(st.manager_instruction)}</span>
    <span>${side} · ${pstatus}</span>
    <span title="Historical TF context segments">${segCount} ctx</span>
    <span title="Latest confirmed bar close (UTC)">bar ${barShort}</span>
    <span>R ${fmtPnl(perf.realised_net_pnl_usd)} / U ${fmtPnl(perf.unrealised_net_pnl_usd ?? perf.unrealised_gross_pnl_usd)}</span>
  `;
}

function preserveViewportAcrossReload(chart, nextCandles) {
  const prevLen = chart.candles.length;
  const prevStart = chart.visibleStart;
  const prevEnd = chart.visibleEnd;
  const prevFollow = chart.followLatest;
  const prevAnchored = chart.userAnchored;
  const span = Math.max(20, prevEnd - prevStart || defaultSpan(chart.tf, nextCandles.length));
  chart.candles = nextCandles;
  if (!prevLen || !nextCandles.length) {
    setDefaultViewport(chart);
    return;
  }
  if (prevFollow && !prevAnchored) {
    chart.followLatest = true;
    chart.userAnchored = false;
    chart.visibleEnd = nextCandles.length;
    chart.visibleStart = Math.max(0, nextCandles.length - span);
  } else {
    chart.followLatest = false;
    chart.userAnchored = true;
    chart.visibleStart = prevStart;
    chart.visibleEnd = prevStart + span;
  }
  applyVisibleWindow(chart);
}

function renderTfChart(tf) {
  const chart = state.charts[tf];
  if (!chart) return;
  const tfBlock = (state.truth && state.truth.timeframes && state.truth.timeframes[tf]) || {};
  ensureTfOrdinals(tf, tfBlock);
  const candles = selectCandles(tfBlock.candles || [], state.range);
  if (!chart._bootstrapped) {
    chart.candles = candles;
    setDefaultViewport(chart);
    chart._bootstrapped = true;
  } else {
    preserveViewportAcrossReload(chart, candles);
  }
  renderHeader(tf, tfBlock);
  const unavailable =
    !candles.length ||
    (tfBlock.freshness && tfBlock.freshness.status === "SOURCE_UNAVAILABLE") ||
    (tfBlock.candle_contract && tfBlock.candle_contract.freshness_status === "SOURCE_UNAVAILABLE");
  if (chart.empty) chart.empty.hidden = !unavailable;
  if (unavailable) {
    if (chart.ctx && chart.canvas) {
      resizeCanvas(chart.canvas);
      chart.ctx.clearRect(0, 0, chart.canvas.clientWidth, chart.canvas.clientHeight);
    }
    return;
  }
  const g = drawCandles(chart, tfBlock);
  drawOverlays(chart, tfBlock, g);
}

function renderAll() {
  activeTimeframes().forEach(renderTfChart);
}

function updateStatus() {
  const tf = state.activeTf;
  if (statusLine) statusLine.textContent = `${tf} standalone · UTC · paper_only`;
  if (statusChips) {
    const block = (state.truth.timeframes || {})[tf] || {};
    const st = block.state || {};
    const closed = (block.closed_trades || []).length;
    const opens = (block.open_positions || []).length;
    const segs = (block.context_segments || []).length;
    statusChips.innerHTML = [
      `<span class="lifecycle-chip">${tf}:${st.directional_state || "—"}</span>`,
      `<span class="lifecycle-chip">${segs} ctx</span>`,
      `<span class="lifecycle-chip">${closed} closed / ${opens} open</span>`,
    ].join("");
  }
  if (refreshLine) refreshLine.textContent = `truth ${state.truth.generated_at || "—"}`;
  if (sourceLine) {
    sourceLine.hidden = false;
    sourceLine.textContent = state.truth.__loaded_from || "timeframe_chart_truth";
  }
  if (truthBanner) {
    truthBanner.textContent = "LIVE PAPER · standalone TF · OPS summary deferred (OPS3A)";
  }
}

function formatTradeDetail(entity, tf) {
  if (!entity) return "";
  const episode =
    entity.episode_status === "PROVEN"
      ? `episode ${entity.episode_id}`
      : "episode UNPROVEN";
  return [
    `<strong>${publicNumber(entity, tf) || "—"}</strong>`,
    `${entity.status || "—"} ${entity.side || ""}`,
    `TF ${entity.timeframe || tf}`,
    `вход ${entity.event_timestamp || entity.entry_fill_timestamp || entity.entry_timestamp || "—"} @ ${fmtPrice(entity.entry_fill_price ?? entity.entry_price)}`,
    `якорь свечи ${entity.bar_anchor_time || "—"}`,
    `qty ${fmt(entity.quantity)} BTC · notional ${fmt(entity.position_notional ?? entity.notional)}`,
    `риск ${fmt(entity.risk_amount_usd)}`,
    `контекст ${entity.context_started_at || "—"} @ ${fmtPrice(entity.context_price)}`,
    `mark ${fmtPrice(entity.mark_price)} (${entity.mark_side || "—"})`,
    `uPnL ${fmtPnl(entity.unrealized_pnl_usd ?? entity.unrealized_pnl)}`,
    `exit ${entity.exit_timestamp || "—"} @ ${fmtPrice(entity.exit_price)}`,
    `PnL ${fmtPnl(entity.net_realised_pnl_usd)}`,
    `Стоп ${fmtPrice(entity.stop_loss_price ?? entity.stop_price)} Цель ${fmtPrice(entity.take_profit_price)}`,
    `trade_id ${entity.trade_id || "—"}`,
    `position_id ${entity.position_id || "—"}`,
    episode,
  ].join(" · ");
}

function selectTrade(entity, tf) {
  state.selectedTradeKey = tradeKey(entity);
  if (tradeDetailPanel) {
    if (!entity) {
      tradeDetailPanel.classList.add("hidden");
      tradeDetailPanel.innerHTML = "";
    } else {
      tradeDetailPanel.classList.remove("hidden");
      tradeDetailPanel.innerHTML = formatTradeDetail(entity, tf);
    }
  }
  renderAll();
}

function hitTest(chart, x, y) {
  let best = null;
  let bestDist = 18;
  (chart.hitRegions || []).forEach((hit) => {
    if (hit.role === "zone" && hit.x1 != null && hit.x2 != null && hit.yTop != null && hit.yBot != null) {
      if (x >= hit.x1 && x <= hit.x2 && y >= hit.yTop && y <= hit.yBot) {
        const d = Math.abs(y - hit.y);
        if (d < bestDist + 40) {
          bestDist = Math.min(bestDist, d);
          best = hit;
        }
        return;
      }
    }
    const d = Math.hypot(hit.x - x, hit.y - y);
    if (d < bestDist) {
      bestDist = d;
      best = hit;
    }
  });
  return best;
}

function bindChartInteractions(tf) {
  const chart = state.charts[tf];
  const canvas = chart && chart.canvas;
  if (!canvas) return;

  canvas.addEventListener("pointerdown", (event) => {
    chart.dragging = true;
    chart._didDrag = false;
    chart.dragStartX = event.clientX;
    chart.dragStartVisibleStart = chart.visibleStart;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (chart.dragging) {
      const dx = event.clientX - chart.dragStartX;
      if (Math.abs(dx) > 3) chart._didDrag = true;
      const g = geometry(chart);
      const shift = Math.round((-dx / Math.max(1, g.plotW)) * Math.max(1, chart.visible.length));
      const span = Math.max(20, chart.visibleEnd - chart.visibleStart);
      chart.visibleStart = chart.dragStartVisibleStart + shift;
      chart.visibleEnd = chart.visibleStart + span;
      chart.followLatest = chart.visibleEnd >= chart.candles.length;
      chart.userAnchored = !chart.followLatest;
      applyVisibleWindow(chart);
      renderTfChart(tf);
      return;
    }
    if (!chart.visible.length) return;
    const g = geometry(chart);
    const idx = g.indexAt(x);
    const candle = chart.visible[idx];
    const hit = hitTest(chart, x, y);
    if (hoverReadout) {
      if (hit) {
        hoverReadout.classList.remove("hidden");
        hoverReadout.textContent = formatTradeDetail(hit.entity, tf).replace(/<[^>]+>/g, "");
      } else if (candle) {
        hoverReadout.classList.remove("hidden");
        hoverReadout.textContent = `${tf} ${candle.timestamp} O:${fmt(candle.open)} H:${fmt(candle.high)} L:${fmt(candle.low)} C:${fmt(candle.close)}`;
      }
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    const wasDrag = chart._didDrag;
    chart.dragging = false;
    if (wasDrag) return;
    const rect = canvas.getBoundingClientRect();
    const hit = hitTest(chart, event.clientX - rect.left, event.clientY - rect.top);
    if (hit) selectTrade(hit.entity, tf);
    else if (state.selectedTradeKey) selectTrade(null, tf);
  });
  canvas.addEventListener("pointerleave", () => {
    chart.dragging = false;
    if (hoverReadout) hoverReadout.classList.add("hidden");
  });
  canvas.addEventListener("dblclick", () => {
    setDefaultViewport(chart);
    renderTfChart(tf);
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY) && Math.abs(event.deltaX) > 0) {
      const span = Math.max(20, chart.visibleEnd - chart.visibleStart);
      const shift = Math.round(event.deltaX / 20);
      chart.visibleStart += shift;
      chart.visibleEnd = chart.visibleStart + span;
      chart.followLatest = chart.visibleEnd >= chart.candles.length;
      chart.userAnchored = !chart.followLatest;
      applyVisibleWindow(chart);
      renderTfChart(tf);
      return;
    }
    const delta = event.deltaY > 0 ? 1.18 : 1 / 1.18;
    const len = Math.max(20, Math.round((chart.visibleEnd - chart.visibleStart) * delta));
    const rect = canvas.getBoundingClientRect();
    const g = geometry(chart);
    const idx = g.indexAt(event.clientX - rect.left);
    const center = chart.visibleStart + idx;
    chart.visibleStart = Math.max(0, center - Math.floor(len / 2));
    chart.visibleEnd = chart.visibleStart + len;
    chart.followLatest = chart.visibleEnd >= chart.candles.length;
    chart.userAnchored = !chart.followLatest;
    applyVisibleWindow(chart);
    renderTfChart(tf);
  }, { passive: false });
}

function resetAllViewports() {
  activeTimeframes().forEach((tf) => setDefaultViewport(state.charts[tf]));
  renderAll();
}

function fitAllViewports() {
  activeTimeframes().forEach((tf) => fitViewport(state.charts[tf]));
  renderAll();
}

function latestAllViewports() {
  activeTimeframes().forEach((tf) => goLatest(state.charts[tf]));
  renderAll();
}

async function refresh() {
  try {
    state.truth = await loadChartTruth();
    showError("");
    updateStatus();
    renderAll();
  } catch (err) {
    showError(String(err.message || err));
  }
}

function boot() {
  const tf = state.activeTf;
  mountStandalonePanel(tf);
  syncTfNav(tf);
  initChartState(tf);
  bindChartInteractions(tf);

  if (rangeSelect) {
    rangeSelect.addEventListener("change", () => {
      state.range = rangeSelect.value;
      activeTimeframes().forEach((t) => {
        const chart = state.charts[t];
        if (chart) chart._bootstrapped = false;
      });
      renderAll();
    });
  }
  if (themeSelect) {
    let theme = "system";
    try {
      theme = localStorage.getItem(THEME_STORAGE_KEY) || "system";
    } catch (_e) {
      theme = "system";
    }
    themeSelect.value = theme;
    applyTheme(theme);
    themeSelect.addEventListener("change", () => {
      applyTheme(themeSelect.value);
      renderAll();
    });
  }

  document.getElementById("btnResetView")?.addEventListener("click", resetAllViewports);
  document.getElementById("btnFitView")?.addEventListener("click", fitAllViewports);
  document.getElementById("btnGoLatest")?.addEventListener("click", latestAllViewports);
  document.querySelectorAll(".tf-chart-nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const navTf = btn.getAttribute("data-tf");
      const nav = btn.getAttribute("data-nav");
      const chart = state.charts[navTf];
      if (!chart) return;
      if (nav === "reset") setDefaultViewport(chart);
      if (nav === "fit") fitViewport(chart);
      if (nav === "latest") goLatest(chart);
      renderTfChart(navTf);
    });
  });

  window.addEventListener("resize", () => renderAll());
  refresh();
  state.pollTimer = window.setInterval(refresh, POLL_INTERVAL_MS);
}

boot();

window.__VIS3C__ = {
  TIMEFRAMES,
  DEFAULT_VISIBLE,
  getState: () => state,
  activeTf: () => state.activeTf,
  activeTimeframes,
  parseStandaloneTf,
  mountStandalonePanel,
  setDefaultViewport,
  fitViewport,
  goLatest,
  applyVisibleWindow,
  preserveViewportAcrossReload,
  publicNumber,
  isStableTfNumber,
  ensureTfOrdinals,
  fmtPrice,
  hasGlobalStrip: () => Boolean(document.querySelector("[data-global-lifecycle-strip]")),
  hasPnlPanel: () => Boolean(document.getElementById("paperPnlBlock") || document.getElementById("paperPnlPanel")),
  hasMetricsPanel: () => Boolean(document.getElementById("modelMetricsBlock") || document.getElementById("modelMetricsPanel")),
  chartCanvases: () => activeTimeframes().map((tf) => document.getElementById(`chart-${tf}`)),
  chartPanelsInDom: () => Array.from(document.querySelectorAll(".tf-chart-panel")).map((el) => el.getAttribute("data-tf")),
  foreignChartsInDom: () => {
    const active = state.activeTf;
    return Array.from(document.querySelectorAll(".tf-chart-panel, canvas.tf-chart-canvas"))
      .map((el) => el.getAttribute("data-tf"))
      .filter((t) => t && t !== active);
  },
};

// Back-compat read-only hooks used by older audits
window.__VIS3A__ = window.__VIS3C__;
window.__VIS2B__ = window.__VIS3C__;
