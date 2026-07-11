import type { ResolvedStatus, StatusTone } from "./types";
import type { ArtifactFreshness } from "../../types/ops";

const RESEARCH_RIBBON_KEYS = new Set([
  "decision_layer",
  "model_governance",
  "economic_validation",
  "shadow_inference",
  "toxic_box",
  "pipeline_sync",
]);

function levelToTone(level: string): StatusTone {
  const normalized = level.toUpperCase();
  if (normalized === "GREEN" || normalized === "HEALTHY") return "operational";
  if (normalized === "YELLOW" || normalized === "DEGRADED") return "degraded";
  if (normalized === "GREY") return "offline";
  return "critical";
}

function researchStatus(label: string, tone: StatusTone): ResolvedStatus {
  return { domain: "research", key: "semantic", label, tone };
}

function isStaleToken(value?: string | null, freshness?: ArtifactFreshness | null): boolean {
  if (freshness?.is_stale) return true;
  const token = (value || "").toUpperCase();
  return (
    token.includes("STALE") ||
    token === "STALE_VALIDATION" ||
    token === "STALE_GOVERNANCE_DATA" ||
    token === "STALE_DRIFT_DATA" ||
    token === "MISSING_DATA" ||
    token === "UNKNOWN_FRESHNESS" ||
    token === "GOVERNANCE_MISSING"
  );
}

/** Decision Layer: business posture — RED only when memories are missing. */
const DECISION_LABELS: Record<string, string> = {
  ENTRY_ELIGIBLE: "Healthy",
  STAND_ASIDE: "Stand Aside",
  OBSERVE: "Observe",
  REVERSAL_WATCH: "Reversal Watch",
  NO_ENTRY: "No Entry",
  WATCH: "Watch",
  UNAVAILABLE: "Unavailable",
};

export function resolveDecisionStatus(level: string, statusLabel?: string): ResolvedStatus {
  const normalized = level.toUpperCase();
  let label = "Watch";

  if (statusLabel && DECISION_LABELS[statusLabel]) {
    label = DECISION_LABELS[statusLabel];
  } else if (normalized === "GREEN") {
    label = "Healthy";
  } else if (normalized === "GREY" || normalized === "RED") {
    label = "Unavailable";
  }

  return researchStatus(label, levelToTone(level));
}

/** ML Governance: display governance_status token directly. */
export function resolveGovernanceStatus(
  level: string,
  governanceStatus?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const raw = governanceStatus?.trim() || "UNKNOWN";
  const upper = raw.toUpperCase();
  if (upper === "GOVERNANCE_MISSING" || upper === "MISSING_DATA" || upper === "MISSING") {
    return researchStatus(upper === "GOVERNANCE_MISSING" ? "GOVERNANCE_MISSING" : "MISSING", "degraded");
  }
  if (isStaleToken(raw, freshness)) {
    const label = raw.includes("STALE") || freshness?.is_stale ? raw : `${raw}+STALE`;
    return researchStatus(label, "degraded");
  }
  return researchStatus(raw, levelToTone(level));
}

/** Drift Monitoring: missing classic metrics is MISSING_DATA, not SEVERE. */
export function resolveDriftStatus(
  level: string,
  severityLabel?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const raw = (severityLabel || "").trim();
  const upper = raw.toUpperCase();
  if (upper === "MISSING_DATA" || upper === "NO_CURRENT_DRIFT_METRICS" || upper === "MISSING") {
    return researchStatus(raw || "MISSING_DATA", "degraded");
  }
  if (isStaleToken(severityLabel, freshness)) {
    const label = severityLabel?.trim() || "STALE_DRIFT_DATA";
    return researchStatus(label, "degraded");
  }
  const label =
    severityLabel?.trim() ||
    (() => {
      const normalized = level.toUpperCase();
      if (normalized === "GREEN") return "Stable";
      if (normalized === "RED") return "Critical";
      if (normalized === "GREY") return "Unknown";
      return "Warning";
    })();
  return researchStatus(label, levelToTone(level));
}

