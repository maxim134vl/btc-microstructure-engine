export type ActivityOutcome = "success" | "failed" | "warning" | "info";

export type ActivityCategory = "engine" | "transition" | "cognition" | "ontology" | "health" | "export";

export interface ActivityEvent {
  id: string;
  timestamp: string | null;
  timestampMs: number;
  title: string;
  subtitle: string;
  category: ActivityCategory;
  outcome: ActivityOutcome;
  durationMs: number | null;
  source: string;
  raw: Record<string, unknown>;
}

export interface ActivityKpis {
  totalEvents: number;
  successCount: number;
  failedCount: number;
  warningCount: number;
  successRate: number | null;
  avgDurationMs: number | null;
  currentCycle: number;
  pipelineHealth: string;
  lastEventAt: string | null;
}

export interface ParsedRuntimeActivity {
  events: ActivityEvent[];
  kpis: ActivityKpis;
  generatedAt: string | null;
  raw: unknown;
}
