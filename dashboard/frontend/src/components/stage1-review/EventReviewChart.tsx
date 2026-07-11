import { useMemo } from "react";
import type { ReviewCandleBar, Stage1EventClass, WindowOverlayEvent } from "../../types/eventReview";
import { EVENT_CLASS_COLORS } from "../../types/eventReview";
import { HollowCandle } from "../visual-cognition/HollowCandle";
import { EXECUTION_MAP, formatPrice, formatTime, priceTicks, timeTickIndices } from "../visual-cognition/chartUtils";
import { useElementSize } from "../visual-cognition/useElementSize";
import { EventOverlayPin } from "./EventOverlayPin";
import { IntraCandleHeatmap } from "./IntraCandleHeatmap";

const PAD = { top: 16, right: 16, bottom: 28, left: 58 };

function priceExtent(bars: ReviewCandleBar[]) {
  let minP = Infinity;
  let maxP = -Infinity;
  for (const bar of bars) {
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

export function EventReviewChart({
  bars,
  eventIndex,
  windowEvents = [],
  showAllInWindow = true,
}: {
  bars: ReviewCandleBar[];
  eventIndex: number | null;
  windowEvents?: WindowOverlayEvent[];
  showAllInWindow?: boolean;
}) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const chartWidth = Math.max(width, 480);
  const chartHeight = Math.max(height, 320);

  const layout = useMemo(() => {
    const plotW = chartWidth - PAD.left - PAD.right;
    const plotH = chartHeight - PAD.top - PAD.bottom;
    const { minP, maxP } = priceExtent(bars);
    const span = maxP - minP || 1;
    const barW = Math.max(2, plotW / Math.max(bars.length, 1) - 1.2);

    return {
      plotH,
      minP,
      maxP,
      barW,
      xFor: (index: number) => PAD.left + (index / Math.max(bars.length - 1, 1)) * plotW,
      yFor: (price: number) => PAD.top + plotH - ((price - minP) / span) * plotH,
    };
  }, [bars, chartWidth, chartHeight]);

  const visibleOverlays = useMemo(() => {
    const list = showAllInWindow ? windowEvents : windowEvents.filter((event) => event.is_primary);
    return [...list].sort((a, b) => {
      if (a.is_primary === b.is_primary) return a.bar_index_in_window - b.bar_index_in_window;
      return a.is_primary ? 1 : -1;
    });
  }, [windowEvents, showAllInWindow]);

  const primaryOverlay = windowEvents.find((event) => event.is_primary);
  const primaryIndex = primaryOverlay?.bar_index_in_window ?? eventIndex;
  const primaryColor =
    primaryOverlay?.event_class ? EVENT_CLASS_COLORS[primaryOverlay.event_class] : "#ef4444";

  return (
    <div ref={ref} className="h-full min-h-[320px] w-full rounded border border-neutral-800 bg-black">
      <svg width={chartWidth} height={chartHeight} role="img" aria-label="M15 event context chart">
        <rect x={0} y={0} width={chartWidth} height={chartHeight} fill={EXECUTION_MAP.background} />

        {priceTicks(layout.minP, layout.maxP).map((price) => {
          const y = layout.yFor(price);
          return (
            <g key={price}>
              <line x1={PAD.left} x2={chartWidth - PAD.right} y1={y} y2={y} stroke={EXECUTION_MAP.grid} strokeWidth={0.5} />
              <text x={PAD.left - 6} y={y + 3} textAnchor="end" fill={EXECUTION_MAP.axis} fontSize={9} fontFamily="ui-monospace, monospace">
                {formatPrice(price)}
              </text>
            </g>
          );
        })}

        {timeTickIndices(bars.length).map((index) => {
          const bar = bars[index];
          if (!bar) return null;
          return (
            <text
              key={index}
              x={layout.xFor(index)}
              y={chartHeight - 8}
              textAnchor="middle"
              fill={EXECUTION_MAP.axis}
              fontSize={8}
              fontFamily="ui-monospace, monospace"
            >
              {formatTime(bar.timestamp)}
            </text>
          );
        })}

        {bars.map((bar, index) => {
          const cx = layout.xFor(index);
          return (
            <HollowCandle
              key={`${bar.timestamp}-${index}`}
              cx={cx}
              x={cx - layout.barW / 2}
              barW={layout.barW}
              yHigh={layout.yFor(bar.high)}
              yLow={layout.yFor(bar.low)}
              yOpen={layout.yFor(bar.open)}
              yClose={layout.yFor(bar.close)}
              opacity={0.82}
            />
          );
        })}

        {visibleOverlays.flatMap((overlay) => {
          const cx = layout.xFor(overlay.bar_index_in_window);
          const bar = bars[overlay.bar_index_in_window];
          const stackIndex = stackIndexForBar(visibleOverlays, overlay);

          const heatmaps = overlay.volume_location_markers.map((marker, markerIndex) => (
            <IntraCandleHeatmap
              key={`heat-${overlay.timestamp}-${overlay.event_class}-${markerIndex}`}
              marker={{ ...marker, event_class: overlay.event_class }}
              cx={cx}
              barW={layout.barW}
              yFor={layout.yFor}
              isPrimary={overlay.is_primary}
            />
          ));

          const pin =
            bar != null ? (
              <EventOverlayPin
                key={`pin-${overlay.timestamp}-${overlay.event_class}`}
                cx={cx}
                yHigh={layout.yFor(bar.high)}
                eventClass={overlay.event_class as Stage1EventClass}
                isPrimary={overlay.is_primary}
                stackIndex={stackIndex}
              />
            ) : null;

          return [...heatmaps, pin].filter(Boolean);
        })}

        {primaryIndex != null ? (
          <line
            x1={layout.xFor(primaryIndex)}
            x2={layout.xFor(primaryIndex)}
            y1={PAD.top}
            y2={PAD.top + layout.plotH}
            stroke={primaryColor}
            strokeWidth={1.5}
            strokeDasharray="5 3"
            opacity={0.95}
          />
        ) : null}
      </svg>
    </div>
  );
}
