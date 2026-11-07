import { useTranslation } from "../../i18n";
import { pnlTone, price, qty, signedUsd, statementTime, usd } from "./format";
import { type ExitReason, type StatementTrade } from "./ledger";
import { useTradeJournal } from "./useTradeJournal";
import { ViewFrame } from "./ViewFrame";

function SummaryTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <article className="ops-card px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">{label}</p>
      <p className="mt-1 font-ds-display text-[22px] font-semibold tabular-nums" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
    </article>
  );
}

function periodLabel(trades: StatementTrade[]): string {
  if (!trades.length) return "";
  const times = trades.map((trade) => trade.time).sort();
  return `${statementTime(times[0])} — ${statementTime(times[times.length - 1])}`;
}

export function StatementPanel({ fillWindow = false }: { fillWindow?: boolean }) {
  const { t } = useTranslation();
  const journal = useTradeJournal();
  const rows = [...journal.trades].sort((a, b) => b.time.localeCompare(a.time));
  const summary = journal.ownerSummary;

  return (
    <ViewFrame fillWindow={fillWindow}>
      {journal.connected ? null : (
        <p className="px-0.5 text-[12px] text-ds-text-secondary">{t("tradingViews.unavailable")}</p>
      )}
      <section className="space-y-2.5" data-section="statement-summary">
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryTile label={t("tradingViews.statement.symbol")} value={journal.symbol} />
          <SummaryTile label={t("tradingViews.statement.trades")} value={String(summary.trades ?? "—")} />
          <SummaryTile
            label={t("tradingViews.statement.netPnl")}
            value={signedUsd(summary.netPnlUsd)}
            tone={pnlTone(summary.netPnlUsd)}
          />
          <SummaryTile label={t("tradingViews.statement.fees")} value={usd(summary.feesUsd)} />
        </div>
        <p className="px-0.5 text-[12px] text-ds-text-tertiary">
          {periodLabel(journal.trades)}
          {periodLabel(journal.trades) ? " · " : ""}
          {t("tradingViews.statement.period")}
        </p>
      </section>

      <section className="ops-card overflow-hidden" data-section="statement-table">
        <div className="panel-scroll overflow-x-auto">
          <table className="w-full min-w-[1080px] border-collapse text-left font-ds-text">
            <thead>
              <tr className="border-b border-ds-border/60 text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.time")}</th>
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.symbol")}</th>
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.timeframe")}</th>
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.side")}</th>
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.exitReason")}</th>
                <th className="px-3.5 py-2.5 text-right font-semibold">{t("tradingViews.statement.columns.qty")}</th>
                <th className="px-3.5 py-2.5 text-right font-semibold">{t("tradingViews.statement.columns.entry")}</th>
                <th className="px-3.5 py-2.5 text-right font-semibold">{t("tradingViews.statement.columns.exit")}</th>
                <th className="px-3.5 py-2.5 text-right font-semibold">{t("tradingViews.statement.columns.fee")}</th>
                <th className="px-3.5 py-2.5 text-right font-semibold">{t("tradingViews.statement.columns.pnl")}</th>
                <th className="px-3.5 py-2.5 font-semibold">{t("tradingViews.statement.columns.order")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={11} className="px-3.5 py-8 text-[13px] text-ds-text-secondary">
                    {t("tradingViews.statement.empty")}
                  </td>
                </tr>
              ) : (
                rows.map((row) => <StatementRow key={`${row.timeframe}:${row.orderId}:${row.time}`} row={row} />)
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-ds-border/70 text-[12px] font-semibold text-ds-text-primary">
                <td className="px-3.5 py-2.5" colSpan={8}>
                  {t("tradingViews.statement.total")}
                </td>
                <td className="px-3.5 py-2.5 text-right font-mono tabular-nums">{usd(summary.feesUsd)}</td>
                <td
                  className="px-3.5 py-2.5 text-right font-mono tabular-nums"
                  style={{ color: pnlTone(summary.netPnlUsd) }}
                >
                  {signedUsd(summary.netPnlUsd)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </section>
    </ViewFrame>
  );
}

function exitLabel(reason: ExitReason, t: (key: string) => string): string {
  if (reason === "new_rule") return t("tradingViews.charts.newRule");
  return t(`tradingViews.charts.${reason}`);
}

function StatementRow({ row }: { row: StatementTrade }) {
  const { t } = useTranslation();
  const sideLabel = row.side === "Long" ? t("tradingViews.statement.long") : t("tradingViews.statement.short");
  return (
    <tr className="border-b border-ds-border/35 text-[13px] text-ds-text-primary last:border-b-0">
      <td className="whitespace-nowrap px-3.5 py-2 font-mono text-[12px] tabular-nums text-ds-text-secondary">
        {statementTime(row.time)}
      </td>
      <td className="px-3.5 py-2 font-medium">{row.symbol}</td>
      <td className="px-3.5 py-2 font-medium">{row.timeframe || "—"}</td>
      <td className="px-3.5 py-2">
        <span style={{ color: row.side === "Long" ? "var(--ds-status-healthy)" : "var(--ds-status-error)" }}>
          {sideLabel}
        </span>
      </td>
      <td className="px-3.5 py-2">{exitLabel(row.exitReason, t)}</td>
      <td className="px-3.5 py-2 text-right font-mono tabular-nums">{qty(row.qty)}</td>
      <td className="px-3.5 py-2 text-right font-mono tabular-nums">{price(row.entryPrice)}</td>
      <td className="px-3.5 py-2 text-right font-mono tabular-nums">{price(row.exitPrice)}</td>
      <td className="px-3.5 py-2 text-right font-mono tabular-nums text-ds-text-secondary">{usd(row.feeUsd)}</td>
      <td className="px-3.5 py-2 text-right font-mono tabular-nums" style={{ color: pnlTone(row.realizedPnlUsd) }}>
        {signedUsd(row.realizedPnlUsd)}
      </td>
      <td className="px-3.5 py-2 font-mono text-[12px] text-ds-text-tertiary">{row.orderId}</td>
    </tr>
  );
}
