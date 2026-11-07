import assert from "node:assert/strict";
import test from "node:test";
import {
  buildDayResults,
  buildLedgerSummary,
  countByExit,
  mapExitReason,
  type StatementTrade,
} from "../src/components/trading-views/ledger.ts";

function trade(partial: Partial<StatementTrade> & Pick<StatementTrade, "time" | "exitReason" | "realizedPnlUsd">): StatementTrade {
  return {
    symbol: "BTCUSDT",
    timeframe: "H1",
    side: "Long",
    qty: 0.1,
    entryPrice: 100,
    exitPrice: 101,
    feeUsd: 1,
    orderId: "t",
    ...partial,
  };
}

test("exit reasons map stop, take, flip, and the near-TP rule", () => {
  assert.equal(mapExitReason("STOP_LOSS"), "stop");
  assert.equal(mapExitReason("SL"), "stop");
  assert.equal(mapExitReason("TAKE_PROFIT"), "take");
  assert.equal(mapExitReason("TP"), "take");
  assert.equal(mapExitReason("CONTEXT_FLIP"), "flip");
  assert.equal(mapExitReason("NEAR_TP_MISS"), "new_rule");
  assert.equal(mapExitReason("CONTEXT_END"), "other");
});

test("day return uses starting equity and exit buckets stay separate", () => {
  const trades = [
    trade({ time: "2026-09-02T07:00:00Z", exitReason: "take", realizedPnlUsd: 100, side: "Long" }),
    trade({ time: "2026-09-02T14:00:00Z", exitReason: "new_rule", realizedPnlUsd: -40, side: "Short" }),
    trade({ time: "2026-09-03T09:00:00Z", exitReason: "stop", realizedPnlUsd: -25, side: "Long" }),
    trade({ time: "2026-09-03T16:00:00Z", exitReason: "flip", realizedPnlUsd: 10, side: "Short" }),
  ];
  const days = buildDayResults(trades, 10_000);
  assert.equal(days[0].date, "2026-09-02");
  assert.equal(days[0].pnlUsd, 60);
  assert.equal(days[0].returnPct, 0.6);
  assert.equal(days[0].success, true);
  assert.equal(days[1].pnlUsd, -15);
  assert.equal(days[1].success, false);
  assert.deepEqual(countByExit(trades), { stop: 1, take: 1, flip: 1, new_rule: 1, other: 0 });
  const summary = buildLedgerSummary(trades, 10_000);
  assert.equal(summary.netPnlUsd, 45);
  assert.ok(summary.returnPct != null && Math.abs(summary.returnPct - 0.45) < 1e-9);
});