/** Toxic Box: display_status drives badge (never trend / CURRENT when missing). */
export function resolveToxicStatus(
  level: string,
  severityLabel?: string | null,
  freshness?: ArtifactFreshness | null,
  displayStatus?: string | null,
): ResolvedStatus {
  const ds = (displayStatus || severityLabel || "").trim().toUpperCase();
  if (ds === "CURRENT" || ds.startsWith("CURRENT")) {
    return researchStatus("CURRENT", "operational");
  }
  if (ds.includes("LEGACY_ONLY") || ds === "LEGACY_ONLY / STALE") {
    return researchStatus("LEGACY_ONLY / STALE", "degraded");
  }
  if (ds.includes("MISSING")) {
    return researchStatus("MISSING_DATA", "degraded");
  }
  const raw = (severityLabel || "").trim();
  const upper = raw.toUpperCase();
  if (
    freshness?.is_stale ||
    upper.includes("STALE") ||
    upper.includes("BASELINE LOADED") ||
    upper.includes("LEGACY")
  ) {
    return researchStatus("LEGACY_ONLY / STALE", "degraded");
  }
  if (isStaleToken(severityLabel, freshness)) {
    return researchStatus("LEGACY_ONLY / STALE", "degraded");
  }
  const label =
    severityLabel?.trim() ||
    (() => {
      const normalized = level.toUpperCase();
      if (normalized === "GREEN") return "Normal";
      if (normalized === "RED") return "Critical";
      return "Elevated";
    })();
  return researchStatus(label, levelToTone(level));
}

/** Economic Validation: outcome health labels. */
export function resolveEconomicStatus(
  level: string,
  status?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const normalized = level.toUpperCase();
  const statusToken = (status || "").toUpperCase();
  if (isStaleToken(status, freshness)) {
    return researchStatus(status?.trim() || "STALE_VALIDATION", "degraded");
  }
  let label = "Review";
  if (normalized === "GREY" || statusToken === "NOT_EVALUATED" || statusToken === "NO_DATA") {
    label = "Not evaluated";
  } else if (normalized === "GREEN") {
    label = "Passing";
  } else if (normalized === "RED") {
    label = "Failing";
  }
  return researchStatus(label, levelToTone(level));
}

/** Shadow Model: validation_status PASS · REVIEW · FAIL · NOT_EVALUATED · STALE_* */
export function resolveShadowStatus(
  level: string,
  validationStatus?: string | null,
  freshness?: ArtifactFreshness | null,
): ResolvedStatus {
  const vs = (validationStatus || "").toUpperCase();
  if (isStaleToken(validationStatus, freshness)) {
    return researchStatus(validationStatus?.trim() || "STALE_VALIDATION", "degraded");
  }
  let label = "REVIEW";
  if (vs === "PASS") label = "PASS";
  else if (vs === "WARNING") label = "REVIEW";
  else if (vs === "NOT_EVALUATED" || vs === "NO_DATA" || vs === "UNAVAILABLE") label = "Not evaluated";
  else if (vs === "MISSING" || vs === "MISSING_DATA") label = "MISSING_DATA";
  else if (vs === "FAIL") label = "FAIL";
  else if (level.toUpperCase() === "GREY") label = "Not evaluated";
  else if (level.toUpperCase() === "GREEN") label = "PASS";
  else if (level.toUpperCase() === "RED") label = "FAIL";

  return researchStatus(label, levelToTone(level));
}

/** Model Summary executive card — header label only (reason shown once separately). */
export function resolveModelSummaryStatus(
  level: string,
  status?: string | null,
  freshness?: ArtifactFreshness | null,
  _attentionReason?: string | null,
): ResolvedStatus {
  const token = (status || "").trim().toUpperCase();
  if (token === "ATTENTION" || isStaleToken(status, freshness)) {
    return researchStatus(token === "ATTENTION" ? "ATTENTION" : status?.trim() || "ATTENTION", "degraded");
  }
  let label = status?.trim() || "UNKNOWN";
  if (token === "MISSING" || token === "NOT_EVALUATED" || level.toUpperCase() === "GREY") {
    label = "Not evaluated";
  }
  return researchStatus(label, levelToTone(level));
}

