import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import { useTranslation } from "../../i18n";
import type { ManualAnchor, ManualAnnotation, ManualEventLink } from "../../types/manualAnnotations";
import { AnchorOverlay } from "./AnchorOverlay";
import { resolveAnchorGeometry } from "./anchorUtils";
import type { ReviewCandleBar, Stage1EventClass, WindowOverlayEvent } from "../../types/eventReview";
import { EVENT_CLASS_COLORS } from "../../types/eventReview";
import { HollowCandle } from "../visual-cognition/HollowCandle";
import { APPLE_EXECUTION_MAP, EXECUTION_MAP, formatPrice, formatTime, priceTicks, timeTickIndices } from "../visual-cognition/chartUtils";
import { useElementSize } from "../visual-cognition/useElementSize";
import { useChartZoomPan } from "../visual-cognition/useChartZoomPan";
import { EventOverlayPin } from "./EventOverlayPin";
import { IntraCandleHeatmap } from "./IntraCandleHeatmap";
import { MeasurementOverlay } from "./MeasurementOverlay";
import type { MeasurementPreview } from "./measurementUtils";

const PAD = { top: 20, right: 16, bottom: 28, left: 58 };
const DEFAULT_VISIBLE_BARS = 120;

export type AnnotationChartHandle = {
  centerOnEvent: () => void;
  zoomToFitAll: () => void;
};

function colorForClass(eventClass: string): string {
  return EVENT_CLASS_COLORS[eventClass as Stage1EventClass] ?? "#a78bfa";
}

function priceExtent(bars: ReviewCandleBar[], start: number, end: number) {
  let minP = Infinity;
  let maxP = -Infinity;
  for (let i = start; i <= end; i++) {
    const bar = bars[i];
    if (!bar) continue;
    minP = Math.min(minP, bar.low);
    maxP = Math.max(maxP, bar.high);
  }
  if (!Number.isFinite(minP)) return { minP: 0, maxP: 1 };
  const pad = (maxP - minP) * 0.04 || maxP * 0.001 || 1;
  return { minP: minP - pad, maxP: maxP + pad };
}

function stackIndexForBar(events: WindowOverlayEvent[], overlay: WindowOverlayEvent): number {
  const sameBar = events.filter((event) => event.bar_index_in_window === overlay.bar_index_in_window);
  return sameBar.findIndex(
    (event) => event.timestamp === overlay.timestamp && event.event_class === overlay.event_class,
  );
}

function pinScale(barPitch: number): number {
  return Math.min(1.2, Math.max(0.35, barPitch / 7));
}

export const AnnotationChart = forwardRef<
  AnnotationChartHandle,
  {
    bars: ReviewCandleBar[];
    focusBarIndex: number | null;
    windowEvents?: WindowOverlayEvent[];
    manualAnnotations?: ManualAnnotation[];
    manualAnchors?: ManualAnchor[];
    manualLinks?: ManualEventLink[];
    showAllInWindow?: boolean;
    addEventMode?: boolean;
    anchorMode?: "single" | "range" | null;
    anchorRangeStart?: number | null;
    anchorRangeEnd?: number | null;
    measureKind?: "measure" | "fixate" | null;
    measureStartIndex?: number | null;
    linkMode?: boolean;
    linkSourceAnchorId?: string | null;
    linkTargetAnchorId?: string | null;
    activeMeasurement?: MeasurementPreview | null;
    savedMeasurements?: MeasurementPreview[];
    onBarClick?: (barIndexInWindow: number, bar: ReviewCandleBar) => void;
    onEventClick?: (event: WindowOverlayEvent) => void;
    onAnchorClick?: (anchorId: string) => void;
    onVisibleRangeChange?: (start: number, end: number, visibleCount: number) => void;
    visualTheme?: "default" | "apple";
  }
