import { RAW_STATUS_PATTERN, labelFor } from "./vocabulary";
import { isResearchRibbonKey, resolveResearchRibbonItem } from "./researchMappers";
import type { ResolvedStatus, StatusDomain, StatusTone } from "./types";

function system(key: ResolvedStatus["key"], tone: StatusTone, label?: string): ResolvedStatus {
  return { domain: "system", key, label: label ?? labelFor("system", key), tone };
}

function feed(key: ResolvedStatus["key"], tone: StatusTone, label?: string): ResolvedStatus {
  return { domain: "feed", key, label: label ?? labelFor("feed", key), tone };
}

function engine(key: ResolvedStatus["key"], tone: StatusTone, label?: string): ResolvedStatus {
  return { domain: "engine", key, label: label ?? labelFor("engine", key), tone };
}

function validation(key: ResolvedStatus["key"], tone: StatusTone, label?: string): ResolvedStatus {
  return { domain: "validation", key, label: label ?? labelFor("validation", key), tone };
}

/** Safe neutral fallback — never interpret unknown tokens as Failed. */
export function resolveUnknownNeutral(token?: string | null): ResolvedStatus {
  const label = (token || "UNKNOWN").trim() || "UNKNOWN";
  return system("informational", "offline", `${label} / Informational`);
}

function opsLevelTone(level?: string | null): StatusTone {
  const normalized = (level || "UNKNOWN").toUpperCase();
  if (
    normalized === "GREEN" ||
    normalized === "HEALTHY" ||
    normalized === "OPERATIONAL" ||
    normalized === "OPERATIONAL_WITH_LIMITATIONS" ||
    normalized === "HEALTHY_WITH_KNOWN_LIMITATIONS" ||
    normalized === "CURRENT" ||
    normalized === "CURRENT_UNCHANGED" ||
    normalized === "MIGRATED" ||
    normalized === "NOT_REQUIRED" ||
    normalized === "EXPECTED" ||
    normalized === "KNOWN_LIMITATION" ||
    normalized === "NON_REQUIRED" ||
    normalized === "NON_BLOCKING" ||
    normalized === "HISTORICAL_ONLY" ||
    normalized === "LEGACY_BASELINE" ||
    normalized === "NOT_IN_CANONICAL_RUNTIME" ||
    normalized === "DEPRECATED" ||
    normalized === "STABLE" ||
    normalized === "STABLE_WITH_WARNINGS" ||
    normalized === "NORMAL" ||
    normalized === "WARNING"
  ) {
    if (normalized === "WARNING" || normalized === "STABLE_WITH_WARNINGS") return "degraded";
    if (
      normalized === "OPERATIONAL_WITH_LIMITATIONS" ||
      normalized === "HEALTHY_WITH_KNOWN_LIMITATIONS" ||
      normalized === "MIGRATED" ||
      normalized === "NOT_REQUIRED" ||
      normalized === "EXPECTED" ||
      normalized === "KNOWN_LIMITATION" ||
      normalized === "NON_REQUIRED" ||
      normalized === "NON_BLOCKING" ||
      normalized === "HISTORICAL_ONLY" ||
      normalized === "LEGACY_BASELINE" ||
      normalized === "NOT_IN_CANONICAL_RUNTIME" ||
      normalized === "DEPRECATED"
    ) {
      return "offline";
    }
    return "operational";
  }
  if (normalized === "YELLOW" || normalized === "DEGRADED" || normalized === "DEFERRED" || normalized === "ATTENTION") {
    return "degraded";
  }
  if (normalized === "GREY" || normalized === "UNKNOWN" || normalized === "MISSING_DATA" || normalized === "") {
    return "offline";
  }
  if (normalized === "RED" || normalized === "CRITICAL" || normalized === "FAILED" || normalized === "BROKEN") {
    return "critical";
  }
  return "offline";
}

function opsLevelToSystem(level: string): ResolvedStatus {
  const token = level.toUpperCase();
  if (token === "OPERATIONAL_WITH_LIMITATIONS" || token === "HEALTHY_WITH_KNOWN_LIMITATIONS") {
    return system("operational_with_limitations", "operational");
  }
  if (token === "OPERATIONAL" || token === "HEALTHY" || token === "GREEN") {
    return system("operational", "operational");
  }
  if (token === "DEGRADED" || token === "YELLOW") {
    return system("degraded", "degraded");
  }
  if (token === "FAILED" || token === "CRITICAL" || token === "BROKEN" || token === "RED") {
    return system("critical", "critical");
  }
  return resolveUnknownNeutral(level);
}

