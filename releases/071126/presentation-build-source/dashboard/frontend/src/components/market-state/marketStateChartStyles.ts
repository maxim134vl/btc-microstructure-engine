export const DECISION_COLORS: Record<string, string> = {
  LONG_SETUP: "#22c55e",
  SHORT_SETUP: "#ef4444",
  EXIT_LONG: "#f97316",
  EXIT_SHORT: "#f97316",
  INVALIDATED: "#8e8e93",
  NO_SETUP: "#8e8e93",
  REGIME_START: "#0a84ff",
  REGIME_CHANGE: "#0a84ff",
  WARNING: "#8e8e93",
};

export const REGIME_PALETTE = [
  "rgba(34,197,94,0.13)",
  "rgba(239,68,68,0.13)",
  "rgba(168,85,247,0.13)",
  "rgba(234,179,8,0.14)",
  "rgba(59,130,246,0.12)",
  "rgba(20,184,166,0.12)",
  "rgba(148,163,184,0.10)",
];

/** Lighter palette for secondary cognitive/composite regime overlay. */
export const COGNITIVE_REGIME_PALETTE = REGIME_PALETTE.map((color) => color.replace(/0\.1[0-9]\)/, "0.07)"));

const MARKET_STATE_COLORS: Record<string, string> = {
  ACCUMULATION: "rgba(59,130,246,0.22)",
  MARKUP: "rgba(34,197,94,0.24)",
  DISTRIBUTION: "rgba(239,68,68,0.22)",
  MARKDOWN: "rgba(249,115,22,0.22)",
  REVERSAL: "rgba(168,85,247,0.22)",
  NEUTRAL: "rgba(148,163,184,0.16)",
  EXHAUSTION: "rgba(234,179,8,0.20)",
};

export function decisionColor(decision?: string | null): string {
  return DECISION_COLORS[decision ?? ""] ?? "#94a3b8";
}

export function regimeColor(index: number): string {
  return REGIME_PALETTE[index % REGIME_PALETTE.length];
}

export function cognitiveRegimeColor(index: number): string {
  return COGNITIVE_REGIME_PALETTE[index % COGNITIVE_REGIME_PALETTE.length];
}

export function marketStateRegimeColor(marketState: string, isActive = false): string {
  const token = marketState.toUpperCase().replace(/\s+/g, "_");
  const base = MARKET_STATE_COLORS[token] ?? "rgba(10,132,255,0.18)";
  if (!isActive) return base;
  return base.replace(/([\d.]+)\)$/, (_, opacity) => `${Math.min(0.38, Number(opacity) + 0.1)})`);
}

export function confidenceLevelColor(level?: string | null): string {
  switch (level) {
    case "HIGH":
      return "var(--ds-status-healthy)";
    case "MEDIUM":
      return "var(--ds-status-warning)";
    case "LOW":
      return "var(--ds-status-error)";
    default:
      return "var(--ds-status-idle)";
  }
}

export function contextEpisodeColor(direction: "LONG" | "SHORT", isActive = false): string {
  const base = direction === "LONG" ? "rgba(34,197,94,0.14)" : "rgba(239,68,68,0.14)";
  return isActive ? base.replace("0.14", "0.24") : base;
}

export function formatConfidenceScore(score?: number | null): string {
  if (score == null || Number.isNaN(score)) return "N/A";
  if (score >= 0 && score <= 1) return `${Math.round(score * 100)}%`;
  return score.toFixed(2);
}

export const MARKET_STATE_TRANSITION_COLOR = "#0a84ff";

export function formatConfidenceDeltaValue(delta?: number | null): string {
  if (delta == null || Number.isNaN(delta)) return "—";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const magnitude = Math.abs(delta);
  if (magnitude <= 1) return `${sign}${Math.round(magnitude * 100)} pts`;
  return `${sign}${magnitude.toFixed(3)}`;
}

export function formatConfidenceDeltaText(delta?: number | null): string {
  if (delta == null || Number.isNaN(delta)) return "Confidence change unavailable";
  if (delta > 0) return "Confidence increased";
  if (delta < 0) return "Confidence decreased";
  return "Confidence unchanged";
}

export function confidenceDeltaTone(delta?: number | null): "good" | "bad" | "default" {
  if (delta == null || Number.isNaN(delta) || delta === 0) return "default";
  return delta > 0 ? "good" : "bad";
}

export function transitionReasonText(transition: {
  reason?: string | null;
  transition_reason?: string | null;
  trader_read?: string | null;
  rule_description?: string | null;
}): string {
  return (
    transition.transition_reason?.trim() ||
    transition.reason?.trim() ||
    transition.trader_read?.trim() ||
    transition.rule_description?.trim() ||
    "Engine state change recorded without additional explanation."
  );
}

export function shortTransitionLabel(fromState: string, toState: string): string {
  const abbrev = (value: string) => value.replace(/_/g, " ").split(" ").map((part) => part.slice(0, 4)).join("");
  return `${abbrev(fromState)}→${abbrev(toState)}`;
}

export function decisionLabel(decision?: string | null): string {
  switch (decision) {
    case "LONG_SETUP":
      return "LONG";
    case "SHORT_SETUP":
      return "SHORT";
    case "EXIT_LONG":
    case "EXIT_SHORT":
      return "EXIT";
    case "INVALIDATED":
      return "INVALID";
    case "NO_SETUP":
      return "NO SETUP";
    default:
      return (decision ?? "NO SETUP").replaceAll("_", " ");
  }
}
