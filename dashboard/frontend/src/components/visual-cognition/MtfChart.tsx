import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ChartAnnotation, CognitionBar } from "../../types/visualCognition";
import { ChartNavigator } from "./ChartNavigator";
import {
  CHART,
  defaultVisibleBarsForTimeframe,
  EXECUTION_MAP,
  annotationY,
  formatPrice,
  formatTime,
  truncateAnnotation,
} from "./chartUtils";
import { HollowCandle } from "./HollowCandle";
import { logChartLayoutDiagnostics, logChartZoom } from "./chartZoomDebug";
import { useChartZoomPan } from "./useChartZoomPan";
import { useElementSize } from "./useElementSize";
import { VolumeConcentrationLevel } from "./VolumeConcentrationLevel";

function StageOverlayAnnotation({
  annotation,
  bars,
  cxFor,
  yFor,
  padTop,
}: {
  annotation: ChartAnnotation;
  bars: CognitionBar[];
  cxFor: (i: number) => number;
  yFor: (p: number) => number;
  padTop: number;
}) {
  const cx = cxFor(annotation.bar_index);
  const cy = annotationY(annotation, bars, yFor, padTop);
  const color = annotation.color ?? "#38bdf8";

  return (
    <g aria-label={annotation.label} opacity={0.92}>
      <line x1={cx} x2={cx + 36} y1={cy} y2={cy - 12} stroke={color} strokeWidth={0.75} strokeDasharray="2 2" />
      <rect x={cx + 36} y={cy - 20} width={110} height={14} rx={1} fill="#0a0a0a" stroke={color} strokeWidth={0.75} />
      <text x={cx + 40} y={cy - 10} fill={color} fontSize={6.5} fontFamily="ui-monospace, monospace">
        {truncateAnnotation(annotation.label, 22)}
      </text>
    </g>
  );
}

const TF_ORDER = ["D1", "H4", "H1", "M15"] as const;