function opsLevelToFeed(level: string): ResolvedStatus {
  const token = level.toUpperCase();
  if (token === "CURRENT_UNCHANGED") return feed("current_unchanged", "operational");
  if (token === "CURRENT" || token === "LIVE" || token === "GREEN") return feed("current", "operational");
  if (token === "DELAYED" || token === "YELLOW") return feed("delayed", "degraded");
  if (token === "STALE") return feed("delayed", "degraded", "Stale");
  if (token === "MISSING" || token === "RED") return feed("disconnected", "critical");
  if (token === "GREY" || token === "UNKNOWN") return feed("disconnected", "offline");
  return resolveUnknownNeutral(level);
}

function opsLevelToValidation(level: string): ResolvedStatus {
  const token = level.toUpperCase();
  if (
    token === "RESEARCH_INCOMPLETE" ||
    token === "INCOMPLETE" ||
    token === "MISSING_NON_BLOCKING" ||
    token === "NON_BLOCKING" ||
    token.includes("NON-BLOCKING") ||
    token.includes("NON_BLOCKING")
  ) {
    return validation("incomplete_non_blocking", "offline");
  }
  const tone = opsLevelTone(level);
  if (tone === "operational") return validation("passing", "operational");
  if (tone === "degraded") return validation("attention_required", "degraded");
  if (tone === "offline") return validation("not_evaluated", "offline");
  return validation("failing", "critical");
}

export function resolveHealthLevel(level?: string | null, displayStatus?: string | null): ResolvedStatus {
  const display = (displayStatus || "").toUpperCase();
  if (display === "OPERATIONAL_WITH_LIMITATIONS" || display === "HEALTHY_WITH_KNOWN_LIMITATIONS") {
    return system("operational_with_limitations", "operational");
  }
  if (display === "OPERATIONAL" || display === "OPERATIONAL_WITH_WARNINGS") {
    return system("operational", "operational");
  }
  if (display === "FAILED" || display === "BROKEN") {
    return system("critical", "critical");
  }
  const normalized = (level || "UNKNOWN").toUpperCase();
  if (normalized === "OPERATIONAL_WITH_LIMITATIONS" || normalized === "HEALTHY_WITH_KNOWN_LIMITATIONS") {
    return system("operational_with_limitations", "operational");
  }
  if (normalized === "HEALTHY" || normalized === "OPERATIONAL") return system("operational", "operational");
  if (normalized === "DEGRADED") return system("degraded", "degraded");
  if (normalized === "CRITICAL" || normalized === "FAILED" || normalized === "BROKEN") {
    return system("critical", "critical");
  }
  if (!level) return system("offline", "offline");
  return opsLevelToSystem(level);
}

export function resolveResourceUsage(percent?: number | null): ResolvedStatus {
  const value = Number(percent);
  if (!Number.isFinite(value)) return system("offline", "offline");
  if (value > 85) return system("critical", "critical", "Critical");
  if (value >= 70) return system("degraded", "degraded", "Warning");
  return system("operational", "operational", "Normal");
}

export function resolveEngineStatus(status?: string | null): ResolvedStatus {
  const normalized = (status || "UNKNOWN").toUpperCase();
  if (normalized === "HEALTHY" || normalized === "RUNNING" || normalized === "SUCCESS") {
    return engine("running", "operational");
  }
  if (normalized === "FAILED" || normalized === "BROKEN" || normalized === "TIMEOUT") {
    return engine("failed", "critical");
  }
  if (normalized === "MIGRATED") return engine("migrated", "offline");
  if (normalized === "NOT_REQUIRED" || normalized === "NON_REQUIRED") return engine("not_required", "offline");
  if (normalized === "NOT_LIVE") return engine("not_live", "offline");
  if (normalized === "EXPECTED") return engine("expected", "offline");
  if (normalized === "KNOWN_LIMITATION") return engine("known_limitation", "offline");
  if (normalized === "NOT_IN_CANONICAL_RUNTIME" || normalized === "PHANTOM") {
    return engine("not_in_canonical_runtime", "offline");
  }
  if (normalized === "DEPRECATED" || normalized === "HISTORICAL_ONLY" || normalized === "REMOVED") {
    return engine(normalized === "DEPRECATED" ? "deprecated" : "historical_only", "offline");
  }
  if (normalized === "DEFERRED" || normalized === "STALLED") {
    return engine("lagging", "degraded");
  }
  if (normalized === "UNKNOWN" || !status) return resolveUnknownNeutral(status);
  return resolveUnknownNeutral(status);
}

