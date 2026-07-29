/** OPS1.7 — display-only lineage guard for Trading State lifecycle. */

export type TradingStateLifecycleInput = {
  trading_state?: string | null;
  lifecycle_state?: string | null;
  lifecycle_episode_id?: string | null;
  context_event_id?: string | null;
};

/**
 * Prevent residual directional lifecycle (e.g. CHALLENGED) from rendering
 * when the TF tip is OBSERVE without an active episode/event.
 */
export function displayLifecycleState(input?: TradingStateLifecycleInput | null): string {
  if (!input) return "—";
  const trading = String(input.trading_state || "").toUpperCase();
  const life = String(input.lifecycle_state || "").trim();
  const episode = String(input.lifecycle_episode_id || "").trim();
  const eventId = String(input.context_event_id || "").trim();
  if (trading === "OBSERVE" || trading === "STAND_ASIDE" || trading === "NO_ACTIVE_CONTEXT") {
    return "NO_ACTIVE_CONTEXT";
  }
  if (life.toUpperCase() === "CHALLENGED" && (!episode || !eventId)) {
    return "UNAVAILABLE";
  }
  return life || "—";
}
