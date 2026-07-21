const state = {
  data: null,
  timeframe: "M15",
  range: "latest500",
  displayMode: "clean",
  autoScroll: true,
  showEventMarkers: true,
  showEventLabels: false,
  showDirectionalContext: true,
  showContextLabels: false,
  rows: [],
  selectedRows: [],
  visibleStart: 0,
  visibleEnd: 0,
  pointer: null,
  dragging: false,
  dragStartX: 0,
  dragStartVisibleStart: 0,
};

const canvas = document.getElementById("marketCanvas");
const context = canvas.getContext("2d");
const tooltip = document.getElementById("chartTooltip");

const timeframeSeconds = {
  M15: 900,
  M30: 1800,
  H1: 3600,
  H4: 14400,
  D1: 86400,
};

const regimeColors = {
  ACCUMULATION: "rgba(48, 209, 88, 0.10)",
  DISTRIBUTION: "rgba(155, 135, 200, 0.11)",
  REVERSAL: "rgba(10, 132, 255, 0.10)",
  TREND_CONTINUATION: "rgba(255, 159, 10, 0.09)",
  NEUTRAL: "rgba(152, 152, 157, 0.08)",
  "N/A": "rgba(152, 152, 157, 0.05)",
};

const tradingStateLaneColors = {
  REVERSAL_WATCH: "rgba(155, 135, 200, 0.42)",
  LONG_CONTEXT: "rgba(48, 209, 88, 0.42)",
  SHORT_CONTEXT: "rgba(255, 69, 58, 0.38)",
  NEUTRAL: "rgba(152, 152, 157, 0.28)",
  "N/A": "rgba(110, 115, 128, 0.22)",
};

const regimeSolidColors = {
  ACCUMULATION: "#30d158",
  DISTRIBUTION: "#9b87c8",
  REVERSAL: "#5ac8fa",
  TREND_CONTINUATION: "#ff9f0a",
  NEUTRAL: "#98989d",
  "N/A": "#6e7380",
};

const PERSISTENCE_WARNING_BARS = 120;

function formatTime(timestampSeconds, includeDate = false) {
  if (!timestampSeconds) return "—";
  const formatter = new Intl.DateTimeFormat("ru-RU", {
    day: includeDate ? "2-digit" : undefined,
    month: includeDate ? "short" : undefined,
    hour: "2-digit",
    minute: "2-digit",
  });
  return formatter.format(new Date(timestampSeconds * 1000));
}

function formatDateTime(timestampSeconds) {
  if (!timestampSeconds) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestampSeconds * 1000));
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const numericValue = Number(value);
  const sign = numericValue > 0 ? "+" : "";
  return `${sign}${numericValue.toFixed(2)}%`;
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function normalizeStateName(value) {
  return value && value !== "N/A" ? String(value) : "N/A";
}

function classifyValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  const numericValue = Number(value);
  if (numericValue >= 0.66) return "HIGH";
  if (numericValue >= 0.4) return "MED";
  return "LOW";
}

async function init() {
  try {
    const response = await fetch("./data/dashboard_market_state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`data load failed: ${response.status}`);
    state.data = await response.json();
    setupControls();
    syncOverlayDefaultsForDisplayMode();
    applyDataSelection(true);
    resizeCanvas();
    renderAll();
    window.addEventListener("resize", resizeCanvas);
  } catch (error) {
    document.body.innerHTML = `<div class="terminal-shell"><main class="workspace"><h1>Market State Sandbox</h1><p>Unable to load generated data: ${error.message}</p><p>Run <code>python3 generate_sandbox_data.py</code> and serve <code>public/</code> over HTTP.</p></main></div>`;
  }
}

function setupControls() {
  document.querySelectorAll("#timeframeControls button").forEach((button) => {
    button.addEventListener("click", () => {
      state.timeframe = button.dataset.timeframe;
      document.querySelectorAll("#timeframeControls button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      applyDataSelection(true);
      renderAll();
    });
  });

  document.getElementById("rangeSelect").addEventListener("change", (event) => {
    state.range = event.target.value;
    applyDataSelection(true);
    renderAll();
  });

  document.getElementById("displaySelect").addEventListener("change", (event) => {
    state.displayMode = event.target.value;
    syncOverlayDefaultsForDisplayMode();
    renderAll();
  });

  document.getElementById("toggleEventMarkers").addEventListener("change", (event) => {
    state.showEventMarkers = event.target.checked;
    renderChart();
  });
  document.getElementById("toggleEventLabels").addEventListener("change", (event) => {
    state.showEventLabels = event.target.checked;
    renderChart();
  });
  document.getElementById("toggleDirectionalContext").addEventListener("change", (event) => {
    state.showDirectionalContext = event.target.checked;
    renderChart();
  });
  document.getElementById("toggleContextLabels").addEventListener("change", (event) => {
    state.showContextLabels = event.target.checked;
    renderChart();
  });

  document.getElementById("eventFilter").addEventListener("change", renderHistoryTable);

  document.getElementById("autoScrollInput").addEventListener("change", (event) => {
    state.autoScroll = event.target.checked;
  });

  document.getElementById("themeButton").addEventListener("click", () => {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    renderChart();
  });

  [
    "fitButton",
    "chartFitButton",
  ].forEach((buttonId) => document.getElementById(buttonId).addEventListener("click", fitVisibleRange));
  [
    "latestButton",
    "chartLatestButton",
  ].forEach((buttonId) => document.getElementById(buttonId).addEventListener("click", goToLatest));
  [
    "resetButton",
    "chartResetButton",
  ].forEach((buttonId) => document.getElementById(buttonId).addEventListener("click", () => {
    applyDataSelection(true);
    renderAll();
  }));

  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseleave", () => {
    state.pointer = null;
    state.dragging = false;
    tooltip.classList.add("hidden");
    renderChart();
  });
  window.addEventListener("mouseup", () => {
    state.dragging = false;
  });
  canvas.addEventListener("dblclick", fitVisibleRange);
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  renderChart();
}

function syncOverlayDefaultsForDisplayMode() {
  if (state.displayMode === "clean") {
    state.showEventMarkers = true;
    state.showEventLabels = false;
    state.showDirectionalContext = true;
    state.showContextLabels = false;
  } else if (state.displayMode === "decision") {
    state.showEventMarkers = true;
    state.showEventLabels = true;
    state.showDirectionalContext = true;
    state.showContextLabels = false;
  } else {
    state.showEventMarkers = true;
    state.showEventLabels = true;
    state.showDirectionalContext = true;
    state.showContextLabels = true;
  }
  document.getElementById("toggleEventMarkers").checked = state.showEventMarkers;
  document.getElementById("toggleEventLabels").checked = state.showEventLabels;
  document.getElementById("toggleDirectionalContext").checked = state.showDirectionalContext;
  document.getElementById("toggleContextLabels").checked = state.showContextLabels;
}

function formatIsoTimestamp(value) {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return String(value).replace("T", " ").replace("Z", "");
  return formatDateTime(Math.floor(parsed / 1000));
}

