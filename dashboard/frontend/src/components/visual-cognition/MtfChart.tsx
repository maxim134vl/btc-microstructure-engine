import type { CognitionBar } from "../../types/visualCognition";

export function MtfChart({
  timeframe,
  bars,
  cursorIndex,
}: {
  timeframe: string;
  bars: CognitionBar[];
  cursorIndex?: number | null;
}) {
  if (!bars.length) {
    return (
      <div className="flex h-32 items-center justify-center rounded border border-slate-900 text-[10px] text-slate-500">
        No {timeframe} cognition bars
      </div>
    );
  }

  const width = 640;
  const height = 120;
  const pad = { top: 8, right: 8, bottom: 18, left: 8 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const lows = bars.map((b) => b.low);
  const highs = bars.map((b) => b.high);
  const minP = Math.min(...lows);
  const maxP = Math.max(...highs);
  const span = maxP - minP || 1;

  const xFor = (index: number) => pad.left + (index / Math.max(bars.length - 1, 1)) * plotW;
  const yFor = (price: number) => pad.top + plotH - ((price - minP) / span) * plotH;
  const barW = Math.max(2, plotW / bars.length - 1);

  return (
    <div className="rounded border border-slate-900 bg-[#070b10] p-2">
      <div className="mb-1 flex items-center justify-between text-[10px] font-mono">
        <span className="text-slate-300">{timeframe}</span>
        <span className="text-slate-500">{bars.length} bars</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={`${timeframe} cognition chart`}>
        {bars.map((bar, index) => {
          const x = xFor(index) - barW / 2;
          const yHigh = yFor(bar.high);
          const yLow = yFor(bar.low);
          const yOpen = yFor(bar.open);
          const yClose = yFor(bar.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyH = Math.max(Math.abs(yClose - yOpen), 1);
          const initiative = bar.initiative ?? "dormant";
          const bodyColor = initiative === "buyer" ? "#22c55e" : initiative === "seller" ? "#ef4444" : "#64748b";
          const overlay = bar.overlay_color ?? "transparent";
          const zoneH = plotH * (1 - (bar.continuation_health ?? 0.5));

          return (
            <g key={`${timeframe}-${bar.timestamp}`}>
              {bar.behaviors && bar.behaviors.length > 0 ? (
                <rect
                  x={x - 1}
                  y={pad.top + zoneH * 0.15}
                  width={barW + 2}
                  height={plotH - zoneH * 0.15}
                  fill={overlay}
                  opacity={0.12}
                />
              ) : null}
              <line x1={x + barW / 2} x2={x + barW / 2} y1={yHigh} y2={yLow} stroke={bodyColor} strokeWidth={1} opacity={0.85} />
              <rect x={x} y={bodyTop} width={barW} height={bodyH} fill={bodyColor} opacity={0.9} />
              {bar.behaviors?.includes("BUYING_CLIMAX") || bar.behaviors?.includes("SELLING_CLIMAX") ? (
                <line x1={x + barW / 2} x2={x + barW / 2} y1={pad.top} y2={pad.top + plotH} stroke="#f97316" strokeWidth={1.5} strokeDasharray="3 2" opacity={0.9} />
              ) : null}
              {bar.behaviors?.includes("CONTRADICTION") ? (
                <rect x={x - 1} y={pad.top} width={barW + 2} height={plotH} fill="#a855f7" opacity={0.08} />
              ) : null}
            </g>
          );
        })}
        {cursorIndex != null && cursorIndex >= 0 ? (
          <line
            x1={xFor(cursorIndex) + barW / 2}
            x2={xFor(cursorIndex) + barW / 2}
            y1={pad.top}
            y2={pad.top + plotH}
            stroke="#38bdf8"
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        ) : null}
      </svg>
    </div>
  );
}
