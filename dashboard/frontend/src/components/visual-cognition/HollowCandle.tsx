import { EXECUTION_MAP } from "./chartUtils";

/** Neutral hollow candle — price context only, never event-colored. */
export function HollowCandle({
  cx,
  x,
  barW,
  yHigh,
  yLow,
  yOpen,
  yClose,
  opacity = 1,
  neutralStroke = EXECUTION_MAP.neutralStroke,
  neutralFill = EXECUTION_MAP.neutralFill,
}: {
  cx: number;
  x: number;
  barW: number;
  yHigh: number;
  yLow: number;
  yOpen: number;
  yClose: number;
  opacity?: number;
  neutralStroke?: string;
  neutralFill?: string;
}) {
  const bodyTop = Math.min(yOpen, yClose);
  const bodyH = Math.max(Math.abs(yClose - yOpen), 0.75);

  return (
    <g opacity={opacity}>
      <line x1={cx} x2={cx} y1={yHigh} y2={yLow} stroke={neutralStroke} strokeWidth={0.75} />
      <rect
        x={x}
        y={bodyTop}
        width={barW}
        height={bodyH}
        fill={neutralFill}
        stroke={neutralStroke}
        strokeWidth={0.75}
      />
    </g>
  );
}
