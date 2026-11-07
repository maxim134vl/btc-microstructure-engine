/** OPS1.8 — display provisional vs active trading-context fields. */

export type TradingStateLifecycleInput = {
  trading_state?: string | null;
  market_state?: string | null;
  provisional_market_context?: string | null;
  active_market_context?: string | null;
  lifecycle_state?: string | null;
  lifecycle_episode_id?: string | null;
  context_event_id?: string | null;
};

export function displayProvisionalContext(input?: TradingStateLifecycleInput | null): string {
  if (!input) return "—";
  return String(input.provisional_market_context || input.market_state || "OBSERVE");
}

export function displayActiveContext(input?: TradingStateLifecycleInput | null): string {
  if (!input) return "—";
  const active = String(input.active_market_context || "").trim();
  if (!active || active.toUpperCase() === "NULL" || active.toUpperCase() === "NONE") {
    return "—";
  }
  return active;
}

/**
 * Lifecycle follows active context. Provisional OBSERVE must not wipe CHALLENGED.
 */
export function displayLifecycleState(input?: TradingStateLifecycleInput | null): string {
  if (!input) return "—";
  const active = String(input.active_market_context || "").toUpperCase();
  const life = String(input.lifecycle_state || "").trim();
  if (!active || active === "NULL" || active === "NONE" || active === "OBSERVE") {
    return "NO_ACTIVE_CONTEXT";
  }
  if (life.toUpperCase() === "CHALLENGED") return "CHALLENGED";
  return life || "ACTIVE";
}
