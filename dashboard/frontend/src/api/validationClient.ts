import type {
  EvolutionReport,
  EvolutionRun,
  EvolutionSnapshot,
  Stage2_5CalibrationSnapshot,
  Stage2_5Comparison,
  StageComparison,
  ValidationReport,
  ValidationRun,
  ValidationSnapshot,
  ValidationSummary,
} from "../types/validation";

const API = "/api/v1";

export async function fetchValidationSnapshot(): Promise<ValidationSnapshot> {
  const response = await fetch(`${API}/validation/snapshot`);
  if (!response.ok) throw new Error(`validation snapshot ${response.status}`);
  return response.json();
}

export async function runValidationBenchmark(lookbackDays = 7, forwardHorizon = 7): Promise<ValidationRun> {
  const response = await fetch(
    `${API}/validation/run?lookback_days=${lookbackDays}&forward_horizon=${forwardHorizon}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`validation run ${response.status}`);
  return response.json();
}

export async function runStage2Benchmark(lookbackDays = 7, forwardHorizon = 11): Promise<ValidationRun> {
  const response = await fetch(
    `${API}/validation/stage2/run?lookback_days=${lookbackDays}&forward_horizon=${forwardHorizon}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`stage2 validation run ${response.status}`);
  return response.json();
}

export async function runIntegratedBenchmark(lookbackDays = 7, forwardHorizon = 11): Promise<ValidationRun> {
  const response = await fetch(
    `${API}/validation/integrated/run?lookback_days=${lookbackDays}&forward_horizon=${forwardHorizon}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`integrated validation run ${response.status}`);
  return response.json();
}

export async function runConformanceBacktest(lookbackDays = 7, layer?: string): Promise<ValidationRun> {
  const layerParam = layer ? `&layer=${layer}` : "";
  const response = await fetch(
    `${API}/validation/conformance/run?lookback_days=${lookbackDays}${layerParam}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`conformance run ${response.status}`);
  return response.json();
}

export async function fetchConformanceHealth(): Promise<{
  status: string;
  cognition_health?: string;
  health_emoji?: string;
  summary?: ValidationSummary;
}> {
  const response = await fetch(`${API}/validation/conformance/health`);
  if (!response.ok) throw new Error(`conformance health ${response.status}`);
  return response.json();
}

export async function runStage2_5Calibration(force = false): Promise<Record<string, unknown>> {
  const response = await fetch(`${API}/validation/stage2_5/calibration/run?force=${force}`, { method: "POST" });
  if (!response.ok) throw new Error(`stage2.5 calibration run ${response.status}`);
  return response.json();
}

export async function fetchStage2_5Calibration(): Promise<Stage2_5CalibrationSnapshot> {
  const response = await fetch(`${API}/validation/stage2_5/calibration`);
  if (!response.ok) throw new Error(`stage2.5 calibration snapshot ${response.status}`);
  return response.json();
}

export async function runStage2_5Benchmark(start = "2026-05-21", end = "2026-05-28 23:59:59"): Promise<ValidationRun> {
  const response = await fetch(
    `${API}/validation/stage2_5/run?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`stage2.5 validation run ${response.status}`);
  return response.json();
}

export async function compareStage2_5VsOutcome(): Promise<Stage2_5Comparison> {
  const response = await fetch(`${API}/validation/stage2_5/compare`);
  if (!response.ok) throw new Error(`stage2.5 compare ${response.status}`);
  return response.json();
}

export async function fetchValidationReport(stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance" = "stage1"): Promise<ValidationReport> {
  const response = await fetch(`${API}/validation/report?stage=${stage}`);
  if (!response.ok) throw new Error(`validation report ${response.status}`);
  return response.json();
}

export async function generateVisualReplay(
  stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance" = "stage1",
  lookbackDays = 7,
  forwardHorizon = stage === "stage1" ? 7 : 11,
): Promise<ValidationRun> {
  if (stage === "conformance") {
    return runConformanceBacktest(lookbackDays);
  }
  const response = await fetch(
    `${API}/validation/visuals?stage=${stage}&lookback_days=${lookbackDays}&forward_horizon=${forwardHorizon}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`validation visuals ${response.status}`);
  return response.json();
}

export async function exportValidationPackage(
  stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance" = "stage1",
): Promise<{ status: string; exports: { type: string; path: string }[] }> {
  const response = await fetch(`${API}/validation/export?stage=${stage}`);
  if (!response.ok) throw new Error(`validation export ${response.status}`);
  return response.json();
}

export async function compareStage1Stage2(): Promise<StageComparison> {
  const response = await fetch(`${API}/validation/compare`);
  if (!response.ok) throw new Error(`validation compare ${response.status}`);
  return response.json();
}

export async function fetchEvolutionSnapshot(): Promise<EvolutionSnapshot> {
  const response = await fetch(`${API}/validation/evolution/snapshot`);
  if (!response.ok) throw new Error(`evolution snapshot ${response.status}`);
  return response.json();
}

export async function runEvolutionCycle(fullCycle = false): Promise<EvolutionRun> {
  const response = await fetch(`${API}/validation/evolution/run?full_cycle=${fullCycle}`, { method: "POST" });
  if (!response.ok) throw new Error(`evolution run ${response.status}`);
  return response.json();
}

export async function fetchEvolutionReport(): Promise<EvolutionReport> {
  const response = await fetch(`${API}/validation/evolution/report`);
  if (!response.ok) throw new Error(`evolution report ${response.status}`);
  return response.json();
}
