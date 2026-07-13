import { RAW_STATUS_PATTERN, labelFor } from "./vocabulary";
import { isResearchRibbonKey, resolveResearchRibbonItem } from "./researchMappers";
import type { ResolvedStatus, StatusDomain, StatusTone } from "./types";

function system(key: ResolvedStatus["key"], tone: StatusTone): ResolvedStatus {
  return { domain: "system", key, label: labelFor("system", key), tone };
}

function feed(key: ResolvedStatus["key"], tone: StatusTone): ResolvedStatus {
  return { domain: "feed", key, label: labelFor("feed", key), tone };
}

function engine(key: ResolvedStatus["key"], tone: StatusTone): ResolvedStatus {
  return { domain: "engine", key, label: labelFor("engine", key), tone };
}

function validation(key: ResolvedStatus["key"], tone: StatusTone): ResolvedStatus {
  return { domain: "validation", key, label: labelFor("validation", key), tone };
}

function opsLevelTone(level?: string | null): StatusTone {
  const normalized = (level || "UNKNOWN").toUpperCase();
  if (normalized === "GREEN" || normalized === "HEALTHY" || normalized === "OPERATIONAL") return "operational";
  if (normalized === "YELLOW" || normalized === "DEGRADED" || normalized === "DEFERRED" || normalized === "ATTENTION") {
    return "degraded";
  }
  if (normalized === "GREY" || normalized === "UNKNOWN" || normalized === "MISSING_DATA" || normalized === "") {
    return "offline";
  }
  return "critical";
}

function opsLevelToSystem(level: string): ResolvedStatus {
  const tone = opsLevelTone(level);
  const key =
    tone === "operational"
      ? "operational"
      : tone === "degraded"
        ? "degraded"
        : tone === "offline"
          ? "offline"
          : "critical";
  return system(key, tone);
}

function opsLevelToFeed(level: string): ResolvedStatus {
  const tone = opsLevelTone(level);
  const key =
    tone === "operational"
      ? "receiving_data"
      : tone === "degraded"
        ? "delayed"
        : tone === "offline"
          ? "disconnected"
          : "disconnected";
  return feed(key, tone);
}

function opsLevelToValidation(level: string): ResolvedStatus {
  const tone = opsLevelTone(level);
  if (tone === "operational") return validation("passing", "operational");
  if (tone === "degraded") return validation("attention_required", "degraded");
  if (tone === "offline") return validation("not_evaluated", "offline");
  return validation("failing", "critical");
}

export function resolveHealthLevel(level?: string | null, displayStatus?: string | null): ResolvedStatus {
  const display = (displayStatus || "").toUpperCase();
  // Legacy OPERATIONAL_WITH_WARNINGS was resource rollup — treat as Operational.
  // Resource warnings stay on resource cards via resolveResourceUsage.
  if (display === "OPERATIONAL_WITH_WARNINGS" || display === "OPERATIONAL") {
    return system("operational", "operational");
  }
  const normalized = (level || "UNKNOWN").toUpperCase();
  if (normalized === "HEALTHY") return system("operational", "operational");
  if (normalized === "DEGRADED") return system("degraded", "degraded");
  if (normalized === "CRITICAL") return system("critical", "critical");
  if (!level) return system("offline", "offline");
  return opsLevelToSystem(level);
}

export function resolveResourceUsage(percent?: number | null): ResolvedStatus {
  const value = Number(percent);
  if (!Number.isFinite(value)) return system("offline", "offline");
  if (value >= 90) return system("critical", "critical");
  if (value >= 75) return system("degraded", "degraded");
  return system("operational", "operational");
}

export function resolveEngineStatus(status?: string | null): ResolvedStatus {
  const normalized = (status || "UNKNOWN").toUpperCase();
  if (normalized === "HEALTHY") return engine("running", "operational");
  if (normalized === "FAILED") return engine("failed", "critical");
  if (normalized === "DEFERRED" || normalized === "STALLED" || normalized === "TIMEOUT") {
    return engine("lagging", "degraded");
  }
  if (normalized === "UNKNOWN" || !status) return engine("running", "offline");
  return engine("running", "offline");
}

export function resolveCollectorStatus(status?: string | null): ResolvedStatus {
  const normalized = (status || "UNKNOWN").toUpperCase();
  if (normalized === "CONNECTED") return feed("receiving_data", "operational");
  if (normalized === "DEGRADED") return feed("delayed", "degraded");
  if (normalized === "DISCONNECTED") return feed("disconnected", "critical");
  if (normalized === "OPTIONAL_OFFLINE" || normalized === "ARCHIVED") {
    return feed("disconnected", "offline");
  }
  return feed("disconnected", "offline");
}

export function resolveFreshness(freshness?: string | null): ResolvedStatus {
  const normalized = (freshness || "UNKNOWN").toUpperCase();
  if (normalized === "LIVE") return feed("receiving_data", "operational");
  if (normalized === "DELAYED" || normalized === "STALE") return feed("delayed", "degraded");
  if (normalized === "MISSING") return feed("disconnected", "critical");
  return feed("disconnected", "offline");
}

export function resolvePipelineState(state?: string | null): ResolvedStatus {
  const normalized = (state || "UNKNOWN").toUpperCase();
  if (normalized.includes("FAIL")) return engine("failed", "critical");
  if (normalized.includes("STALL") || normalized.includes("TIMEOUT")) return engine("lagging", "degraded");
  if (normalized.includes("IDLE") || normalized.includes("WAIT") || normalized === "UNKNOWN") {
    return engine("running", "offline");
  }
  return engine("running", "operational");
}