function aggregateRows(rows, timeframe) {
  if (timeframe === "M5" || timeframe === "M15") {
    return rows.slice();
  }

  const bucketSeconds = timeframeSeconds[timeframe] || timeframeSeconds.M15;
  const buckets = new Map();

  rows.forEach((row) => {
    const bucketTime = Math.floor(row.time / bucketSeconds) * bucketSeconds;
    if (!buckets.has(bucketTime)) {
      buckets.set(bucketTime, {
        ...row,
        timestamp: new Date(bucketTime * 1000).toISOString(),
        time: bucketTime,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
        volume: row.volume || 0,
        source_count: 1,
      });
      return;
    }
    const bucket = buckets.get(bucketTime);
    bucket.high = Math.max(bucket.high, row.high);
    bucket.low = Math.min(bucket.low, row.low);
    bucket.close = row.close;
    bucket.volume += row.volume || 0;
    bucket.source_count += 1;
    Object.keys(row).forEach((key) => {
      if (!["timestamp", "time", "open", "high", "low", "close", "volume", "source_count"].includes(key)) {
        bucket[key] = row[key];
      }
    });
  });

  return [...buckets.values()].sort((left, right) => left.time - right.time);
}

function applyDataSelection(resetViewport = false) {
  const baseRows = (state.data?.rows || []).filter((row) => row.time && row.open !== null);
  state.rows = aggregateRows(baseRows, state.timeframe);

  const latestRow = state.rows[state.rows.length - 1];
  if (!latestRow) {
    state.selectedRows = [];
    state.visibleStart = 0;
    state.visibleEnd = 0;
    return;
  }

  const range = state.range;
  if (range === "latest100") {
    state.selectedRows = state.rows.slice(-100);
  } else if (range === "latest500") {
    state.selectedRows = state.rows.slice(-500);
  } else if (range === "latest1000") {
    state.selectedRows = state.rows.slice(-1000);
  } else if (range === "last3d") {
    state.selectedRows = state.rows.filter((row) => row.time >= latestRow.time - 3 * 86400);
  } else if (range === "last14d") {
    state.selectedRows = state.rows.filter((row) => row.time >= latestRow.time - 14 * 86400);
  } else if (range === "last7d") {
    state.selectedRows = state.rows.filter((row) => row.time >= latestRow.time - 7 * 86400);
  } else {
    state.selectedRows = state.rows.slice();
  }

  if (resetViewport || state.autoScroll) {
    state.visibleStart = 0;
    state.visibleEnd = state.selectedRows.length;
  } else {
    constrainViewport();
  }
  document.getElementById("chartTimeframe").textContent = state.timeframe === "M5" ? "M5* / M15 source" : state.timeframe;
  const warningBox = document.getElementById("rangeWarning");
  if (state.timeframe === "M5") {
    warningBox.textContent = "M5 native candles are not available for the selected runtime range; sandbox falls back to M15 source candles.";
    warningBox.classList.remove("hidden");
  } else {
    warningBox.classList.add("hidden");
  }
}

function constrainViewport() {
  const totalRows = state.selectedRows.length;
  const visibleCount = Math.max(12, state.visibleEnd - state.visibleStart);
  if (visibleCount >= totalRows) {
    state.visibleStart = 0;
    state.visibleEnd = totalRows;
    return;
  }
  state.visibleStart = clamp(state.visibleStart, 0, totalRows - visibleCount);
  state.visibleEnd = state.visibleStart + visibleCount;
}

function fitVisibleRange() {
  state.visibleStart = 0;
  state.visibleEnd = state.selectedRows.length;
  renderChart();
}

function goToLatest() {
  const visibleCount = Math.max(40, state.visibleEnd - state.visibleStart);
  state.visibleEnd = state.selectedRows.length;
  state.visibleStart = Math.max(0, state.visibleEnd - visibleCount);
  renderChart();
}

function onWheel(event) {
  event.preventDefault();
  if (!state.selectedRows.length) return;

  const rect = canvas.getBoundingClientRect();
  const chartBounds = getChartBounds(rect.width, rect.height);
  const oldVisibleCount = state.visibleEnd - state.visibleStart;
  const zoomFactor = event.deltaY > 0 ? 1.18 : 0.82;
  const newVisibleCount = clamp(Math.round(oldVisibleCount * zoomFactor), 24, state.selectedRows.length);
  const anchorRatio = clamp((event.clientX - rect.left - chartBounds.left) / chartBounds.width, 0, 1);
  const anchorIndex = state.visibleStart + Math.round(oldVisibleCount * anchorRatio);
  state.visibleStart = Math.round(anchorIndex - newVisibleCount * anchorRatio);
  state.visibleEnd = state.visibleStart + newVisibleCount;
  constrainViewport();
  state.autoScroll = false;
  document.getElementById("autoScrollInput").checked = false;
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
    clientX: event.clientX,
    clientY: event.clientY,
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };

  if (state.dragging) {
    const visibleCount = state.visibleEnd - state.visibleStart;
    const chartBounds = getChartBounds(rect.width, rect.height);
    const candleWidth = chartBounds.width / Math.max(1, visibleCount);
    const indexDelta = Math.round((state.dragStartX - event.clientX) / Math.max(1, candleWidth));
    state.visibleStart = state.dragStartVisibleStart + indexDelta;
    state.visibleEnd = state.visibleStart + visibleCount;
    constrainViewport();
    state.autoScroll = false;
    document.getElementById("autoScrollInput").checked = false;
  }

  renderChart();
}

function getChartBounds(width, height) {
  const leftPad = 10;
  const priceScaleWidth = 56;
  const rightPad = 6;
  const laneLabelWidth = 30;
  const laneHeight = 16;
  const laneGap = 3;
  const volumeHeight = 34;
  const bottomPad = 14;
  const lanesTotal = laneHeight * 2 + laneGap;
  const volumeBottom = height - bottomPad - lanesTotal;
  const volumeTop = volumeBottom - volumeHeight;
  const contextLaneTop = volumeBottom + laneGap;
  const contextLaneBottom = contextLaneTop + laneHeight;
  const tradingLaneTop = contextLaneBottom + laneGap;
  const tradingLaneBottom = tradingLaneTop + laneHeight;
  const left = leftPad;
  const right = Math.max(left + 120, width - priceScaleWidth - rightPad);

  return {
    left,
    right,
    laneLabelWidth,
    priceScaleLeft: right + 2,
    priceScaleRight: width - rightPad,
    priceScaleWidth,
    bottom: height - 6,
    top: 20,
    width: right - left,
    height: height - 26,
    priceTop: 28,
    priceBottom: volumeTop - 5,
    volumeTop,
    volumeBottom,
    contextLaneTop,
    contextLaneBottom,
    tradingLaneTop,
    tradingLaneBottom,
  };
}

function renderAll() {
  renderTopStatus();
  renderFreshness();
  renderPanels();
  renderRegimeTimeline();
  renderHistoryTable();
  renderMetrics();
  renderChart();
}

function renderTopStatus() {
  const summary = state.data.summary || {};
  const latestTime = state.selectedRows[state.selectedRows.length - 1]?.time;
  const firstTime = state.selectedRows[0]?.time;
  document.getElementById("lastUpdate").textContent = formatDateTime(latestTime);
  document.getElementById("sideLastUpdate").textContent = formatTime(latestTime, true);
  document.getElementById("sideContextCounts").textContent = `${summary.long_episodes || 0}L / ${summary.short_episodes || 0}S`;
  document.getElementById("sideLiveFeed").textContent = summary.live_feed_latest_timestamp ? "LIVE" : "N/A";
  document.getElementById("timelineRangeLabel").textContent = `${formatTime(firstTime, true)} — ${formatTime(latestTime, true)}`;

  const statusPill = document.getElementById("dataStatus");
  const warnings = summary.warnings || [];
  const hasCoreData = Boolean((state.data.candles || []).length && (state.data.context_events || []).length);
  statusPill.textContent = warnings.length ? "PARTIAL" : hasCoreData ? "LIVE" : "STALE";
  statusPill.className = `pill ${warnings.length ? "degraded" : hasCoreData ? "live" : "stale"}`;
}