>(function AnnotationChart(
  {
    bars,
    focusBarIndex,
    windowEvents = [],
    manualAnnotations = [],
    manualAnchors = [],
    manualLinks = [],
    showAllInWindow = true,
    addEventMode = false,
    anchorMode = null,
    anchorRangeStart = null,
    anchorRangeEnd = null,
    measureKind = null,
    measureStartIndex = null,
    linkMode = false,
    linkSourceAnchorId = null,
    linkTargetAnchorId = null,
    activeMeasurement = null,
    savedMeasurements = [],
    onBarClick,
    onEventClick,
    onAnchorClick,
    onVisibleRangeChange,
    visualTheme = "default",
  },
  ref,
) {
  const { t } = useTranslation();
  const palette = visualTheme === "apple" ? APPLE_EXECUTION_MAP : EXECUTION_MAP;
  const { ref: containerRef, width, height } = useElementSize<HTMLDivElement>();
  const chartHeight = Math.max(height, 320);
  const viewportW = Math.max(width, 480);
  const initializedRef = useRef(false);
  const lastBarsLengthRef = useRef(0);
  const interactionActive = addEventMode || measureKind != null || linkMode || anchorMode != null;

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
  } = useChartZoomPan(bars.length, viewportW, PAD.left, PAD.right, !interactionActive);

  useImperativeHandle(ref, () => ({
    centerOnEvent: () => {
      if (focusBarIndex != null) {
        centerOnBarWithVisibleCount(focusBarIndex, DEFAULT_VISIBLE_BARS);
      }
    },
    zoomToFitAll,
  }));

  // Initial center on event; re-init only when dataset length changes (full history reload)
  useEffect(() => {
    if (bars.length === 0 || focusBarIndex == null) return;
    if (!initializedRef.current || lastBarsLengthRef.current !== bars.length) {
      lastBarsLengthRef.current = bars.length;
      initializedRef.current = true;
      centerOnBarWithVisibleCount(focusBarIndex, DEFAULT_VISIBLE_BARS);
    }
  }, [bars.length, focusBarIndex, centerOnBarWithVisibleCount]);

  useEffect(() => {
    onVisibleRangeChange?.(visibleStart, visibleEnd, visibleCount);
  }, [visibleStart, visibleEnd, visibleCount, onVisibleRangeChange]);

  const renderStart = Math.max(0, visibleStart - 3);
  const renderEnd = Math.min(bars.length - 1, visibleEnd + 3);

  const { minP, maxP } = useMemo(
    () => priceExtent(bars, renderStart, renderEnd),
    [bars, renderStart, renderEnd],
  );
  const span = maxP - minP || 1;
  const plotH = chartHeight - PAD.top - PAD.bottom;

  const yFor = (price: number) => PAD.top + plotH - ((price - minP) / span) * plotH;
  const xFor = (index: number) => PAD.left + index * barPitch + barPitch / 2;

  const markerScale = pinScale(barPitch);
  const showHeatmaps = barPitch >= 3.5;
  const showMissedLabels = barPitch >= 6;

  const visibleOverlays = useMemo(() => {
    const list = showAllInWindow ? windowEvents : windowEvents.filter((event) => event.is_primary);
    return [...list].sort((a, b) => {
      if (a.is_primary === b.is_primary) return a.bar_index_in_window - b.bar_index_in_window;
      return a.is_primary ? 1 : -1;
    });
  }, [windowEvents, showAllInWindow]);

  const missedEvents = useMemo(
    () => manualAnnotations.filter((item) => item.review_type === "MISSED_EVENT"),
    [manualAnnotations],
  );

  const anchorById = useMemo(() => {
    const map = new Map<string, ManualAnchor>();
    for (const anchor of manualAnchors) map.set(anchor.anchor_id, anchor);
    return map;
  }, [manualAnchors]);

  const linkLines = useMemo(() => {
    const lines: Array<{
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      status: string;
    }> = [];
    for (const link of manualLinks) {
      const src = anchorById.get(link.source_anchor_id);
      const tgt = anchorById.get(link.target_anchor_id);
      if (!src || !tgt) continue;
      const srcGeom = resolveAnchorGeometry(src, bars);
      const tgtGeom = resolveAnchorGeometry(tgt, bars);
      if (!srcGeom || !tgtGeom) continue;
      lines.push({
        x1: xFor(srcGeom.midIndex),
        y1: yFor(srcGeom.midPrice),
        x2: xFor(tgtGeom.midIndex),
        y2: yFor(tgtGeom.midPrice),
        status: link.link_status ?? "Активная",
      });
    }
    return lines;
  }, [manualLinks, anchorById, bars, barPitch, minP, maxP]);

  const primaryOverlay = windowEvents.find((event) => event.is_primary);
  const primaryIndex = primaryOverlay?.bar_index_in_window ?? focusBarIndex;
  const primaryColor = primaryOverlay?.event_class ? colorForClass(primaryOverlay.event_class) : "#ef4444";

  return (
    <div
      ref={containerRef}
      className={`relative h-full min-h-[320px] w-full rounded border bg-black ${
        addEventMode ? "border-amber-600" : measureKind ? "border-violet-600" : anchorMode ? "border-orange-600" : linkMode ? "border-sky-600" : "border-neutral-800"
      }`}
    >
      <div
        ref={scrollRef}
        className={`h-full w-full overflow-x-auto overflow-y-hidden ${
          interactionActive ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing"
        }`}
        onScroll={onScroll}
      >
        <svg width={contentWidth} height={chartHeight} role="img" aria-label="M15 full-history chart">
          <rect x={0} y={0} width={contentWidth} height={chartHeight} fill={palette.background} />

          {priceTicks(minP, maxP).map((price) => {
            const y = yFor(price);
            return (
              <g key={price}>
                <line
                  x1={PAD.left}
                  x2={contentWidth - PAD.right}
                  y1={y}
                  y2={y}
                  stroke={palette.grid}
                  strokeWidth={visualTheme === "apple" ? 0.35 : 0.5}
                />
                <text
                  x={PAD.left - 6}
                  y={y + 3}
                  textAnchor="end"
                  fill={palette.axis}
                  fontSize={visualTheme === "apple" ? 10 : 9}
                  fontFamily={visualTheme === "apple" ? "-apple-system, system-ui, sans-serif" : "ui-monospace, monospace"}
                >
                  {formatPrice(price)}
                </text>
              </g>
            );
          })}

          {timeTickIndices(bars.length).map((index) => {
            if (index < renderStart || index > renderEnd) return null;
            const bar = bars[index];
            if (!bar) return null;
            return (
              <text
                key={index}
                x={xFor(index)}
                y={chartHeight - 8}
                textAnchor="middle"
                fill={palette.axis}
                fontSize={visualTheme === "apple" ? 9 : 8}
                fontFamily={visualTheme === "apple" ? "-apple-system, system-ui, sans-serif" : "ui-monospace, monospace"}
              >
                {formatTime(bar.timestamp)}
              </text>
            );
          })}

          <AnchorOverlay
            anchors={manualAnchors}
            bars={bars}
            plotTop={PAD.top}
            plotHeight={plotH}
            xFor={xFor}
            yFor={yFor}
            barPitch={barPitch}
            selectedSourceId={linkSourceAnchorId}
            selectedTargetId={linkTargetAnchorId}
            pendingRangeStart={anchorMode ? anchorRangeStart : null}
            pendingRangeEnd={anchorMode ? anchorRangeEnd : null}
            onAnchorClick={onAnchorClick}
            linkMode={linkMode}
            interactive={false}
            showRanges={!linkMode}
            showSingles={false}
          />

          {bars.slice(renderStart, renderEnd + 1).map((bar) => {
            const index = bar.index;
            const cx = xFor(index);
            const barW = Math.max(0.75, barPitch * 0.72);
            return (
              <g
                key={`${bar.timestamp}-${index}`}
                onClick={(e) => {
                  if (interactionActive && !linkMode) {
                    e.stopPropagation();
                    onBarClick?.(index, bar);
                  }
                }}
              >
                <rect x={cx - barPitch / 2} y={PAD.top} width={barPitch} height={plotH} fill="transparent" />
                {measureStartIndex === index ? (
                  <rect
                    x={cx - barPitch / 2 - 1}
                    y={PAD.top}
                    width={barPitch + 2}
                    height={plotH}
                    fill="none"
                    stroke="#a78bfa"
                    strokeWidth={1.5}
                    strokeDasharray="4 2"
                  />
                ) : null}
                {anchorRangeStart === index ? (
                  <rect
                    x={cx - barPitch / 2 - 1}
                    y={PAD.top}
                    width={barPitch + 2}
                    height={plotH}
                    fill="none"
                    stroke="#fb923c"
                    strokeWidth={1.5}
                    strokeDasharray="4 2"
                  />
                ) : null}
                {anchorRangeEnd === index ? (
                  <rect
                    x={cx - barPitch / 2 - 1}
                    y={PAD.top}
                    width={barPitch + 2}
                    height={plotH}
                    fill="none"
                    stroke="#fdba74"
                    strokeWidth={1.5}
                  />
                ) : null}
                <HollowCandle
                  cx={cx}
                  x={cx - barW / 2}
                  barW={barW}
                  yHigh={yFor(bar.high)}
                  yLow={yFor(bar.low)}
                  yOpen={yFor(bar.open)}
                  yClose={yFor(bar.close)}
                  opacity={index === focusBarIndex ? 1 : 0.82}
                  neutralStroke={palette.neutralStroke}
                  neutralFill={palette.neutralFill}
                />
              </g>
            );
          })}

          {visibleOverlays.map((overlay) => {
            const index = overlay.bar_index_in_window;
            if (index < renderStart || index > renderEnd) return null;
            const cx = xFor(index);
            const bar = bars[index];
            const barW = Math.max(0.75, barPitch * 0.72);
            const stackIndex = stackIndexForBar(visibleOverlays, overlay);

            return (
              <g
                key={`ov-${overlay.timestamp}-${overlay.event_class}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onEventClick?.(overlay);
                }}
                style={{ cursor: "pointer" }}
              >
                {showHeatmaps
                  ? overlay.volume_location_markers.map((marker, markerIndex) => (
                      <IntraCandleHeatmap
                        key={`heat-${markerIndex}`}
                        marker={{ ...marker, event_class: overlay.event_class }}
                        cx={cx}
                        barW={barW}
                        yFor={yFor}
                        isPrimary={overlay.is_primary}
                      />
                    ))
                  : null}
                {bar ? (
                  <EventOverlayPin
                    cx={cx}
                    yHigh={yFor(bar.high)}
                    eventClass={overlay.event_class as Stage1EventClass}
                    isPrimary={overlay.is_primary}
                    stackIndex={stackIndex}
                    scale={markerScale}
                  />
                ) : null}
              </g>
            );
          })}

          {missedEvents.map((ann) => {
            const local = bars.find((b) => b.timestamp === ann.timestamp);
            if (!local) return null;
            const index = local.index;
            if (index < renderStart || index > renderEnd) return null;
            const cx = xFor(index);
            const r = Math.max(2, 4 * markerScale);
            return (
              <g key={ann.annotation_id}>
                <circle cx={cx} cy={yFor(local.close)} r={r} fill="#a78bfa" stroke="#f8fafc" strokeWidth={0.8} />
                {showMissedLabels ? (
                  <text x={cx + r + 2} y={yFor(local.close) - 2} fill="#c4b5fd" fontSize={7} fontFamily="monospace">
                    {(ann.human_event_class ?? "Проп").slice(0, 10)}
                  </text>
                ) : null}
              </g>
            );
          })}

          {!linkMode ? (
            <AnchorOverlay
              anchors={manualAnchors}
              bars={bars}
              plotTop={PAD.top}
              plotHeight={plotH}
              xFor={xFor}
              yFor={yFor}
              barPitch={barPitch}
              selectedSourceId={linkSourceAnchorId}
              selectedTargetId={linkTargetAnchorId}
              onAnchorClick={onAnchorClick}
              linkMode={false}
              interactive={false}
              showRanges={false}
              showSingles
            />
          ) : null}

          {linkLines.map((line, index) => {
            const isActive = line.status === "Активная";
            const isCompleted = line.status === "Завершенная";
            const stroke = isCompleted ? "#22c55e" : isActive ? "#38bdf8" : "#ef4444";
            const opacity = isActive ? 0.85 : isCompleted ? 0.65 : 0.45;
            const dash = isActive ? "4 3" : isCompleted ? undefined : "2 5";
            return (
              <g key={`link-${index}`}>
                <line
                  x1={line.x1}
                  y1={line.y1}
                  x2={line.x2}
                  y2={line.y2}
                  stroke={stroke}
                  strokeWidth={Math.max(0.6, 1.2 * markerScale)}
                  strokeDasharray={dash}
                  opacity={opacity}
                />
                <circle
                  cx={line.x1}
                  cy={line.y1}
                  r={Math.max(1.5, 3 * markerScale)}
                  fill={stroke}
                  opacity={opacity}
                />
                <circle
                  cx={line.x2}
                  cy={line.y2}
                  r={Math.max(1.5, 3 * markerScale)}
                  fill={stroke}
                  opacity={opacity}
                />
              </g>
            );
          })}

          {savedMeasurements.map((measurement, index) => (
            <g key={`saved-${measurement.start_timestamp}-${measurement.end_timestamp}-${index}`} opacity={0.55}>
              <MeasurementOverlay measurement={measurement} xFor={xFor} yFor={yFor} />
            </g>
          ))}

          {activeMeasurement ? (
            <MeasurementOverlay measurement={activeMeasurement} xFor={xFor} yFor={yFor} />
          ) : null}

          {linkMode ? (
            <AnchorOverlay
              anchors={manualAnchors}
              bars={bars}
              plotTop={PAD.top}
              plotHeight={plotH}
              xFor={xFor}
              yFor={yFor}
              barPitch={barPitch}
              selectedSourceId={linkSourceAnchorId}
              selectedTargetId={linkTargetAnchorId}
              onAnchorClick={onAnchorClick}
              linkMode
              interactive
              showRanges
              showSingles
            />
          ) : null}

          {primaryIndex != null ? (
            <line
              x1={xFor(primaryIndex)}
              x2={xFor(primaryIndex)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke={primaryColor}
              strokeWidth={Math.max(0.8, 1.5 * markerScale)}
              strokeDasharray="5 3"
              opacity={0.95}
            />
          ) : null}
        </svg>
      </div>

      <div
        className={`pointer-events-none absolute right-3 top-3 rounded-full px-3 py-1.5 text-[11px] ${
          visualTheme === "apple"
            ? "bg-black/40 text-[#98989d] backdrop-blur-md"
            : "bg-neutral-950/90 font-mono text-ds-text-secondary"
        }`}
      >
        {t("stage1.chartHints.visibleStats", { visible: visibleCount, total: bars.length })}
      </div>

      {addEventMode ? (
        <div className="pointer-events-none absolute left-2 top-2 rounded bg-amber-950/90 px-2 py-1 text-[10px] font-mono text-ds-status-warning">
          {t("stage1.chartHints.clickAddEvent")}
        </div>
      ) : null}
      {measureKind ? (
        <div
          className={`pointer-events-none absolute rounded px-2 py-1 text-[10px] font-mono ${
            measureKind === "fixate"
              ? "bg-emerald-950/90 text-ds-status-healthy"
              : "bg-violet-950/90 text-ds-text-primary"
          } ${addEventMode ? "left-2 top-8" : "left-2 top-2"}`}
        >
          {measureKind === "fixate"
            ? t("stage1.chartHints.fixateEnd")
            : measureStartIndex == null
              ? t("stage1.chartHints.rulerStart")
              : t("stage1.chartHints.rulerEnd")}
        </div>
      ) : null}
      {anchorMode ? (
        <div
          className={`pointer-events-none absolute rounded bg-orange-950/90 px-2 py-1 text-[10px] font-mono text-ds-status-warning ${
            addEventMode || measureKind || linkMode ? "left-2 top-14" : "left-2 top-2"
          }`}
        >
          {anchorMode === "single"
            ? t("stage1.chartHints.anchorSingle")
            : anchorRangeStart == null
              ? t("stage1.chartHints.anchorRangeStart")
              : anchorRangeEnd == null
                ? t("stage1.chartHints.anchorRangeEnd")
                : t("stage1.chartHints.anchorSave")}
        </div>
      ) : null}
      {linkMode ? (
        <div
          className={`pointer-events-none absolute rounded bg-sky-950/90 px-2 py-1 text-[10px] font-mono text-ds-text-primary ${
            addEventMode || measureKind || anchorMode ? "left-2 top-14" : "left-2 top-2"
          }`}
        >
          {!linkSourceAnchorId
            ? t("stage1.chartHints.linkSelectSource")
            : !linkTargetAnchorId
              ? t("stage1.chartHints.linkSelectTarget")
              : t("stage1.chartHints.linkSelectType")}
        </div>
      ) : null}
    </div>
  );
});