export function resolveOpsLevel(level?: string | null, domain: StatusDomain = "system"): ResolvedStatus {
  const token = level || "UNKNOWN";
  switch (domain) {
    case "feed":
      return opsLevelToFeed(token);
    case "engine":
      return opsLevelToEngineFromLevel(token);
    case "validation":
      return opsLevelToValidation(token);
    default:
      return opsLevelToSystem(token);
  }
}

function opsLevelToEngineFromLevel(level: string): ResolvedStatus {
  const tone = opsLevelTone(level);
  if (tone === "operational") return engine("running", "operational");
  if (tone === "degraded") return engine("lagging", "degraded");
  if (tone === "offline") return engine("running", "offline");
  return engine("failed", "critical");
}

export function resolveAlertSeverity(severity?: string | null): ResolvedStatus {
  const normalized = (severity || "UNKNOWN").toUpperCase();
  if (normalized === "CRITICAL") return system("critical", "critical");
  if (normalized === "WARNING") return system("degraded", "degraded");
  if (normalized === "UNKNOWN" || !severity) return system("offline", "offline");
  return system("operational", "operational");
}

export function resolveFailedEngineCount(count?: number | null): ResolvedStatus {
  return Number(count || 0) > 0 ? engine("failed", "critical") : engine("running", "operational");
}

export function resolveStallCount(count?: number | null): ResolvedStatus {
  return Number(count || 0) > 0 ? engine("lagging", "degraded") : engine("running", "operational");
}

export function resolveHealthDimensionStatus(status?: string | null): ResolvedStatus {
  const token = (status || "UNKNOWN").toUpperCase();
  if (token === "OPERATIONAL" || token === "HEALTHY" || token === "INFORMATIONAL" || token === "UNKNOWN") {
    return system("operational", "operational");
  }
  // Research incompleteness / stale artifacts → ATTENTION|INCOMPLETE, never "Degraded".
  if (
    token === "ATTENTION" ||
    token === "INCOMPLETE" ||
    token === "STALE" ||
    token === "MISSING_DATA" ||
    token === "OPERATIONAL_WITH_WARNINGS"
  ) {
    const label = token === "INCOMPLETE" ? "INCOMPLETE" : "ATTENTION";
    return { domain: "validation", key: "attention_required", label, tone: "degraded" };
  }
  // Research must not surface the word Degraded for artifact gaps.
  if (token === "DEGRADED") {
    return { domain: "validation", key: "attention_required", label: "ATTENTION", tone: "degraded" };
  }
  if (token === "CRITICAL") return system("critical", "critical");
  return system("operational", "operational");
}

export function resolveRuntimeStability(input?: {
  currentStalls?: number;
  restartCount?: number;
  runtimeStatus?: string | null;
} | null): ResolvedStatus {
  const current = Number(input?.currentStalls || 0);
  if (current > 0 || String(input?.runtimeStatus || "").toUpperCase() === "DEGRADED") {
    return system("degraded", "degraded");
  }
  if (String(input?.runtimeStatus || "").toUpperCase() === "CRITICAL") {
    return system("critical", "critical");
  }
  return system("operational", "operational");
}

export function resolveOpenAlerts(count: number, hasCritical: boolean): ResolvedStatus {
  if (count === 0) return system("operational", "operational");
  if (hasCritical) return system("critical", "critical");
  return system("degraded", "degraded");
}

export function resolveParquetSummary(missing: number, stale: number): ResolvedStatus {
  if (missing > 0) return feed("disconnected", "critical");
  if (stale > 0) return feed("delayed", "degraded");
  return feed("receiving_data", "operational");
}

export function resolveStabilityRestarts(_restarts: number): ResolvedStatus {
  // Restart history alone is not current runtime degradation (Stage 13).
  return system("operational", "operational");
}

export function resolveConnectionLive(connected: boolean): ResolvedStatus {
  return connected ? system("operational", "operational") : system("degraded", "degraded");
}

export function resolveRibbonItem(item: {
  key: string;
  label: string;
  level: string;
  value?: string;
}): ResolvedStatus {
  if (isResearchRibbonKey(item.key)) {
    return resolveResearchRibbonItem(item);
  }

  if (item.value && !RAW_STATUS_PATTERN.test(item.value)) {
    const domainHint = `${item.key} ${item.label}`.toLowerCase();
    const domain: StatusDomain = /validation/i.test(domainHint)
      ? "validation"
      : /feed|stream|ws|socket|collector|data|parquet/i.test(domainHint)
        ? "feed"
        : /engine|pipeline|cycle/i.test(domainHint)
          ? "engine"
          : "system";
    return resolveOpsLevel(item.level, domain === "system" ? "system" : domain);
  }

  const key = `${item.key} ${item.label}`.toLowerCase();
  if (/validation/i.test(key)) return opsLevelToValidation(item.level);
  if (/feed|stream|ws|socket|collector|data|parquet|store/i.test(key)) return opsLevelToFeed(item.level);
  if (/engine|pipeline|cycle/i.test(key)) return opsLevelToEngineFromLevel(item.level);
  return opsLevelToSystem(item.level);
}

/** Uptime-backed services that are actively connected. */
export function resolveActiveService(): ResolvedStatus {
  return feed("receiving_data", "operational");
}
