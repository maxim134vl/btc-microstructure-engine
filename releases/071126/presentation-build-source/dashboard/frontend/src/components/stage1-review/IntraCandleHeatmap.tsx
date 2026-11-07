import { EVENT_CLASS_COLORS, type VolumeLocationMarker } from "../../types/eventReview";

/** Heatmap-style volume zone inside candle — no symbols or labels. */
export function IntraCandleHeatmap({
  marker,
  cx,
  barW,
  yFor,
  isPrimary = false,
}: {
  marker: VolumeLocationMarker;
  cx: number;
  barW: number;
  yFor: (price: number) => number;
  isPrimary?: boolean;
}) {
  const color = EVENT_CLASS_COLORS[marker.event_class as keyof typeof EVENT_CLASS_COLORS] ?? "#06b6d4";
  const widthScale = isPrimary ? 0.85 : 0.68;
  const opacity = isPrimary ? 0.55 : 0.38;
  const bandW = barW * widthScale;
  const x = cx - bandW / 2;

  const zoneLow = marker.zone_low;
  const zoneHigh = marker.zone_high;
  const hasZone =
    zoneLow != null &&
    zoneHigh != null &&
    Number.isFinite(zoneLow) &&
    Number.isFinite(zoneHigh) &&
    Math.abs(zoneHigh - zoneLow) > 1e-9;

  const rect = hasZone ? (
    (() => {
      const yTop = yFor(zoneHigh);
      const yBottom = yFor(zoneLow);
      return (
        <rect
          x={x}
          y={yTop}
          width={bandW}
          height={Math.max(yBottom - yTop, 1)}
          fill={color}
          opacity={opacity}
          stroke={isPrimary ? color : "none"}
          strokeWidth={isPrimary ? 1.2 : 0}
        />
      );
    })()
  ) : marker.price != null && Number.isFinite(marker.price) ? (
    <rect
      x={x}
      y={yFor(marker.price) - (isPrimary ? 2 : 1.5)}
      width={bandW}
      height={isPrimary ? 4 : 3}
      fill={color}
      opacity={opacity}
      stroke={isPrimary ? color : "none"}
      strokeWidth={isPrimary ? 1 : 0}
    />
  ) : null;

  return rect;
}
