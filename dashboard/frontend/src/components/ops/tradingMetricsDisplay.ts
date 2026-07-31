/**
 * Display-only mapping for Trading Metrics.
 * Reads canonical OPS `trading_operations.performance` — never recomputes economics.
 */

export type MetricStatusBlock = {
  value?: number | null;
  status?: string | null;
  reason?: string | null;
};

export type TradingPerformancePortfolio = {
  closed_trade_count?: number | null;
  open_position_count?: number | null;
  total_fees_usd?: number | null;
  total_slippage_usd?: number | null;
  total_trading_costs_usd?: number | null;
  best_trade_usd?: number | null;
  worst_trade_usd?: number | null;
};

export type TradingDescriptiveMetrics = {
  wins?: number | null;
  losses?: number | null;
  win_rate?: number | MetricStatusBlock | null;
  average_win?: number | null;
  average_loss?: number | null;
  best_trade?: number | null;
  worst_trade?: number | null;
  profit_factor?: number | MetricStatusBlock | null;
  status?: string | null;
};

export type TradingRiskAdjustedMetrics = {
  sharpe?: number | MetricStatusBlock | null;
  sortino?: number | MetricStatusBlock | null;
  calmar?: number | MetricStatusBlock | null;
  max_drawdown?: number | MetricStatusBlock | null;
  drawdown?: number | MetricStatusBlock | null;
  drawdown_duration?: number | MetricStatusBlock | null;
  drawdown_duration_bars?: number | null;
  drawdown_duration_days?: number | null;
  status?: string | null;
};

export type TradingOperationsPerformance = {
  status?: string | null;
  error?: string | null;
  portfolio?: TradingPerformancePortfolio | null;
  descriptive_metrics?: TradingDescriptiveMetrics | null;
  risk_adjusted_metrics?: TradingRiskAdjustedMetrics | null;
};

/** Exact operator-facing labels — order matches OPS1.3 target block. */
export const TRADING_METRIC_LABELS = [
  "Closed trades",
  "Open positions",
  "Winning trades",
  "Losing trades",
  "Win rate",
  "Average win",
  "Average loss",
  "Best trade",
  "Worst trade",
  "Fees paid",
  "Slippage",
  "Total trading costs",
  "Sharpe",
  "Sortino",
  "Calmar",
  "Maximum drawdown",
  "Drawdown duration",
  "Profit factor",
] as const;

export type TradingMetricLabel = (typeof TRADING_METRIC_LABELS)[number];

export type TradingMetricKind = "count" | "usd" | "percent" | "ratio" | "duration";

export type TradingMetricDef = {
  label: TradingMetricLabel;
  kind: TradingMetricKind;
  /** Zero is a valid live value for this metric (empty epoch counts/fees). */
  zeroIsValid: boolean;
};

export const TRADING_METRIC_DEFS: readonly TradingMetricDef[] = [
  { label: "Closed trades", kind: "count", zeroIsValid: true },
  { label: "Open positions", kind: "count", zeroIsValid: true },
  { label: "Winning trades", kind: "count", zeroIsValid: true },
  { label: "Losing trades", kind: "count", zeroIsValid: true },
  { label: "Win rate", kind: "percent", zeroIsValid: true },
  { label: "Average win", kind: "usd", zeroIsValid: true },
  { label: "Average loss", kind: "usd", zeroIsValid: true },
  { label: "Best trade", kind: "usd", zeroIsValid: true },
  { label: "Worst trade", kind: "usd", zeroIsValid: true },
  { label: "Fees paid", kind: "usd", zeroIsValid: true },
  { label: "Slippage", kind: "usd", zeroIsValid: true },
  { label: "Total trading costs", kind: "usd", zeroIsValid: true },
  { label: "Sharpe", kind: "ratio", zeroIsValid: true },
  { label: "Sortino", kind: "ratio", zeroIsValid: true },
  { label: "Calmar", kind: "ratio", zeroIsValid: true },
  { label: "Maximum drawdown", kind: "percent", zeroIsValid: true },
  { label: "Drawdown duration", kind: "duration", zeroIsValid: true },
  { label: "Profit factor", kind: "ratio", zeroIsValid: true },
];

