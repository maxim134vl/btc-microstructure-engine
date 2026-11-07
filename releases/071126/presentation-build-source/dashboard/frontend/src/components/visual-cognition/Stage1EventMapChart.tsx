import type { Stage1EventMapBar, Stage1EventMapEvent } from "../../types/visualCognition";
import { EXECUTION_MAP, barWidthForCount, formatPrice, formatTime } from "./chartUtils";
import { HollowCandle } from "./HollowCandle";
import { VolumeConcentrationLevel } from "./VolumeConcentrationLevel";

const AUDIT = {
  height: 320,
  pad: { top: 12, right: 16, bottom: 28, left: 58 },
};

export function Stage1EventMapChart({
  bars,
  events,
}: {
  bars: Stage1EventMapBar[];
  events: Stage1EventMapEvent[];
}) {
  if (!bars.length) {
    return <div className="py-8 text-center text-xs text-ds-text-tertiary">No candle history</div>;
  }

  const barW = barWidthForCount(bars.length);
  const { pad, height } = AUDIT;
  const plotH = height - pad.top - pad.bottom;
  const width = pad.left + pad.right + bars.length * barW;
  const minP = Math.min(...bars.map((b) => b.low));
  const maxP = Math.max(...bars.map((b) => b.high));
  const plotW = bars.length * barW;

  const xFor = (index: number) => pad.left + index * barW + barW / 2;
  const yFor = (price: number) => pad.top + plotH - ((price - minP) / (maxP - minP || 1)) * plotH;

  const tickStep = Math.max(1, Math.floor(bars.length / 8));
  const priceStep = (maxP - minP) / 4;

  return (
    <div className="overflow-x-auto rounded border border-neutral-800 bg-black">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Stage 1 full history event map">
        <rect width={width} height={height} fill={EXECUTION_MAP.background} />

        {Array.from({ length: 5 }, (_, i) => {
          const price = minP + priceStep * i;
          const y = yFor(price);
          return (
            <g key={`grid-${i}`}>
              <line x1={pad.left} x2={pad.left + plotW} y1={y} y2={y} stroke={EXECUTION_MAP.grid} strokeWidth={0.5} />
              <text x={pad.left - 6} y={y + 3} textAnchor="end" fill={EXECUTION_MAP.axis} fontSize={8} fontFamily="ui-monospace, monospace">
                {formatPrice(price)}
              </text>
            </g>
          );
        })}

        {bars.map((bar, index) => {
          const cx = xFor(index);
          return (
            <HollowCandle
              key={bar.timestamp}
              cx={cx}
              x={cx - barW / 2}
              barW={barW}
              yHigh={yFor(bar.high)}
              yLow={yFor(bar.low)}
              yOpen={yFor(bar.open)}
              yClose={yFor(bar.close)}
              opacity={0.85}
            />
          );
        })}

        {events.map((event) => (
          <VolumeConcentrationLevel
            key={`${event.bar_index}-${event.event}`}
            marker={{
              event: event.event,
              price: event.price,
              zone_low: event.zone_low,
              zone_high: event.zone_high,
              color: event.color,
            }}
            cx={xFor(event.bar_index)}
            cy={yFor(event.price)}
            barW={barW}
          />
        ))}

        {bars.map((bar, index) => {
          if (index % tickStep !== 0 && index !== bars.length - 1) return null;
          return (
            <text key={`t-${index}`} x={xFor(index)} y={height - 6} textAnchor="middle" fill={EXECUTION_MAP.axis} fontSize={7} fontFamily="ui-monospace, monospace">
              {formatTime(bar.timestamp)}
            </text>
          );
        })}

        <line x1={pad.left} x2={pad.left} y1={pad.top} y2={pad.top + plotH} stroke={EXECUTION_MAP.grid} strokeWidth={0.75} />
        <line x1={pad.left} x2={pad.left + plotW} y1={pad.top + plotH} y2={pad.top + plotH} stroke={EXECUTION_MAP.grid} strokeWidth={0.75} />
      </svg>
    </div>
  );
}