/** Compact local row status — never embeds the global Model Summary reason. */
export function resolveLocalTokenStatus(token?: string | null): ResolvedStatus {
  const label = (token || "UNKNOWN").trim() || "UNKNOWN";
  const upper = label.toUpperCase();
  if (
    upper === "CURRENT" ||
    upper === "AVAILABLE" ||
    upper === "PASS" ||
    upper === "HEALTHY"
  ) {
    return researchStatus(label, "operational");
  }
  if (
    upper.includes("MISSING") ||
    upper === "STALE" ||
    upper === "HISTORICAL" ||
    upper === "NOT_PRIMARY" ||
    upper === "LEGACY_ONLY" ||
    upper === "GOVERNANCE_MISSING" ||
    upper === "ATTENTION" ||
    upper === "REVIEW"
  ) {
    return researchStatus(label, "degraded");
  }
  return researchStatus(label, levelToTone(label));
}

/** Pipeline sync: 24/24 orchestration health. */
export function resolvePipelineSyncStatus(level: string): ResolvedStatus {
  const normalized = level.toUpperCase();
  const label = normalized === "GREEN" ? "Synced" : "Out of Sync";
  return researchStatus(label, levelToTone(level));
}

export function isResearchRibbonKey(key: string): boolean {
  return RESEARCH_RIBBON_KEYS.has(key);
}

export function resolveResearchRibbonItem(item: {
  key: string;
  label: string;
  level: string;
  value?: string;
}): ResolvedStatus {
  switch (item.key) {
    case "decision_layer":
      return resolveDecisionStatus(item.level, item.value);
    case "model_governance":
      return resolveGovernanceStatus(item.level, item.value);
    case "economic_validation":
      return resolveEconomicStatus(item.level, item.value);
    case "shadow_inference":
      return resolveShadowStatus(item.level, item.value);
    case "toxic_box":
      return resolveToxicStatus(item.level);
    case "pipeline_sync":
      return resolvePipelineSyncStatus(item.level);
    default:
      return resolveDecisionStatus(item.level);
  }
}

export function formatSourceTimestamp(value?: string | null): string {
  if (!value) return "MISSING";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return String(value);
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** True when a date string is the June legacy monitoring stamp. */
export function isLegacyJunePrimaryDate(value?: string | null): boolean {
  if (!value) return false;
  const normalized = String(value);
  return /2026-06-14/.test(normalized) || /Jun\s*14/i.test(normalized);
}

/** Display lines for Model Summary sources — no global ATTENTION reason here. */
export function formatModelSummarySourceLines(
  sources?: {
    diagnostics_primary?: {
      generated_at?: string | null;
      freshness_status?: string;
      source_path?: string | null;
      used_as_primary?: boolean;
    } | null;
    governance?: {
      status?: string;
      missing_reason?: string | null;
      source_path?: string | null;
    } | null;
    legacy_monitoring?: {
      timestamp?: string | null;
      used_as_primary?: boolean;
      is_stale?: boolean;
      freshness_status?: string;
      source_path?: string | null;
    } | null;
  } | null,
  options?: {
    version?: string | null;
    promotionEligible?: string | null;
    /** @deprecated Reason is shown once in the Model Summary header, not per line. */
    reason?: string | null;
  },
): string[] {
  const diagnostics = sources?.diagnostics_primary;
  const governance = sources?.governance;
  const legacy = sources?.legacy_monitoring;

  const diagStatus = (diagnostics?.freshness_status || "MISSING").toUpperCase();
  const govRaw = (governance?.status || "MISSING").toUpperCase();
  const govStatus =
    govRaw === "GOVERNANCE_MISSING" || govRaw === "MISSING_DATA" ? "GOVERNANCE_MISSING" : govRaw;
  const legacyStatus =
    legacy?.is_stale || (legacy?.freshness_status || "").toUpperCase().includes("STALE")
      ? "STALE"
      : (legacy?.freshness_status || "MISSING").toUpperCase();

  return [
    `Data source: ${options?.version || "benchmark_primary_v1"}`,
    `Latest diagnostics: ${formatSourceTimestamp(diagnostics?.generated_at ?? null)} · ${diagStatus}`,
    `Source: ${diagnostics?.source_path || "MISSING"}`,
    `Governance: ${govStatus}`,
    `Legacy monitoring: ${formatSourceTimestamp(legacy?.timestamp ?? null)} · ${legacyStatus} · ${
      legacy?.used_as_primary ? "primary" : "not primary"
    }`,
    `Promotion eligible: ${options?.promotionEligible || "NO"}`,
  ];
}

/** Count how many times the global attention reason appears in rendered Model Summary lines. */
export function countAttentionReasonOccurrences(lines: string[], reason?: string | null): number {
  if (!reason) return 0;
  const needle = reason.trim();
  if (!needle) return 0;
  return lines.filter((line) => line.includes(needle)).length;
}

/** Collapse consecutive / duplicate phrases in a list of display strings. */
export function dedupeRepeatedPhrases(lines: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of lines) {
    const key = line.trim().toLowerCase().replace(/\s+/g, " ");
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(line);
  }
  return out;
}