function isStatusBlock(value: unknown): value is MetricStatusBlock {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) && "value" in value);
}

/** Unwrap `{ value }` status blocks or plain numbers — no math. */
export function unwrapMetricNumber(
  value: number | MetricStatusBlock | null | undefined,
): number | null {
  if (value == null) return null;
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (isStatusBlock(value)) {
    const inner = value.value;
    return typeof inner === "number" && Number.isFinite(inner) ? inner : null;
  }
  return null;
}

function formatCount(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(0);
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

function formatPercent(value: number): string {
  // Canonical descriptive win_rate is already 0–100; drawdown may be fraction.
  if (Math.abs(value) <= 1) return `${(value * 100).toFixed(2)}%`;
  return `${value.toFixed(2)}%`;
}

function formatRatio(value: number): string {
  return value.toFixed(4);
}

function formatDuration(value: number): string {
  if (Number.isInteger(value)) return `${value}`;
  return value.toFixed(2);
}

export function formatTradingMetricValue(
  value: number | null | undefined,
  kind: TradingMetricKind,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  switch (kind) {
    case "count":
      return formatCount(value);
    case "usd":
      return formatUsd(value);
    case "percent":
      return formatPercent(value);
    case "ratio":
      return formatRatio(value);
    case "duration":
      return formatDuration(value);
    default:
      return String(value);
  }
}

/**
 * Pull the 18 display values from the existing performance payload.
 * Missing backend fields stay null (render as —) — never invent or sum.
 */
export function resolveTradingMetricRawValues(
  performance: TradingOperationsPerformance | null | undefined,
): Record<TradingMetricLabel, number | null> {
  const portfolio = performance?.portfolio ?? {};
  const descriptive = performance?.descriptive_metrics ?? {};
  const risk = performance?.risk_adjusted_metrics ?? {};

  const maxDrawdown =
    unwrapMetricNumber(risk.max_drawdown) ?? unwrapMetricNumber(risk.drawdown);

  const drawdownDuration =
    unwrapMetricNumber(risk.drawdown_duration) ??
    (typeof risk.drawdown_duration_bars === "number" ? risk.drawdown_duration_bars : null) ??
    (typeof risk.drawdown_duration_days === "number" ? risk.drawdown_duration_days : null);

  const bestTrade =
    unwrapMetricNumber(descriptive.best_trade) ??
    (typeof portfolio.best_trade_usd === "number" ? portfolio.best_trade_usd : null);
  const worstTrade =
    unwrapMetricNumber(descriptive.worst_trade) ??
    (typeof portfolio.worst_trade_usd === "number" ? portfolio.worst_trade_usd : null);

  const totalCosts =
    typeof portfolio.total_trading_costs_usd === "number" &&
    Number.isFinite(portfolio.total_trading_costs_usd)
      ? portfolio.total_trading_costs_usd
      : null;

  return {
    "Closed trades":
      typeof portfolio.closed_trade_count === "number" ? portfolio.closed_trade_count : null,
    "Open positions":
      typeof portfolio.open_position_count === "number" ? portfolio.open_position_count : null,
    "Winning trades": typeof descriptive.wins === "number" ? descriptive.wins : null,
    "Losing trades": typeof descriptive.losses === "number" ? descriptive.losses : null,
    "Win rate": unwrapMetricNumber(descriptive.win_rate),
    "Average win": typeof descriptive.average_win === "number" ? descriptive.average_win : null,
    "Average loss": typeof descriptive.average_loss === "number" ? descriptive.average_loss : null,
    "Best trade": bestTrade,
    "Worst trade": worstTrade,
    "Fees paid": typeof portfolio.total_fees_usd === "number" ? portfolio.total_fees_usd : null,
    Slippage: typeof portfolio.total_slippage_usd === "number" ? portfolio.total_slippage_usd : null,
    "Total trading costs": totalCosts,
    Sharpe: unwrapMetricNumber(risk.sharpe),
    Sortino: unwrapMetricNumber(risk.sortino),
    Calmar: unwrapMetricNumber(risk.calmar),
    "Maximum drawdown": maxDrawdown,
    "Drawdown duration": drawdownDuration,
    "Profit factor": unwrapMetricNumber(descriptive.profit_factor),
  };
}
