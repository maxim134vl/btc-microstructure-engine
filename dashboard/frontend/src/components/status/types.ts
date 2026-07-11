/** Platform-wide visual tone — maps to dot, badge, and card accent colors. */
export type StatusTone = "operational" | "degraded" | "critical" | "offline";

export type StatusDomain = "system" | "feed" | "engine" | "validation" | "research";

export type SystemStatusKey = "operational" | "degraded" | "critical" | "offline";
export type FeedStatusKey = "receiving_data" | "delayed" | "disconnected";
export type EngineStatusKey = "running" | "lagging" | "failed";
export type ValidationStatusKey = "passing" | "attention_required" | "failing" | "not_evaluated";
export type ResearchStatusKey = "semantic";

export type StatusKey = SystemStatusKey | FeedStatusKey | EngineStatusKey | ValidationStatusKey | ResearchStatusKey;

export type ResolvedStatus = {
  domain: StatusDomain;
  key: StatusKey;
  label: string;
  tone: StatusTone;
};
