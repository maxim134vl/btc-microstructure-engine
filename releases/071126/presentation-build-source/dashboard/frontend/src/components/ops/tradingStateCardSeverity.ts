/** Per-timeframe Trading State card severity (OPS1.6). */

import type { ResolvedStatus, StatusKey, StatusTone } from "../status/types";

function status(label: string, tone: StatusTone, key: StatusKey): ResolvedStatus {
  return { domain: "system", key, label, tone };
}

export function mapTradingStateTimeframeSeverity(input?: {
  trading_state?: string | null;
  active_market_context?: string | null;
  provisional_market_context?: string | null;
  stale?: boolean | null;
  level?: string | null;
} | null): ResolvedStatus {
  if (!input) {
    return status("Critical", "critical", "critical");
  }
  if (input.stale) {
    return status("Warning", "degraded", "degraded");
  }
  const active = String(input.active_market_context || "").toUpperCase();
  const provisional = String(input.provisional_market_context || input.trading_state || "").toUpperCase();
  if (provisional === "UNAVAILABLE" || provisional === "INVALID" || provisional.includes("MISSING")) {
    return status("Critical", "critical", "critical");
  }
  if (
    active === "LONG_CONTEXT" ||
    active === "SHORT_CONTEXT" ||
    provisional === "LONG_CONTEXT" ||
    provisional === "SHORT_CONTEXT" ||
    provisional === "LONG" ||
    provisional === "SHORT"
  ) {
    return status("Healthy", "operational", "operational");
  }
  if (provisional === "OBSERVE" || provisional === "STAND_ASIDE" || provisional === "NO_ACTIVE_CONTEXT") {
    return status("Informational", "offline", "informational");
  }
  const level = String(input.level || "").toUpperCase();
  if (level === "RED") return status("Critical", "critical", "critical");
  if (level === "YELLOW") return status("Warning", "degraded", "degraded");
  if (level === "GREEN") return status("Healthy", "operational", "operational");
  return status("Informational", "offline", "informational");
}
