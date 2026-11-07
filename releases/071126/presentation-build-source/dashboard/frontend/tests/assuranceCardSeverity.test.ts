import assert from "node:assert/strict";
import test from "node:test";
import {
  mapActiveRuntimeSeverity,
  mapOverallAssuranceSeverity,
  mapPromotionSeverity,
  mapRuntimeSafetySeverity,
} from "../src/components/ops/assuranceCardSeverity.ts";

test("1 CURRENT_CRITICAL + SAFE_PAPER_ONLY keeps only overall critical", () => {
  const overall = mapOverallAssuranceSeverity("CURRENT_CRITICAL");
  const runtime = mapActiveRuntimeSeverity({
    status: "ACTIVE_REGISTERED",
    paper_only: true,
    real_execution: false,
  });
  const safety = mapRuntimeSafetySeverity("SAFE_PAPER_ONLY");
  const promotion = mapPromotionSeverity({
    promotion_execution_status: "DISABLED",
    promotion_control: "GOVERNANCE_GATE",
    candidate_status: "NONE_REGISTERED",
    eligibility_status: "NOT_APPLICABLE",
    environment_blockers: ["INPUT_DRIFT_CRITICAL"],
    blockers: [],
    active_model_change_performed: false,
  });

  assert.equal(overall.tone, "critical");
  assert.equal(overall.label, "Critical");
  assert.equal(runtime.tone, "operational");
  assert.equal(runtime.label, "Healthy");
  assert.equal(safety.tone, "operational");
  assert.equal(safety.label, "Healthy");
  assert.equal(promotion.tone, "offline");
  assert.equal(promotion.label, "Informational");
});

test("2 real_execution or unsafe runtime makes Runtime Safety critical", () => {
  const unsafe = mapRuntimeSafetySeverity("UNSAFE");
  const unexpected = mapRuntimeSafetySeverity("REAL_EXECUTION_ENABLED_UNEXPECTEDLY");
  const liveRuntime = mapActiveRuntimeSeverity({
    status: "ACTIVE_REGISTERED",
    paper_only: true,
    real_execution: true,
  });

  assert.equal(unsafe.tone, "critical");
  assert.equal(unexpected.tone, "critical");
  assert.equal(liveRuntime.tone, "critical");
  assert.equal(mapOverallAssuranceSeverity("CURRENT_CRITICAL").tone, "critical");
});
