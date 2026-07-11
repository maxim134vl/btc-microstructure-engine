import { EVENT_CLASS_COLORS, type Stage1EventClass } from "../../types/eventReview";

/** Visible class-colored pin above the candle — scales with zoom level. */
export function EventOverlayPin({
  cx,
  yHigh,
  eventClass,
  isPrimary,
  stackIndex = 0,
  scale = 1,
}: {
  cx: number;
  yHigh: number;
  eventClass: Stage1EventClass;
  isPrimary: boolean;
  stackIndex?: number;
  scale?: number;
}) {
  const color = EVENT_CLASS_COLORS[eventClass];
  const baseSize = isPrimary ? 6 : 4.5;
  const size = Math.max(2, baseSize * scale);
  const offsetX = stackIndex * (size + 1);
  const cy = yHigh - (isPrimary ? 12 : 9) * scale - stackIndex * 1.5 * scale;

  return (
    <g transform={`translate(${cx + offsetX}, ${cy})`} opacity={isPrimary ? 1 : 0.85}>
      <polygon
        points={`0,${size} ${-size},${-size} ${size},${-size}`}
        fill={color}
        stroke={isPrimary ? "#f8fafc" : color}
        strokeWidth={Math.max(0.4, (isPrimary ? 1.2 : 0.6) * scale)}
      />
      {isPrimary && scale >= 0.5 ? (
        <circle
          cx={0}
          cy={0}
          r={size + 2 * scale}
          fill="none"
          stroke={color}
          strokeWidth={Math.max(0.5, 1.4 * scale)}
          opacity={0.9}
        />
      ) : null}
    </g>
  );
}
