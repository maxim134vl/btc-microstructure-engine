import type {
  EngineStatusKey,
  FeedStatusKey,
  StatusDomain,
  StatusKey,
  SystemStatusKey,
  ValidationStatusKey,
} from "./types";

export const SYSTEM_STATUS: Record<SystemStatusKey, string> = {
  operational: "Operational",
  operational_with_limitations: "Operational with Limitations",
  degraded: "Degraded",
  critical: "Failed",
  offline: "Offline",
  informational: "Informational",
};

export const FEED_STATUS: Record<FeedStatusKey, string> = {
  receiving_data: "Receiving Data",
  current: "Current",
  current_unchanged: "Current Unchanged",
  delayed: "Delayed",
  disconnected: "Disconnected",
};

export const ENGINE_STATUS: Record<EngineStatusKey, string> = {
  running: "Running",
  receiving_data: "Receiving Data",
  lagging: "Lagging",
  failed: "Failed",
  migrated: "Migrated",
  not_required: "Not Required",
  not_live: "Not Live",
  expected: "Expected",
  known_limitation: "Known Limitation",
  not_in_canonical_runtime: "Not In Canonical Runtime",
  deprecated: "Deprecated",
  historical_only: "Historical Only",
  informational: "Informational",
};

export const VALIDATION_STATUS: Record<ValidationStatusKey, string> = {
  passing: "Passing",
  attention_required: "Attention Required",
  failing: "Failing",
  not_evaluated: "Not evaluated",
  incomplete_non_blocking: "Incomplete — Non-Blocking",
  informational: "Informational",
};

export function labelFor(domain: StatusDomain, key: StatusKey): string {
  switch (domain) {
    case "system":
      return SYSTEM_STATUS[key as SystemStatusKey] ?? "Unknown / Informational";
    case "feed":
      return FEED_STATUS[key as FeedStatusKey] ?? "Unknown / Informational";
    case "engine":
      return ENGINE_STATUS[key as EngineStatusKey] ?? "Unknown / Informational";
    case "validation":
      return VALIDATION_STATUS[key as ValidationStatusKey] ?? "Unknown / Informational";
    case "research":
      return "Research";
  }
}

/** Raw API tokens that must never appear in the UI. */
export const RAW_STATUS_PATTERN =
  /^(GREEN|YELLOW|RED|GREY|HEALTHY|DEGRADED|CRITICAL|CONNECTED|DISCONNECTED|LIVE|STALE|MISSING|FAILED|HEALTHY)$/i;
