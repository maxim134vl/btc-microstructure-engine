import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type {
  CognitiveRegime,
  DecisionMarker,
  DirectionalContextEpisode,
  MarketStateRegime,
  MarketStateRow,
  MarketStateSnapshot,
  MarketStateTransition,
  SetupLifecycle,
} from "../../types/marketState";
import {
  cognitiveRegimeColor,
  contextEpisodeColor,
  decisionColor,
  decisionLabel,
  formatConfidenceScore,
  MARKET_STATE_TRANSITION_COLOR,
  marketStateRegimeColor,
  regimeColor,
  shortTransitionLabel,
} from "./marketStateChartStyles";
import type { ChartViewCommand } from "./marketStateSelection";

interface RegimeRect {
  id: string;
  left: number;
  width: number;
  label: string;
  meta: string;
  color: string;
  isActive?: boolean;
}

interface DecisionCallout {
  id: string;
  left: number;
  label: string;
  subtitle: string;
  reason: string;
  color: string;
  side: "top" | "bottom";
}

interface LifecycleBand {
  id: string;
  left: number;
  width: number;
  label: string;
  meta: string;
  color: string;
}

interface ContextBand {
  id: string;
  left: number;
  width: number;
  label: string;
  meta: string;
  color: string;
  isActive: boolean;
}

interface TooltipState {
  x: number;
  y: number;
  title: string;
  rows: Array<[string, string]>;
}

interface ChartTheme {
  background: string;
  surface: string;
  textPrimary: string;
  textSecondary: string;
  border: string;
  accent: string;
  healthy: string;
  warning: string;
  error: string;
  idle: string;
}

interface MarketStateChartProps {
  snapshot: MarketStateSnapshot;
  showMarketStateRegimes: boolean;
  showCognitiveRegimes: boolean;
  showTransitions: boolean;
  showDirectionalContext: boolean;
  showDecisions: boolean;
  showVolume: boolean;
  showOverlayLabels: boolean;
  autoScroll: boolean;
  viewCommand: ChartViewCommand | null;
}

function applyChartView(chart: IChartApi, action: ChartViewCommand["action"], autoScroll: boolean): void {
  const timeScale = chart.timeScale();
  if (action === "fit") {
    timeScale.fitContent();
    return;
  }
  if (action === "latest") {
    timeScale.scrollToRealTime();
    return;
  }
  timeScale.resetTimeScale();
  if (autoScroll) {
    timeScale.scrollToRealTime();
  } else {
    timeScale.fitContent();
  }
}

function toUtcTimestamp(timestamp: string | number | null | undefined): UTCTimestamp | null {
  if (timestamp == null) return null;
  if (typeof timestamp === "number") return timestamp as UTCTimestamp;
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return null;
  return Math.floor(parsed / 1000) as UTCTimestamp;
}

function formatMetric(value?: number | null, digits = 3): string {
  return value == null || Number.isNaN(value) ? "N/A" : value.toFixed(digits);
}

