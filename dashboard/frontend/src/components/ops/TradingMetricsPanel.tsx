import type { ReactNode } from "react";
import {
  TRADING_METRIC_DEFS,
  formatTradingMetricValue,
  resolveTradingMetricRawValues,
  type TradingOperationsPerformance,
} from "./tradingMetricsDisplay";

/** Existing project card shell (`ops-card` from index.css). */
function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <article className={`ops-card ${className}`}>{children}</article>;
}

function unavailableCaption(lastKnownAt?: string | null): string {
  if (lastKnownAt) return `Last known at: ${lastKnownAt}`;
  return "Unavailable";
}

/**
 * Trading Metrics — display-only grid for the 18 OPS performance fields.
 * Data source: `runtime_truth.trading_operations.performance` (active paper epoch).
 */
export function TradingMetricsPanel({
  performance,
  liveConnected,
  generatedAt,
}: {
  performance?: TradingOperationsPerformance | null;
  liveConnected: boolean;
  generatedAt?: string | null;
}) {
  const raw = resolveTradingMetricRawValues(performance);
  const sourceUnavailable =
    !liveConnected ||
    !performance ||
    performance.status === "UNKNOWN" ||
    Boolean(performance.error);

  return (
    <Card className="overflow-hidden" data-panel="trading-metrics">
      <div className="flex items-center justify-between gap-3 border-b border-ds-border/35 px-3.5 py-3">
        <h3 className="text-[14px] font-semibold text-ds-text-primary">Trading Metrics</h3>
        {sourceUnavailable ? (
          <span className="text-[11px] text-ds-text-tertiary">
            {!liveConnected ? unavailableCaption(generatedAt) : performance?.error || "Unavailable"}
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2.5 p-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
        {TRADING_METRIC_DEFS.map((def) => {
          const value = raw[def.label];
          const text =
            sourceUnavailable || value == null
              ? "—"
              : formatTradingMetricValue(value, def.kind);
          return (
            <Card key={def.label} className="min-w-0 p-2.5">
              <p className="truncate text-[11px] text-ds-text-secondary">{def.label}</p>
              <p className="mt-1 truncate text-[13px] font-medium tabular-nums text-ds-text-primary">
                {text}
              </p>
            </Card>
          );
        })}
      </div>
    </Card>
  );
}