const TOXIC_ACTION =
  "Refresh toxic/economic validation artifacts if current toxic monitoring is required.";

/** Prefer a single toxic action; never governance/retrain copy. */
export function pickToxicAction(warning?: string | null, refreshHint?: string | null): string | null {
  const candidates = [warning, refreshHint].filter(Boolean).map((s) => String(s).trim());
  for (const text of candidates) {
    if (/model governance|retrain/i.test(text)) continue;
    if (/toxic|economic validation artifacts/i.test(text)) {
      // Normalize to one canonical action sentence.
      if (/refresh toxic\/economic/i.test(text)) return TOXIC_ACTION;
      // If warning is the long historical sentence, still return action once.
      if (/historical toxic baseline is stale/i.test(text)) return TOXIC_ACTION;
      return text;
    }
  }
  return candidates.length ? TOXIC_ACTION : null;
}

export function isToxicHistoricalBaseline(severityLabel?: string | null, isStale?: boolean): boolean {
  const upper = (severityLabel || "").toUpperCase();
  return Boolean(
    isStale ||
      upper.includes("STALE") ||
      upper.includes("BASELINE") ||
      upper.includes("LEGACY_ONLY"),
  );
}

function basenamePath(path?: string | null): string | null {
  if (!path) return null;
  const parts = String(path).split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || String(path);
}

