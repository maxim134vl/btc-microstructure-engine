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
  lastVisualTimestamp: null,
  pollTimer: null,
};

const POLL_INTERVAL_MS = 60_000;
const STALE_THRESHOLD_MINUTES = 30;

const viewerRoot = document.getElementById("viewerRoot");
const errorPanel = document.getElementById("viewerErrorPanel");
const canvas = document.getElementById("lifecycleCanvas");
const statusLine = document.getElementById("statusLine");
const sourceLine = document.getElementById("sourceLine");
const hoverReadout = document.getElementById("hoverReadout");
const rangeSelect = document.getElementById("rangeSelect");
const ctx = canvas && typeof canvas.getContext === "function" ? canvas.getContext("2d") : null;

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
  if (meta) {
    meta.insertBefore(refreshLine, meta.firstChild);
  } else if (statusLine && statusLine.parentElement) {
    statusLine.parentElement.appendChild(refreshLine);
  } else if (viewerRoot) {
    viewerRoot.insertBefore(refreshLine, viewerRoot.firstChild);
  }
  return refreshLine;
}

function cacheBust(path) {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}v=${Date.now()}`;
}

function parseLatestTimestamp(latest) {
  if (!latest) return null;
  const raw = latest.timestamp || latest.generated_at || latest.as_of;
  if (!raw) return null;
  const ms = Date.parse(raw);
  return Number.isNaN(ms) ? null : ms;
}

function updateRefreshLine() {
  const refreshLine = ensureRefreshLine();
  if (!refreshLine) return;
  const latest = state.latest || {};
  const tsMs = parseLatestTimestamp(latest);
  const now = Date.now();
  let lagMinutes = null;
  let stale = true;
  if (tsMs != null) {
    lagMinutes = Math.max(0, (now - tsMs) / 60_000);
    stale = lagMinutes > STALE_THRESHOLD_MINUTES;
  }
  const stamp = tsMs != null ? formatTime(Math.floor(tsMs / 1000)) : "—";
  const lagText = lagMinutes == null ? "—" : `${lagMinutes.toFixed(0)} min`;
  const mode = stale ? "VISUAL DATA STALE" : "LIVE SNAPSHOT / AUTO-REFRESH";
  refreshLine.textContent = `${mode} · Last visual refresh: ${stamp} · Live lag: ${lagText}`;
  refreshLine.classList.toggle("is-stale", stale);
  refreshLine.classList.toggle("is-live", !stale);
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

function updateStatusLine() {
  if (!statusLine || !sourceLine) return;
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
  const episodes = Array.isArray(state.episodes) ? state.episodes : [];
  const blocks = latest.context_blocks_count ?? episodes.filter((ep) => ep.context === "LONG_CONTEXT" || ep.context === "SHORT_CONTEXT").length;
  sourceLine.textContent = `source: lifecycle episodes · ${blocks} context blocks`;
  updateRefreshLine();
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
  const response = await fetch(cacheBust(path), { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return response.json();
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
  state.latest = latest && typeof latest === "object" ? latest : {};
  if (!state.latest.timestamp && !state.latest.generated_at && !state.latest.as_of) {
    showViewerError("lifecycle_latest.json is missing timestamp fields; chart may still render.");
  } else {
    clearViewerError();
  }
  state.lastVisualTimestamp = state.latest.timestamp || state.latest.generated_at || null;
  updateStatusLine();
  applyRange(false);
  renderChart();
}

async function pollLatest() {
  try {
    const latest = await loadJson("./data/lifecycle_latest.json");
    const nextTs = latest?.timestamp || latest?.generated_at || null;
    if (nextTs && nextTs !== state.lastVisualTimestamp) {
      await loadAllVisualData();
      return;
    }
    // Even without data change, refresh stale/live badge vs wall clock.
    if (latest) state.latest = { ...(state.latest || {}), ...latest };
    updateRefreshLine();
  } catch (_error) {
    // Keep last good chart; badge can show stale on next successful poll.
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
    canvas.addEventListener("mouseleave", () => {
      state.pointer = null;
      state.dragging = false;
      if (hoverReadout) hoverReadout.classList.add("hidden");
      renderChart();
    });
    window.addEventListener("mouseup", () => {
      state.dragging = false;
    });
  } catch (error) {
    const message = error?.message || String(error);
    showViewerError(`Unable to load lifecycle visual data: ${message}`);
    if (sourceLine) sourceLine.textContent = "Run shadow-chain refresher or generate_lifecycle_context_data.py";
    const refreshLine = ensureRefreshLine();
    if (refreshLine) {
      refreshLine.textContent = "VISUAL DATA STALE · awaiting shadow-chain refresh";
      refreshLine.classList.add("is-stale");
    }
  }
}

init();