function renderFreshness() {
  const summary = state.data.summary || {};
  const current = state.data.current_state || {};
  const barTs = summary.latest_bar_timestamp || summary.candle_end || current.bar_timestamp || current.timestamp;
  const marketTs = summary.latest_market_state_timestamp || current.market_state_timestamp;
  const tradingTs = summary.latest_trading_state_timestamp || current.trading_state_timestamp;
  const marketState = current.market_state || "—";
  const tradingState = current.trading_state || "—";
  const confidenceBand = current.confidence_band || "—";
  const confidenceScore = current.market_state_confidence;

  document.getElementById("freshBarTs").textContent = formatIsoTimestamp(barTs);
  document.getElementById("freshMarketTs").textContent = formatIsoTimestamp(marketTs);
  document.getElementById("freshTradingTs").textContent = formatIsoTimestamp(tradingTs);
  document.getElementById("freshCurrentState").textContent = `${marketState} · ${tradingState}`;
  document.getElementById("freshConfidence").textContent = Number.isFinite(Number(confidenceScore))
    ? `${confidenceBand} · ${Number(confidenceScore).toFixed(3)}`
    : confidenceBand;

  const warningEl = document.getElementById("freshnessWarning");
  if (summary.data_is_stale) {
    warningEl.textContent = summary.stale_reason || "Data may be stale";
    warningEl.classList.remove("hidden");
  } else {
    warningEl.textContent = "";
    warningEl.classList.add("hidden");
  }

  const statusPill = document.getElementById("dataStatus");
  if (summary.data_is_stale) {
    statusPill.textContent = "STALE";
    statusPill.className = "pill stale";
  }
}

function renderPanels() {
  const current = state.data.current_state || {};
  const summary = state.data.summary || {};
  const activeContext = summary.current_active_context || null;
  const confidenceClass = current.confidence_band === "LOW_CONFIDENCE" ? "warning" : "positive";

  document.getElementById("currentStatePanel").innerHTML = [
    wrapStateRow("Market State", current.market_state, "info"),
    wrapStateRow("Trading State", current.trading_state, current.trading_state === "REVERSAL_WATCH" ? "warning" : "info"),
    wrapStateRow("Auction", current.auction_state),
    wrapStateRow("Regime", current.regime_state || current.synthesis_state, "info"),
    wrapStateRow("Structure", current.synthesis_state),
    wrapStateRow("Context Bias", current.market_bias, current.market_bias === "BULLISH" ? "positive" : "negative"),
    wrapStateRow("Location", current.location_bias, current.location_bias?.includes("LOWER") ? "positive" : "warning"),
    wrapStateRow("Confidence Band", current.confidence_band, confidenceClass),
    wrapStateRow("Confidence Score", current.market_state_confidence, confidenceClass, true),
    wrapStateRow("Rule", current.rule_id),
    wrapStateRow("Rule Description", current.rule_description, "", false, true),
    wrapStateRow("Auction Read", current.trader_read, "", false, true),
    wrapStateRow("Context Read", current.human_message, "", false, true),
    wrapStateRow("Active Context", activeContext || "None", activeContext ? "positive" : "warning"),
    wrapStateRow("Last Context Transition", summary.last_context_transition?.timestamp ? formatIsoTimestamp(summary.last_context_transition.timestamp) : "—"),
  ].join("");

  renderPersistenceWarning(current, summary);
  renderReversalWatchPanel();

  document.getElementById("probabilityPanel").innerHTML = [
    compactMetricLine("Continuation", current.regime_confidence),
    compactMetricLine("Reversal", current.market_state === "REVERSAL" ? current.market_state_confidence : null),
    compactMetricLine("Absorption", current.absorption_probability),
    compactMetricLine("Distribution", current.distribution_probability),
    compactMetricLine("Conviction", current.conviction_probability),
  ].join("");

  const mtfRows = state.data.mtf_alignment || [];
  document.getElementById("mtfPanel").innerHTML = mtfRows
    .map((row) => {
      const alignment = row.alignment === null ? "—" : Number(row.alignment).toFixed(2);
      return `<div class="mtf-row"><strong>${row.timeframe}</strong><span class="truncate" title="${escapeHtml(row.state)}">${escapeHtml(row.state)}</span><span>${alignment}</span></div>`;
    })
    .join("");

  document.getElementById("locationPanel").innerHTML = [
    compactStateRow("Location", current.location_bias, current.location_bias?.includes("LOWER") ? "positive" : "warning"),
    compactStateRow("Behavior", current.localized_behavior),
    compactStateRow("Effort/Result", current.effort_result_state),
    compactStateRow("Unfinished", current.unfinished_auction === true ? "ACTIVE" : "INACTIVE", current.unfinished_auction === true ? "warning" : "positive"),
    compactStateRow("Convergence", current.convergence_state),
  ].join("");

  const warnings = summary.warnings || [];
  const topWarnings = warnings.slice(0, 3).map((warning) => `<li title="${escapeHtml(warning)}">${escapeHtml(warning)}</li>`);
  if (!topWarnings.length) topWarnings.push("<li>No active sandbox warnings.</li>");
  const hiddenWarnings = warnings.slice(3).map((warning) => `<li title="${escapeHtml(warning)}">${escapeHtml(warning)}</li>`).join("");
  const details = hiddenWarnings
    ? `<details class="warnings-details"><summary>View all warnings (${warnings.length})</summary><ul>${hiddenWarnings}</ul></details>`
    : "";
  document.getElementById("warningsList").innerHTML = [
    `<li><strong>Chart:</strong> OK · <strong>Contexts:</strong> OK · auxiliary sources may be stale.</li>`,
    ...topWarnings,
  ].join("") + details;
}

function computeTradingStatePersistence(tradingState) {
  const rows = state.selectedRows.length ? state.selectedRows : state.rows;
  if (!rows.length || !tradingState) return { bars: 0, days: 0 };

  let bars = 0;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].trading_state === tradingState) bars += 1;
    else break;
  }

  const bucketSeconds = timeframeSeconds[state.timeframe] || timeframeSeconds.M15;
  const days = (bars * bucketSeconds) / 86400;
  return { bars, days: Math.round(days * 10) / 10 };
}

function renderPersistenceWarning(current, summary) {
  const warningEl = document.getElementById("persistenceWarning");
  const tradingState = current.trading_state;
  if (tradingState !== "REVERSAL_WATCH") {
    warningEl.classList.add("hidden");
    warningEl.textContent = "";
    return;
  }

  const activeRegime = state.data.active_market_state_regime;
  const fromRegime = activeRegime?.duration_bars;
  const computed = computeTradingStatePersistence(tradingState);
  const bars = Math.max(fromRegime || 0, computed.bars);
  const days = Math.max(
    activeRegime?.duration_bars ? (activeRegime.duration_bars * (timeframeSeconds[state.timeframe] || 900)) / 86400 : 0,
    computed.days,
  );

  if (bars < PERSISTENCE_WARNING_BARS) {
    warningEl.classList.add("hidden");
    warningEl.textContent = "";
    return;
  }

  warningEl.textContent = `${tradingState} has persisted for ${bars} bars / ${days.toFixed(1)} days. Review lifecycle TTL (24h) — watch-state is context only, not a trade signal.`;
  warningEl.classList.remove("hidden");
}

