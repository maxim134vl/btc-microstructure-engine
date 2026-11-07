import type { VolumeClassLabel, VolumeLocationMarker } from "../../types/visualCognition";
import { EVENT_MARKER_COLORS } from "./IntraCandleMarker";

/** Stage 1 volume event — horizontal concentration level inside candle only. No dots or symbols. */
export function VolumeConcentrationLevel({
  marker,
  cx,
  cy,
  barW,
}: {
  marker: VolumeLocationMarker;
  cx: number;
  cy: number;
  barW: number;
}) {
  const color = marker.color ?? EVENT_MARKER_COLORS[marker.event as VolumeClassLabel] ?? EVENT_MARKER_COLORS.NORMAL;
  const half = barW * 0.48;
  const isHav = marker.event === "HIGH_VARIANCE_VOLUME";

  return (
    <line
      x1={cx - half}
      x2={cx + half}
      y1={cy}
      y2={cy}
      stroke={color}
      strokeWidth={isHav ? 0.85 : 1.15}
      opacity={isHav ? 0.75 : 0.95}
      strokeLinecap="butt"
      aria-label={`${marker.event} at ${marker.price}`}
    />
  );
}
