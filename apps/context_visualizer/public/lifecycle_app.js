/**
 * VIS2B Live View: four isolated TF charts + singular global lifecycle strip.
 * Visual-only. No trading logic. Cache-busted fetches.
 * Primary identity = trade_id / position_id. CTX is never a trade id.
 */

const TF_STORAGE_KEY = "btcml-context-visual-chart-mode";
const VALID_MODES = ["GRID", "M15", "M30", "H1", "H4"];
const TIMEFRAMES = ["M15", "M30", "H1", "H4"];
const THEME_STORAGE_KEY = "btcml-context-visual-theme";
const POLL_INTERVAL_MS = 15_000;

const state = {
  truth: null,
  mode: "GRID",
  range: "latest500",
  charts: {},
  pollTimer: null,
};

const statusLine = document.getElementById("statusLine");
const statusChips = document.getElementById("statusChips");
const refreshLine = document.getElementById("refreshLine");
const sourceLine = document.getElementById("sourceLine");
const truthBanner = document.getElementById("truthBanner");
const hoverReadout = document.getElementById("hoverReadout");
const rangeSelect = document.getElementById("rangeSelect");
const timeframeSelect = document.getElementById("timeframeSelect");
const themeSelect = document.getElementById("themeSelect");
const tfChartGrid = document.getElementById("tfChartGrid");
const globalCanvas = document.getElementById("globalLifecycleCanvas");
const globalCtx = globalCanvas && globalCanvas.getContext ? globalCanvas.getContext("2d") : null;
const errorPanel = document.getElementById("viewerErrorPanel");

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
    shortZone: cssVar("--short-zone", "rgba(255, 69, 58, 0.12)"),
    observeZone: "rgba(100, 210, 255, 0.08)",
    connector: cssVar("--connector", "rgba(255, 214, 10, 0.55)"),
    markerStroke: cssVar("--marker-stroke", "rgba(255,255,255,0.65)"),
    tradeEntry: cssVar("--trade-entry-color", "#0a84ff"),
    tradeExit: cssVar("--trade-exit-color", "#ff9f0a"),
    tradeStop: cssVar("--trade-stop-color", "#ff453a"),
    tradeTake: cssVar("--trade-take-color", "#30d158"),
    muted: cssVar("--text-muted", "#6e7380"),
    text: cssVar("--text-primary", "#f5f5f7"),
    mono: cssVar("--font-mono", "ui-monospace, SF Mono, Menlo, monospace"),
  };
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.abs(value) >= 1000 ? value.toFixed(2) : value.toFixed(4);
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
    "/data/candidate/architecture_recovery/vis2b_four_native_timeframe_charts/candidate/timeframe_chart_truth.json",
    "../../data/candidate/architecture_recovery/vis2b_four_native_timeframe_charts/candidate/timeframe_chart_truth.json",
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
    dragging: false,
    dragStartX: 0,
    dragStartVisibleStart: 0,
    pointer: null,
  };
}

function resizeCanvas(canvas) {
  if (!canvas) return;
  const parent = canvas.parentElement;
  const width = Math.max(120, Math.floor(parent.clientWidth || 120));
  const height = Math.max(140, Math.floor(parent.clientHeight || 140));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function applyVisibleWindow(chart) {
  const rows = chart.candles;
  if (!rows.length) {
    chart.visible = [];
    chart.visibleStart = 0;
    chart.visibleEnd = 0;
    return;
  }
  const maxStart = Math.max(0, rows.length - 20);
  chart.visibleStart = Math.max(0, Math.min(chart.visibleStart, maxStart));
  const span = Math.min(rows.length, Math.max(20, chart.visibleEnd - chart.visibleStart || Math.min(120, rows.length)));
  chart.visibleEnd = Math.min(rows.length, chart.visibleStart + span);
  if (chart.visibleEnd <= chart.visibleStart) chart.visibleEnd = Math.min(rows.length, chart.visibleStart + 20);
  chart.visible = rows.slice(chart.visibleStart, chart.visibleEnd);
}

function geometry(chart) {
  const canvas = chart.canvas;
  const w = canvas.clientWidth || 100;
  const h = canvas.clientHeight || 100;
  const pad = { top: 12, right: 12, bottom: 22, left: 52 };
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
  const padP = (maxP - minP) * 0.06;
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
  };
}