function renderReversalWatchPanel() {
  const panel = document.getElementById("reversalWatchPanel");
  if (!panel) return;

  const lifecycle = state.data.reversal_watch_lifecycle || state.data.current_state?.reversal_watch_lifecycle || null;
  const episodes = (state.data.reversal_watch_episodes || []).slice().reverse();
  const lines = [];

  if (lifecycle) {
    lines.push(
      wrapStateRow("Current Watch", "ACTIVE", "warning"),
      wrapStateRow("Watch Started", formatIsoTimestamp(lifecycle.watch_started_at)),
      wrapStateRow("Age (hours)", lifecycle.age_hours),
      wrapStateRow("TTL Remaining (hours)", lifecycle.remaining_hours),
      wrapStateRow("Cooldown Until", formatIsoTimestamp(lifecycle.cooldown_until)),
      wrapStateRow("Context Read", lifecycle.human_message, "", false, true),
    );
  } else {
    lines.push(`<p class="panel-note">No active REVERSAL_WATCH lifecycle at latest trading_state row.</p>`);
  }

  if (episodes.length) {
    const latest = episodes[0];
    lines.push(
      `<div class="rw-episode-card">`,
      `<div class="rw-episode-title">Latest episode</div>`,
      wrapStateRow("Start", formatIsoTimestamp(latest.start_ts)),
      wrapStateRow("End", formatIsoTimestamp(latest.end_ts)),
      wrapStateRow("Duration (h)", latest.duration_hours),
      wrapStateRow("TTL Limit (h)", latest.ttl_limit_hours ?? 24),
      wrapStateRow("Next State", latest.next_state || "—"),
      wrapStateRow("Expired By TTL", latest.expired_by_ttl ? "YES" : "NO", latest.expired_by_ttl ? "warning" : "info"),
      wrapStateRow("Cooldown Until", formatIsoTimestamp(latest.cooldown_until)),
      `</div>`,
    );
    if (episodes.length > 1) {
      lines.push(`<p class="panel-note">${episodes.length} REVERSAL_WATCH episodes in loaded data.</p>`);
    }
  } else {
    lines.push(`<p class="panel-note">No REVERSAL_WATCH episodes in loaded trading_state memory.</p>`);
  }

  panel.innerHTML = lines.join("");
}

function wrapStateRow(label, value, tone = "", withMeter = false, multiline = false) {
  const normalizedValue = value === null || value === undefined || value === "" ? "—" : value;
  const displayValue = typeof normalizedValue === "number" ? normalizedValue.toFixed(3) : escapeHtml(String(normalizedValue));
  const title = typeof normalizedValue === "number" ? normalizedValue.toFixed(3) : String(normalizedValue ?? "—");
  const numericValue = Number(value);
  const meter = withMeter && Number.isFinite(numericValue)
    ? `<div class="meter" style="--value:${clamp(numericValue * 100, 0, 100)}%"><span></span></div>`
    : "";
  const rowClass = multiline ? "state-row readable multiline" : "state-row readable";
  return `<div class="${rowClass}"><span>${label}</span><strong class="${tone}" title="${escapeHtml(title)}">${displayValue}</strong>${meter}</div>`;
}

function stateRow(label, value, tone = "", withMeter = false) {
  const normalizedValue = value === null || value === undefined ? "—" : value;
  const displayValue = typeof normalizedValue === "number" ? normalizedValue.toFixed(3) : escapeHtml(String(normalizedValue));
  const numericValue = Number(value);
  const meter = withMeter && Number.isFinite(numericValue)
    ? `<div class="meter" style="--value:${clamp(numericValue * 100, 0, 100)}%"><span></span></div>`
    : "";
  return `<div class="state-row"><span>${label}</span><strong class="${tone}">${displayValue}</strong>${meter}</div>`;
}

function metricLine(label, value) {
  const numericValue = Number(value);
  const displayValue = Number.isFinite(numericValue) ? numericValue.toFixed(3) : "—";
  const width = Number.isFinite(numericValue) ? clamp(numericValue * 100, 0, 100) : 0;
  return `<div class="state-row"><span>${label}</span><strong>${displayValue}</strong><div class="meter" style="--value:${width}%"><span></span></div></div>`;
}


function compactStateRow(label, value, tone = "", withMeter = false) {
  const normalizedValue = value === null || value === undefined ? "—" : value;
  const displayValue = typeof normalizedValue === "number" ? normalizedValue.toFixed(3) : escapeHtml(String(normalizedValue));
  const title = typeof normalizedValue === "number" ? normalizedValue.toFixed(3) : String(normalizedValue ?? "—");
  const numericValue = Number(value);
  const meter = withMeter && Number.isFinite(numericValue)
    ? `<div class="meter" style="--value:${clamp(numericValue * 100, 0, 100)}%"><span></span></div>`
    : "";
  return `<div class="state-row compact"><span>${label}</span><strong class="${tone}" title="${escapeHtml(title)}">${displayValue}</strong>${meter}</div>`;
}

function compactMetricLine(label, value) {
  const numericValue = Number(value);
  const displayValue = Number.isFinite(numericValue) ? numericValue.toFixed(3) : "—";
  const width = Number.isFinite(numericValue) ? clamp(numericValue * 100, 0, 100) : 0;
  return `<div class="state-row compact"><span>${label}</span><strong>${displayValue}</strong><div class="meter" style="--value:${width}%"><span></span></div></div>`;
}

function renderMetrics() {
  const current = state.data.current_state || {};
  const probabilityMetrics = [
    ["Conviction Prob.", current.conviction_probability],
    ["Absorption Prob.", current.absorption_probability],
    ["Distribution Prob.", current.distribution_probability],
    ["Regime Confidence", current.regime_confidence],
  ];
  const runtimeMetrics = [
    ["Persistence Score", current.persistence_score],
    ["Alignment Score", current.alignment_score],
    ["Structural Rank", current.structural_rank],
    ["Unfinished Auction", current.unfinished_auction === true ? "YES" : "NO"],
  ];
  document.getElementById("probabilityMetrics").innerHTML = probabilityMetrics.map(renderMetricRow).join("");
  document.getElementById("runtimeMetrics").innerHTML = runtimeMetrics.map(renderMetricRow).join("");
}

function renderMetricRow([label, value]) {
  const isNumeric = Number.isFinite(Number(value));
  const rawValue = isNumeric ? Number(value).toFixed(3) : String(value ?? "—");
  const displayValue = isNumeric ? rawValue : escapeHtml(rawValue);
  const quality = isNumeric ? classifyValue(value) : "";
  const qualityClass = quality ? `metric-band ${String(quality).toLowerCase()}` : "metric-band empty";
  const rowClass = quality ? "metric-row" : "metric-row no-band";
  return `<div class="${rowClass}"><span class="metric-label" title="${escapeHtml(String(label))}">${label}</span><strong class="metric-value" title="${escapeHtml(rawValue)}">${displayValue}</strong><em class="${qualityClass}" title="${escapeHtml(String(quality || "—"))}">${quality}</em></div>`;
}

