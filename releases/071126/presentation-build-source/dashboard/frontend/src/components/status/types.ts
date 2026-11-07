/** Platform-wide visual tone — maps to dot, badge, and card accent colors. */
export type StatusTone = "operational" | "degraded" | "critical" | "offline";

export type StatusDomain = "system" | "feed" | "engine" | "validation" | "research";

export type SystemStatusKey =
  | "operational"
  | "operational_with_limitations"
  | "degraded"
  | "critical"
  | "offline"
  | "informational";
export type FeedStatusKey =
  | "receiving_data"
  | "current"
  | "current_unchanged"
  | "delayed"
  | "disconnected";
export type EngineStatusKey =
  | "running"
  | "receiving_data"
  | "lagging"
  | "failed"
  | "migrated"
  | "not_required"
  | "not_live"
  | "expected"
  | "known_limitation"
  | "not_in_canonical_runtime"
  | "deprecated"
  | "historical_only"
  | "informational";
export type ValidationStatusKey =
  | "passing"
  | "attention_required"
  | "failing"
  | "not_evaluated"
  | "incomplete_non_blocking"
  | "informational";
export type ResearchStatusKey = "semantic";

export type StatusKey =
  | SystemStatusKey
  | FeedStatusKey
  | EngineStatusKey
  | ValidationStatusKey
  | ResearchStatusKey;

export type ResolvedStatus = {
  domain: StatusDomain;
  key: StatusKey;
  label: string;
  tone: StatusTone;
};
