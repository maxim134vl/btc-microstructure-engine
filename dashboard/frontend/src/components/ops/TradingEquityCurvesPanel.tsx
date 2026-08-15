import type { ReactNode } from "react";
import type { EquityPnlCurvePoint, EquityPnlCurves, TradingOperationsPerformance } from "../../types/ops";

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <article className={`ops-card ${className}`}>{children}</article>;
}

function usd(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(2)}` : "—";
}

function signedUsd(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

function shortTs(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 16) + "Z";
}

function finitePoints(points: EquityPnlCurvePoint[] | null | undefined, key: "equity_usd" | "pnl_usd") {
  return (points || []).filter((p) => typeof p[key] === "number" && Number.isFinite(p[key] as number) && Boolean(p.ts));
}

function sparkPath(
  values: number[],
  width: number,
  height: number,
  pad = 8,
  yMinOverride?: number,
  yMaxOverride?: number,
): { line: string; area: string; zeroY: number | null; yMin: number; yMax: number } {
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  let yMin = yMinOverride ?? Math.min(...values);
  let yMax = yMaxOverride ?? Math.max(...values);
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const scaleX = (i: number) => pad + (values.length <= 1 ? innerW / 2 : (i / (values.length - 1)) * innerW);
  const scaleY = (v: number) => pad + ((yMax - v) / (yMax - yMin)) * innerH;
  const coords = values.map((v, i) => `${scaleX(i).toFixed(2)},${scaleY(v).toFixed(2)}`);
  const line = coords.length ? `M ${coords.join(" L ")}` : "";
  const area = coords.length
    ? `M ${scaleX(0).toFixed(2)},${(pad + innerH).toFixed(2)} L ${coords.join(" L ")} L ${scaleX(values.length - 1).toFixed(2)},${(pad + innerH).toFixed(2)} Z`
    : "";
  const zeroY = yMin <= 0 && yMax >= 0 ? scaleY(0) : null;
  return { line, area, zeroY, yMin, yMax };
}

function CurveCard({
  title,
  value,
  hint,
  empty,
  stroke,
  fill,
  values,
  showZero,
}: {
  title: string;
  value: string;
  hint?: string;
  empty?: string;
  stroke: string;
  fill: string;
  values: number[];
  showZero?: boolean;
}) {
  const width = 640;
  const height = 168;
  const path = values.length ? sparkPath(values, width, height, 10, showZero ? Math.min(0, ...values) : undefined, showZero ? Math.max(0, ...values) : undefined) : null;
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-ds-border/35 px-3.5 py-3">
        <h3 className="text-[14px] font-semibold text-ds-text-primary">{title}</h3>
        <div className="text-right">
          <div className="text-[13px] font-medium tabular-nums text-ds-text-primary">{value}</div>
          {hint ? <div className="text-[11px] text-ds-text-tertiary">{hint}</div> : null}
        </div>
      </div>
      {empty ? (
        <p className="px-3.5 py-6 text-[12px] text-ds-text-secondary">{empty}</p>
      ) : (
        <svg viewBox={`0 0 ${width} ${height}`} className="block h-[168px] w-full" role="img" aria-label={title}>
          {path?.zeroY != null ? (
            <line
              x1="10"
              x2={width - 10}
              y1={path.zeroY}
              y2={path.zeroY}
              stroke="currentColor"
              strokeOpacity="0.22"
              strokeDasharray="4 4"
              className="text-ds-text-tertiary"
            />
          ) : null}
          {path?.area ? <path d={path.area} fill={fill} /> : null}
          {path?.line ? <path d={path.line} fill="none" stroke={stroke} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" /> : null}
        </svg>
      )}
    </Card>
  );
}

export function TradingEquityCurvesPanel({
  performance,
  liveConnected,
  generatedAt,
}: {
  performance?: TradingOperationsPerformance | null;
  liveConnected: boolean;
  generatedAt?: string | null;
}) {
  const curves: EquityPnlCurves | null | undefined = performance?.equity_pnl_curves;
  const points = curves?.points || [];
  const equityPts = finitePoints(points, "equity_usd");
  const pnlPts = finitePoints(points, "pnl_usd");
  const unavailable = !liveConnected;
  const emptyCaption = unavailable
    ? generatedAt
      ? `Last known at: ${generatedAt}`
      : "Unavailable"
    : curves?.status === "AVAILABLE"
      ? undefined
      : "No equity series";

  const lastPnl = curves?.last_pnl_usd;
  const pnlPositive = typeof lastPnl === "number" && lastPnl >= 0;
  const pnlStroke = pnlPositive ? "var(--ds-status-healthy)" : "var(--ds-status-error)";
  const pnlFill = pnlPositive
    ? "color-mix(in srgb, var(--ds-status-healthy) 16%, transparent)"
    : "color-mix(in srgb, var(--ds-status-error) 16%, transparent)";

  return (
    <div className="grid gap-3.5 xl:grid-cols-2" data-panel="trading-equity-curves">
      <CurveCard
        title="PnL curve"
        value={unavailable ? "—" : signedUsd(lastPnl)}
        hint={unavailable ? emptyCaption : `${curves?.point_count ?? 0} closes · ${shortTs(curves?.start_ts)} → ${shortTs(curves?.end_ts)}`}
        empty={emptyCaption && (!liveConnected || !pnlPts.length) ? emptyCaption : undefined}
        stroke={pnlStroke}
        fill={pnlFill}
        values={pnlPts.map((p) => p.pnl_usd as number)}
        showZero
      />
      <CurveCard
        title="Capital curve"
        value={unavailable ? "—" : usd(curves?.last_equity_usd)}
        hint={unavailable ? emptyCaption : `initial ${usd(curves?.initial_equity_usd)}`}
        empty={emptyCaption && (!liveConnected || !equityPts.length) ? emptyCaption : undefined}
        stroke="var(--ds-status-running)"
        fill="color-mix(in srgb, var(--ds-status-running) 14%, transparent)"
        values={equityPts.map((p) => p.equity_usd as number)}
      />
    </div>
  );
}
