/**
 * Clean View: lifecycle context intervals only.
 * Data sources:
 *   ./data/lifecycle_candles.json
 *   ./data/lifecycle_context_episodes.json
 *   ./data/lifecycle_latest.json
 * Does not read trading_state / market_state / arbitration / V4.
 */

const state = {
  candles: [],
  episodes: [],
  latest: null,
  selected: [],
  visibleStart: 0,
  visibleEnd: 0,
  range: "latest500",
  pointer: null,
  dragging: false,
  dragStartX: 0,
  dragStartVisibleStart: 0,
};

const canvas = document.getElementById("lifecycleCanvas");
const ctx = canvas.getContext("2d");
const statusLine = document.getElementById("statusLine");
const sourceLine = document.getElementById("sourceLine");
const hoverReadout = document.getElementById("hoverReadout");
const rangeSelect = document.getElementById("rangeSelect");

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

function updateStatusLine() {
  const latest = state.latest || {};
  if (latest.status_line) {
    statusLine.textContent = `Current: ${latest.status_line}`;
  } else {
    const context = latest.active_market_context || "OBSERVE";
    const lifecycle = latest.lifecycle_state || "NO_ACTIVE_CONTEXT";
    if (context === "OBSERVE") {
      const prev = latest.previous_active_market_context;
      const inv = latest.invalidation_type;
      if (prev && inv && inv !== "NONE") {
        statusLine.textContent = `Current: ${context} · ${lifecycle} · previous ${prev} invalidated · ${inv}`;
      } else {
        statusLine.textContent = `Current: ${context} · ${lifecycle} · no active directional context · ${actionLabel(Boolean(latest.action_allowed))}`;
      }
    } else {
      const age = latest.active_context_age_bars ?? 0;
      statusLine.textContent = `Current: ${context} · ${lifecycle} · age ${age} bars · ${actionLabel(Boolean(latest.action_allowed))}`;
    }
  }
  const blocks = latest.context_blocks_count ?? state.episodes.filter((ep) => ep.context === "LONG_CONTEXT" || ep.context === "SHORT_CONTEXT").length;
  sourceLine.textContent = `source: lifecycle episodes · ${blocks} context blocks`;
}

function applyRange(resetViewport = true) {
  const rows = state.candles.filter((row) => row.time && row.open != null);
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
  const challenged = Number(episode.challenge_ratio || 0) > 0.5
    || String(episode.dominant_lifecycle_state || "").toUpperCase() === "CHALLENGED";
  if (episode.context === "LONG_CONTEXT") {
    return challenged
      ? { mode: "hatch", color: "rgba(48, 209, 88, 0.10)" }
      : { mode: "solid", color: "rgba(48, 209, 88, 0.20)" };
  }
  if (episode.context === "SHORT_CONTEXT") {
    return challenged
      ? { mode: "hatch", color: "rgba(255, 69, 58, 0.10)" }
      : { mode: "solid", color: "rgba(255, 69, 58, 0.20)" };
  }
  return null; // OBSERVE: no fill
}

