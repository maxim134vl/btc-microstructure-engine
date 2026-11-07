import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

test("Trading Operations section renders paired PnL and capital curve cards", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /TradingEquityCurvesPanel/);
  const panel = readFileSync(join(root, "src/components/ops/TradingEquityCurvesPanel.tsx"), "utf8");
  assert.match(panel, /PnL curve/);
  assert.match(panel, /Capital curve/);
  assert.match(panel, /equity_pnl_curves/);
  assert.doesNotMatch(panel, /shadow_economic_correlation|shadow_structural_protection/);
});

test("Trading Operations renders Long/Short mix under the equity curve cards", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  const curvesIdx = src.indexOf("<TradingEquityCurvesPanel");
  const mixIdx = src.indexOf("<TradingDirectionMixPanel");
  const marketIdx = src.indexOf('data-section="market-context"');
  assert.ok(curvesIdx >= 0 && mixIdx > curvesIdx && marketIdx > mixIdx);

  const panel = readFileSync(join(root, "src/components/ops/TradingDirectionMixPanel.tsx"), "utf8");
  assert.match(panel, /data-panel="trading-direction-mix"/);
  assert.match(panel, /Long \/ Short mix/);
  assert.match(panel, /Open positions/);
  assert.match(panel, /Closed trades/);
  assert.match(panel, /directional_position_stats/);
  assert.match(panel, /win_rate_pct/);
  assert.doesNotMatch(panel, /net_realised_pnl_usd|closed_trades\.map/);
});