function renderRegimeTimeline() {
  const container = document.getElementById("regimeTimeline");
  const selectedRows = state.selectedRows || [];
  const selectedStart = selectedRows[0]?.time;
  const selectedEnd = selectedRows[selectedRows.length - 1]?.time;
  document.getElementById("timelineRangeLabel").textContent = `${formatTime(selectedStart, true)} — ${formatTime(selectedEnd, true)}`;

  if (!selectedStart || !selectedEnd || !selectedRows.length) {
    container.innerHTML = "";
    return;
  }

  const mergedSegments = [];
  selectedRows.forEach((row) => {
    const stateName = normalizeStateName(row.market_state);
    const last = mergedSegments[mergedSegments.length - 1];
    if (last && last.state === stateName) {
      last.end_time = row.time;
      last.duration_bars += 1;
      return;
    }
    mergedSegments.push({
      state: stateName,
      label: regimeShortLabel(stateName),
      start_time: row.time,
      end_time: row.time,
      duration_bars: 1,
    });
  });

  const totalDuration = Math.max(1, selectedEnd - selectedStart);
  const currentMarketState = state.data.current_state?.market_state;
  container.innerHTML = mergedSegments
    .map((segment, index) => {
      const width = Math.max(0.35, ((segment.end_time - segment.start_time + timeframeSeconds[state.timeframe]) / totalDuration) * 100);
      const color = regimeSolidColors[segment.state] || regimeSolidColors["N/A"];
      const isCurrent = index === mergedSegments.length - 1 || segment.state === currentMarketState;
      const label = width > 14 ? escapeHtml(segment.label) : "";
      return `<div class="regime-segment${isCurrent ? " current" : ""}" title="${escapeHtml(segment.label)} · ${segment.duration_bars} bars" style="width:${width}%; background:${color}${isCurrent ? "d9" : "8f"}">${label}</div>`;
    })
    .join("");
}

