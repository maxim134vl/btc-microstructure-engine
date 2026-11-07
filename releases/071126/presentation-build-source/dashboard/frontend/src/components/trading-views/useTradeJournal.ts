import { useMonitorStore } from "../../store/monitorStore";
import type { EquityPnlCurvePoint, TradeJournalRow } from "../../types/ops";
import { mapExitReason, type EquityPoint, type StatementSide, type StatementTrade } from "./ledger";

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function mapSide(raw: string | null | undefined): StatementSide | null {
  const side = String(raw ?? "").trim().toUpperCase();
  if (side === "LONG" || side === "BUY") return "Long";
  if (side === "SHORT" || side === "SELL") return "Short";
  return null;
}

function mapRow(row: TradeJournalRow): StatementTrade | null {
  const side = mapSide(row.side);
  const pnl = finite(row.realized_pnl_usd);
  const time = String(row.time ?? "").trim();
  if (!side || pnl == null || !time) return null;
  return {
    time,
    symbol: String(row.symbol ?? "BTCUSDT"),
    timeframe: String(row.timeframe ?? ""),
    side,
    exitReason: mapExitReason(row.exit_reason),
    qty: finite(row.qty),
    entryPrice: finite(row.entry_price),
    exitPrice: finite(row.exit_price),
    feeUsd: finite(row.fee_usd),
    realizedPnlUsd: pnl,
    orderId: String(row.order_id ?? ""),
  };
}

function mapCurve(points: EquityPnlCurvePoint[] | null | undefined): EquityPoint[] {
  const out: EquityPoint[] = [];
  for (const point of points ?? []) {
    const equity = finite(point.equity_usd);
    const pnl = finite(point.pnl_usd);
    const time = String(point.ts ?? "").trim();
    if (equity == null || pnl == null || !time) continue;
    out.push({ time, equityUsd: equity, pnlUsd: pnl });
  }
  return out;
}

export function useTradeJournal() {
  const connected = useMonitorStore((state) => state.connected);
  const performance = useMonitorStore(
    (state) => state.snapshot?.runtime_truth?.trading_operations?.performance ?? null,
  );
  const journal = performance?.trade_journal ?? null;
  const ready = connected && journal != null;
  const trades = ready ? (journal?.trades ?? []).flatMap((row) => {
    const mapped = mapRow(row);
    return mapped ? [mapped] : [];
  }) : [];
  const curves = performance?.equity_pnl_curves;
  const equityCurve = ready && curves?.status === "AVAILABLE" ? mapCurve(curves.points) : [];
  return {
    connected: ready,
    trades,
    symbol: journal?.symbol || "BTCUSDT",
    initialEquity: finite(journal?.initial_equity_usd) ?? finite(performance?.equity_pnl_curves?.initial_equity_usd),
    equityCurve,
    ownerSummary: {
      trades: performance?.portfolio?.closed_trade_count ?? null,
      netPnlUsd: performance?.portfolio?.realised_net_pnl_usd ?? null,
      feesUsd: performance?.portfolio?.total_fees_usd ?? null,
    },
  };
}
