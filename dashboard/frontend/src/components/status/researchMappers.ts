import type { ResolvedStatus, StatusTone } from "./types";

const RESEARCH_RIBBON_KEYS = new Set([
  "decision_layer",
  "model_governance",
  "economic_validation",
  "shadow_inference",
  "toxic_box",
  "pipeline_sync",
]);

function levelToTone(level: string): StatusTone {
  const normalized = level.toUpperCase();
  if (normalized === "GREEN" || normalized === "HEALTHY") return "operational";
  if (normalized === "YELLOW" || normalized === "DEGRADED") return "degraded";
  if (normalized === "GREY") return "offline";
  return "critical";
}

function researchStatus(label: string, tone: StatusTone): ResolvedStatus {
  return { domain: "research", key: "semantic", label, tone };
}

/** Decision Layer: business posture — RED only when memories are missing. */
const DECISION_LABELS: Record<string, string> = {
  ENTRY_ELIGIBLE: "Healthy",
  STAND_ASIDE: "Stand Aside",
  OBSERVE: "Observe",
  REVERSAL_WATCH: "Reversal Watch",
  NO_ENTRY: "No Entry",
  WATCH: "Watch",
  UNAVAILABLE: "Unavailable",
};

export function resolveDecisionStatus(level: string, statusLabel?: string): ResolvedStatus {
  const normalized = level.toUpperCase();
  let label = "Watch";

  if (statusLabel && DECISION_LABELS[statusLabel]) {
    label = DECISION_LABELS[statusLabel];
  } else if (normalized === "GREEN") {
    label = "Healthy";
  } else if (normalized === "GREY" || normalized === "RED") {
    label = "Unavailable";
  }

  return researchStatus(label, levelToTone(level));
}

/** ML Governance: display governance_status token directly. */
export function resolveGovernanceStatus(level: string, governanceStatus?: string | null): ResolvedStatus {
  const label = governanceStatus?.trim() || "UNKNOWN";
  return researchStatus(label, levelToTone(level));
}

/** Drift Monitoring: composite PSI + shadow performance severity. */
export function resolveDriftStatus(level: string, severityLabel?: string | null): ResolvedStatus {
  const label = severityLabel?.trim() || (() => {
    const normalized = level.toUpperCase();
    if (normalized === "GREEN") return "Stable";
    if (normalized === "RED") return "Critical";
    if (normalized === "GREY") return "Unknown";
    return "Warning";
  })();
  return researchStatus(label, levelToTone(level));
}

/** Toxic Box: rate-based severity labels. */
export function resolveToxicStatus(level: string, severityLabel?: string | null): ResolvedStatus {
  const label = severityLabel?.trim() || (() => {
    const normalized = level.toUpperCase();
    if (normalized === "GREEN") return "Normal";
    if (normalized === "RED") return "Critical";
    return "Elevated";
  })();
  return researchStatus(label, levelToTone(level));
}

/** Economic Validation: outcome health labels. */
export function resolveEconomicStatus(level: string, status?: string | null): ResolvedStatus {
  const normalized = level.toUpperCase();
  const statusToken = (status || "").toUpperCase();
  let label = "Review";
  if (normalized === "GREY" || statusToken === "NOT_EVALUATED" || statusToken === "NO_DATA") {
    label = "Not evaluated";
  } else if (normalized === "GREEN") {
    label = "Passing";
  } else if (normalized === "RED") {
    label = "Failing";
  }
  return researchStatus(label, levelToTone(level));
}

/** Shadow Model: validation_status PASS · REVIEW · FAIL · NOT_EVALUATED */
export function resolveShadowStatus(level: string, validationStatus?: string | null): ResolvedStatus {
  const vs = (validationStatus || "").toUpperCase();
  let label = "REVIEW";
  if (vs === "PASS") label = "PASS";
  else if (vs === "WARNING") label = "REVIEW";
  else if (vs === "NOT_EVALUATED" || vs === "NO_DATA" || vs === "UNAVAILABLE") label = "Not evaluated";
  else if (vs === "MISSING") label = "Not evaluated";
  else if (vs === "FAIL") label = "FAIL";
  else if (level.toUpperCase() === "GREY") label = "Not evaluated";
  else if (level.toUpperCase() === "GREEN") label = "PASS";
  else if (level.toUpperCase() === "RED") label = "FAIL";

  return researchStatus(label, levelToTone(level));
}

/** Model Summary executive card. */
export function resolveModelSummaryStatus(level: string, status?: string | null): ResolvedStatus {
  const token = (status || "").trim().toUpperCase();
  let label = status?.trim() || "UNKNOWN";
  if (token === "MISSING" || token === "NOT_EVALUATED" || level.toUpperCase() === "GREY") {
    label = "Not evaluated";
  }
  return researchStatus(label, levelToTone(level));
}

/** Pipeline sync: 24/24 orchestration health. */
export function resolvePipelineSyncStatus(level: string): ResolvedStatus {
  const normalized = level.toUpperCase();
  const label = normalized === "GREEN" ? "Synced" : "Out of Sync";
  return researchStatus(label, levelToTone(level));
}

export function isResearchRibbonKey(key: string): boolean {
  return RESEARCH_RIBBON_KEYS.has(key);
}

export function resolveResearchRibbonItem(item: {
  key: string;
  label: string;
  level: string;
  value?: string;
}): ResolvedStatus {
  switch (item.key) {
    case "decision_layer":
      return resolveDecisionStatus(item.level, item.value);
    case "model_governance":
      return resolveGovernanceStatus(item.level, item.value);
    case "economic_validation":
      return resolveEconomicStatus(item.level, item.value);
    case "shadow_inference":
      return resolveShadowStatus(item.level, item.value);
    case "toxic_box":
      return resolveToxicStatus(item.level);
    case "pipeline_sync":
      return resolvePipelineSyncStatus(item.level);
    default:
      return resolveDecisionStatus(item.level);
  }
}
