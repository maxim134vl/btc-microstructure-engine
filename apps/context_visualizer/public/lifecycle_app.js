/**
 * VIS3C Standalone TF charts: one chart per ?tf= URL, historical context bands,
 * TF-isolated trades, TradingView-style markers with stable TF_N numbers.
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
    longZone: cssVar("--long-zone", "rgba(48, 209, 88, 0.14)"),
    shortZone: cssVar("--short-zone", "rgba(255, 69, 58, 0.14)"),
    observeZone: "rgba(100, 210, 255, 0.08)",
    connector: cssVar("--connector", "rgba(255, 214, 10, 0.7)"),
    markerStroke: cssVar("--marker-stroke", "rgba(255,255,255,0.65)"),
    tradeEntry: cssVar("--trade-entry-color", "#0a84ff"),
    tradeExit: cssVar("--trade-exit-color", "#ff9f0a"),
    tradeStop: cssVar("--trade-stop-color", "#ff453a"),
    tradeTake: cssVar("--trade-take-color", "#30d158"),
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

function publicNumber(entity) {
  if (!entity) return "";
  return entity.public_number || entity.display_label || "";
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
  return [
    "./data/timeframe_chart_truth.json",
    "/data/candidate/architecture_recovery/vis3c_standalone_tf_charts/timeframe_chart_truth.json",
  ];
}

async function loadChartTruth() {
  const errors = [];
  for (const path of candidateTruthCandidates()) {
    try {
      const payload = await loadJson(path);
      if (payload && payload.schema_version && payload.timeframes) {
        payload.__loaded_from = path;
        return payload;
      }
    } catch (err) {
      errors.push(`${path}: ${err.message || err}`);
    }
  }
  throw new Error(`timeframe_chart_truth unavailable\n${errors.join("\n")}`);
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

function geometry(chart) {
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
    const name = String(seg.directional_state || "").toUpperCase();
    let fill = colors.observeZone;
    if (name.includes("LONG")) fill = colors.longZone;
    if (name.includes("SHORT")) fill = colors.shortZone;
    ctx.fillStyle = fill;
    ctx.fillRect(x1, g.pad.top, Math.max(2, x2 - x1), g.plotH);
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
  const g = geometry(chart);
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

/** TradingView-like LONG entry: arrow below candle low. */
function drawLongEntryMarker(ctx, x, yBelow, label, selected, colors) {
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
  ctx.fillStyle = selected ? colors.text : colors.tradeEntry;
  ctx.font = `${selected ? 11 : 10}px ${colors.mono}`;
  ctx.textAlign = "center";
  ctx.fillText(`▲ ${label}`, x, yBelow + size + 12);
  ctx.textAlign = "left";
}

/** TradingView-like SHORT entry: arrow above candle high. */
function drawShortEntryMarker(ctx, x, yAbove, label, selected, colors) {
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
  ctx.fillStyle = selected ? colors.text : colors.negative;
  ctx.font = `${selected ? 11 : 10}px ${colors.mono}`;
  ctx.textAlign = "center";
  ctx.fillText(`▼ ${label}`, x, yAbove - size - 4);
  ctx.textAlign = "left";
}

