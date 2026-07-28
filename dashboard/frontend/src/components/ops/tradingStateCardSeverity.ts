/** Per-timeframe Trading State card severity (OPS1.6). */

import type { ResolvedStatus, StatusKey, StatusTone } from "../status/types";

function status(label: string, tone: StatusTone, key: StatusKey): ResolvedStatus {
  return { domain: "system", key, label, tone };
}

export function mapTradingStateTimeframeSeverity(input?: {
  trading_state?: string | null;
  stale?: boolean | null;
  level?: string | null;
} | null): ResolvedStatus {
  if (!input) {
    return status("Critical", "critical", "critical");
  }
  if (input.stale) {
    return status("Warning", "degraded", "degraded");
  }
  const state = String(input.trading_state || "").toUpperCase();
  if (state === "UNAVAILABLE" || state === "INVALID" || state.includes("MISSING")) {
    return status("Critical", "critical", "critical");
  }
  if (state === "LONG_CONTEXT" || state === "SHORT_CONTEXT" || state === "LONG" || state === "SHORT") {
    return status("Healthy", "operational", "operational");
  }
  if (state === "OBSERVE" || state === "STAND_ASIDE" || state === "NO_ACTIVE_CONTEXT") {
    return status("Informational", "offline", "informational");
  }
  const level = String(input.level || "").toUpperCase();
  if (level === "RED") return status("Critical", "critical", "critical");
  if (level === "YELLOW") return status("Warning", "degraded", "degraded");
  if (level === "GREEN") return status("Healthy", "operational", "operational");
  return status("Informational", "offline", "informational");
}
