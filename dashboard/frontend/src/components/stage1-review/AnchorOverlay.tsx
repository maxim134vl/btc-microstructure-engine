import type { ManualAnchor } from "../../types/manualAnnotations";
import type { ReviewCandleBar } from "../../types/eventReview";
import { anchorColor, resolveAnchorGeometry, type AnchorGeometry } from "./anchorUtils";
import { formatTime } from "../visual-cognition/chartUtils";

export function AnchorOverlay({
  anchors,
  bars,
  plotTop,
  plotHeight,
  xFor,
  yFor,
  barPitch,
  selectedSourceId,
  selectedTargetId,
  pendingRangeStart,
  pendingRangeEnd,
  onAnchorClick,
  linkMode,
  interactive = true,
  showRanges = true,
  showSingles = true,
}: {
  anchors: ManualAnchor[];
  bars: ReviewCandleBar[];
  plotTop: number;
  plotHeight: number;
  xFor: (index: number) => number;
  yFor: (price: number) => number;
  barPitch: number;
  selectedSourceId?: string | null;
  selectedTargetId?: string | null;
  pendingRangeStart?: number | null;
  pendingRangeEnd?: number | null;
  onAnchorClick?: (anchorId: string) => void;
  linkMode?: boolean;
  interactive?: boolean;
  showRanges?: boolean;
  showSingles?: boolean;
}) {
  const geometries = anchors
    .map((anchor) => resolveAnchorGeometry(anchor, bars))
    .filter((item): item is AnchorGeometry => item != null);

  return (
    <g pointerEvents={interactive ? "auto" : "none"}>
      {geometries.map((geom) => {
        if (geom.isRange && !showRanges) return null;
        if (!geom.isRange && !showSingles) return null;
        const color = anchorColor(geom.label);
        const isSource = selectedSourceId === geom.anchorId;
        const isTarget = selectedTargetId === geom.anchorId;
        const stroke = isSource ? "#38bdf8" : isTarget ? "#7dd3fc" : color;
        const opacity = isSource || isTarget ? 0.55 : 0.35;

        if (geom.isRange) {
          const x1 = xFor(geom.startIndex) - barPitch / 2;
          const x2 = xFor(geom.endIndex) + barPitch / 2;
          return (
            <g
              key={geom.anchorId}
              onClick={(event) => {
                if (linkMode && interactive) {
                  event.stopPropagation();
                  onAnchorClick?.(geom.anchorId);
                }
              }}
              style={{ cursor: linkMode && interactive ? "pointer" : "default" }}
            >
              <rect
                x={x1}
                y={plotTop}
                width={Math.max(x2 - x1, barPitch)}
                height={plotHeight}
                fill={color}
                opacity={opacity}
                stroke={stroke}
                strokeWidth={isSource || isTarget ? 1.5 : 0.8}
              />
              <text
                x={(x1 + x2) / 2}
                y={plotTop + 12}
                textAnchor="middle"
                fill={color}
                fontSize={8}
                fontFamily="monospace"
                opacity={0.95}
              >
                {geom.label.slice(0, 18)}
              </text>
            </g>
          );
        }

        const cx = xFor(geom.startIndex);
        const cy = yFor(geom.startPrice);
        return (
          <g
            key={geom.anchorId}
            onClick={(event) => {
              if (linkMode && interactive) {
                event.stopPropagation();
                onAnchorClick?.(geom.anchorId);
              }
            }}
            style={{ cursor: linkMode && interactive ? "pointer" : "default" }}
          >
            <line
              x1={cx}
              x2={cx}
              y1={plotTop}
              y2={plotTop + plotHeight}
              stroke={stroke}
              strokeWidth={isSource || isTarget ? 2 : 1.2}
              strokeDasharray={isSource || isTarget ? undefined : "3 2"}
              opacity={0.85}
            />
            <polygon
              points={`${cx},${cy - 8} ${cx + 6},${cy} ${cx},${cy + 8} ${cx - 6},${cy}`}
              fill={color}
              stroke={stroke}
              strokeWidth={1}
              opacity={0.95}
            />
            <text x={cx + 8} y={cy - 4} fill={color} fontSize={7} fontFamily="monospace">
              {geom.label.slice(0, 14)}
            </text>
          </g>
        );
      })}

      {showRanges && pendingRangeStart != null && pendingRangeEnd != null ? (
        <rect
          x={xFor(Math.min(pendingRangeStart, pendingRangeEnd)) - barPitch / 2}
          y={plotTop}
          width={Math.abs(xFor(pendingRangeEnd) - xFor(pendingRangeStart)) + barPitch}
          height={plotHeight}
          fill="#38bdf8"
          opacity={0.2}
          stroke="#38bdf8"
          strokeDasharray="4 2"
        />
      ) : null}

      {showRanges && pendingRangeStart != null && pendingRangeEnd == null ? (
        <line
          x1={xFor(pendingRangeStart)}
          x2={xFor(pendingRangeStart)}
          y1={plotTop}
          y2={plotTop + plotHeight}
          stroke="#38bdf8"
          strokeWidth={1.5}
          strokeDasharray="4 2"
        />
      ) : null}
    </g>
  );
}

export function anchorTimeLabel(anchor: ManualAnchor): string {
  if (anchor.anchor_type === "single" || anchor.start_timestamp === anchor.end_timestamp) {
    return formatTime(anchor.start_timestamp);
  }
  return `${formatTime(anchor.start_timestamp)} → ${formatTime(anchor.end_timestamp)}`;
}
