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
  degraded: "Degraded",
  critical: "Critical",
  offline: "Offline",
};

export const FEED_STATUS: Record<FeedStatusKey, string> = {
  receiving_data: "Receiving Data",
  delayed: "Delayed",
  disconnected: "Disconnected",
};

export const ENGINE_STATUS: Record<EngineStatusKey, string> = {
  running: "Running",
  lagging: "Lagging",
  failed: "Failed",
};

export const VALIDATION_STATUS: Record<ValidationStatusKey, string> = {
  passing: "Passing",
  attention_required: "Attention Required",
  failing: "Failing",
  not_evaluated: "Not evaluated",
};

export function labelFor(domain: StatusDomain, key: StatusKey): string {
  switch (domain) {
    case "system":
      return SYSTEM_STATUS[key as SystemStatusKey];
    case "feed":
      return FEED_STATUS[key as FeedStatusKey];
    case "engine":
      return ENGINE_STATUS[key as EngineStatusKey];
    case "validation":
      return VALIDATION_STATUS[key as ValidationStatusKey];
    case "research":
      return "Research";
  }
}

/** Raw API tokens that must never appear in the UI. */
export const RAW_STATUS_PATTERN =
  /^(GREEN|YELLOW|RED|GREY|HEALTHY|DEGRADED|CRITICAL|CONNECTED|DISCONNECTED|LIVE|STALE|MISSING|FAILED|HEALTHY)$/i;