export function TimeframeSwitcher({
  timeframes,
  active,
  onChange,
}: {
  timeframes: string[];
  active: string;
  onChange: (tf: string) => void;
}) {
  const ordered = TF_ORDER.filter((tf) => timeframes.includes(tf));
  const rest = timeframes.filter((tf) => !TF_ORDER.includes(tf as (typeof TF_ORDER)[number]));

  return (
    <div
      className="inline-flex rounded-ds-pill border border-ds-border bg-ds-surface-secondary p-0.5"
      role="tablist"
      aria-label="Timeframe"
    >
      {[...ordered, ...rest].map((tf) => {
        const selected = tf === active;
        return (
          <button
            key={tf}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tf)}
            className={`min-w-[3rem] rounded-ds-pill px-3 py-1 text-[11px] font-medium transition-colors duration-ds ${
              selected
                ? "bg-ds-surface text-ds-text-primary shadow-ds-sm"
                : "text-ds-text-secondary hover:text-ds-text-primary"
            }`}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
}

function isIntermediateChartOverlay(annotation: ChartAnnotation): boolean {
  if (annotation.source === "stage2_5") return true;
  const label = String(annotation.label ?? "");
  return label.startsWith("IC_") || label.includes(" IC_");
}

function visiblePriceExtent(bars: CognitionBar[], start: number, end: number) {
  let minP = Infinity;
  let maxP = -Infinity;
  for (let i = start; i <= end; i++) {
    const b = bars[i];
    if (!b) continue;
    minP = Math.min(minP, b.low);
    maxP = Math.max(maxP, b.high);
  }
  if (!Number.isFinite(minP)) return { minP: 0, maxP: 1 };
  const pad = (maxP - minP) * 0.04 || maxP * 0.001 || 1;
  return { minP: minP - pad, maxP: maxP + pad };
}

function visibleVolumeMax(bars: CognitionBar[], start: number, end: number) {
  let maxV = 1;
  for (let i = start; i <= end; i++) {
    maxV = Math.max(maxV, bars[i]?.volume ?? 0);
  }
  return maxV;
}

export function MtfChart({
  timeframe,
  bars,
  cursorIndex,
  annotations = [],
  barCount,
  markerCounts,
}: {
  timeframe: string;
  bars: CognitionBar[];
  cursorIndex?: number | null;
  annotations?: ChartAnnotation[];
  barCount?: number;
  markerCounts?: Record<string, number>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { ref: chartPaneRef, width: chartPaneW, height: chartPaneH } = useElementSize<HTMLDivElement>("MtfChart.chartPane");

  const { pad, volumeHeight, volumeGap } = CHART;
  /** SVG height — chart pane only; navigator is excluded from measurement. */
  const chartHeight = chartPaneH > 0 ? chartPaneH : 280;
  const pricePlotH = chartHeight - volumeHeight - volumeGap - pad.bottom - pad.top;
  const volumeTop = pad.top + pricePlotH + volumeGap;
  const volumePlotH = volumeHeight - 6;

  const {
    scrollRef,
    barPitch,
    contentWidth,
    visibleStart,
    visibleEnd,
    visibleCount,
    onScroll,
    centerOnBarWithVisibleCount,
    zoomToFitAll,
  } = useChartZoomPan(bars.length, Math.max(chartPaneW, 320), pad.left, pad.right);

  const defaultVisibleBars = defaultVisibleBarsForTimeframe(timeframe);
  const viewportInitializedRef = useRef(false);
  const lastBarsLengthRef = useRef(0);
  const lastChartPaneWRef = useRef(0);

  const focusBarIndex =
    cursorIndex != null && cursorIndex >= 0 && cursorIndex < bars.length ? cursorIndex : Math.max(0, bars.length - 1);

  const resetToDefaultViewport = useCallback(() => {
    if (bars.length === 0) return;
    centerOnBarWithVisibleCount(focusBarIndex, defaultVisibleBars);
  }, [bars.length, focusBarIndex, defaultVisibleBars, centerOnBarWithVisibleCount]);

  useEffect(() => {
    if (bars.length === 0 || chartPaneW <= 0) return;
    const barsChanged = lastBarsLengthRef.current !== bars.length;
    const widthReady = lastChartPaneWRef.current <= 0 && chartPaneW > 0;
    if (!viewportInitializedRef.current || barsChanged || widthReady) {
      logChartZoom("viewport-init", {
        reason: !viewportInitializedRef.current ? "first" : barsChanged ? "bars-changed" : "width-ready",
        chartPaneW,
        chartPaneH,
        defaultVisibleBars,
        focusBarIndex,
      });
      lastBarsLengthRef.current = bars.length;
      lastChartPaneWRef.current = chartPaneW;
      viewportInitializedRef.current = true;
      centerOnBarWithVisibleCount(focusBarIndex, defaultVisibleBars);
    }
  }, [bars.length, chartPaneW, focusBarIndex, defaultVisibleBars, centerOnBarWithVisibleCount]);

  useEffect(() => {
    const containerHeight = containerRef.current?.getBoundingClientRect().height ?? 0;
    const navigatorHeight = Math.max(0, containerHeight - chartPaneH);
    logChartLayoutDiagnostics({
      chartHeight,
      containerHeight,
      navigatorHeight,
      pageHeight: document.documentElement.scrollHeight,
    });
  }, [chartHeight, chartPaneH, barPitch, visibleCount, contentWidth]);

  const barW = Math.max(1, barPitch * 0.82);
  const cxFor = (index: number) => pad.left + index * barPitch + barPitch / 2;

  const { minP, maxP } = useMemo(
    () => visiblePriceExtent(bars, visibleStart, visibleEnd),
    [bars, visibleStart, visibleEnd],
  );
  const span = maxP - minP || 1;
  const yFor = (price: number) => pad.top + pricePlotH - ((price - minP) / span) * pricePlotH;

  const maxV = useMemo(() => visibleVolumeMax(bars, visibleStart, visibleEnd), [bars, visibleStart, visibleEnd]);
  const yVol = (volume: number) => volumeTop + volumePlotH - (volume / maxV) * volumePlotH;

  const priceStep = span / 5;
  const renderStart = Math.max(0, visibleStart - 2);
  const renderEnd = Math.min(bars.length - 1, visibleEnd + 2);
  const tickStep = Math.max(1, Math.floor(visibleCount / 8));

  if (!bars.length) {
    return (
      <div className="flex flex-1 items-center justify-center rounded border border-neutral-800 bg-black text-[11px] text-ds-text-tertiary">
        No {timeframe} bars
      </div>
    );
  }

  const visibleAnnotations = annotations.filter(
    (a) => !isIntermediateChartOverlay(a) && a.bar_index >= renderStart && a.bar_index <= renderEnd,
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded border border-neutral-800 bg-black">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-neutral-800 px-3 py-1.5 text-[10px] font-mono text-ds-text-secondary">
        <span className="text-ds-text-primary">{timeframe}</span>
        <span>
          {barCount ?? bars.length} bars · visible ~{visibleCount} · pitch {barPitch.toFixed(1)}px
        </span>
        <span className="text-ds-text-tertiary">
          {formatPrice(minP)} – {formatPrice(maxP)}
        </span>
        {markerCounts ? (
          <span className="hidden text-ds-text-tertiary xl:inline">
            {Object.entries(markerCounts)
              .map(([k, v]) => `${k.replace("_VOLUME", "").replace("HIGH_VARIANCE", "HAV")}:${v}`)
              .join(" · ")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={zoomToFitAll}
          className="rounded border border-neutral-700 px-1.5 py-0.5 text-[9px] text-ds-text-secondary hover:text-ds-text-primary"
        >
          Fit all
        </button>
      </div>

      <div ref={containerRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div ref={chartPaneRef} className="relative min-h-0 flex-1 overflow-hidden">
          {/* Fixed Y-axis — visible range only */}
          <svg
            className="pointer-events-none absolute left-0 top-0 z-10"
            width={pad.left}
            height={chartHeight}
            aria-hidden
          >
          <rect width={pad.left} height={chartHeight} fill={EXECUTION_MAP.background} opacity={0.92} />
          {Array.from({ length: 6 }, (_, i) => {
            const price = minP + priceStep * i;
            const y = yFor(price);
            return (
              <text
                key={`ylabel-${i}`}
                x={pad.left - 6}
                y={y + 3}
                textAnchor="end"
                fill={EXECUTION_MAP.axis}
                fontSize={8}
                fontFamily="ui-monospace, monospace"
              >
                {formatPrice(price)}
              </text>
            );
          })}
          <text x={pad.left - 6} y={volumeTop + volumePlotH / 2 + 3} textAnchor="end" fill={EXECUTION_MAP.axis} fontSize={7} fontFamily="ui-monospace, monospace">
            Vol
          </text>
        </svg>

          <div
            ref={scrollRef}
            className="h-full overflow-x-auto overflow-y-hidden"
            onScroll={onScroll}
            onDoubleClick={resetToDefaultViewport}
            title="Double-click to reset viewport"
          >
          <svg
            width={contentWidth}
            height={chartHeight}
            role="img"
            aria-label={`${timeframe} Stage 1 execution map`}
            className="block max-h-full"
          >
            <rect x={0} y={0} width={contentWidth} height={chartHeight} fill={EXECUTION_MAP.background} />

            {Array.from({ length: 6 }, (_, i) => {
              const price = minP + priceStep * i;
              const y = yFor(price);
              return (
                <line
                  key={`grid-${i}`}
                  x1={pad.left}
                  x2={contentWidth - pad.right}
                  y1={y}
                  y2={y}
                  stroke={EXECUTION_MAP.grid}
                  strokeWidth={0.5}
                />
              );
            })}

            {bars.slice(renderStart, renderEnd + 1).map((bar, offset) => {
              const index = renderStart + offset;
              const cx = cxFor(index);
              return (
                <HollowCandle
                  key={`candle-${bar.timestamp}`}
                  cx={cx}
                  x={cx - barW / 2}
                  barW={barW}
                  yHigh={yFor(bar.high)}
                  yLow={yFor(bar.low)}
                  yOpen={yFor(bar.open)}
                  yClose={yFor(bar.close)}
                />
              );
            })}

            {bars.slice(renderStart, renderEnd + 1).map((bar, offset) => {
              const index = renderStart + offset;
              const markers = bar.volume_location_markers ?? [];
              if (!markers.length) return null;
              const cx = cxFor(index);
              return markers.map((marker) => (
                <VolumeConcentrationLevel
                  key={`loc-${bar.timestamp}-${marker.event}`}
                  marker={marker}
                  cx={cx}
                  cy={yFor(marker.price)}
                  barW={barW}
                />
              ));
            })}

            {visibleAnnotations.map((annotation) => (
              <StageOverlayAnnotation
                key={`${annotation.timestamp}-${annotation.bar_index}`}
                annotation={annotation}
                bars={bars}
                cxFor={cxFor}
                yFor={yFor}
                padTop={pad.top}
              />
            ))}

            <line x1={pad.left} x2={contentWidth - pad.right} y1={volumeTop - 2} y2={volumeTop - 2} stroke={EXECUTION_MAP.grid} strokeWidth={0.75} />

            <rect x={pad.left} y={volumeTop} width={contentWidth - pad.left - pad.right} height={volumePlotH} fill={EXECUTION_MAP.background} />

            {bars.slice(renderStart, renderEnd + 1).map((bar, offset) => {
              const index = renderStart + offset;
              const volume = bar.volume ?? 0;
              const cx = cxFor(index);
              const x = cx - barW / 2;
              const yBase = volumeTop + volumePlotH;
              const yTop = yVol(volume);
              const barH = Math.max(yBase - yTop, volume > 0 ? 1 : 0);
              return (
                <rect
                  key={`vol-${bar.timestamp}`}
                  x={x}
                  y={yTop}
                  width={barW}
                  height={barH}
                  fill={EXECUTION_MAP.neutralStroke}
                  opacity={0.2}
                  stroke={EXECUTION_MAP.grid}
                  strokeWidth={0.5}
                />
              );
            })}

            {bars.slice(renderStart, renderEnd + 1).map((bar, offset) => {
              const index = renderStart + offset;
              if ((index - visibleStart) % tickStep !== 0 && index !== visibleEnd && index !== bars.length - 1) {
                return null;
              }
              return (
                <text
                  key={`time-${index}`}
                  x={cxFor(index)}
                  y={chartHeight - 4}
                  textAnchor="middle"
                  fill={EXECUTION_MAP.axis}
                  fontSize={7}
                  fontFamily="ui-monospace, monospace"
                >
                  {formatTime(bar.timestamp)}
                </text>
              );
            })}

            {cursorIndex != null && cursorIndex >= 0 && cursorIndex < bars.length ? (
              <line
                x1={cxFor(cursorIndex)}
                x2={cxFor(cursorIndex)}
                y1={pad.top}
                y2={volumeTop + volumePlotH}
                stroke="#38bdf8"
                strokeWidth={1}
                strokeDasharray="4 3"
                opacity={0.7}
              />
            ) : null}

            <line x1={pad.left} x2={pad.left} y1={pad.top} y2={volumeTop + volumePlotH} stroke={EXECUTION_MAP.grid} strokeWidth={0.75} />
            <line
              x1={pad.left}
              x2={contentWidth - pad.right}
              y1={volumeTop + volumePlotH}
              y2={volumeTop + volumePlotH}
              stroke={EXECUTION_MAP.grid}
              strokeWidth={0.75}
            />
          </svg>
          </div>
        </div>

        <ChartNavigator
          bars={bars}
          visibleStart={visibleStart}
          visibleEnd={visibleEnd}
          width={Math.max(chartPaneW, 320)}
        />
      </div>
    </div>
  );
}
