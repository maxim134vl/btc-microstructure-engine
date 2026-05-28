export type HealthLevel = "GREEN" | "YELLOW" | "RED";

export interface LiveSnapshot {
  runtime_operations?: RuntimeOperations;
  ontology?: OntologyPanel;
  probabilistic_cognition?: ProbabilisticCognition;
  state_transitions?: StateTransitions;
  mtf_cognition?: MtfCognition;
  reinforcement?: ReinforcementPanel;
  regime?: RegimePanel;
  runtime_health?: RuntimeHealth;
  replay_audit?: ReplayAudit;
  topology?: TopologyPanel;
  generated_at?: string;
}

export interface RuntimeOperations {
  operational_health: HealthLevel;
  runtime_alive: boolean;
  pipeline_cycle_counter: number;
  current_cycle: number;
  engine_execution_order: EngineExecution[];
  failed_engines: string[];
  state_transition_waiting: boolean;
  synthesis_row_count: number;
  last_parquet_writes: ParquetWrite[];
  runtime_continuity: { status: HealthLevel; loop_audit_cycles: number };
  system: { cpu_percent: number; memory_percent: number; disk_percent: number; uptime_seconds: number };
  recent_events: EngineEvent[];
}

export interface EngineExecution {
  engine: string;
  status: string;
  duration_s?: number;
  timestamp?: string;
  mode: string;
}

export interface EngineEvent {
  engine: string;
  status: string;
  duration?: number;
  timestamp?: string;
}

export interface ParquetWrite {
  file: string;
  mtime?: string;
  age_seconds?: number;
  row_count?: number;
  stale?: boolean;
}

export interface OntologyPanel {
  ontology_event_feed: Record<string, unknown>[];
  event_counts_by_timeframe: Record<string, Record<string, number>>;
  ontology_density: Record<string, unknown>;
  climactic_behavior?: Record<string, unknown>;
}

export interface ProbabilisticCognition {
  latest: Record<string, unknown>;
  decomposition: Record<string, unknown>;
  timeline: Record<string, unknown>[];
  entropy_state: Record<string, unknown>;
  contradiction: Record<string, unknown>;
}

export interface StateTransitions {
  waiting_for_second_state: boolean;
  current_auction_state?: string;
  previous_auction_state?: string;
  latest_transition?: Record<string, unknown>;
  chronology: Record<string, unknown>[];
}

export interface MtfCognition {
  timeframe_states: TimeframeState[];
  stage2_synthesis?: Record<string, unknown>;
  runtime_cognition?: Record<string, unknown>;
  d1_macro_anchor?: TimeframeState;
}

export interface TimeframeState {
  timeframe: string;
  status: string;
  latest_event_type?: string;
  auction_state?: string;
  in_live_pipeline?: boolean;
  recent_events?: Record<string, unknown>[];
}

export interface ReinforcementPanel {
  reinforcement_latest?: Record<string, unknown>;
  contradiction_escalation_score?: number;
  unresolved_contradiction_score?: number;
  reinforcement_stability_score?: number;
}

export interface RegimePanel {
  current_regime?: string;
  regime_state?: string;
  regime_confidence?: number;
  regime_transition_probability?: number;
  regime_probabilities: Record<string, number>;
  regime_timeline: Record<string, unknown>[];
}

export interface RuntimeHealth {
  operational_health: HealthLevel;
  stale_parquet: ParquetWrite[];
  missing_parquet: ParquetWrite[];
  alerts: { severity: HealthLevel; type: string; file?: string }[];
}

export interface ReplayAudit {
  replay_exports: { name: string; path: string; mtime: string }[];
  replay_controls: Record<string, string>;
}

export interface TopologyPanel {
  pipeline_nodes: { id: string; order: number; status: string; dependencies: string[] }[];
  edges: { from: string; to: string; type: string }[];
  dead_nodes: string[];
  orchestration_integrity: HealthLevel;
}

export type PanelId =
  | "runtime"
  | "ontology"
  | "cognition"
  | "transitions"
  | "mtf"
  | "reinforcement"
  | "regime"
  | "health"
  | "replay"
  | "topology";
