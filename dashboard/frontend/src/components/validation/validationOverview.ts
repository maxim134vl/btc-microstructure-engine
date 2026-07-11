import type { ValidationSnapshot } from "../../types/validation";

export type ValidationDomain =
  | "perception"
  | "reasoning"
  | "intermediate"
  | "calibration"
  | "evolution"
  | "architecture";

export const VALIDATION_DOMAIN_IDS: ValidationDomain[] = [
  "perception",
  "reasoning",
  "intermediate",
  "calibration",
  "evolution",
  "architecture",
];

/** @deprecated Use VALIDATION_DOMAIN_IDS with i18n keys validation.domains.{id} */
export const VALIDATION_DOMAINS: { id: ValidationDomain; label: string; description: string }[] = [
  { id: "perception", label: "Perception", description: "Stage 1 market perception benchmarks" },
  { id: "reasoning", label: "Reasoning", description: "Stage 2 synthesis and integrated chain" },
  { id: "intermediate", label: "Intermediate Cognition", description: "Stage 2.5 narration and live IC memory" },
  { id: "calibration", label: "Calibration", description: "Weekly intermediate cognition calibration" },
  { id: "evolution", label: "Evolution", description: "Longitudinal cognition memory and trust" },
  { id: "architecture", label: "Architecture", description: "Conformance backtest and drift" },
];

function pct(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

function avgScore(values: Array<number | null | undefined>): number | null {
  const nums = values.filter((v): v is number => v != null && !Number.isNaN(v));
  if (nums.length === 0) return null;
  return nums.reduce((sum, v) => sum + v, 0) / nums.length;
}

export type ExecutiveKpi = {
  id: string;
  label: string;
  value: string;
  hint?: string;
  tone?: "healthy" | "warning" | "error" | "neutral";
};

export function buildExecutiveKpis(
  snapshot: ValidationSnapshot,
  t: (key: string) => string,
): ExecutiveKpi[] {
  const s1 = snapshot.stage1.latest_run?.summary;
  const s2 = snapshot.stage2.latest_run?.summary;
  const integrated = snapshot.integrated.latest_run?.summary;
  const conformance = snapshot.conformance.latest_run?.summary;
  const calibration = snapshot.stage2_5_calibration?.live_assessment ?? snapshot.stage2_5_calibration?.latest_run;
  const evolution = snapshot.evolution;

  const overallScore = avgScore([
    s1?.confirmed_rate,
    s2?.reasoning_accuracy,
    integrated?.fully_confirmed_rate,
    conformance?.cognition_stability_score,
  ]);

  const cognitionHealth = snapshot.conformance.cognition_health ?? "UNKNOWN";
  const healthEmoji = snapshot.conformance.health_emoji ?? "⚪";

  const archScore = conformance?.cognition_stability_score;
  const calibrationScore = conformance?.calibration_health_score;
  const calibrationStatus = calibration?.overall_status ?? conformance?.calibration_health_score != null ? "Tracked" : "—";

  const evolutionVerdict = evolution.regression?.verdict ?? evolution.trust?.current_trust_level ?? "—";
  const improving =
    evolution.regression?.verdict === "IMPROVEMENT" ||
    Object.values(evolution.evolution?.trends ?? {}).filter((t) => t === "improving").length >
      Object.values(evolution.evolution?.trends ?? {}).filter((t) => t === "degrading").length;

  return [
    {
      id: "overall",
      label: t("validation.kpis.overallScore.label"),
      value: overallScore != null ? pct(overallScore) : "—",
      hint: overallScore != null ? t("validation.kpis.overallScore.hintBlend") : t("validation.kpis.overallScore.hintBaseline"),
      tone: overallScore != null && overallScore >= 0.55 ? "healthy" : overallScore != null ? "warning" : "neutral",
    },
    {
      id: "health",
      label: t("validation.kpis.cognitionHealth.label"),
      value: `${healthEmoji} ${cognitionHealth}`,
      hint: snapshot.conformance.purpose,
      tone:
        cognitionHealth === "DRIFTING" || cognitionHealth === "DEGRADED"
          ? "warning"
          : cognitionHealth === "HEALTHY" || cognitionHealth === "STABLE"
            ? "healthy"
            : "neutral",
    },
    {
      id: "architecture",
      label: t("validation.kpis.architecture.label"),
      value: archScore != null ? pct(archScore) : cognitionHealth,
      hint: archScore != null ? t("validation.kpis.architecture.hintScore") : t("validation.kpis.architecture.hintState"),
      tone: archScore != null && archScore >= 0.5 ? "healthy" : archScore != null ? "warning" : "neutral",
    },
    {
      id: "calibration",
      label: t("validation.kpis.calibration.label"),
      value: calibrationScore != null ? pct(calibrationScore) : String(calibrationStatus),
      hint: calibration?.overall_metrics ? t("validation.kpis.calibration.hintTracker") : t("validation.kpis.calibration.hintWeekly"),
      tone:
        String(calibrationStatus).includes("DEGRAD") || String(calibrationStatus).includes("NEEDS")
          ? "warning"
          : calibrationScore != null && calibrationScore >= 0.4
            ? "healthy"
            : "neutral",
    },
    {
      id: "evolution",
      label: t("validation.kpis.evolution.label"),
      value: String(evolutionVerdict),
      hint: improving ? t("validation.kpis.evolution.hintImproving") : t("validation.kpis.evolution.hintVerdict"),
      tone: evolutionVerdict === "IMPROVEMENT" ? "healthy" : evolutionVerdict === "REGRESSION" ? "error" : "neutral",
    },
  ];
}