function drawExitMarker(ctx, x, y, label, selected, colors) {
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
  ctx.fillStyle = selected ? colors.text : colors.tradeExit;
  ctx.font = `${selected ? 11 : 10}px ${colors.mono}`;
  ctx.textAlign = "center";
  ctx.fillText(`× ${label}`, x, y - size - 4);
  ctx.textAlign = "left";
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
  const opens = (tfBlock.open_positions || []).filter((p) => (p.timeframe || chart.tf) === chart.tf);
  const closed = (tfBlock.closed_trades || []).filter((t) => (t.timeframe || chart.tf) === chart.tf);
  const selected = state.selectedTradeKey;
  const offscreen = { tpAbove: null, slBelow: null, tpBelow: null, slAbove: null };

  const drawOne = (entity, kind) => {
    const key = tradeKey(entity);
    const label = publicNumber(entity);
    if (!label || /[0-9a-f]{8}-[0-9a-f-]{20,}/i.test(label)) {
      // Refuse to paint raw long IDs on canvas.
    }
    const isSel = selected && key === selected;
    const dim = selected && !isSel;
    const alpha = dim ? 0.22 : 1;
    ctx.save();
    ctx.globalAlpha = alpha;
    const iEntry = timeIndex(chart.visible, parseTs(entity.entry_timestamp));
    const iExit = kind === "closed" ? timeIndex(chart.visible, parseTs(entity.exit_timestamp)) : null;
    const x1 = iEntry == null ? null : g.xAt(iEntry);
    const x2 = iExit == null ? null : g.xAt(iExit);
    const tipX = g.xAt(chart.visible.length - 1);
    const side = String(entity.side || "LONG").toUpperCase();
    const entryCandle = iEntry == null ? null : chart.visible[iEntry];

    if (kind === "closed" && x1 != null && x2 != null && entity.entry_price != null && entity.exit_price != null) {
      ctx.strokeStyle = isSel ? colors.connector : colors.dim;
      ctx.lineWidth = isSel ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(x1, g.yAt(entity.entry_price));
      ctx.lineTo(x2, g.yAt(entity.exit_price));
      ctx.stroke();
      ctx.lineWidth = 1;
    }

    if (x1 != null && entryCandle && label) {
      if (side === "SHORT") {
        const y = g.yAt(entryCandle.high) - 10;
        drawShortEntryMarker(ctx, x1, y, label, isSel, colors);
        chart.hitRegions.push({ key, x: x1, y, entity, kind, role: "entry" });
      } else {
        const y = g.yAt(entryCandle.low) + 10;
        drawLongEntryMarker(ctx, x1, y, label, isSel, colors);
        chart.hitRegions.push({ key, x: x1, y, entity, kind, role: "entry" });
      }
    }

    if (kind === "closed" && x2 != null && entity.exit_price != null && label) {
      const y = g.yAt(entity.exit_price);
      if (g.inPlotY(y)) {
        drawExitMarker(ctx, x2, y, label, isSel, colors);
        chart.hitRegions.push({ key, x: x2, y, entity, kind, role: "exit" });
      }
    }

    if (kind === "open" && x1 != null && entity.entry_price != null) {
      const yEntry = g.yAt(entity.entry_price);
      ctx.strokeStyle = colors.tradeEntry;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, yEntry);
      ctx.lineTo(tipX, yEntry);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = colors.text;
      ctx.font = `10px ${colors.mono}`;
      if (isSel || !selected) ctx.fillText("OPEN", tipX - 34, yEntry - 6);

      if (entity.stop_price != null) {
        const y = g.yAt(entity.stop_price);
        if (g.inPlotY(y)) {
          ctx.strokeStyle = colors.tradeStop;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(x1, y);
          ctx.lineTo(tipX, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = colors.tradeStop;
          ctx.fillText("SL", tipX - 18, y - 4);
        } else if (entity.stop_price < g.minP) {
          offscreen.slBelow = entity.stop_price;
        } else if (entity.stop_price > g.maxP) {
          offscreen.slAbove = entity.stop_price;
        }
      }
      if (entity.take_profit_price != null) {
        const y = g.yAt(entity.take_profit_price);
        if (g.inPlotY(y)) {
          ctx.strokeStyle = colors.tradeTake;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(x1, y);
          ctx.lineTo(tipX, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = colors.tradeTake;
          ctx.fillText("TP", tipX - 18, y - 4);
        } else if (entity.take_profit_price > g.maxP) {
          offscreen.tpAbove = entity.take_profit_price;
        } else if (entity.take_profit_price < g.minP) {
          offscreen.tpBelow = entity.take_profit_price;
        }
      }
    }
    ctx.restore();
  };

  closed.forEach((t) => drawOne(t, "closed"));
  opens.forEach((p) => drawOne(p, "open"));

  ctx.font = `11px ${colors.mono}`;
  if (offscreen.tpAbove != null) {
    ctx.fillStyle = colors.tradeTake;
    ctx.fillText(`TP ↑ ${fmt(offscreen.tpAbove)}`, g.pad.left + 6, g.pad.top + 12);
  }
  if (offscreen.slAbove != null) {
    ctx.fillStyle = colors.tradeStop;
    ctx.fillText(`SL ↑ ${fmt(offscreen.slAbove)}`, g.pad.left + 6, g.pad.top + 26);
  }
  if (offscreen.slBelow != null) {
    ctx.fillStyle = colors.tradeStop;
    ctx.fillText(`SL ↓ ${fmt(offscreen.slBelow)}`, g.pad.left + 6, g.pad.top + g.plotH - 4);
  }
  if (offscreen.tpBelow != null) {
    ctx.fillStyle = colors.tradeTake;
    ctx.fillText(`TP ↓ ${fmt(offscreen.tpBelow)}`, g.pad.left + 6, g.pad.top + g.plotH - 18);
  }
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
    `<strong>${publicNumber(entity) || "—"}</strong>`,
    `${entity.status || "—"} ${entity.side || ""}`,
    `TF ${entity.timeframe || tf}`,
    `entry ${entity.entry_timestamp || "—"} @ ${fmt(entity.entry_price)}`,
    `exit ${entity.exit_timestamp || "—"} @ ${fmt(entity.exit_price)}`,
    `PnL ${fmtPnl(entity.net_realised_pnl_usd)}`,
    `fees ${fmt(entity.fees_usd)} slippage ${fmt(entity.slippage_usd)}`,
    `SL ${fmt(entity.stop_price)} TP ${fmt(entity.take_profit_price)}`,
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
  let bestDist = 16;
  (chart.hitRegions || []).forEach((hit) => {
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
