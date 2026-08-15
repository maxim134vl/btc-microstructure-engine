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