function drawLifecycleBands(bounds, visibleStartTime, visibleEndTime, xForTime) {
  state.episodes.forEach((episode) => {
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

function drawCandles(bounds, rows, xForTime, yForPrice) {
  if (rows.length < 2) return;
  const step = Math.max(1, (rows[1].time - rows[0].time) || 900);
  const candleWidth = Math.max(1.5, (xForTime(rows[0].time + step) - xForTime(rows[0].time)) * 0.7);
  rows.forEach((row) => {
    const x = xForTime(row.time);
    const openY = yForPrice(row.open);
    const closeY = yForPrice(row.close);
    const highY = yForPrice(row.high);
    const lowY = yForPrice(row.low);
    const up = row.close >= row.open;
    const color = up ? "#30d158" : "#ff453a";
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

function drawVolume(bounds, rows, xForTime, volumeMax) {
  if (!rows.length) return;
  const step = Math.max(1, (rows[1]?.time || rows[0].time + 900) - rows[0].time);
  const barWidth = Math.max(1, (xForTime(rows[0].time + step) - xForTime(rows[0].time)) * 0.65);
  rows.forEach((row) => {
    const height = ((row.volume || 0) / volumeMax) * (bounds.volumeBottom - bounds.volumeTop);
    const x = xForTime(row.time);
    const up = row.close >= row.open;
    ctx.fillStyle = up ? "rgba(48, 209, 88, 0.28)" : "rgba(255, 69, 58, 0.28)";
    ctx.fillRect(x - barWidth / 2, bounds.volumeBottom - height, barWidth, height);
  });
}

function drawGrid(bounds, priceMin, priceMax) {
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 5; i += 1) {
    const y = bounds.priceTop + ((bounds.priceBottom - bounds.priceTop) / 5) * i;
    ctx.moveTo(bounds.left, y);
    ctx.lineTo(bounds.right, y);
  }
  ctx.stroke();

  ctx.fillStyle = "#8b919a";
  ctx.font = "11px ui-monospace, SF Mono, Menlo, monospace";
  ctx.textAlign = "left";
  for (let i = 0; i <= 5; i += 1) {
    const price = priceMax - ((priceMax - priceMin) / 5) * i;
    const y = bounds.priceTop + ((bounds.priceBottom - bounds.priceTop) / 5) * i;
    ctx.fillText(formatNumber(price, 0), bounds.right + 6, y + 3);
  }
}

function drawTimeAxis(bounds, rows, xForTime) {
  if (!rows.length) return;
  ctx.fillStyle = "#8b919a";
  ctx.font = "11px ui-monospace, SF Mono, Menlo, monospace";
  ctx.textAlign = "center";
  const step = Math.max(1, Math.floor(rows.length / 6));
  for (let i = 0; i < rows.length; i += step) {
    const row = rows[i];
    ctx.fillText(formatTime(row.time), xForTime(row.time), bounds.bottom + 14);
  }
}

function rowAtPointer(rows, bounds, xForTime) {
  if (!state.pointer || !rows.length) return null;
  let best = null;
  let bestDist = Infinity;
  rows.forEach((row, index) => {
    const dist = Math.abs(xForTime(row.time) - state.pointer.x);
    if (dist < bestDist) {
      bestDist = dist;
      best = { row, index };
    }
  });
  if (!best || bestDist > 28) return null;
  return best.row;
}

function updateHover(rows, bounds, xForTime) {
  const row = rowAtPointer(rows, bounds, xForTime);
  if (!row) {
    hoverReadout.classList.add("hidden");
    return;
  }
  hoverReadout.classList.remove("hidden");
  hoverReadout.textContent = [
    formatTime(row.time),
    `close ${formatNumber(row.close)}`,
    row.active_market_context || "OBSERVE",
    row.lifecycle_state || "—",
  ].join(" · ");
}

function renderChart() {
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(width * ratio));
  canvas.height = Math.max(1, Math.floor(height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const rows = state.selected.slice(state.visibleStart, state.visibleEnd);
  if (rows.length < 2) {
    ctx.fillStyle = "#8b919a";
    ctx.textAlign = "center";
    ctx.font = "14px sans-serif";
    ctx.fillText("No lifecycle candle data. Run generate_lifecycle_context_data.py", width / 2, height / 2);
    return;
  }

  const bounds = getBounds(width, height);
  const visibleStartTime = rows[0].time;
  const visibleEndTime = rows[rows.length - 1].time;
  const prices = rows.flatMap((row) => [row.high, row.low]).filter((v) => Number.isFinite(v));
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
  drawCandles(bounds, rows, xForTime, yForPrice);
  drawVolume(bounds, rows, xForTime, volumeMax);
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

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return response.json();
}

async function init() {
  try {
    const [candlesPayload, episodes, latest] = await Promise.all([
      loadJson("./data/lifecycle_candles.json"),
      loadJson("./data/lifecycle_context_episodes.json"),
      loadJson("./data/lifecycle_latest.json"),
    ]);
    state.candles = candlesPayload.rows || [];
    state.episodes = Array.isArray(episodes) ? episodes : [];
    state.latest = latest || {};
    updateStatusLine();
    applyRange(true);
    renderChart();

    rangeSelect.addEventListener("change", () => {
      state.range = rangeSelect.value;
      applyRange(true);
      renderChart();
    });
    window.addEventListener("resize", renderChart);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseleave", () => {
      state.pointer = null;
      state.dragging = false;
      hoverReadout.classList.add("hidden");
      renderChart();
    });
    window.addEventListener("mouseup", () => {
      state.dragging = false;
    });
  } catch (error) {
    statusLine.textContent = `Unable to load lifecycle visual data: ${error.message}`;
    sourceLine.textContent = "Run: python3 generate_lifecycle_context_data.py";
  }
}

init();
