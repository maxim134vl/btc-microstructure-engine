import type { MeasurementPreview } from "./measurementUtils";
import { formatReturnPct, formatUsdChange } from "./measurementUtils";
import { formatPrice } from "../visual-cognition/chartUtils";

export function MeasurementOverlay({
  measurement,
  xFor,
  yFor,
}: {
  measurement: MeasurementPreview;
  xFor: (index: number) => number;
  yFor: (price: number) => number;
}) {
  const { start_index, end_index, start_price, end_price, return_pct, bars_count, absolute_price_change } =
    measurement;

  const x1 = xFor(start_index);
  const x2 = xFor(end_index);
  const y1 = yFor(start_price);
  const y2 = yFor(end_price);
  const positive = return_pct >= 0;
  const color = positive ? "#22c55e" : "#ef4444";

  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;
  const boxW = 118;
  const boxH = 62;

  return (
    <g pointerEvents="none">
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.5} strokeDasharray="6 4" opacity={0.95} />
      <circle cx={x1} cy={y1} r={4} fill={color} stroke="#f8fafc" strokeWidth={1} />
      <circle cx={x2} cy={y2} r={4} fill={color} stroke="#f8fafc" strokeWidth={1} />

      <rect
        x={midX - boxW / 2}
        y={midY - boxH / 2 - 8}
        width={boxW}
        height={boxH}
        rx={4}
        fill="#0a0a0a"
        stroke={color}
        strokeWidth={1}
        opacity={0.92}
      />
      <text x={midX} y={midY - 22} textAnchor="middle" fill={color} fontSize={13} fontWeight="600" fontFamily="monospace">
        {formatReturnPct(return_pct)}
      </text>
      <text x={midX} y={midY - 6} textAnchor="middle" fill="#e5e7eb" fontSize={10} fontFamily="monospace">
        {bars_count} bars
      </text>
      <text x={midX} y={midY + 10} textAnchor="middle" fill="#a3a3a3" fontSize={9} fontFamily="monospace">
        {formatUsdChange(absolute_price_change)}
      </text>
      <text x={midX} y={midY + 24} textAnchor="middle" fill="#737373" fontSize={8} fontFamily="monospace">
        {formatPrice(start_price)} → {formatPrice(end_price)}
      </text>
    </g>
  );
}