/** Compact Toxic Box copy — current vs historical source truth. */
export function formatToxicBoxDisplay(input: {
  displayStatus?: string | null;
  severityLabel?: string | null;
  events?: number;
  eventsLast7d?: number;
  toxicRate7d?: number | null;
  toxicRate30d?: number | null;
  trend?: string | null;
  sourcePath?: string | null;
  asOf?: string | null;
  ageDays?: number | null;
  isStale?: boolean;
  staleWarning?: string | null;
  refreshHint?: string | null;
  currentStatus?: string | null;
  currentSourcePath?: string | null;
  currentGeneratedAt?: string | null;
  historicalSourcePath?: string | null;
  historicalTimestamp?: string | null;
  historicalAgeDays?: number | null;
}): {
  headerStatus: string;
  currentLine: string | null;
  baselineLine: string | null;
  eventsLine: string;
  ratesLine: string;
  trendLine: string;
  sourceLine: string | null;
  asOfLine: string | null;
  historicalSourceLine: string | null;
  actionLine: string | null;
  showRowBadges: boolean;
  renderedLines: string[];
} {
  const display = (input.displayStatus || input.severityLabel || "").toUpperCase();
  const currentMissing =
    (input.currentStatus || "").toUpperCase().includes("MISSING") ||
    display.includes("LEGACY_ONLY") ||
    display.includes("MISSING");
  const isCurrent = display === "CURRENT" || display.startsWith("CURRENT ");
  const legacyOnly = !isCurrent && (currentMissing || isToxicHistoricalBaseline(input.severityLabel, input.isStale));

  const headerStatus = isCurrent
    ? "CURRENT"
    : legacyOnly
      ? "LEGACY_ONLY / STALE"
      : input.severityLabel?.trim() || "MISSING_DATA";

  const currentLine = legacyOnly ? "Current toxic monitoring: MISSING_DATA" : null;
  const baselineLine = isCurrent
    ? "Current toxic monitoring loaded"
    : legacyOnly
      ? "Historical toxic baseline loaded"
      : null;

  const eventsLine = `Toxic events: ${input.events ?? 0}`;
  const ratesLine = `7d: ${input.eventsLast7d ?? 0} · 7d toxic rate: ${
    input.toxicRate7d != null ? input.toxicRate7d.toFixed(2) : "0.00"
  }/d · 30d: ${input.toxicRate30d != null ? input.toxicRate30d.toFixed(2) : "0.00"}/d`;

  const trendValue = input.trend || "—";
  const trendLine = legacyOnly ? `Historical trend: ${trendValue}` : `Trend: ${trendValue}`;

  let sourceLine: string | null = null;
  let asOfLine: string | null = null;
  let historicalSourceLine: string | null = null;

  if (isCurrent) {
    const src = basenamePath(input.currentSourcePath || input.sourcePath);
    sourceLine = src ? `Source: ${input.currentSourcePath || src}` : null;
    // Prefer relative display path when available.
    if (input.currentSourcePath) {
      sourceLine = `Source: ${input.currentSourcePath}`;
    }
    const ageLabel =
      input.ageDays != null ? `${Number(input.ageDays).toFixed(2)} days` : "0 days";
    const asOf = input.currentGeneratedAt
      ? formatSourceTimestamp(input.currentGeneratedAt)
      : input.asOf;
    asOfLine = asOf ? `As of: ${asOf} · age: ${ageLabel}` : null;
    const histSrc = basenamePath(input.historicalSourcePath);
    if (histSrc) {
      const histWhen = input.historicalTimestamp
        ? formatSourceTimestamp(input.historicalTimestamp)
        : null;
      historicalSourceLine = histWhen
        ? `Historical source: ${histSrc} · ${histWhen} · STALE · not primary`
        : `Historical source: ${histSrc} · STALE · not primary`;
    }
  } else {
    const histSrc =
      basenamePath(input.historicalSourcePath || input.sourcePath) || "toxic_box_memory.parquet";
    sourceLine = `Historical source: ${histSrc}`;
    const ageDays = input.historicalAgeDays ?? input.ageDays;
    const ageLabel = ageDays != null ? `${Number(ageDays).toFixed(2)} days` : "—";
    const asOfRaw = input.historicalTimestamp || input.asOf;
    const asOf = asOfRaw ? formatSourceTimestamp(String(asOfRaw)) : null;
    asOfLine = asOf ? `Historical as of: ${asOf} · age: ${ageLabel}` : null;
  }

  const action =
    legacyOnly || input.isStale
      ? pickToxicAction(input.staleWarning, input.refreshHint) || TOXIC_ACTION
      : null;
  const actionLine = action ? `Action: ${action}` : null;

  const renderedLines = dedupeRepeatedPhrases(
    [
      headerStatus,
      currentLine,
      baselineLine,
      eventsLine,
      ratesLine,
      trendLine,
      sourceLine,
      asOfLine,
      historicalSourceLine,
      actionLine,
    ].filter((x): x is string => Boolean(x)),
  );

  return {
    headerStatus,
    currentLine,
    baselineLine,
    eventsLine,
    ratesLine,
    trendLine,
    sourceLine,
    asOfLine,
    historicalSourceLine,
    actionLine,
    showRowBadges: isCurrent,
    renderedLines,
  };
}

/** Single Drift legacy metric line — no standalone HISTORICAL badge text. */
export function formatDriftLegacyPsiLine(input: {
  legacyPsi?: number | null;
  legacyTimestamp?: string | null;
}): string | null {
  if (input.legacyPsi == null) return null;
  const psi = Number(input.legacyPsi).toFixed(3);
  const when = input.legacyTimestamp ? formatSourceTimestamp(input.legacyTimestamp) : null;
  return when
    ? `Legacy PSI: ${psi} · HISTORICAL · STALE · not primary · ${when}`
    : `Legacy PSI: ${psi} · HISTORICAL · STALE · not primary`;
}

/** Count phrase occurrences across rendered lines (case-insensitive substring). */
export function countPhraseOccurrences(lines: string[], phrase: string): number {
  const needle = phrase.trim().toLowerCase();
  if (!needle) return 0;
  return lines.reduce((n, line) => n + (line.toLowerCase().includes(needle) ? 1 : 0), 0);
}
