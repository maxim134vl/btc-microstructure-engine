import type { ResolvedStatus, StatusTone } from "./types";
import type { ArtifactFreshness } from "../../types/ops";

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

function isStaleToken(value?: string | null, freshness?: ArtifactFreshness | null): boolean {
  if (freshness?.is_stale) return true;
  const token = (value || "").toUpperCase();
  return (
    token.includes("STALE") ||
    token === "STALE_VALIDATION" ||
    token === "STALE_GOVERNANCE_DATA" ||
    token === "STALE_DRIFT_DATA" ||
    token === "MISSING_DATA" ||
    token === "UNKNOWN_FRESHNESS" ||
    token === "GOVERNANCE_MISSING"
  );
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
export function resolveGovernanceStatus(
  level: string,
  governanceStatus?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const raw = governanceStatus?.trim() || "UNKNOWN";
  const upper = raw.toUpperCase();
  if (upper === "GOVERNANCE_MISSING" || upper === "MISSING_DATA" || upper === "MISSING") {
    return researchStatus(upper === "GOVERNANCE_MISSING" ? "GOVERNANCE_MISSING" : "MISSING", "degraded");
  }
  if (isStaleToken(raw, freshness)) {
    const label = raw.includes("STALE") || freshness?.is_stale ? raw : `${raw}+STALE`;
    return researchStatus(label, "degraded");
  }
  return researchStatus(raw, levelToTone(level));
}

/** Drift Monitoring: composite PSI + shadow performance severity. */
export function resolveDriftStatus(
  level: string,
  severityLabel?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  if (isStaleToken(severityLabel, freshness)) {
    const label = severityLabel?.trim() || "STALE_DRIFT_DATA";
    return researchStatus(label, "degraded");
  }
  const label =
    severityLabel?.trim() ||
    (() => {
      const normalized = level.toUpperCase();
      if (normalized === "GREEN") return "Stable";
      if (normalized === "RED") return "Critical";
      if (normalized === "GREY") return "Unknown";
      return "Warning";
    })();
  return researchStatus(label, levelToTone(level));
}

/** Toxic Box: rate-based severity labels. */
export function resolveToxicStatus(
  level: string,
  severityLabel?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  if (isStaleToken(severityLabel, freshness)) {
    return researchStatus(severityLabel?.trim() || "STALE", "degraded");
  }
  const label =
    severityLabel?.trim() ||
    (() => {
      const normalized = level.toUpperCase();
      if (normalized === "GREEN") return "Normal";
      if (normalized === "RED") return "Critical";
      return "Elevated";
    })();
  return researchStatus(label, levelToTone(level));
}

/** Economic Validation: outcome health labels. */
export function resolveEconomicStatus(
  level: string,
  status?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const normalized = level.toUpperCase();
  const statusToken = (status || "").toUpperCase();
  if (isStaleToken(status, freshness)) {
    return researchStatus(status?.trim() || "STALE_VALIDATION", "degraded");
  }
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

/** Shadow Model: validation_status PASS · REVIEW · FAIL · NOT_EVALUATED · STALE_* */
export function resolveShadowStatus(
  level: string,
  validationStatus?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const vs = (validationStatus || "").toUpperCase();
  if (isStaleToken(validationStatus, freshness)) {
    return researchStatus(validationStatus?.trim() || "STALE_VALIDATION", "degraded");
  }
  let label = "REVIEW";
  if (vs === "PASS") label = "PASS";
  else if (vs === "WARNING") label = "REVIEW";
  else if (vs === "NOT_EVALUATED" || vs === "NO_DATA" || vs === "UNAVAILABLE") label = "Not evaluated";
  else if (vs === "MISSING" || vs === "MISSING_DATA") label = "MISSING_DATA";
  else if (vs === "FAIL") label = "FAIL";
  else if (level.toUpperCase() === "GREY") label = "Not evaluated";
  else if (level.toUpperCase() === "GREEN") label = "PASS";
  else if (level.toUpperCase() === "RED") label = "FAIL";

  return researchStatus(label, levelToTone(level));
}

/** Model Summary executive card. */
export function resolveModelSummaryStatus(
  level: string,
  status?: string | null,
  freshness?: ArtifactFreshness | null,
  attentionReason?: string | null,
): ResolvedStatus {
  const token = (status || "").trim().toUpperCase();
  if (isStaleToken(status, freshness) || token === "ATTENTION") {
    const reason = attentionReason?.trim();
    const label = reason
      ? `ATTENTION · ${reason}`
      : token === "ATTENTION"
        ? "ATTENTION"
        : status?.trim() || "STALE_VALIDATION";
    return researchStatus(label, "degraded");
  }
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

export function formatSourceTimestamp(value?: string | null): string {
  if (!value) return "MISSING";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return String(value);
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** True when a date string is the June legacy monitoring stamp. */
export function isLegacyJunePrimaryDate(value?: string | null): boolean {
  if (!value) return false;
  const normalized = String(value);
  return /2026-06-14/.test(normalized) || /Jun\s*14/i.test(normalized);
}

/** Display lines for Model Summary source priority (benchmark primary / governance / legacy). */
export function formatModelSummarySourceLines(
  sources?: {
    diagnostics_primary?: {
      generated_at?: string | null;
      freshness_status?: string;
      source_path?: string | null;
      used_as_primary?: boolean;
    } | null;
    governance?: {
      status?: string;
      missing_reason?: string | null;
      source_path?: string | null;
    } | null;
    legacy_monitoring?: {
      timestamp?: string | null;
      used_as_primary?: boolean;
      is_stale?: boolean;
      freshness_status?: string;
      source_path?: string | null;
    } | null;
  } | null,
  options?: {
    version?: string | null;
    promotionEligible?: string | null;
    reason?: string | null;
  },
): string[] {
  const diagnostics = sources?.diagnostics_primary;
  const governance = sources?.governance;
  const legacy = sources?.legacy_monitoring;

  const diagStatus = (diagnostics?.freshness_status || "MISSING").toUpperCase();
  const govRaw = (governance?.status || "MISSING").toUpperCase();
  const govStatus =
    govRaw === "GOVERNANCE_MISSING" || govRaw === "MISSING_DATA" ? "GOVERNANCE_MISSING" : govRaw;
  const legacyStatus =
    legacy?.is_stale || (legacy?.freshness_status || "").toUpperCase().includes("STALE")
      ? "STALE"
      : (legacy?.freshness_status || "MISSING").toUpperCase();

  const lines = [
    `Data source: ${options?.version || "benchmark_primary_v1"}`,
    `Latest diagnostics: ${formatSourceTimestamp(diagnostics?.generated_at ?? null)} · ${diagStatus}`,
    `Source: ${diagnostics?.source_path || "MISSING"}`,
    `Governance: ${govStatus}`,
    `Legacy monitoring: ${formatSourceTimestamp(legacy?.timestamp ?? null)} · ${legacyStatus} · ${
      legacy?.used_as_primary ? "primary" : "not primary"
    }`,
    `Promotion eligible: ${options?.promotionEligible || "NO"}`,
  ];
  if (options?.reason) {
    lines.push(`Reason: ${options.reason}`);
  }
  return lines;
}
