import assert from "node:assert/strict";
import test from "node:test";
import {
  TRADING_METRIC_DEFS,
  TRADING_METRIC_LABELS,
  formatTradingMetricValue,
  resolveTradingMetricRawValues,
  unwrapMetricNumber,
} from "../src/components/ops/tradingMetricsDisplay.ts";

test("trading metrics exposes exactly 18 labels", () => {
  assert.equal(TRADING_METRIC_LABELS.length, 18);
  assert.equal(TRADING_METRIC_DEFS.length, 18);
  assert.deepEqual(
    TRADING_METRIC_DEFS.map((d) => d.label),
    [...TRADING_METRIC_LABELS],
  );
});

test("unwrapMetricNumber reads status blocks without inventing values", () => {
  assert.equal(unwrapMetricNumber(null), null);
  assert.equal(unwrapMetricNumber({ value: null, status: "INSUFFICIENT_SAMPLE" }), null);
  assert.equal(unwrapMetricNumber({ value: 1.25, status: "PRELIMINARY" }), 1.25);
  assert.equal(unwrapMetricNumber(0.42), 0.42);
});

test("resolveTradingMetricRawValues maps portfolio/descriptive fields only", () => {
  const raw = resolveTradingMetricRawValues({
    status: "AVAILABLE",
    portfolio: {
      closed_trade_count: 0,
      open_position_count: 0,
      total_fees_usd: 0,
      total_slippage_usd: 0,
    },
    descriptive_metrics: {
      status: "EMPTY_EPOCH",
      win_rate: null,
      profit_factor: null,
    },
    risk_adjusted_metrics: {
      status: "INSUFFICIENT_HISTORY",
      sharpe: null,
      calmar: null,
      drawdown: null,
    },
  });
  assert.equal(raw["Closed trades"], 0);
  assert.equal(raw["Open positions"], 0);
  assert.equal(raw["Fees paid"], 0);
  assert.equal(raw.Slippage, 0);
  assert.equal(raw["Total trading costs"], null); // no precomputed field — do not sum
  assert.equal(raw.Sortino, null);
  assert.equal(raw["Best trade"], null);
  assert.equal(raw["Win rate"], null);
  assert.equal(formatTradingMetricValue(0, "count"), "0");
  assert.equal(formatTradingMetricValue(null, "ratio"), "—");
});

test("canonical performance payload shows closed trades and win rate; Sharpe stays dash", () => {
  const performance = {
    status: "AVAILABLE",
    portfolio: {
      closed_trade_count: 6,
      open_position_count: 1,
      total_fees_usd: 12.5,
      total_slippage_usd: 3.25,
    },
    descriptive_metrics: {
      wins: 2,
      losses: 4,
      win_rate: 33.33,
      average_win: 10,
      average_loss: -5,
      profit_factor: { value: 1.2, status: "PRELIMINARY" },
    },
    risk_adjusted_metrics: {
      sharpe: { value: null, status: "INSUFFICIENT_SAMPLE" },
      sortino: { value: null, status: "INSUFFICIENT_SAMPLE" },
      calmar: { value: null, status: "INSUFFICIENT_HISTORY" },
    },
    source: {
      adapter: "src/btc_ml/trading/trading_performance_truth.py",
      included_sources: ["data/trading/intrabar_paper/EPOCH/books"],
      excluded_sources: ["RESEARCH_BAR_POLICY", "LEGACY_PAPER_CONTROLLER"],
    },
  };
  const raw = resolveTradingMetricRawValues(performance);
  assert.equal(raw["Closed trades"], 6);
  assert.equal(raw["Win rate"], 33.33);
  assert.equal(formatTradingMetricValue(raw["Win rate"], "percent"), "33.33%");
  assert.equal(raw.Sharpe, null);
  assert.equal(formatTradingMetricValue(raw.Sharpe, "ratio"), "—");
  // Panel contract: never treat shadow overlay paths as metric sources.
  assert.ok(!JSON.stringify(performance).includes("shadow_economic_correlation"));
  assert.ok(!JSON.stringify(performance).includes("shadow_structural_protection"));
  assert.ok(String(performance.source.adapter).endsWith("trading_performance_truth.py"));
});

test("preliminary equity-curve values render; drawdown duration uses hours", () => {
  const raw = resolveTradingMetricRawValues({
    status: "AVAILABLE",
    portfolio: { closed_trade_count: 8, open_position_count: 1 },
    descriptive_metrics: { wins: 2, losses: 6, win_rate: 25 },
    risk_adjusted_metrics: {
      sharpe: { value: -1.2345, status: "PRELIMINARY" },
      sortino: { value: -1.5, status: "PRELIMINARY" },
      calmar: { value: -12.3, status: "UNSTABLE_SHORT_HISTORY" },
      max_drawdown: { value: 0.0125, status: "PRELIMINARY" },
      drawdown_duration: { value: 31.5, status: "PRELIMINARY" },
    },
  });
  assert.equal(raw.Sharpe, -1.2345);
  assert.equal(formatTradingMetricValue(raw.Sharpe, "ratio"), "-1.2345");
  assert.equal(formatTradingMetricValue(raw["Maximum drawdown"], "percent"), "1.25%");
  assert.equal(formatTradingMetricValue(raw["Drawdown duration"], "duration"), "1d 7.50h");
  assert.equal(formatTradingMetricValue(12.5, "duration"), "12.50h");
});
