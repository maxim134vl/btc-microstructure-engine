import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  RAW_ENUM_KEY_PATTERN,
  countSectionMarkers,
  formatLiveMetric,
  humanizeStatusLabel,
  pickStatusLabel,
  toxicShowsQuietWhenDisconnected,
  unavailableCaption,
} from "../src/components/ops/unifiedDisplay.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

test("1 live API path uses real metric formatting", () => {
  const cycle = formatLiveMetric(5259, { liveConnected: true, zeroIsValid: false });
  assert.equal(cycle.text, "5259");
  assert.equal(cycle.isUnavailable, false);
});

test("2 API disconnected yields LIVE DATA UNAVAILABLE semantics", () => {
  const metric = formatLiveMetric(0, { liveConnected: false, zeroIsValid: false });
  assert.equal(metric.text, "—");
  assert.equal(metric.isUnavailable, true);
});

test("3 fallback does not invent zeros", () => {
  assert.equal(formatLiveMetric(0, { liveConnected: false }).text, "—");
  assert.equal(formatLiveMetric(null, { liveConnected: false }).text, "—");
});

test("4 last-known caption includes timestamp", () => {
  assert.match(unavailableCaption("2026-07-25T12:00:00Z"), /Last known at:/);
});

test("5 raw enum keys never displayed", () => {
  assert.equal(humanizeStatusLabel("status.system.informational"), "Informational");
  assert.equal(humanizeStatusLabel("status.engine.informational"), "Not evaluated");
  assert.equal(humanizeStatusLabel("status.validation.not_evaluated"), "Not evaluated");
  assert.equal(humanizeStatusLabel("status.validation.incomplete_non_blocking"), "Incomplete · Non-blocking");
  assert.ok(!humanizeStatusLabel("status.system.informational").includes("status."));
  assert.ok(RAW_ENUM_KEY_PATTERN.test("status.system.informational"));
});

test("6-11 section markers once in unified source", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  for (const marker of [
    'data-section="live-operations-summary"',
    'data-section="runtime-processes"',
    'data-section="trading-operations"',
    'data-section="market-context"',
    'data-section="pipeline-detail"',
    'data-section="known-limitations"',
    'data-section="model-assurance"',
    'data-section="historical-audit"',
  ]) {
    assert.equal(countSectionMarkers(src, marker), 1, marker);
  }
  assert.equal(countSectionMarkers(src, "<SectionLabel>Live Operations Summary</SectionLabel>"), 1);
  assert.equal(countSectionMarkers(src, "<SectionLabel>Model Assurance</SectionLabel>"), 1);
  assert.equal(countSectionMarkers(src, "<SectionLabel>Historical Audit</SectionLabel>"), 1);
});

test("12 paper controller migrated label present", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /MIGRATED · NOT REQUIRED/);
});

test("13 D1 expected", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /NOT LIVE · EXPECTED/);
});

test("14 auction synthesis non-required via known limitations status mapping", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /KNOWN_LIMITATION/);
});

test("15 phantom modules excluded from required process list", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /isPhantomProcessId/);
  assert.match(src, /Legacy \/ Excluded Modules/);
});

test("16 model assurance non-blocking observational copy", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /non-blocking for paper runtime/);
  assert.match(src, /mapOverallAssuranceSeverity/);
  assert.match(src, /mapRuntimeSafetySeverity/);
});

test("17 historical failures separated from active", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /Active failures/);
  assert.match(src, /Historical failures/);
});

test("18 toxic quiet suppressed when disconnected", () => {
  assert.equal(
    toxicShowsQuietWhenDisconnected({
      displayStatus: "HISTORICAL_ONLY",
      currentStatus: "NOT_CONNECTED",
      severityLabel: "QUIET",
    }),
    true,
  );
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.match(src, /LIVE DATA UNAVAILABLE/);
  assert.doesNotMatch(src, /Trend: flat/);
});

test("19 display helpers do not recompute trading totals", () => {
  // formatLiveMetric only formats provided values
  assert.equal(formatLiveMetric(1000, { liveConnected: true, format: (v) => `$${v}` }).text, "$1000");
});

test("20 trading metrics block mounted once under Trading Operations", () => {
  const src = readFileSync(join(root, "src/components/ops/OpsUnifiedDashboard.tsx"), "utf8");
  assert.equal(countSectionMarkers(src, "<TradingMetricsPanel"), 1);
  assert.equal(countSectionMarkers(src, 'data-panel="trading-metrics"'), 0); // panel marker lives in TradingMetricsPanel
  const tradingIdx = src.indexOf('data-section="trading-operations"');
  const metricsIdx = src.indexOf("<TradingMetricsPanel");
  const marketIdx = src.indexOf('data-section="market-context"');
  assert.ok(tradingIdx >= 0 && metricsIdx > tradingIdx && marketIdx > metricsIdx);

  const panel = readFileSync(join(root, "src/components/ops/TradingMetricsPanel.tsx"), "utf8");
  assert.match(panel, /data-panel="trading-metrics"/);
  assert.doesNotMatch(panel, /Initial capital|Current equity|Realized PnL|Unrealized PnL|Total return/);
});

test("pickStatusLabel hides raw i18n misses", () => {
  assert.equal(
    pickStatusLabel({
      resolvedLabel: "Operational with Limitations",
      i18nValue: "status.system.operational_with_limitations",
      i18nKey: "status.system.operational_with_limitations",
    }),
    "Operational with Limitations",
  );
});
