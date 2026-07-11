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

function opsLevelTone(level: string): StatusTone {
  const normalized = level.toUpperCase();
  if (normalized === "GREEN" || normalized === "HEALTHY") return "operational";
  if (normalized === "YELLOW" || normalized === "DEGRADED" || normalized === "DEFERRED") return "degraded";
  if (normalized === "GREY") return "offline";
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

export function resolveHealthLevel(level: string): ResolvedStatus {
  const normalized = level.toUpperCase();
  if (normalized === "HEALTHY") return system("operational", "operational");
  if (normalized === "DEGRADED") return system("degraded", "degraded");
  if (normalized === "CRITICAL") return system("critical", "critical");
  return opsLevelToSystem(level);
}

export function resolveResourceUsage(percent: number): ResolvedStatus {
  if (percent >= 90) return system("critical", "critical");
  if (percent >= 75) return system("degraded", "degraded");
  return system("operational", "operational");
}

export function resolveEngineStatus(status: string): ResolvedStatus {
  const normalized = status.toUpperCase();
  if (normalized === "HEALTHY") return engine("running", "operational");
  if (normalized === "FAILED") return engine("failed", "critical");
  if (normalized === "DEFERRED" || normalized === "STALLED" || normalized === "TIMEOUT") {
    return engine("lagging", "degraded");
  }
  return engine("running", "offline");
}

export function resolveCollectorStatus(status: string): ResolvedStatus {
  const normalized = status.toUpperCase();
  if (normalized === "CONNECTED") return feed("receiving_data", "operational");
  if (normalized === "DEGRADED") return feed("delayed", "degraded");
  if (normalized === "DISCONNECTED") return feed("disconnected", "critical");
  if (normalized === "OPTIONAL_OFFLINE" || normalized === "ARCHIVED") {
    return feed("disconnected", "offline");
  }
  return feed("disconnected", "offline");
}

export function resolveFreshness(freshness: string): ResolvedStatus {
  const normalized = freshness.toUpperCase();
  if (normalized === "LIVE") return feed("receiving_data", "operational");
  if (normalized === "DELAYED" || normalized === "STALE") return feed("delayed", "degraded");
  if (normalized === "MISSING") return feed("disconnected", "critical");
  return feed("disconnected", "offline");
}

export function resolvePipelineState(state: string): ResolvedStatus {
  const normalized = state.toUpperCase();
  if (normalized.includes("FAIL")) return engine("failed", "critical");
  if (normalized.includes("STALL") || normalized.includes("TIMEOUT")) return engine("lagging", "degraded");
  if (normalized.includes("IDLE") || normalized.includes("WAIT")) return engine("running", "offline");
  return engine("running", "operational");
}

export function resolveOpsLevel(level: string, domain: StatusDomain = "system"): ResolvedStatus {
  switch (domain) {
    case "feed":
      return opsLevelToFeed(level);
    case "engine":
      return opsLevelToEngineFromLevel(level);
    case "validation":
      return opsLevelToValidation(level);
    default:
      return opsLevelToSystem(level);
  }
}

function opsLevelToEngineFromLevel(level: string): ResolvedStatus {
  const tone = opsLevelTone(level);
  if (tone === "operational") return engine("running", "operational");
  if (tone === "degraded") return engine("lagging", "degraded");
  if (tone === "offline") return engine("running", "offline");
  return engine("failed", "critical");
}

export function resolveAlertSeverity(severity: string): ResolvedStatus {
  const normalized = severity.toUpperCase();
  if (normalized === "CRITICAL") return system("critical", "critical");
  if (normalized === "WARNING") return system("degraded", "degraded");
  return system("operational", "operational");
}

export function resolveFailedEngineCount(count: number): ResolvedStatus {
  return count > 0 ? engine("failed", "critical") : engine("running", "operational");
}

export function resolveStallCount(count: number): ResolvedStatus {
  return count > 0 ? engine("lagging", "degraded") : engine("running", "operational");
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

export function resolveStabilityRestarts(restarts: number): ResolvedStatus {
  return restarts > 0 ? system("degraded", "degraded") : system("operational", "operational");
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
