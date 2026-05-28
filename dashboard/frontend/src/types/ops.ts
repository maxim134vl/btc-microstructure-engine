export type OpsLevel = "GREEN" | "YELLOW" | "RED" | "GREY";

export type ComponentClass = "REQUIRED" | "OPTIONAL" | "LEGACY" | "RESEARCH" | "DORMANT";

export type EngineStatus = "HEALTHY" | "DEFERRED" | "FAILED" | "TIMEOUT" | "STALLED";

export interface OpsSnapshot {
  generated_at?: string;
  ribbon: RibbonItem[];
  engines: EngineRow[];
  parquet: ParquetSummary;
  collectors: CollectorSummary;
  pipeline: PipelineSummary;
  feed_confidence?: FeedConfidence;
  stability?: StabilitySummary;
  health: HealthSummary;
  alerts: OpsAlert[];
  alert_groups?: AlertGroups;
  manifest?: ManifestSummary;
  classification?: ClassificationSummary;
}

export interface ManifestSummary {
  path: string;
  required_collectors: string[];
  required_parquet: string[];
  required_engines: string[];
  thresholds: Record<string, number>;
}

export interface FeedConfidence {
  overall: OpsLevel;
  ws: ConfidenceSignal;
  write: ConfidenceSignal;
  consume: ConfidenceSignal;
}

export interface ConfidenceSignal {
  level: OpsLevel;
  label: string;
  reason: string;
}

export interface StabilitySummary {
  runtime_uptime_s?: number | null;
  collector_uptime_s?: number | null;
  websocket_uptime_s?: number | null;
  last_disconnect?: string | null;
  last_timeout?: string | null;
  last_pipeline_stall?: string | null;
  restart_count: number;
  disconnect_count: number;
  last_write_at?: string | null;
  last_consume_at?: string | null;
  recent_events: StabilityEvent[];
}

export interface StabilityEvent {
  timestamp: string;
  type: string;
  detail: string;
}

export interface AlertGroups {
  actionable: OpsAlert[];
  informational: OpsAlert[];
  all: OpsAlert[];
}

export interface ClassificationSummary {
  required_only_health: boolean;
  archived_parquet_count: number;
  optional_offline_count: number;
  deferred_engine_count: number;
}

export interface RibbonItem {
  key: string;
  label: string;
  level: OpsLevel;
  value?: string;
}

export interface EngineRow {
  engine: string;
  short_name: string;
  status: EngineStatus;
  classification?: ComponentClass;
  affects_health?: boolean;
  ignored_by_health?: boolean;
  last_run?: string;
  last_run_ago?: string;
  duration_s?: number;
  mode: string;
  note?: string;
}

export interface ParquetSummary {
  summary_level: OpsLevel;
  live_count: number;
  stale_count: number;
  delayed_count?: number;
  missing_count: number;
  optional_stale_count?: number;
  archived_count?: number;
  stale_files: ParquetRow[];
  delayed_files?: ParquetRow[];
  missing_files: ParquetRow[];
  required?: ParquetRow[];
  optional?: ParquetRow[];
  archived?: ParquetRow[];
  all: ParquetRow[];
}

export interface ParquetRow {
  file: string;
  freshness: "LIVE" | "DELAYED" | "STALE" | "MISSING";
  level: OpsLevel;
  classification?: ComponentClass;
  affects_health?: boolean;
  ignored_by_health?: boolean;
  age_seconds?: number;
  mtime?: string;
}

export interface CollectorSummary {
  level: OpsLevel;
  collectors: CollectorRow[];
  required?: CollectorRow[];
  optional?: CollectorRow[];
  legacy?: CollectorRow[];
}

export interface CollectorRow {
  name: string;
  status: "CONNECTED" | "DEGRADED" | "DISCONNECTED" | "OPTIONAL_OFFLINE" | "ARCHIVED";
  level: OpsLevel;
  classification?: ComponentClass;
  affects_health?: boolean;
  ignored_by_health?: boolean;
  age_seconds?: number;
  last_message?: string;
  latency_note?: string;
}

export interface PipelineSummary {
  current_cycle: number;
  average_cycle_duration_s?: number;
  uptime_seconds: number;
  failed_engine_count: number;
  timeout_count: number;
  stalled_engine_count: number;
  heartbeat_level: OpsLevel;
  active_state: string;
}

export interface HealthSummary {
  level: "HEALTHY" | "DEGRADED" | "CRITICAL";
  primary_reason: string;
  reasons: string[];
  critical_reasons?: string[];
  degraded_reasons?: string[];
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  deferred_engine_count?: number;
  optional_offline_count?: number;
}

export interface OpsAlert {
  id: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  type: string;
  message: string;
  timestamp: string;
  count?: number;
  items?: string[];
  classification?: ComponentClass;
  ignored_by_health?: boolean;
  actionable?: boolean;
}
