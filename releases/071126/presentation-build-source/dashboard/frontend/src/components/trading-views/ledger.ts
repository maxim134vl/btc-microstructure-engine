export type StatementSide = "Long" | "Short";
export type ExitReason = "stop" | "take" | "flip" | "new_rule" | "other";

export type StatementTrade = {
  time: string;
  symbol: string;
  timeframe: string;
  side: StatementSide;
  exitReason: ExitReason;
  qty: number | null;
  entryPrice: number | null;
  exitPrice: number | null;
  feeUsd: number | null;
  realizedPnlUsd: number;
  orderId: string;
};

export type DayResult = {
  date: string;
  trades: number;
  wins: number;
  winRate: number;
  pnlUsd: number;
  returnPct: number | null;
  success: boolean;
};

export type EquityPoint = {
  time: string;
  equityUsd: number;
  pnlUsd: number;
};

export type LedgerSummary = {
  trades: number;
  wins: number;
  winRate: number;
  netPnlUsd: number;
  feesUsd: number;
  returnPct: number | null;
  maxDrawdownPct: number | null;
  profitFactor: number | null;
};

export function mapExitReason(raw: string | null | undefined): ExitReason {
  const text = String(raw ?? "").trim().toUpperCase();
  if (!text) return "other";
  if (text.includes("NEAR_TP")) return "new_rule";
  if (text.includes("FLIP")) return "flip";
  if (text === "TP" || text.includes("TAKE")) return "take";
  if (text === "SL" || text.includes("STOP")) return "stop";
  return "other";
}

export function dayKeyFromIso(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function buildEquitySeries(trades: StatementTrade[], initialEquity: number): EquityPoint[] {
  const ordered = [...trades].sort((a, b) => a.time.localeCompare(b.time));
  if (!ordered.length || !Number.isFinite(initialEquity)) return [];
  let equity = initialEquity;
  let pnl = 0;
  const points: EquityPoint[] = [{ time: ordered[0].time, equityUsd: equity, pnlUsd: 0 }];
  for (const trade of ordered) {
    pnl += trade.realizedPnlUsd;
    equity += trade.realizedPnlUsd;
    points.push({ time: trade.time, equityUsd: equity, pnlUsd: pnl });
  }
  return points;
}

export function buildDayResults(trades: StatementTrade[], initialEquity: number | null): DayResult[] {
  const ordered = [...trades].sort((a, b) => a.time.localeCompare(b.time));
  const groups = new Map<string, StatementTrade[]>();
  for (const trade of ordered) {
    const key = dayKeyFromIso(trade.time);
    const bucket = groups.get(key);
    if (bucket) bucket.push(trade);
    else groups.set(key, [trade]);
  }

  let equity = initialEquity;
  const days: DayResult[] = [];
  for (const [date, bucket] of groups) {
    const pnlUsd = bucket.reduce((sum, trade) => sum + trade.realizedPnlUsd, 0);
    const wins = bucket.filter((trade) => trade.realizedPnlUsd > 0).length;
    const startEquity = equity;
    if (equity != null) equity += pnlUsd;
    days.push({
      date,
      trades: bucket.length,
      wins,
      winRate: bucket.length ? wins / bucket.length : 0,
      pnlUsd,
      returnPct: startEquity != null && startEquity !== 0 ? (pnlUsd / startEquity) * 100 : null,
      success: pnlUsd > 0,
    });
  }
  return days;
}

export function countBySide(trades: StatementTrade[]): { long: number; short: number } {
  return {
    long: trades.filter((trade) => trade.side === "Long").length,
    short: trades.filter((trade) => trade.side === "Short").length,
  };
}

export function countByExit(trades: StatementTrade[]): Record<ExitReason, number> {
  const counts: Record<ExitReason, number> = { stop: 0, take: 0, flip: 0, new_rule: 0, other: 0 };
  for (const trade of trades) counts[trade.exitReason] += 1;
  return counts;
}

export function dayResultMap(days: DayResult[]): Map<string, DayResult> {
  return new Map(days.map((day) => [day.date, day]));
}

export function buildLedgerSummary(
  trades: StatementTrade[],
  initialEquity: number | null,
  equityPoints: EquityPoint[] = [],
): LedgerSummary {
  const wins = trades.filter((trade) => trade.realizedPnlUsd > 0);
  const losses = trades.filter((trade) => trade.realizedPnlUsd < 0);
  const grossWin = wins.reduce((sum, trade) => sum + trade.realizedPnlUsd, 0);
  const grossLoss = Math.abs(losses.reduce((sum, trade) => sum + trade.realizedPnlUsd, 0));
  const netPnlUsd = trades.reduce((sum, trade) => sum + trade.realizedPnlUsd, 0);
  const feesUsd = trades.reduce((sum, trade) => sum + (trade.feeUsd ?? 0), 0);
  const series = equityPoints.length
    ? equityPoints
    : initialEquity != null
      ? buildEquitySeries(trades, initialEquity)
      : [];
  let maxDrawdownPct: number | null = series.length ? 0 : null;
  if (series.length && maxDrawdownPct != null) {
    let peak = series[0].equityUsd;
    for (const point of series) {
      peak = Math.max(peak, point.equityUsd);
      const dd = peak ? ((peak - point.equityUsd) / peak) * 100 : 0;
      maxDrawdownPct = Math.max(maxDrawdownPct, dd);
    }
  }
  return {
    trades: trades.length,
    wins: wins.length,
    winRate: trades.length ? wins.length / trades.length : 0,
    netPnlUsd,
    feesUsd,
    returnPct: initialEquity != null && initialEquity !== 0 ? (netPnlUsd / initialEquity) * 100 : null,
    maxDrawdownPct,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
  };
}
