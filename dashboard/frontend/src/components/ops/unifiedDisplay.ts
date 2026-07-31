/**
 * Display-only helpers for the unified OPS live view.
 * Never invent live health or trading metrics — normalize presentation only.
 */

export const RAW_ENUM_KEY_PATTERN = /^status\.(system|engine|feed|validation|research)\.[a-z0-9_]+$/i;

const ENUM_DISPLAY: Record<string, string> = {
  "status.system.informational": "Informational",
  "status.system.operational": "Operational",
  "status.system.operational_with_limitations": "Operational with Limitations",
  "status.system.degraded": "Degraded",
  "status.system.critical": "Failed",
  "status.system.offline": "Offline",
  "status.engine.informational": "Not evaluated",
  "status.engine.running": "Running",
  "status.engine.receiving_data": "Receiving Data",
  "status.engine.lagging": "Lagging",
  "status.engine.failed": "Failed",
  "status.engine.migrated": "Migrated",
  "status.engine.not_required": "Not Required",
  "status.engine.not_live": "Not Live",
  "status.engine.expected": "Expected",
  "status.engine.known_limitation": "Known Limitation",
  "status.engine.not_in_canonical_runtime": "Not In Canonical Runtime",
  "status.engine.deprecated": "Deprecated",
  "status.engine.historical_only": "Historical Only",
  "status.validation.not_evaluated": "Not evaluated",
  "status.validation.incomplete_non_blocking": "Incomplete · Non-blocking",
  "status.validation.informational": "Informational",
  "status.validation.passing": "Passing",
  "status.validation.attention_required": "Attention Required",
  "status.validation.failing": "Failing",
  "status.feed.receiving_data": "Receiving Data",
  "status.feed.current": "Current",
  "status.feed.current_unchanged": "Current Unchanged",
  "status.feed.delayed": "Delayed",
  "status.feed.disconnected": "Disconnected",
};

/** Never show raw i18n/enum keys to operators. */
export function humanizeStatusLabel(raw: string | null | undefined, fallbackLabel?: string | null): string {
  const text = (raw ?? "").trim();
  if (!text) return (fallbackLabel ?? "").trim() || "Unknown status";
  if (ENUM_DISPLAY[text]) return ENUM_DISPLAY[text];
  if (RAW_ENUM_KEY_PATTERN.test(text)) return "Unknown status";
  if (text.startsWith("status.") && text.split(".").length >= 3) return "Unknown status";
  return text;
}

export function pickStatusLabel(options: {
  resolvedLabel?: string | null;
  i18nValue?: string | null;
  i18nKey?: string | null;
}): string {
  const resolved = (options.resolvedLabel ?? "").trim();
  const i18nValue = (options.i18nValue ?? "").trim();
  const i18nKey = (options.i18nKey ?? "").trim();
  if (i18nValue && i18nValue !== i18nKey && !RAW_ENUM_KEY_PATTERN.test(i18nValue) && !i18nValue.startsWith("status.")) {
    return i18nValue;
  }
  return humanizeStatusLabel(resolved || i18nValue || i18nKey);
}

export type LiveMetricDisplay = {
  text: string;
  isUnavailable: boolean;
  lastKnownAt?: string | null;
};

/** Fallback must not invent zeros as live values. */
export function formatLiveMetric(
  value: number | string | null | undefined,
  opts: {
    liveConnected: boolean;
    lastKnownAt?: string | null;
    format?: (v: number | string) => string;
    zeroIsValid?: boolean;
  },
): LiveMetricDisplay {
  if (!opts.liveConnected) {
    if (value == null || value === "" || (value === 0 && !opts.zeroIsValid)) {
      return {
        text: "—",
        isUnavailable: true,
        lastKnownAt: opts.lastKnownAt ?? null,
      };
    }
    const formatted = opts.format ? opts.format(value) : String(value);
    return {
      text: formatted,
      isUnavailable: true,
      lastKnownAt: opts.lastKnownAt ?? null,
    };
  }
  if (value == null || value === "") {
    return { text: "—", isUnavailable: true };
  }
  return {
    text: opts.format ? opts.format(value) : String(value),
    isUnavailable: false,
  };
}

export function unavailableCaption(lastKnownAt?: string | null): string {
  if (lastKnownAt) return `Last known at: ${lastKnownAt}`;
  return "Unavailable";
}

export const REQUIRED_PROCESS_ORDER = [
  "live_feed",
  "canonical_pipeline",
  "context_refresher",
  "dashboard_refresher",
  "visual_refresher",
  "timeframe_manager",
  "trader_M15",
  "trader_M30",
  "trader_H1",
  "trader_H4",
  "ops_backend",
] as const;

export function isPhantomProcessId(processId?: string | null): boolean {
  const id = (processId ?? "").toLowerCase();
  return id === "paper_controller" || id.includes("phantom");
}

export function countSectionMarkers(source: string, marker: string): number {
  if (!source) return 0;
  return source.split(marker).length - 1;
}

export function toxicShowsQuietWhenDisconnected(opts: {
  displayStatus?: string | null;
  currentStatus?: string | null;
  severityLabel?: string | null;
}): boolean {
  const historical =
    (opts.displayStatus ?? "").toUpperCase().includes("HISTORICAL") ||
    (opts.currentStatus ?? "").toUpperCase().includes("NOT_CONNECTED") ||
    (opts.currentStatus ?? "").toUpperCase().includes("UNAVAILABLE");
  if (!historical) return false;
  return (opts.severityLabel ?? "").toUpperCase() === "QUIET";
}