function compactTime(value?: string | null): string {
  if (!value) return "N/A";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type BarMarkerPosition = "aboveBar" | "belowBar" | "inBar";

function cssVar(style: CSSStyleDeclaration, name: string, fallback: string): string {
  return style.getPropertyValue(name).trim() || fallback;
}

function readChartTheme(container: HTMLElement): ChartTheme {
  const scope = container.closest(".ops-surface") ?? document.documentElement;
  const style = getComputedStyle(scope);
  return {
    background: cssVar(style, "--ds-color-surface", "#1b2028"),
    surface: cssVar(style, "--ds-color-surface-secondary", "#151922"),
    textPrimary: cssVar(style, "--ds-color-text-primary", "#f5f5f7"),
    textSecondary: cssVar(style, "--ds-color-text-secondary", "#a1a6b0"),
    border: cssVar(style, "--ds-color-border", "rgba(148,163,184,0.25)"),
    accent: cssVar(style, "--ds-color-accent", "#0a84ff"),
    healthy: cssVar(style, "--ds-status-healthy", "#30d158"),
    warning: cssVar(style, "--ds-status-warning", "#ff9f0a"),
    error: cssVar(style, "--ds-status-error", "#ff453a"),
    idle: cssVar(style, "--ds-status-idle", "#98989d"),
  };
}

function markerShape(decision: string): SeriesMarker<Time>["shape"] {
  if (decision === "LONG_SETUP") return "arrowUp";
  if (decision === "SHORT_SETUP" || decision.startsWith("EXIT")) return "arrowDown";
  return "circle";
}

function markerPosition(decision: string): BarMarkerPosition {
  if (decision === "LONG_SETUP") return "belowBar";
  return "aboveBar";
}

function decisionSide(decision: string): DecisionCallout["side"] {
  return decision === "LONG_SETUP" ? "bottom" : "top";
}

function buildMarkers(decisions: DecisionMarker[]): SeriesMarker<Time>[] {
  return decisions
    .map((decision): SeriesMarker<Time> | null => {
      const time = toUtcTimestamp(decision.time);
      if (time == null) return null;
      const state = decision.trade_decision ?? decision.decision_state ?? "NO_SETUP";
      return {
        time,
        position: markerPosition(state),
        shape: markerShape(state),
        color: decisionColor(state),
        text: decisionLabel(state),
        size: 1.6,
      };
    })
    .filter((marker): marker is SeriesMarker<Time> => marker !== null);
}

function buildTransitionMarkers(transitions: MarketStateTransition[]): SeriesMarker<Time>[] {
  return transitions
    .map((transition): SeriesMarker<Time> | null => {
      const time = toUtcTimestamp(transition.timestamp);
      if (time == null) return null;
      const label = shortTransitionLabel(transition.from_market_state, transition.to_market_state);
      return {
        time,
        position: "aboveBar",
        shape: "circle",
        color: MARKET_STATE_TRANSITION_COLOR,
        text: label.length <= 12 ? label : "MS chg",
        size: 1.1,
      };
    })
    .filter((marker): marker is SeriesMarker<Time> => marker !== null);
}

function lifecycleLineData(lifecycle: SetupLifecycle, lastTime: UTCTimestamp | null): LineData<Time>[] {
  const start = toUtcTimestamp(lifecycle.start_timestamp);
  const end = toUtcTimestamp(lifecycle.end_timestamp) ?? lastTime;
  const price = lifecycle.entry_price;
  if (start == null || end == null || price == null) return [];
  return [
    { time: start, value: price },
    { time: end, value: price },
  ];
}

function setupLabel(lifecycle: SetupLifecycle): string {
  const prefix = lifecycle.setup_direction === "LONG" ? "LONG" : "SHORT";
  const status = lifecycle.end_timestamp ? "EXIT" : "ACTIVE";
  return `${prefix} ${status}`;
}

function initialBarSpacing(barCount: number): number {
  if (barCount >= 500) return 2.2;
  if (barCount >= 250) return 3.2;
  if (barCount >= 100) return 5;
  return 8;
}

function tooltipRows(row: MarketStateRow | undefined, decision: DecisionMarker | undefined): Array<[string, string]> {
  if (!row && !decision) return [];
  const tradeDecision = decision?.trade_decision ?? row?.trade_decision ?? row?.decision_state ?? "NO_SETUP";
  const cognitiveState = decision?.cognitive_state ?? row?.cognitive_state ?? "N/A";
  const explanation = row?.confidence_explanation;
  const rows: Array<[string, string]> = [
    ["Trade Decision", String(tradeDecision)],
    ["Cognitive State", String(cognitiveState)],
    ["Market State", String(decision?.market_state ?? row?.market_state ?? "N/A")],
    ["Trading State", String(decision?.trading_state ?? row?.trading_state ?? "N/A")],
    ["Setup", String(decision?.setup_id ?? row?.setup_id ?? "N/A")],
    ["Reason", String(decision?.decision_reason ?? row?.decision_reason ?? "N/A")],
    ["Cognition", String(decision?.cognition_state ?? row?.cognition_state ?? "N/A")],
    ["Synthesis", String(decision?.synthesis_state ?? row?.synthesis_state ?? "N/A")],
    ["Prob. regime", String(decision?.probabilistic_regime ?? row?.probabilistic_regime ?? "N/A")],
    ["Location", String(decision?.location_bias ?? row?.location_bias ?? "N/A")],
    ["Alignment", formatMetric(decision?.alignment_score ?? row?.alignment_score)],
    ["Persistence", formatMetric(decision?.persistence_score ?? row?.persistence_score)],
    ["Confidence", formatMetric(decision?.market_state_confidence ?? row?.market_state_confidence ?? decision?.conviction_probability ?? row?.conviction_probability)],
    ["Absorption", formatMetric(decision?.absorption_probability ?? row?.absorption_probability)],
    ["Distribution", formatMetric(decision?.distribution_probability ?? row?.distribution_probability)],
  ];
  if (explanation) {
    rows.push(
      ["Conf. Level", explanation.level],
      ["Conf. Score", formatConfidenceScore(explanation.score)],
      ["Conf. Summary", explanation.summary],
    );
    if (explanation.drivers.length) {
      rows.push(["Conf. Drivers", explanation.drivers.join(" · ")]);
    }
    if (explanation.suppressors.length) {
      rows.push(["Conf. Suppressors", explanation.suppressors.join(" · ")]);
    }
  }
  return rows;
}

function useCognitiveRegimeOverlay(
  chart: IChartApi | null,
  regimes: CognitiveRegime[],
  enabled: boolean,
  secondary: boolean,
): RegimeRect[] {
  const [rects, setRects] = useState<RegimeRect[]>([]);

  useEffect(() => {
    if (!chart || !enabled) {
      setRects([]);
      return;
    }

    const update = () => {
      const timeScale = chart.timeScale();
      const width = timeScale.width();
      const next = regimes
        .map((regime, index): RegimeRect | null => {
          const start = toUtcTimestamp(regime.start_timestamp);
          const end = toUtcTimestamp(regime.end_timestamp);
          if (start == null || end == null) return null;
          const left = timeScale.timeToCoordinate(start);
          const right = timeScale.timeToCoordinate(end);
          if (left == null && right == null) return null;
          const clampedLeft = Math.max(0, left ?? 0);
          const clampedRight = Math.min(width, (right ?? width) + 12);
          if (clampedRight < 0 || clampedLeft > width) return null;
          const color = secondary ? cognitiveRegimeColor(index) : regimeColor(index);
          return {
            id: regime.regime_id,
            left: clampedLeft,
            width: Math.max(2, clampedRight - clampedLeft),
            label: secondary ? regime.primary_state : regime.primary_state,
            meta: secondary
              ? `Cognitive · ${regime.duration_bars} bars · conv ${formatMetric(regime.avg_conviction, 2)}`
              : `${regime.duration_bars} bars · conv ${formatMetric(regime.avg_conviction, 2)}`,
            color,
          };
        })
        .filter((rect): rect is RegimeRect => rect !== null);
      setRects(next);
    };

    update();
    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    return () => chart.timeScale().unsubscribeVisibleTimeRangeChange(update);
  }, [chart, enabled, regimes, secondary]);

  return rects;
}

function useMarketStateRegimeOverlay(
  chart: IChartApi | null,
  regimes: MarketStateRegime[],
  enabled: boolean,
): RegimeRect[] {
  const [rects, setRects] = useState<RegimeRect[]>([]);

  useEffect(() => {
    if (!chart || !enabled || regimes.length === 0) {
      setRects([]);
      return;
    }

    const update = () => {
      const timeScale = chart.timeScale();
      const width = timeScale.width();
      const next = regimes
        .map((regime): RegimeRect | null => {
          const start = toUtcTimestamp(regime.start_timestamp);
          const end = toUtcTimestamp(regime.end_timestamp);
          if (start == null || end == null) return null;
          const left = timeScale.timeToCoordinate(start);
          const right = timeScale.timeToCoordinate(end);
          if (left == null && right == null) return null;
          const clampedLeft = Math.max(0, left ?? 0);
          const clampedRight = Math.min(width, (right ?? width) + 12);
          if (clampedRight < 0 || clampedLeft > width) return null;
          return {
            id: regime.regime_id,
            left: clampedLeft,
            width: Math.max(2, clampedRight - clampedLeft),
            label: regime.market_state,
            meta: `Market State · ${regime.duration_bars} bars · conf ${formatConfidenceScore(regime.market_state_confidence)}${regime.confidence_level ? ` · ${regime.confidence_level}` : ""}`,
            color: marketStateRegimeColor(regime.market_state, regime.is_active),
            isActive: regime.is_active,
          };
        })
        .filter((rect): rect is RegimeRect => rect !== null);
      setRects(next);
    };

    update();
    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    return () => chart.timeScale().unsubscribeVisibleTimeRangeChange(update);
  }, [chart, enabled, regimes]);

  return rects;
}

function useContextEpisodeOverlay(
  chart: IChartApi | null,
  episodes: DirectionalContextEpisode[],
  enabled: boolean,
): ContextBand[] {
  const [bands, setBands] = useState<ContextBand[]>([]);

  useEffect(() => {
    if (!chart || !enabled || episodes.length === 0) {
      setBands([]);
      return;
    }

    const update = () => {
      const timeScale = chart.timeScale();
      const width = timeScale.width();
      const next = episodes
        .map((episode): ContextBand | null => {
          const start = toUtcTimestamp(episode.start_timestamp);
          const end = toUtcTimestamp(episode.end_timestamp);
          if (start == null || end == null) return null;
          const left = timeScale.timeToCoordinate(start);
          const right = timeScale.timeToCoordinate(end);
          if (left == null && right == null) return null;
          const clampedLeft = Math.max(0, left ?? 0);
          const clampedRight = Math.min(width, (right ?? width) + 12);
          if (clampedRight < 0 || clampedLeft > width) return null;
          return {
            id: episode.episode_id,
            left: clampedLeft,
            width: Math.max(2, clampedRight - clampedLeft),
            label: episode.direction === "LONG" ? "Long context" : "Short context",
            meta: `Directional Context · ${episode.duration_bars} bars`,
            color: contextEpisodeColor(episode.direction, episode.is_active),
            isActive: episode.is_active,
          };
        })
        .filter((band): band is ContextBand => band !== null);
      setBands(next);
    };

    update();
    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    return () => chart.timeScale().unsubscribeVisibleTimeRangeChange(update);
  }, [chart, enabled, episodes]);

  return bands;
}

function useRegimeOverlay(
  chart: IChartApi | null,
  regimes: CognitiveRegime[],
  enabled: boolean,
): RegimeRect[] {
  return useCognitiveRegimeOverlay(chart, regimes, enabled, false);
}

function useDecisionOverlay(
  chart: IChartApi | null,
  decisions: DecisionMarker[],
  enabled: boolean,
): DecisionCallout[] {
  const [callouts, setCallouts] = useState<DecisionCallout[]>([]);

  useEffect(() => {
    if (!chart || !enabled) {
      setCallouts([]);
      return;
    }

    const update = () => {
      const timeScale = chart.timeScale();
      const width = timeScale.width();
      const next = decisions
        .map((decision, index): DecisionCallout | null => {
          const time = toUtcTimestamp(decision.time);
          if (time == null) return null;
          const x = timeScale.timeToCoordinate(time);
          if (x == null || x < -120 || x > width + 120) return null;
          const state = String(decision.trade_decision ?? decision.decision_state ?? "NO_SETUP");
          return {
            id: `${decision.timestamp}-${state}-${index}`,
            left: Math.max(8, Math.min(width - 96, x - 48)),
            label: decisionLabel(state),
            subtitle: compactTime(decision.timestamp),
            reason: decision.decision_reason ?? decision.exit_reason ?? "Runtime transition",
            color: decisionColor(state),
            side: decisionSide(state),
          };
        })
        .filter((callout): callout is DecisionCallout => callout !== null);
      setCallouts(next);
    };

    update();
    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    return () => chart.timeScale().unsubscribeVisibleTimeRangeChange(update);
  }, [chart, decisions, enabled]);

  return callouts;
}

function useLifecycleOverlay(
  chart: IChartApi | null,
  lifecycles: SetupLifecycle[],
  lastTime: UTCTimestamp | null,
  enabled: boolean,
): LifecycleBand[] {
  const [bands, setBands] = useState<LifecycleBand[]>([]);

  useEffect(() => {
    if (!chart || !enabled) {
      setBands([]);
      return;
    }

    const update = () => {
      const timeScale = chart.timeScale();
      const width = timeScale.width();
      const next = lifecycles
        .slice(-40)
        .map((lifecycle): LifecycleBand | null => {
          const start = toUtcTimestamp(lifecycle.start_timestamp);
          const end = toUtcTimestamp(lifecycle.end_timestamp) ?? lastTime;
          if (start == null || end == null) return null;
          const left = timeScale.timeToCoordinate(start);
          const right = timeScale.timeToCoordinate(end);
          if (left == null && right == null) return null;
          const clampedLeft = Math.max(0, left ?? 0);
          const clampedRight = Math.min(width, right ?? width);
          if (clampedRight < 0 || clampedLeft > width) return null;
          return {
            id: lifecycle.setup_id,
            left: clampedLeft,
            width: Math.max(24, clampedRight - clampedLeft),
            label: setupLabel(lifecycle),
            meta: `${lifecycle.duration_bars ?? "N/A"} bars`,
            color: lifecycle.setup_direction === "LONG" ? decisionColor("LONG_SETUP") : decisionColor("SHORT_SETUP"),
          };
        })
        .filter((band): band is LifecycleBand => band !== null);
      setBands(next);
    };

    update();
    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    return () => chart.timeScale().unsubscribeVisibleTimeRangeChange(update);
  }, [chart, enabled, lastTime, lifecycles]);

  return bands;
}

export function MarketStateChart({
  snapshot,
  showMarketStateRegimes,
  showCognitiveRegimes,
  showTransitions,
  showDirectionalContext,
  showDecisions,
  showVolume,
  showOverlayLabels,
  autoScroll,
  viewCommand,
}: MarketStateChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartApi, setChartApi] = useState<IChartApi | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [themeVersion, setThemeVersion] = useState(0);
  const lifecycleSeriesRef = useRef<Array<ISeriesApi<"Line", Time>>>([]);

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeVersion((value) => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => observer.disconnect();
  }, []);

  const rowByTime = useMemo(() => {
    const map = new Map<number, MarketStateRow>();
    snapshot.dashboard_market_state_df.forEach((row) => {
      const time = toUtcTimestamp(row.timestamp);
      if (time != null) map.set(time as number, row);
    });
    return map;
  }, [snapshot.dashboard_market_state_df]);

  const decisionByTime = useMemo(() => {
    const map = new Map<number, DecisionMarker>();
    snapshot.decisions.forEach((decision) => {
      const time = toUtcTimestamp(decision.time);
      if (time != null) map.set(time as number, decision);
    });
    return map;
  }, [snapshot.decisions]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    container.innerHTML = "";
    lifecycleSeriesRef.current = [];
    const theme = readChartTheme(container);

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: theme.background },
        textColor: theme.textSecondary,
        fontFamily: "Inter, ui-sans-serif, system-ui",
      },
      grid: {
        vertLines: { color: theme.border },
        horzLines: { color: theme.border },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: theme.textSecondary, labelBackgroundColor: theme.surface },
        horzLine: { color: theme.textSecondary, labelBackgroundColor: theme.surface },
      },
      rightPriceScale: {
        borderColor: theme.border,
        scaleMargins: showVolume ? { top: 0.08, bottom: 0.24 } : { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: theme.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 12,
        barSpacing: initialBarSpacing(snapshot.candles.length),
        fixLeftEdge: false,
        fixRightEdge: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      localization: {
        priceFormatter: (price: number) =>
          price.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }),
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: theme.healthy,
      downColor: theme.error,
      borderUpColor: theme.healthy,
      borderDownColor: theme.error,
      wickUpColor: theme.healthy,
      wickDownColor: theme.error,
      priceLineColor: theme.accent,
      lastValueVisible: true,
      priceLineVisible: true,
    });

    candleSeries.setData(
      snapshot.candles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );

    if (showVolume) {
      const volumeSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          lastValueVisible: false,
          priceLineVisible: false,
        },
        1,
      );
      volumeSeries.setData(
        snapshot.volume.map((bar) => ({
          time: bar.time as UTCTimestamp,
          value: bar.value,
          color: bar.color,
        })),
      );
      chart.panes()[1]?.setHeight(120);
    }

    const chartMarkers = [
      ...(showDecisions ? buildMarkers(snapshot.decisions) : []),
      ...(showTransitions ? buildTransitionMarkers(snapshot.market_state_transitions ?? []) : []),
    ];
    if (chartMarkers.length) {
      createSeriesMarkers(candleSeries, chartMarkers);
    }

    const lastTime = snapshot.candles.length
      ? (snapshot.candles[snapshot.candles.length - 1].time as UTCTimestamp)
      : null;

    snapshot.setup_lifecycles.slice(-30).forEach((lifecycle) => {
      const data = lifecycleLineData(lifecycle, lastTime);
      if (data.length === 0) return;
      const line = chart.addSeries(LineSeries, {
        color: lifecycle.setup_direction === "LONG" ? theme.healthy : theme.error,
        lineWidth: 2,
        lineStyle: 2,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      line.setData(data);
      lifecycleSeriesRef.current.push(line);
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.point || !param.time) {
        setTooltip(null);
        return;
      }
      const time = typeof param.time === "number" ? param.time : Number.NaN;
      if (!Number.isFinite(time)) {
        setTooltip(null);
        return;
      }
      const row = rowByTime.get(time);
      const decision = decisionByTime.get(time);
      if (!row && !decision) {
        setTooltip(null);
        return;
      }
      setTooltip({
        x: Math.min(param.point.x + 18, Math.max(260, container.clientWidth - 320)),
        y: Math.max(12, param.point.y - 24),
        title: compactTime(row?.timestamp ?? decision?.timestamp),
        rows: tooltipRows(row, decision),
      });
    });

    if (autoScroll) {
      chart.timeScale().scrollToRealTime();
    } else {
      chart.timeScale().fitContent();
    }

    setChartApi(chart);
    return () => {
      setTooltip(null);
      setChartApi(null);
      lifecycleSeriesRef.current = [];
      chart.remove();
    };
  }, [
    autoScroll,
    decisionByTime,
    rowByTime,
    showDecisions,
    showMarketStateRegimes,
    showCognitiveRegimes,
    showTransitions,
    showDirectionalContext,
    showVolume,
    themeVersion,
    snapshot.candles,
    snapshot.decisions,
    snapshot.market_state_transitions,
    snapshot.setup_lifecycles,
    snapshot.volume,
  ]);

  useEffect(() => {
    if (!chartApi || !viewCommand) return;
    applyChartView(chartApi, viewCommand.action, autoScroll);
  }, [autoScroll, chartApi, viewCommand]);

  const lastCandleTime = snapshot.candles.length
    ? (snapshot.candles[snapshot.candles.length - 1].time as UTCTimestamp)
    : null;
  const engineRegimes = snapshot.market_state_regimes ?? [];
  const hasEngineRegimes = engineRegimes.length > 0;
  const cognitiveRegimeRects = useCognitiveRegimeOverlay(
    chartApi,
    snapshot.regimes,
    showCognitiveRegimes && hasEngineRegimes,
    true,
  );
  const legacyRegimeRects = useRegimeOverlay(chartApi, snapshot.regimes, showCognitiveRegimes && !hasEngineRegimes);
  const marketStateRegimeRects = useMarketStateRegimeOverlay(chartApi, engineRegimes, showMarketStateRegimes && hasEngineRegimes);
  const contextBands = useContextEpisodeOverlay(chartApi, snapshot.directional_context_episodes ?? [], showDirectionalContext);
  const decisionCallouts = useDecisionOverlay(chartApi, snapshot.decisions, showDecisions && showOverlayLabels);
  const lifecycleBands = useLifecycleOverlay(chartApi, snapshot.setup_lifecycles, lastCandleTime, showDecisions && showOverlayLabels);
  const rangeLabel = snapshot.range === "all" ? "Full available history" : `${snapshot.bar_count} bars loaded`;

  return (
    <section className="flex h-full min-h-[520px] flex-col overflow-hidden rounded-xl border border-ds-border/60 bg-ds-surface">
      <div className="flex items-center justify-between gap-3 border-b border-ds-border/50 px-4 py-2">
        <div className="min-w-0">
          <div className="flex items-center gap-3 text-[12px] text-ds-text-primary">
            <span className="font-semibold">BTCUSDT · {snapshot.timeframe}</span>
            {snapshot.candles.at(-1) ? (
              <span className="font-mono text-[color:var(--ds-status-healthy)]">
                C {snapshot.candles.at(-1)?.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 truncate text-[11px] text-ds-text-secondary">
            {rangeLabel}
            {snapshot.time_range?.start ? ` · ${compactTime(snapshot.time_range.start)} → ${compactTime(snapshot.time_range.end)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => chartApi && applyChartView(chartApi, "fit", autoScroll)}
            className="rounded-lg border border-ds-border px-2.5 py-1 text-[11px] text-ds-text-secondary hover:bg-ds-surface-secondary"
          >
            Fit content
          </button>
          <button
            type="button"
            onClick={() => chartApi && applyChartView(chartApi, "latest", autoScroll)}
            className="rounded-lg border border-ds-border px-2.5 py-1 text-[11px] text-ds-text-secondary hover:bg-ds-surface-secondary"
          >
            Scroll to latest
          </button>
          <button
            type="button"
            onClick={() => chartApi && applyChartView(chartApi, "reset", autoScroll)}
            className="rounded-lg border border-ds-border px-2.5 py-1 text-[11px] text-ds-text-secondary hover:bg-ds-surface-secondary"
          >
            Reset view
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />

        <div className="pointer-events-none absolute inset-x-0 top-0 z-[5] h-[72%] overflow-hidden">
          {cognitiveRegimeRects.map((rect) => (
            <div
              key={`cognitive-${rect.id}`}
              className="absolute top-0 h-full border-l border-r border-ds-border/20"
              style={{ left: rect.left, width: rect.width, background: rect.color }}
              title={`Cognitive Regime: ${rect.label}`}
            >
              {rect.width >= 140 && showOverlayLabels ? (
                <>
                  <div className="mt-8 max-w-[260px] truncate px-2 text-center text-[9px] font-medium uppercase tracking-wide text-ds-text-secondary/80">
                    Cognitive · {rect.label}
                  </div>
                  <div className="truncate px-2 text-center text-[8px] text-ds-text-tertiary">{rect.meta}</div>
                </>
              ) : null}
            </div>
          ))}
          {legacyRegimeRects.map((rect) => (
            <div
              key={rect.id}
              className="absolute top-0 h-full border-l border-r border-ds-border/40"
              style={{ left: rect.left, width: rect.width, background: rect.color }}
            >
              {rect.width >= 110 && showOverlayLabels ? (
                <>
                  <div className="mt-3 max-w-[260px] truncate px-2 text-center text-[10px] font-semibold uppercase tracking-wide text-ds-text-primary">
                    {rect.label}
                  </div>
                  <div className="truncate px-2 text-center text-[9px] text-ds-text-secondary">{rect.meta}</div>
                </>
              ) : null}
            </div>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[72%] overflow-hidden">
          {marketStateRegimeRects.map((rect) => (
            <div
              key={rect.id}
              className="absolute top-0 h-full border-l border-r"
              style={{
                left: rect.left,
                width: rect.width,
                background: rect.color,
                borderColor: rect.isActive
                  ? "color-mix(in srgb, var(--ds-color-accent) 55%, transparent)"
                  : "color-mix(in srgb, var(--ds-color-border) 35%, transparent)",
                boxShadow: rect.isActive
                  ? "inset 0 0 0 2px color-mix(in srgb, var(--ds-color-accent) 55%, transparent)"
                  : undefined,
              }}
            >
              {rect.width >= 110 && showOverlayLabels ? (
                <>
                  <div className="mt-3 max-w-[260px] truncate px-2 text-center text-[10px] font-black uppercase tracking-wide text-ds-text-primary">
                    {rect.label}
                  </div>
                  <div className="truncate px-2 text-center text-[9px] text-ds-text-secondary">{rect.meta}</div>
                </>
              ) : null}
            </div>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-[118px] z-[8] h-6 overflow-hidden px-1">
          {contextBands.map((band) => (
            <div
              key={band.id}
              className="absolute top-0 h-6 rounded-md border px-2 text-[9px] font-semibold uppercase tracking-wide"
              style={{
                left: band.left,
                width: band.width,
                minWidth: 72,
                borderColor: band.isActive ? "color-mix(in srgb, var(--ds-color-accent) 45%, transparent)" : "color-mix(in srgb, var(--ds-color-border) 80%, transparent)",
                background: band.color,
                color: "var(--ds-color-text-primary)",
              }}
              title={`${band.label} · ${band.meta}`}
            >
              {band.width >= 88 && showOverlayLabels ? (
                <span className="truncate">{band.label}</span>
              ) : (
                <span className="sr-only">{band.label}</span>
              )}
            </div>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 h-[72%] overflow-hidden">
          {decisionCallouts.map((callout) => (
            <div
              key={callout.id}
              className={`absolute flex w-24 flex-col items-center ${callout.side === "bottom" ? "bottom-8" : "top-6"}`}
              style={{ left: callout.left }}
              title={callout.reason}
            >
              <div
                className="rounded-xl border px-2.5 py-2 text-center shadow-lg backdrop-blur"
                style={{
                  borderColor: callout.color,
                  background: `color-mix(in srgb, ${callout.color} 16%, var(--ds-color-surface-elevated))`,
                  color: "var(--ds-color-text-primary)",
                  boxShadow: `0 0 0 1px color-mix(in srgb, ${callout.color} 28%, transparent), 0 10px 24px color-mix(in srgb, ${callout.color} 18%, transparent)`,
                }}
              >
                <div className="text-[10px] font-black uppercase tracking-wide" style={{ color: callout.color }}>
                  {callout.label}
                </div>
                <div className="mt-1 font-mono text-[9px] text-ds-text-secondary">{callout.subtitle}</div>
              </div>
              <div className="h-16 border-l border-dashed" style={{ borderColor: callout.color }} />
            </div>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-[118px] z-20 h-9 overflow-hidden px-1">
          {lifecycleBands.map((band) => (
            <div
              key={band.id}
              className="absolute top-1 h-7 rounded-full border px-3 text-[10px] font-semibold uppercase tracking-wide shadow-sm"
              style={{
                left: band.left,
                width: band.width,
                minWidth: 96,
                borderColor: band.color,
                background: `linear-gradient(90deg, color-mix(in srgb, ${band.color} 24%, transparent), color-mix(in srgb, ${band.color} 10%, transparent))`,
                color: "var(--ds-color-text-primary)",
              }}
              title={`${band.id} · ${band.meta}`}
            >
              <span style={{ color: band.color }}>{band.label}</span>
              <span className="ml-2 text-ds-text-secondary">{band.meta}</span>
            </div>
          ))}
        </div>

        {tooltip ? (
          <div
            className="pointer-events-none absolute z-30 w-[300px] rounded-xl border border-ds-border bg-ds-surface-elevated/95 p-3 shadow-2xl backdrop-blur"
            style={{ left: tooltip.x, top: tooltip.y }}
          >
            <div className="mb-2 font-mono text-[11px] font-semibold text-ds-text-primary">{tooltip.title}</div>
            <div className="grid gap-1">
              {tooltip.rows.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[96px_1fr] gap-2 text-[10px]">
                  <span className="uppercase tracking-wide text-ds-text-tertiary">{label}</span>
                  <span className="truncate font-mono text-ds-text-primary">{value}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-ds-border/50 px-4 py-2 text-[10px] text-ds-text-secondary">
        {showMarketStateRegimes && hasEngineRegimes ? (
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ background: "rgba(10,132,255,0.24)" }} />
            Market State Regime
          </span>
        ) : null}
        {showCognitiveRegimes ? (
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ background: cognitiveRegimeColor(0) }} />
            Cognitive Regime
          </span>
        ) : null}
        {showDirectionalContext && (snapshot.directional_context_episodes?.length ?? 0) > 0 ? (
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-6 rounded-sm" style={{ background: contextEpisodeColor("LONG", true) }} />
            Directional Context
          </span>
        ) : null}
        {showTransitions && (snapshot.market_state_transitions?.length ?? 0) > 0 ? (
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKET_STATE_TRANSITION_COLOR }} />
            Market State Transition
          </span>
        ) : null}
        {showDecisions
          ? Object.entries({
              LONG_SETUP: "Long setup marker",
              SHORT_SETUP: "Short setup marker",
              EXIT_LONG: "Exit long marker",
              EXIT_SHORT: "Exit short marker",
              INVALIDATED: "Invalidated marker",
            }).map(([key, label]) => (
              <span key={key} className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: decisionColor(key) }} />
                {label}
              </span>
            ))
          : null}
        {showOverlayLabels ? <span className="ml-auto font-mono text-ds-text-tertiary">Overlay labels on</span> : null}
      </div>
    </section>
  );
}
