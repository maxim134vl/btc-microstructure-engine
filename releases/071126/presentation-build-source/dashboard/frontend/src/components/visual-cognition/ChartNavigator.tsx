import { useMemo } from "react";
import type { CognitionBar } from "../../types/visualCognition";
import { EXECUTION_MAP } from "./chartUtils";

export function ChartNavigator({
  bars,
  visibleStart,
  visibleEnd,
  width,
}: {
  bars: CognitionBar[];
  visibleStart: number;
  visibleEnd: number;
  width: number;
}) {
  const { path } = useMemo(() => {
    if (bars.length === 0 || width <= 0) {
      return { path: "" };
    }
    let min = Infinity;
    let max = -Infinity;
    for (const bar of bars) {
      min = Math.min(min, bar.low);
      max = Math.max(max, bar.high);
    }
    if (!Number.isFinite(min)) return { path: "" };
    const pad = (max - min) * 0.05 || max * 0.001 || 1;
    min -= pad;
    max += pad;
    const span = max - min || 1;
    const height = 32;
    const innerH = height - 6;

    const points = bars.map((bar, index) => {
      const x = bars.length <= 1 ? width / 2 : (index / (bars.length - 1)) * width;
      const y = 3 + innerH - ((bar.close - min) / span) * innerH;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    });

    return { path: points.join(" ") };
  }, [bars, width]);

  if (bars.length === 0 || width <= 0) return null;

  const height = 32;
  const denom = Math.max(bars.length - 1, 1);
  const viewLeft = (visibleStart / denom) * width;
  const viewRight = (visibleEnd / denom) * width;
  const viewWidth = Math.max(viewRight - viewLeft, 4);

  return (
    <div
      className="shrink-0 border-t border-neutral-800 bg-black/80 px-1 py-1"
      aria-label="Full history viewport indicator"
    >
      <svg width={width} height={height} className="block" role="img">
        <rect x={0} y={0} width={width} height={height} fill={EXECUTION_MAP.background} rx={2} />
        {path ? (
          <path d={path} fill="none" stroke={EXECUTION_MAP.neutralStroke} strokeWidth={0.75} opacity={0.45} />
        ) : null}
        <rect
          x={viewLeft}
          y={1}
          width={viewWidth}
          height={height - 2}
          fill="none"
          stroke="#38bdf8"
          strokeWidth={1}
          rx={2}
          opacity={0.85}
        />
        <rect x={viewLeft} y={1} width={viewWidth} height={height - 2} fill="#38bdf8" opacity={0.08} rx={2} />
      </svg>
    </div>
  );
}