function drawCandles(chart) {
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

function drawOverlays(chart, tfBlock) {
  const ctx = chart.ctx;
  const colors = chartColors();
  if (!ctx || !chart.visible.length) return;
  const g = geometry(chart);
  const opens = tfBlock.open_positions || [];
  const closed = tfBlock.closed_trades || [];
  const tipTs = parseTs(chart.visible[chart.visible.length - 1].timestamp);

  closed.forEach((trade) => {
    if ((trade.timeframe || chart.tf) !== chart.tf) return;
    const iEntry = timeIndex(chart.visible, parseTs(trade.entry_timestamp));
    const iExit = timeIndex(chart.visible, parseTs(trade.exit_timestamp));
    if (iEntry == null && iExit == null) return;
    const x1 = iEntry == null ? null : g.xAt(iEntry);
    const x2 = iExit == null ? null : g.xAt(iExit);
    if (x1 != null && trade.entry_price != null) {
      const y = g.yAt(trade.entry_price);
      ctx.fillStyle = colors.tradeEntry;
      ctx.beginPath();
      ctx.arc(x1, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = colors.markerStroke;
      ctx.stroke();
    }
    if (x2 != null && trade.exit_price != null) {
      const y = g.yAt(trade.exit_price);
      ctx.fillStyle = colors.tradeExit;
      ctx.beginPath();
      ctx.arc(x2, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = colors.markerStroke;
      ctx.stroke();
    }
    if (x1 != null && x2 != null && trade.entry_price != null && trade.exit_price != null) {
      ctx.strokeStyle = colors.connector;
      ctx.beginPath();
      ctx.moveTo(x1, g.yAt(trade.entry_price));
      ctx.lineTo(x2, g.yAt(trade.exit_price));
      ctx.stroke();
    }
    const label = trade.display_label || trade.trade_id || "trade";
    const lx = x2 != null ? x2 : x1;
    const ly = trade.exit_price != null ? g.yAt(trade.exit_price) : g.yAt(trade.entry_price);
    if (lx != null && ly != null) {
      ctx.fillStyle = colors.text;
      ctx.font = `10px ${colors.mono}`;
      ctx.fillText(label, lx + 6, ly - 6);
    }
  });

  opens.forEach((pos) => {
    if ((pos.timeframe || chart.tf) !== chart.tf) return;
    const iEntry = timeIndex(chart.visible, parseTs(pos.entry_timestamp));
    if (iEntry == null || pos.entry_price == null) return;
    const x1 = g.xAt(iEntry);
    const x2 = g.xAt(chart.visible.length - 1);
    const yEntry = g.yAt(pos.entry_price);
    ctx.strokeStyle = colors.tradeEntry;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(x1, yEntry);
    ctx.lineTo(x2, yEntry);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = colors.tradeEntry;
    ctx.beginPath();
    ctx.arc(x1, yEntry, 4, 0, Math.PI * 2);
    ctx.fill();
    if (pos.stop_price != null) {
      const y = g.yAt(pos.stop_price);
      ctx.strokeStyle = colors.tradeStop;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, y);
      ctx.lineTo(x2, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (pos.take_profit_price != null) {
      const y = g.yAt(pos.take_profit_price);
      ctx.strokeStyle = colors.tradeTake;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x1, y);
      ctx.lineTo(x2, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    const label = pos.display_label || pos.position_id || "position";
    ctx.fillStyle = colors.text;
    ctx.font = `10px ${colors.mono}`;
    ctx.fillText(label, x1 + 6, yEntry - 6);
    void tipTs;
  });
}

function renderHeader(tf, tfBlock) {
  const chart = state.charts[tf];
  if (!chart || !chart.header) return;
  const st = tfBlock.state || {};
  const perf = tfBlock.performance || {};
  const contract = tfBlock.candle_contract || {};
  const openCount = (tfBlock.open_positions || []).length;
  const side = st.position_side || "—";
  const pstatus = st.position_status || "—";
  chart.header.innerHTML = `
    <span class="tf-name">${tf}</span>
    <span>bar ${fmt(contract.latest_confirmed_close)}</span>
    <span>${fmt(st.availability_status)}</span>
    <span>${fmt(st.directional_state)} / ${fmt(st.manager_instruction)}</span>
    <span>${side} · ${pstatus} · open ${openCount}</span>
    <span>R ${fmtPnl(perf.realised_net_pnl_usd)} / U ${fmtPnl(perf.unrealised_net_pnl_usd ?? perf.unrealised_gross_pnl_usd)}</span>
  `;
}

function renderTfChart(tf) {
  const chart = state.charts[tf];
  const tfBlock = (state.truth && state.truth.timeframes && state.truth.timeframes[tf]) || {};
  const candles = selectCandles(tfBlock.candles || [], state.range);
  chart.candles = candles;
  if (!chart.visibleEnd || chart.visibleEnd > candles.length) {
    chart.visibleStart = Math.max(0, candles.length - Math.min(120, candles.length || 0));
    chart.visibleEnd = candles.length;
  }
  applyVisibleWindow(chart);
  renderHeader(tf, tfBlock);
  const unavailable = !candles.length || (tfBlock.freshness && tfBlock.freshness.status === "SOURCE_UNAVAILABLE");
  if (chart.empty) chart.empty.hidden = !unavailable;
  if (unavailable) {
    if (chart.ctx && chart.canvas) {
      resizeCanvas(chart.canvas);
      chart.ctx.clearRect(0, 0, chart.canvas.clientWidth, chart.canvas.clientHeight);
    }
    return;
  }
  drawCandles(chart);
  drawOverlays(chart, tfBlock);
}

function renderGlobalStrip() {
  if (!globalCtx || !globalCanvas) return;
  const parent = globalCanvas.parentElement;
  const width = Math.max(200, Math.floor(parent.clientWidth || 200));
  const height = 44;
  const dpr = window.devicePixelRatio || 1;
  globalCanvas.width = Math.floor(width * dpr);
  globalCanvas.height = Math.floor(height * dpr);
  globalCanvas.style.width = `${width}px`;
  globalCanvas.style.height = `${height}px`;
  globalCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  globalCtx.clearRect(0, 0, width, height);
  const colors = chartColors();
  const life = (state.truth && state.truth.global_lifecycle) || {};
  const episodes = Array.isArray(life.episodes) ? life.episodes : [];
  const windowStart = parseTs(state.truth && state.truth.window_start);
  const windowEnd = parseTs(state.truth && state.truth.window_end);
  if (!episodes.length || windowStart == null || windowEnd == null || windowEnd <= windowStart) {
    globalCtx.fillStyle = colors.muted;
    globalCtx.font = `11px ${colors.mono}`;
    globalCtx.fillText("Global lifecycle unavailable", 8, 26);
    return;
  }
  const span = windowEnd - windowStart;
  episodes.forEach((ep) => {
    const start = parseTs(ep.start_timestamp);
    const end = parseTs(ep.end_timestamp) || windowEnd;
    if (start == null) return;
    const x1 = ((Math.max(start, windowStart) - windowStart) / span) * width;
    const x2 = ((Math.min(end, windowEnd) - windowStart) / span) * width;
    const stateName = String(ep.state || "").toUpperCase();
    let fill = colors.observeZone;
    if (stateName.includes("LONG")) fill = colors.longZone;
    if (stateName.includes("SHORT")) fill = colors.shortZone;
    globalCtx.fillStyle = fill;
    globalCtx.fillRect(x1, 8, Math.max(2, x2 - x1), 20);
    if (ep.active) {
      globalCtx.strokeStyle = colors.info;
      globalCtx.lineWidth = 2;
      globalCtx.strokeRect(x1, 8, Math.max(2, x2 - x1), 20);
    }
  });
  const active = life.active_episode;
  globalCtx.fillStyle = colors.text;
  globalCtx.font = `11px ${colors.mono}`;
  const label = active
    ? `ACTIVE ${active.episode_key || active.episode_id || "—"} · ${active.state || "—"}`
    : "No active episode";
  globalCtx.fillText(label, 8, 40);
}

function renderAll() {
  TIMEFRAMES.forEach(renderTfChart);
  renderGlobalStrip();
}

function updateStatus() {
  const life = (state.truth && state.truth.global_lifecycle) || {};
  const active = life.active_episode || {};
  if (statusLine) {
    statusLine.textContent = `Global ${active.state || "—"} · episode ${active.episode_key || active.episode_id || "—"}`;
  }
  if (statusChips) {
    statusChips.innerHTML = TIMEFRAMES.map((tf) => {
      const block = (state.truth.timeframes || {})[tf] || {};
      const st = block.state || {};
      return `<span class="lifecycle-chip">${tf}:${st.availability_status || "—"}</span>`;
    }).join("");
  }
  if (refreshLine) {
    refreshLine.textContent = `truth ${state.truth.generated_at || "—"}`;
  }
  if (sourceLine) {
    sourceLine.hidden = false;
    sourceLine.textContent = state.truth.__loaded_from || "timeframe_chart_truth";
  }
  if (truthBanner) {
    truthBanner.textContent = "Trading runtime: LIVE PAPER · isolated TF charts";
  }
}

function bindChartInteractions(tf) {
  const chart = state.charts[tf];
  const canvas = chart.canvas;
  if (!canvas) return;

  canvas.addEventListener("pointerdown", (event) => {
    chart.dragging = true;
    chart.dragStartX = event.clientX;
    chart.dragStartVisibleStart = chart.visibleStart;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    if (chart.dragging) {
      const g = geometry(chart);
      const dx = event.clientX - chart.dragStartX;
      const shift = Math.round((-dx / Math.max(1, g.plotW)) * Math.max(1, chart.visible.length));
      chart.visibleStart = chart.dragStartVisibleStart + shift;
      applyVisibleWindow(chart);
      renderTfChart(tf);
      return;
    }
    if (!chart.visible.length) return;
    const g = geometry(chart);
    const idx = g.indexAt(x);
    const candle = chart.visible[idx];
    const tfBlock = (state.truth.timeframes || {})[tf] || {};
    const hits = [];
    (tfBlock.closed_trades || []).forEach((t) => {
      if (t.trade_id) hits.push(t);
    });
    (tfBlock.open_positions || []).forEach((p) => {
      if (p.position_id) hits.push(p);
    });
    const near = hits.find((h) => {
      const ts = parseTs(h.entry_timestamp || h.exit_timestamp);
      const i = timeIndex(chart.visible, ts);
      return i != null && Math.abs(i - idx) <= 1;
    });
    if (hoverReadout) {
      if (near) {
        hoverReadout.classList.remove("hidden");
        hoverReadout.textContent = [
          near.display_label || near.trade_id || near.position_id,
          `tf=${near.timeframe || tf}`,
          `id=${near.trade_id || near.position_id || "—"}`,
          `entry=${near.entry_timestamp || "—"} @ ${fmt(near.entry_price)}`,
          `exit=${near.exit_timestamp || "—"} @ ${fmt(near.exit_price)}`,
          `episode=${near.episode_status === "PROVEN" ? near.episode_id : "—"}`,
          `stop=${fmt(near.stop_price)} take=${fmt(near.take_profit_price)}`,
          near.net_realised_pnl_usd != null ? `pnl=${fmtPnl(near.net_realised_pnl_usd)}` : null,
        ].filter(Boolean).join(" · ");
      } else if (candle) {
        hoverReadout.classList.remove("hidden");
        hoverReadout.textContent = `${tf} ${candle.timestamp} O:${fmt(candle.open)} H:${fmt(candle.high)} L:${fmt(candle.low)} C:${fmt(candle.close)}`;
      }
    }
  });
  canvas.addEventListener("pointerup", () => {
    chart.dragging = false;
  });
  canvas.addEventListener("pointerleave", () => {
    chart.dragging = false;
    if (hoverReadout) hoverReadout.classList.add("hidden");
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const len = Math.max(20, Math.round((chart.visibleEnd - chart.visibleStart) * delta));
    const center = Math.floor((chart.visibleStart + chart.visibleEnd) / 2);
    chart.visibleStart = Math.max(0, center - Math.floor(len / 2));
    chart.visibleEnd = chart.visibleStart + len;
    applyVisibleWindow(chart);
    renderTfChart(tf);
  }, { passive: false });
}

function setMode(mode) {
  const next = VALID_MODES.includes(mode) ? mode : "GRID";
  state.mode = next;
  if (tfChartGrid) tfChartGrid.dataset.mode = next;
  if (timeframeSelect) timeframeSelect.value = next;
  try {
    localStorage.setItem(TF_STORAGE_KEY, next);
  } catch (_e) {
    /* ignore */
  }
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
  TIMEFRAMES.forEach(initChartState);
  TIMEFRAMES.forEach(bindChartInteractions);

  let savedMode = "GRID";
  try {
    savedMode = localStorage.getItem(TF_STORAGE_KEY) || "GRID";
  } catch (_e) {
    savedMode = "GRID";
  }
  if (savedMode === "ALL") savedMode = "GRID";
  setMode(savedMode);

  if (rangeSelect) {
    rangeSelect.addEventListener("change", () => {
      state.range = rangeSelect.value;
      TIMEFRAMES.forEach((tf) => {
        const chart = state.charts[tf];
        chart.visibleStart = 0;
        chart.visibleEnd = 0;
      });
      renderAll();
    });
  }
  if (timeframeSelect) {
    timeframeSelect.addEventListener("change", () => setMode(timeframeSelect.value));
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

  window.addEventListener("resize", () => renderAll());
  refresh();
  state.pollTimer = window.setInterval(refresh, POLL_INTERVAL_MS);
}

boot();

// Test hooks (read-only)
window.__VIS2B__ = {
  VALID_MODES,
  TIMEFRAMES,
  getState: () => state,
  hasPnlPanel: () => Boolean(document.getElementById("paperPnlBlock") || document.getElementById("paperPnlPanel")),
  hasMetricsPanel: () => Boolean(document.getElementById("modelMetricsBlock") || document.getElementById("modelMetricsPanel")),
  hasLegacyCanvas: () => Boolean(document.getElementById("lifecycleCanvas")),
  chartCanvases: () => TIMEFRAMES.map((tf) => document.getElementById(`chart-${tf}`)),
  globalStrip: () => document.getElementById("globalLifecycleStrip"),
};
