/** Per-card Model Assurance severity — never inherit overall CRITICAL onto all four cards. */

import type { ResolvedStatus, StatusKey, StatusTone } from "../status/types";

function status(label: string, tone: StatusTone, key: StatusKey): ResolvedStatus {
  return { domain: "system", key, label, tone };
}

export function mapOverallAssuranceSeverity(overall?: string | null): ResolvedStatus {
  const token = String(overall || "").toUpperCase();
  if (token === "CURRENT_CRITICAL" || token.includes("CRITICAL")) {
    return status("Critical", "critical", "critical");
  }
  if (token === "CURRENT_WARNING" || token.includes("WARNING")) {
    return status("Warning", "degraded", "degraded");
  }
  if (token === "CURRENT_STALE" || token.includes("STALE") || token.includes("MISSING")) {
    return status("Warning", "degraded", "degraded");
  }
  if (token === "CURRENT_WATCH" || token.includes("WATCH")) {
    return status("Informational", "offline", "informational");
  }
  if (token === "CURRENT_STABLE" || token.includes("STABLE") || token.includes("HEALTHY")) {
    return status("Healthy", "operational", "operational");
  }
  return status("Informational", "offline", "informational");
}

export function mapActiveRuntimeSeverity(active?: {
  status?: string | null;
  paper_only?: boolean | null;
  real_execution?: boolean | null;
} | null): ResolvedStatus {
  const runtimeStatus = String(active?.status || "").toUpperCase();
  const paperOnly = active?.paper_only !== false;
  const realExecution = active?.real_execution === true;

  if (
    runtimeStatus.includes("MISSING") ||
    runtimeStatus.includes("INVALID") ||
    runtimeStatus.includes("CONFLICT") ||
    runtimeStatus.includes("MISMATCH")
  ) {
    return status("Critical", "critical", "critical");
  }
  if (realExecution && paperOnly) {
    // Unexpected live execution while paper-only contract is claimed.
    return status("Critical", "critical", "critical");
  }
  if (realExecution) {
    return status("Critical", "critical", "critical");
  }
  if (runtimeStatus === "ACTIVE_REGISTERED" && paperOnly && !realExecution) {
    return status("Healthy", "operational", "operational");
  }
  if (runtimeStatus === "ACTIVE_REGISTERED") {
    return status("Healthy", "operational", "operational");
  }
  return status("Warning", "degraded", "degraded");
}

export function mapRuntimeSafetySeverity(safety?: string | null): ResolvedStatus {
  const token = String(safety || "").toUpperCase();
  if (
    token === "UNSAFE" ||
    token.includes("UNSAFE") ||
    token === "REAL_EXECUTION_ENABLED_UNEXPECTEDLY" ||
    token.includes("REAL_EXECUTION")
  ) {
    return status("Critical", "critical", "critical");
  }
  if (token === "SAFE_PAPER_ONLY") {
    return status("Healthy", "operational", "operational");
  }
  if (token === "UNKNOWN" || !token) {
    return status("Informational", "offline", "informational");
  }
  return status("Warning", "degraded", "degraded");
}

export function mapPromotionSeverity(input?: {
  promotion_execution_status?: string | null;
  promotion_control?: string | null;
  candidate_status?: string | null;
  eligibility_status?: string | null;
  environment_blockers?: string[] | null;
  blockers?: string[] | null;
  active_model_change_performed?: boolean | null;
  gate_status?: string | null;
} | null): ResolvedStatus {
  const execution = String(input?.promotion_execution_status || "DISABLED").toUpperCase();
  const control = String(input?.promotion_control || "GOVERNANCE_GATE").toUpperCase();
  const candidate = String(input?.candidate_status || "NONE_REGISTERED").toUpperCase();
  const eligibility = String(input?.eligibility_status || "NOT_APPLICABLE").toUpperCase();
  const gate = String(input?.gate_status || "").toUpperCase();
  const blockers = [...(input?.blockers || []), ...(input?.environment_blockers || [])].map((b) =>
    String(b).toUpperCase(),
  );
  const changed = input?.active_model_change_performed === true;

  if (changed || execution === "ENABLED" || execution.includes("EXECUTE")) {
    return status("Critical", "critical", "critical");
  }

  const hasCandidate =
    Boolean(candidate) &&
    candidate !== "NONE_REGISTERED" &&
    candidate !== "NOT_APPLICABLE" &&
    candidate !== "NO_CANDIDATE_REGISTERED";

  if (hasCandidate && (gate === "BLOCKED" || eligibility === "BLOCKED")) {
    const criticalBlocker = blockers.some((b) => b.includes("CRITICAL") || b.includes("EXECUTION"));
    if (criticalBlocker) {
      return status("Critical", "critical", "critical");
    }
    return status("Warning", "degraded", "degraded");
  }

  if (
    execution === "DISABLED" &&
    (control === "GOVERNANCE_GATE" || control === "BLOCKING") &&
    !hasCandidate
  ) {
    return status("Informational", "offline", "informational");
  }

  if (gate === "APPROVED_FOR_PROMOTION" && execution === "DISABLED") {
    return status("Informational", "offline", "informational");
  }

  return status("Informational", "offline", "informational");
}