export function resolveCollectorStatus(status?: string | null): ResolvedStatus {
  const normalized = (status || "UNKNOWN").toUpperCase();
  if (normalized === "CONNECTED") return feed("receiving_data", "operational");
  if (normalized === "DEGRADED") return feed("delayed", "degraded");
  if (normalized === "DISCONNECTED") return feed("disconnected", "critical");
  if (normalized === "OPTIONAL_OFFLINE" || normalized === "ARCHIVED") {
    return feed("disconnected", "offline");
  }
  return resolveUnknownNeutral(status);
}

export function resolveFreshness(freshness?: string | null): ResolvedStatus {
  const normalized = (freshness || "UNKNOWN").toUpperCase();
  if (normalized === "CURRENT_UNCHANGED") return feed("current_unchanged", "operational");
  if (normalized === "CURRENT" || normalized === "LIVE") return feed("current", "operational");
  if (normalized === "DELAYED") return feed("delayed", "degraded");
  if (normalized === "STALE") return feed("delayed", "degraded", "Stale");
  if (normalized === "MISSING") return feed("disconnected", "critical");
  return resolveUnknownNeutral(freshness);
}

export function resolvePipelineState(state?: string | null): ResolvedStatus {
  const normalized = (state || "UNKNOWN").toUpperCase();
  if (normalized.includes("FAIL")) return engine("failed", "critical");
  if (normalized.includes("STALL") || normalized.includes("TIMEOUT")) return engine("lagging", "degraded");
  if (normalized.includes("IDLE") || normalized.includes("WAIT") || normalized === "UNKNOWN") {
    return resolveUnknownNeutral(state);
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
  const token = level.toUpperCase();
  if (token === "MIGRATED") return engine("migrated", "offline");
  if (token === "NOT_REQUIRED" || token === "NON_REQUIRED") return engine("not_required", "offline");
  if (token === "NOT_LIVE") return engine("not_live", "offline");
  if (token === "EXPECTED") return engine("expected", "offline");
  if (token === "KNOWN_LIMITATION") return engine("known_limitation", "offline");
  if (token === "NOT_IN_CANONICAL_RUNTIME" || token === "PHANTOM") {
    return engine("not_in_canonical_runtime", "offline");
  }
  if (token === "DEPRECATED") return engine("deprecated", "offline");
  if (token === "HISTORICAL_ONLY" || token === "LEGACY_BASELINE") return engine("historical_only", "offline");
  if (token === "GREEN" || token === "HEALTHY" || token === "RUNNING") return engine("running", "operational");
  if (token === "YELLOW" || token === "DEGRADED" || token === "STALLED") return engine("lagging", "degraded");
  if (token === "RED" || token === "FAILED" || token === "CRITICAL" || token === "BROKEN") {
    return engine("failed", "critical");
  }
  if (token === "GREY" || token === "UNKNOWN") return engine("informational", "offline");
  return resolveUnknownNeutral(level);
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
  if (token === "OPERATIONAL" || token === "HEALTHY" || token === "INFORMATIONAL") {
    return system("operational", "operational");
  }
  if (
    token === "RESEARCH_INCOMPLETE" ||
    token === "INCOMPLETE" ||
    token === "ATTENTION" ||
    token === "STALE" ||
    token === "MISSING_DATA" ||
    token === "MISSING_NON_BLOCKING" ||
    token === "NON_BLOCKING" ||
    token === "OPERATIONAL_WITH_WARNINGS"
  ) {
    return validation("incomplete_non_blocking", "offline");
  }
  if (token === "DEGRADED") {
    return system("degraded", "degraded");
  }
  if (token === "CRITICAL" || token === "FAILED") return system("critical", "critical");
  return resolveUnknownNeutral(status);
}

export function resolveRuntimeStability(input?: {
  currentStalls?: number;
  restartCount?: number;
  runtimeStatus?: string | null;
  runtimeStability?: string | null;
} | null): ResolvedStatus {
  const stability = String(input?.runtimeStability || "").toUpperCase();
  if (stability === "STABLE") {
    return system("operational", "operational", "Stable");
  }
  if (stability === "STABLE_WITH_WARNINGS") {
    return system("degraded", "degraded", "Stable with Warnings");
  }
  if (stability === "DEGRADED") {
    return system("degraded", "degraded", "Degraded");
  }
  const current = Number(input?.currentStalls || 0);
  const runtime = String(input?.runtimeStatus || "").toUpperCase();
  if (current > 0 || runtime === "DEGRADED") {
    return system("degraded", "degraded", "Degraded");
  }
  if (runtime === "CRITICAL" || runtime === "FAILED") {
    return system("critical", "critical", "Failed");
  }
  return system("operational", "operational", "Stable");
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
