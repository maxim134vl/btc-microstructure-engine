import type { ReactNode } from "react";
import type {
  DirectionalPositionStats,
  DirectionalSideStats,
  DirectionalStatusStats,
  TradingOperationsPerformance,
} from "../../types/ops";

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <article className={`ops-card ${className}`}>{children}</article>;
}

function formatCount(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function formatPct(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";
}

function SideRow({
  label,
  tone,
  stats,
  showWinRate,
}: {
  label: string;
  tone: "long" | "short";
  stats?: DirectionalSideStats | null;
  showWinRate: boolean;
}) {
  const color = tone === "long" ? "var(--ds-status-healthy)" : "var(--ds-status-error)";
  const wl =
    showWinRate && stats?.wins != null && stats?.losses != null
      ? `${stats.wins}W / ${stats.losses}L`
      : null;
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_5.5rem_6.5rem] items-baseline gap-2 py-1.5">
      <span className="text-[12px] font-semibold tracking-wide" style={{ color }}>
        {label}
      </span>
      <span className="text-[18px] font-semibold tabular-nums text-ds-text-primary">
        {formatCount(stats?.count)}
      </span>
      <span className="text-right text-[12px] tabular-nums text-ds-text-secondary">
        {formatPct(stats?.pct)}
      </span>
      <span className="text-right text-[12px] tabular-nums text-ds-text-primary">
        {showWinRate ? formatPct(stats?.win_rate_pct) : "—"}
        {wl ? <span className="mt-0.5 block text-[10px] text-ds-text-tertiary">{wl}</span> : null}
      </span>
    </div>
  );
}

function StatusColumn({
  title,
  group,
  showWinRate,
}: {
  title: string;
  group?: DirectionalStatusStats | null;
  showWinRate: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h4 className="text-[12px] font-semibold text-ds-text-primary">{title}</h4>
        <span className="text-[11px] tabular-nums text-ds-text-tertiary">
          {formatCount(group?.total)} total
        </span>
      </div>
      <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_5.5rem_6.5rem] gap-2 text-[10px] uppercase tracking-[0.08em] text-ds-text-tertiary">
        <span>Side</span>
        <span>Count</span>
        <span className="text-right">Share</span>
        <span className="text-right">Win rate</span>
      </div>
      <SideRow label="LONG" tone="long" stats={group?.long} showWinRate={showWinRate} />
      <SideRow label="SHORT" tone="short" stats={group?.short} showWinRate={showWinRate} />
    </div>
  );
}

export function TradingDirectionMixPanel({
  performance,
  liveConnected,
  generatedAt,
}: {
  performance?: TradingOperationsPerformance | null;
  liveConnected: boolean;
  generatedAt?: string | null;
}) {
  const unavailable = !liveConnected;
  const performanceUnavailable =
    !performance || performance.status === "UNKNOWN" || Boolean(performance.error);
  const hideLiveValues = unavailable || performanceUnavailable;
  const stats: DirectionalPositionStats | null | undefined = hideLiveValues
    ? null
    : performance?.directional_position_stats;
  const caption = unavailable
    ? generatedAt
      ? `Last known at: ${generatedAt}`
      : "Unavailable"
    : performanceUnavailable
      ? performance?.error || "Performance unavailable"
      : undefined;

  return (
    <Card className="overflow-hidden" data-panel="trading-direction-mix">
      <div className="flex items-center justify-between gap-3 border-b border-ds-border/35 px-3.5 py-3">
        <h3 className="text-[14px] font-semibold text-ds-text-primary">Long / Short mix</h3>
        {caption ? <span className="text-[11px] text-ds-text-tertiary">{caption}</span> : null}
      </div>
      <div className="grid gap-4 p-3.5 md:grid-cols-2">
        <StatusColumn title="Open positions" group={stats?.open} showWinRate={false} />
        <StatusColumn title="Closed trades" group={stats?.closed} showWinRate />
      </div>
      <p className="border-t border-ds-border/35 px-3.5 py-2 text-[11px] text-ds-text-tertiary">
        Share is LONG vs SHORT within open and within closed. Win rate is closed trades only (net &gt; 0).
      </p>
    </Card>
  );
}