function renderHistoryTable() {
  const tbody = document.getElementById("contextHistoryBody");
  const statusLine = document.getElementById("contextStatusLine");
  const summary = state.data.summary || {};
  const filter = document.getElementById("eventFilter").value;
  const selectedStart = state.selectedRows[0]?.time || 0;
  const selectedEnd = state.selectedRows[state.selectedRows.length - 1]?.time || Number.MAX_SAFE_INTEGER;
  const events = (state.data.timeline_events || [])
    .filter((eventItem) => eventItem.time >= selectedStart && eventItem.time <= selectedEnd)
    .filter((eventItem) => {
      if (filter === "long") return eventItem.direction === "LONG";
      if (filter === "short") return eventItem.direction === "SHORT";
      if (filter === "start") return eventItem.event_type === "CONTEXT_START";
      if (filter === "end") return eventItem.event_type === "CONTEXT_END";
      if (filter === "mode") return eventItem.event_type === "MODE_SHIFT";
      if (filter === "warning") return eventItem.event_type?.includes("WARNING");
      return true;
    })
    .sort((left, right) => {
      const leftPriority = left.event_type === "MODE_SHIFT" ? 1 : 0;
      const rightPriority = right.event_type === "MODE_SHIFT" ? 1 : 0;
      return leftPriority - rightPriority || right.time - left.time;
    });

  const activeContext = summary.current_active_context;
  const lastTransition = summary.last_context_transition;
  if (activeContext) {
    statusLine.textContent = `Active directional context: ${activeContext}.`;
  } else if (lastTransition?.timestamp) {
    statusLine.textContent = `No active directional context. Last directional context ended on ${formatIsoTimestamp(lastTransition.timestamp)}.`;
  } else {
    statusLine.textContent = "No directional context events in the selected range.";
  }

  if (!events.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="reason-cell">No context or regime-shift events in the selected range.</td></tr>`;
    return;
  }

  tbody.innerHTML = events
    .map((eventItem) => {
      const directionClass = eventItem.direction === "LONG" ? "positive" : eventItem.direction === "SHORT" ? "negative" : "info";
      const reason = escapeHtml(eventItem.reason || "—");
      return `<tr title="${reason}">
        <td>${formatDateTime(eventItem.time)}</td>
        <td><strong>${escapeHtml(formatContextEventLabel(eventItem))}</strong></td>
        <td class="${directionClass}">${escapeHtml(eventItem.direction || "—")}</td>
        <td><span class="truncate" title="${escapeHtml(eventItem.from_state || "—")}">${escapeHtml(eventItem.from_state || "—")}</span></td>
        <td><span class="truncate" title="${escapeHtml(eventItem.to_state || "—")}">${escapeHtml(eventItem.to_state || "—")}</span></td>
        <td>${escapeHtml(eventItem.context_id || "—")}</td>
        <td>${eventItem.duration_bars ?? "—"} bars</td>
        <td class="${Number(eventItem.price_change_pct) >= 0 ? "positive" : "negative"}">${formatPct(eventItem.price_change_pct)}</td>
      </tr>`;
    })
    .join("");
}

function renderChart() {
  if (!state.data) return;

  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  context.clearRect(0, 0, width, height);

  const bounds = getChartBounds(width, height);
  const rows = state.selectedRows.slice(state.visibleStart, state.visibleEnd);
  if (rows.length < 2) {
    drawEmptyChart(width, height);
    return;
  }

  const visibleStartTime = rows[0].time;
  const visibleEndTime = rows[rows.length - 1].time;
  const priceValues = rows.flatMap((row) => [row.high, row.low]).filter((value) => Number.isFinite(Number(value)));
  const priceMinimumRaw = Math.min(...priceValues);
  const priceMaximumRaw = Math.max(...priceValues);
  const pricePadding = Math.max(12, (priceMaximumRaw - priceMinimumRaw) * 0.08);
  const priceMinimum = priceMinimumRaw - pricePadding;
  const priceMaximum = priceMaximumRaw + pricePadding;
  const volumeMaximum = Math.max(...rows.map((row) => row.volume || 0), 1);

  const xForTime = (timestampSeconds) => {
    const range = Math.max(1, visibleEndTime - visibleStartTime);
    return bounds.left + ((timestampSeconds - visibleStartTime) / range) * bounds.width;
  };
  const yForPrice = (price) => {
    const range = Math.max(1, priceMaximum - priceMinimum);
    return bounds.priceTop + ((priceMaximum - price) / range) * (bounds.priceBottom - bounds.priceTop);
  };

  drawChartFrame(bounds, width, height, rows, priceMinimum, priceMaximum);
  drawRegimeZones(bounds, rows, visibleStartTime, visibleEndTime, xForTime);
  drawCandles(bounds, rows, xForTime, yForPrice);
  drawCurrentPriceLine(bounds, rows, yForPrice);
  drawVolume(bounds, rows, xForTime, volumeMaximum);
  if (state.showDirectionalContext) {
    drawContextLane(bounds, visibleStartTime, visibleEndTime, xForTime);
  }
  drawTradingStateLane(bounds, rows, visibleStartTime, visibleEndTime, xForTime);
  if (state.showEventMarkers || state.showEventLabels) {
    drawModeShifts(bounds, visibleStartTime, visibleEndTime, xForTime);
    drawContextMarkers(bounds, rows, visibleStartTime, visibleEndTime, xForTime, yForPrice);
  }
  drawLaneGuides(bounds);
  drawPriceScale(bounds, priceMinimum, priceMaximum, yForPrice);
  drawTimeScale(bounds, rows, xForTime);
  drawCrosshair(bounds, rows, xForTime, yForPrice, priceMinimum, priceMaximum);
  updateOhlcLine(rows[rows.length - 1]);
}

function drawEmptyChart(width, height) {
  context.fillStyle = "rgba(148, 163, 184, 0.65)";
  context.textAlign = "center";
  context.font = "14px Inter, sans-serif";
  context.fillText("No candle data available for selected range.", width / 2, height / 2);
}

function drawChartFrame(bounds, width, height, rows, priceMinimum, priceMaximum) {
  const textColor = getCss("--muted");
  const gridColor = getThemeAwareGrid();
  context.strokeStyle = gridColor;
  context.lineWidth = 1;
  context.beginPath();
  for (let gridIndex = 0; gridIndex <= 5; gridIndex += 1) {
    const yCoord = bounds.priceTop + ((bounds.priceBottom - bounds.priceTop) / 5) * gridIndex;
    context.moveTo(bounds.left, yCoord);
    context.lineTo(bounds.right, yCoord);
  }
  for (let gridIndex = 0; gridIndex <= 8; gridIndex += 1) {
    const xCoord = bounds.left + (bounds.width / 8) * gridIndex;
    context.moveTo(xCoord, bounds.priceTop);
    context.lineTo(xCoord, bounds.volumeBottom);
  }
  context.stroke();

  context.fillStyle = textColor;
  context.font = "10px Inter, sans-serif";
  context.textAlign = "left";
  context.fillText(`${rows.length} bars · ${formatNumber(priceMinimum, 0)} — ${formatNumber(priceMaximum, 0)}`, bounds.left, 16);

  context.strokeStyle = getThemeAwareGrid();
  context.beginPath();
  context.moveTo(bounds.right + 0.5, bounds.priceTop);
  context.lineTo(bounds.right + 0.5, bounds.volumeBottom);
  context.stroke();
}

function drawRegimeZones(bounds, rows, visibleStartTime, visibleEndTime, xForTime) {
  const segments = mergeRowSegments(rows, "market_state");
  segments.forEach((segment) => {
    const startX = clamp(xForTime(Math.max(segment.start_time, visibleStartTime)), bounds.left, bounds.right);
    const endX = clamp(xForTime(Math.min(segment.end_time, visibleEndTime)), bounds.left, bounds.right);
    const width = Math.max(1, endX - startX);
    context.fillStyle = regimeColors[segment.state] || regimeColors["N/A"];
    context.fillRect(startX, bounds.priceTop, width, bounds.priceBottom - bounds.priceTop);
    if (width > 96 && state.showEventLabels && state.displayMode === "debug") {
      context.fillStyle = regimeSolidColors[segment.state] || regimeSolidColors["N/A"];
      context.font = "600 10px Inter, sans-serif";
      context.textAlign = "center";
      context.globalAlpha = 0.55;
      context.fillText(String(segment.state).slice(0, 18), startX + width / 2, bounds.priceTop + 16);
      context.globalAlpha = 1;
    }
  });
}

function mergeRowSegments(rows, field) {
  if (!rows.length) return [];
  const segments = [];
  let current = normalizeStateName(rows[0][field]);
  let startTime = rows[0].time;
  let endTime = rows[0].time;
  rows.slice(1).forEach((row) => {
    const next = normalizeStateName(row[field]);
    if (next === current) {
      endTime = row.time;
      return;
    }
    segments.push({ state: current, start_time: startTime, end_time: endTime });
    current = next;
    startTime = row.time;
    endTime = row.time;
  });
  segments.push({ state: current, start_time: startTime, end_time: endTime });
  return segments;
}

function drawCurrentPriceLine(bounds, rows, yForPrice) {
  const latestRow = rows[rows.length - 1];
  if (!latestRow) return;
  const latestY = yForPrice(latestRow.close);
  context.strokeStyle = "rgba(96, 165, 250, 0.55)";
  context.lineWidth = 1;
  context.setLineDash([5, 6]);
  context.beginPath();
  context.moveTo(bounds.left, latestY);
  context.lineTo(bounds.right, latestY);
  context.stroke();
  context.setLineDash([]);
}

function drawContextLane(bounds, visibleStartTime, visibleEndTime, xForTime) {
  const laneStart = bounds.left + bounds.laneLabelWidth;
  (state.data.context_episodes || [])
    .filter((episode) => (episode.end_time || visibleEndTime) >= visibleStartTime && episode.start_time <= visibleEndTime)
    .forEach((episode) => {
      const startX = clamp(xForTime(Math.max(episode.start_time, visibleStartTime)), laneStart, bounds.right);
      const endX = clamp(xForTime(Math.min(episode.end_time || visibleEndTime, visibleEndTime)), laneStart, bounds.right);
      const width = Math.max(1, endX - startX);
      context.fillStyle = episode.direction === "LONG" ? "rgba(48, 209, 88, 0.55)" : "rgba(255, 69, 58, 0.50)";
      context.fillRect(startX, bounds.contextLaneTop, width, bounds.contextLaneBottom - bounds.contextLaneTop);
      if (state.showContextLabels && width > 72) {
        context.fillStyle = "rgba(255,255,255,0.92)";
        context.font = "600 8px Inter, sans-serif";
        context.textAlign = "center";
        context.fillText(episode.direction === "LONG" ? "LONG" : "SHORT", startX + width / 2, (bounds.contextLaneTop + bounds.contextLaneBottom) / 2 + 3.5);
      }
    });
}

function drawTradingStateLane(bounds, rows, visibleStartTime, visibleEndTime, xForTime) {
  const laneStart = bounds.left + bounds.laneLabelWidth;
  mergeRowSegments(rows, "trading_state").forEach((segment) => {
    const startX = clamp(xForTime(Math.max(segment.start_time, visibleStartTime)), laneStart, bounds.right);
    const endX = clamp(xForTime(Math.min(segment.end_time, visibleEndTime)), bounds.left + bounds.laneLabelWidth, bounds.right);
    const width = Math.max(1, endX - startX);
    context.fillStyle = tradingStateLaneColors[segment.state] || tradingStateLaneColors["N/A"];
    context.fillRect(startX, bounds.tradingLaneTop, width, bounds.tradingLaneBottom - bounds.tradingLaneTop);
  });
}

function drawLaneGuides(bounds) {
  const laneStart = bounds.left + bounds.laneLabelWidth;
  context.strokeStyle = getThemeAwareGrid();
  context.lineWidth = 1;
  [bounds.volumeTop].forEach((yCoord) => {
    context.beginPath();
    context.moveTo(bounds.left, yCoord);
    context.lineTo(bounds.right, yCoord);
    context.stroke();
  });
  [bounds.contextLaneTop - 1, bounds.tradingLaneTop - 1].forEach((yCoord) => {
    context.beginPath();
    context.moveTo(laneStart, yCoord);
    context.lineTo(bounds.right, yCoord);
    context.stroke();
  });
  context.fillStyle = getCss("--text-secondary");
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.font = "600 10px Inter, sans-serif";
  context.fillText("Ctx", bounds.left + 1, (bounds.contextLaneTop + bounds.contextLaneBottom) / 2);
  context.fillText("State", bounds.left + 1, (bounds.tradingLaneTop + bounds.tradingLaneBottom) / 2);
}

function drawCandles(bounds, rows, xForTime, yForPrice) {
  const candleWidth = clamp((bounds.width / rows.length) * 0.64, 2, 16);
  rows.forEach((row) => {
    const xCoord = xForTime(row.time);
    const openY = yForPrice(row.open);
    const closeY = yForPrice(row.close);
    const highY = yForPrice(row.high);
    const lowY = yForPrice(row.low);
    const isUp = row.close >= row.open;
    const color = row.close >= row.open ? "rgba(48, 209, 88, 0.82)" : "rgba(255, 69, 58, 0.82)";
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(xCoord, highY);
    context.lineTo(xCoord, lowY);
    context.stroke();
    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(1, Math.abs(closeY - openY));
    context.globalAlpha = isUp ? 0.86 : 0.9;
    context.fillRect(xCoord - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
    context.globalAlpha = 1;
  });
}

function drawVolume(bounds, rows, xForTime, volumeMaximum) {
  const candleWidth = clamp((bounds.width / rows.length) * 0.64, 2, 16);
  rows.forEach((row) => {
    const volumeHeight = ((row.volume || 0) / volumeMaximum) * (bounds.volumeBottom - bounds.volumeTop);
    const xCoord = xForTime(row.time);
    context.fillStyle = row.close >= row.open ? "rgba(48, 209, 88, 0.28)" : "rgba(255, 69, 58, 0.28)";
    context.fillRect(xCoord - candleWidth / 2, bounds.volumeBottom - volumeHeight, candleWidth, volumeHeight);
  });
  context.strokeStyle = getThemeAwareGrid();
  context.beginPath();
  context.moveTo(bounds.left, bounds.volumeTop);
  context.lineTo(bounds.right, bounds.volumeTop);
  context.stroke();
}

function drawModeShifts(bounds, visibleStartTime, visibleEndTime, xForTime) {
  if (!state.showEventMarkers && !state.showEventLabels) return;
  const visibleModeShifts = (state.data.mode_shifts || [])
    .filter((eventItem) => eventItem.time >= visibleStartTime && eventItem.time <= visibleEndTime);
  const modeShifts = state.displayMode === "debug"
    ? visibleModeShifts
    : pickMajorModeShifts(visibleModeShifts, visibleStartTime, visibleEndTime);
  const labelPlacer = state.showEventLabels ? createLabelPlacer(bounds) : null;

  modeShifts.forEach((eventItem) => {
    const xCoord = xForTime(eventItem.time);
    if (state.showEventMarkers) {
      context.strokeStyle = "rgba(250, 204, 21, 0.55)";
      context.lineWidth = 1;
      context.setLineDash([2, 5]);
      context.beginPath();
      context.moveTo(xCoord, bounds.priceTop);
      context.lineTo(xCoord, bounds.priceBottom);
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = "#facc15";
      context.beginPath();
      context.arc(xCoord, bounds.priceTop + 6, 3, 0, Math.PI * 2);
      context.fill();
    }
    if (state.showEventLabels) {
      drawLabelBox(xCoord, bounds.priceTop + 14, "Regime shift", eventItem.reason, "#facc15", labelPlacer);
    }
  });
}

function drawContextMarkers(bounds, rows, visibleStartTime, visibleEndTime, xForTime, yForPrice) {
  if (!state.showEventMarkers && !state.showEventLabels) return;
  const eventSource = (state.data.context_events || [])
    .filter((eventItem) => eventItem.time >= visibleStartTime && eventItem.time <= visibleEndTime);

  const labelPlacer = state.showEventLabels ? createLabelPlacer(bounds) : null;
  eventSource.forEach((eventItem) => {
    const eventRow = findNearestRow(rows, eventItem.time);
    if (!eventRow) return;
    const eventX = xForTime(eventItem.time);
    const isStart = eventItem.event_type === "CONTEXT_START";
    const isLong = eventItem.direction === "LONG";
    const markerColor = isStart ? (isLong ? "#22c55e" : "#ff526b") : "#facc15";

    if (state.showEventMarkers) {
      const yCoord = bounds.priceBottom - 8;
      drawTriangle(eventX, yCoord, isStart && isLong ? "up" : "down", markerColor, 4);
    }

    if (state.showEventLabels) {
      const subtitle = eventItem.event_type === "CONTEXT_END"
        ? `${eventItem.duration_bars ?? "—"} bars`
        : eventItem.direction === "LONG"
          ? "Long context"
          : "Short context";
      drawLabelBox(eventX, bounds.priceTop + 18, eventItem.label, subtitle, markerColor, labelPlacer);
    }
  });
}

function drawTriangle(centerX, centerY, direction, color, size = 7) {
  context.fillStyle = color;
  context.beginPath();
  if (direction === "up") {
    context.moveTo(centerX, centerY - size);
    context.lineTo(centerX - size, centerY + size - 2);
    context.lineTo(centerX + size, centerY + size - 2);
  } else {
    context.moveTo(centerX, centerY + size);
    context.lineTo(centerX - size, centerY - size + 2);
    context.lineTo(centerX + size, centerY - size + 2);
  }
  context.closePath();
  context.fill();
}

function pickMajorModeShifts(events, visibleStartTime, visibleEndTime) {
  if (events.length <= 8) return events;
  const minimumGap = Math.max(45 * 60, (visibleEndTime - visibleStartTime) / 9);
  const majorStates = new Set(["ACCUMULATION", "DISTRIBUTION", "REVERSAL", "TREND_CONTINUATION", "NEUTRAL"]);
  const picked = [];
  events.forEach((eventItem) => {
    const isMajorState = majorStates.has(eventItem.from_state) || majorStates.has(eventItem.to_state);
    const farEnough = !picked.length || eventItem.time - picked[picked.length - 1].time >= minimumGap;
    if (isMajorState && farEnough) picked.push(eventItem);
  });
  return picked.length ? picked : events.filter((_, index) => index % Math.ceil(events.length / 8) === 0);
}

function groupEventsByX(events, xForTime, thresholdPx) {
  const groups = [];
  events.forEach((eventItem) => {
    const xCoord = xForTime(eventItem.time);
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && Math.abs(xForTime(lastGroup[lastGroup.length - 1].time) - xCoord) <= thresholdPx) {
      lastGroup.push(eventItem);
      return;
    }
    groups.push([eventItem]);
  });
  return groups;
}

function createLabelPlacer(bounds) {
  const occupied = [];
  return function placeLabel(centerX, desiredTop, width, height) {
    const left = clamp(centerX - width / 2, bounds.left + 4, bounds.right - width - 4);
    const candidateOffsets = [0, 28, -28, 56, -56, 84, -84, 112, -112];
    for (const offset of candidateOffsets) {
      const top = clamp(desiredTop + offset, bounds.priceTop + 8, bounds.volumeTop - height - 18);
      const box = { left, top, right: left + width, bottom: top + height };
      const collides = occupied.some((used) => !(box.right < used.left || box.left > used.right || box.bottom < used.top || box.top > used.bottom));
      if (!collides) {
        occupied.push(box);
        return top;
      }
    }
    return null;
  };
}

function regimeShortLabel(value) {
  if (value === "TREND_CONTINUATION") return "Markup";
  if (value === "REVERSAL") return "Reversal";
  if (value === "ACCUMULATION") return "Accumulation";
  if (value === "DISTRIBUTION") return "Distribution";
  if (value === "NEUTRAL") return "Neutral";
  return value || "N/A";
}


function drawLabelBox(centerX, topY, title, subtitle, color, labelPlacer = null) {
  const titleText = String(title || "").slice(0, 24);
  const subtitleText = String(subtitle || "").slice(0, 34);
  const width = Math.max(92, Math.min(172, Math.max(titleText.length, subtitleText.length) * 6.6 + 18));
  const height = subtitleText ? 38 : 26;
  const placedTop = labelPlacer ? labelPlacer(centerX, topY, width, height) : topY;
  if (placedTop === null) {
    return;
  }
  const left = centerX - width / 2;
  context.fillStyle = "rgba(5, 9, 17, 0.78)";
  context.strokeStyle = color;
  context.lineWidth = 1;
  roundedRect(left, placedTop, width, height, 8);
  context.fill();
  context.stroke();
  context.fillStyle = color;
  context.textAlign = "center";
  context.font = "700 10px Inter, sans-serif";
  context.fillText(titleText, centerX, placedTop + 15);
  if (subtitleText) {
    context.fillStyle = getCss("--text");
    context.font = "9px Inter, sans-serif";
    context.fillText(subtitleText, centerX, placedTop + 29);
  }
}

function roundedRect(left, top, width, height, radius) {
  context.beginPath();
  context.moveTo(left + radius, top);
  context.arcTo(left + width, top, left + width, top + height, radius);
  context.arcTo(left + width, top + height, left, top + height, radius);
  context.arcTo(left, top + height, left, top, radius);
  context.arcTo(left, top, left + width, top, radius);
  context.closePath();
}

function drawPriceScale(bounds, priceMinimum, priceMaximum, yForPrice) {
  const badgeWidth = Math.max(44, bounds.priceScaleRight - bounds.priceScaleLeft - 2);
  context.fillStyle = getCss("--text-secondary");
  context.font = "11px Inter, sans-serif";
  context.textAlign = "right";
  context.textBaseline = "alphabetic";
  for (let gridIndex = 0; gridIndex <= 5; gridIndex += 1) {
    const price = priceMinimum + ((priceMaximum - priceMinimum) / 5) * gridIndex;
    const yCoord = yForPrice(price);
    context.fillText(formatNumber(price, 0), bounds.priceScaleRight, yCoord + 4);
  }

  const latestRow = state.selectedRows[state.selectedRows.length - 1];
  if (latestRow) {
    const latestY = yForPrice(latestRow.close);
    context.fillStyle = getCss("--accent-blue") || "#0a84ff";
    context.fillRect(bounds.priceScaleLeft, latestY - 10, badgeWidth, 20);
    context.fillStyle = "#ffffff";
    context.textAlign = "center";
    context.font = "700 10.5px Inter, sans-serif";
    context.fillText(formatNumber(latestRow.close, 2), bounds.priceScaleLeft + badgeWidth / 2, latestY + 4);
  }
}

function drawTimeScale(bounds, rows, xForTime) {
  const labelCount = Math.min(8, rows.length);
  context.fillStyle = getCss("--muted");
  context.font = "11px Inter, sans-serif";
  context.textAlign = "center";
  for (let labelIndex = 0; labelIndex < labelCount; labelIndex += 1) {
    const rowIndex = Math.floor((rows.length - 1) * (labelIndex / Math.max(1, labelCount - 1)));
    const row = rows[rowIndex];
    context.fillText(formatTime(row.time, labelIndex === 0 || labelIndex === labelCount - 1), xForTime(row.time), bounds.bottom + 19);
  }
}

function drawCrosshair(bounds, rows, xForTime, yForPrice, priceMinimum, priceMaximum) {
  if (!state.pointer) {
    tooltip.classList.add("hidden");
    return;
  }
  const pointer = state.pointer;
  if (pointer.x < bounds.left || pointer.x > bounds.right || pointer.y < bounds.priceTop || pointer.y > bounds.volumeBottom) {
    tooltip.classList.add("hidden");
    return;
  }

  const nearest = findNearestRowByX(rows, pointer.x, xForTime);
  if (!nearest) return;
  context.strokeStyle = "rgba(148, 163, 184, 0.48)";
  context.lineWidth = 1;
  context.setLineDash([3, 5]);
  context.beginPath();
  const xCoord = xForTime(nearest.time);
  context.moveTo(xCoord, bounds.priceTop);
  context.lineTo(xCoord, bounds.volumeBottom);
  context.moveTo(bounds.left, pointer.y);
  context.lineTo(bounds.right, pointer.y);
  context.stroke();
  context.setLineDash([]);

  const priceAtPointer = priceMaximum - ((pointer.y - bounds.priceTop) / (bounds.priceBottom - bounds.priceTop)) * (priceMaximum - priceMinimum);
  tooltip.innerHTML = `
    <strong>${formatDateTime(nearest.time)}</strong><br />
    O ${formatNumber(nearest.open, 2)} · H ${formatNumber(nearest.high, 2)} · L ${formatNumber(nearest.low, 2)} · C ${formatNumber(nearest.close, 2)}<br />
    Volume ${formatNumber(nearest.volume, 2)} · Cursor ${formatNumber(priceAtPointer, 2)}<br />
    Regime: <strong>${escapeHtml(nearest.market_state)}</strong><br />
    Trading State: <strong>${escapeHtml(nearest.trading_state)}</strong><br />
    Bias: ${escapeHtml(nearest.location_bias)} · Confidence ${formatNumber(nearest.market_state_confidence, 3)}<br />
    Conviction ${formatNumber(nearest.conviction_probability, 3)} · Absorption ${formatNumber(nearest.absorption_probability, 3)} · Distribution ${formatNumber(nearest.distribution_probability, 3)}
  `;
  const tooltipLeft = clamp(pointer.x + 18, 12, bounds.right - 280);
  const tooltipTop = clamp(pointer.y + 18, 12, bounds.volumeBottom - 160);
  tooltip.style.left = `${tooltipLeft}px`;
  tooltip.style.top = `${tooltipTop}px`;
  tooltip.classList.remove("hidden");
}

function findNearestRow(rows, timestampSeconds) {
  if (!rows.length) return null;
  let nearestRow = rows[0];
  let nearestDelta = Math.abs(rows[0].time - timestampSeconds);
  rows.forEach((row) => {
    const delta = Math.abs(row.time - timestampSeconds);
    if (delta < nearestDelta) {
      nearestRow = row;
      nearestDelta = delta;
    }
  });
  return nearestRow;
}

function findNearestRowByX(rows, pointerX, xForTime) {
  if (!rows.length) return null;
  let nearestRow = rows[0];
  let nearestDelta = Math.abs(xForTime(rows[0].time) - pointerX);
  rows.forEach((row) => {
    const delta = Math.abs(xForTime(row.time) - pointerX);
    if (delta < nearestDelta) {
      nearestRow = row;
      nearestDelta = delta;
    }
  });
  return nearestRow;
}

function updateOhlcLine(row) {
  if (!row) return;
  const direction = row.close >= row.open ? "+" : "";
  const changePct = ((row.close - row.open) / row.open) * 100;
  document.getElementById("ohlcLine").textContent = `O ${formatNumber(row.open, 2)} · H ${formatNumber(row.high, 2)} · L ${formatNumber(row.low, 2)} · C ${formatNumber(row.close, 2)} · ${direction}${formatNumber(changePct, 2)}% · Volume ${formatNumber(row.volume, 2)}`;
}

function getCss(variableName) {
  return getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
}

function getThemeAwareGrid() {
  return document.documentElement.dataset.theme === "light"
    ? "rgba(30, 41, 59, 0.10)"
    : "rgba(148, 163, 184, 0.13)";
}

function formatContextEventLabel(eventItem) {
  const label = eventItem.label || eventItem.event_type || "—";
  if (label === "CONTEXT START") return "Context started";
  if (label === "CONTEXT END") return "Context ended";
  if (eventItem.event_type === "CONTEXT_START") return "Context started";
  if (eventItem.event_type === "CONTEXT_END") return "Context ended";
  return label;
}

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("DOMContentLoaded", init);
