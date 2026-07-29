export type OpsLevel = "GREEN" | "YELLOW" | "RED" | "GREY";

export type ComponentClass = "REQUIRED" | "OPTIONAL" | "LEGACY" | "RESEARCH" | "DORMANT";

export type EngineStatus = "HEALTHY" | "DEFERRED" | "FAILED" | "TIMEOUT" | "STALLED";

export interface OpsSnapshot {
  generated_at?: string;
  schema_version?: string;
  ribbon: RibbonItem[];
  engines: EngineRow[];
  parquet: ParquetSummary;
  collectors: CollectorSummary;
  pipeline: PipelineSummary;
  feed_confidence?: FeedConfidence;
  stability?: StabilitySummary;
  health: HealthSummary;
  health_dimensions?: HealthDimensions;
  runtime_stability?: string;
  status_planes?: Record<string, unknown>;
  alerts: OpsAlert[];
  alert_groups?: AlertGroups;
  manifest?: ManifestSummary;
  classification?: ClassificationSummary;
  research_pipeline?: ResearchPipelineSnapshot;
  runtime_failure_audit?: RuntimeFailureAuditSummary;
  runtime_skipped_engine_audit?: RuntimeSkippedEngineAuditSummary;
  /** offline fallback marker when live :8080 is unavailable */
  snapshot_mode?: string;
  /** Patch 4.2 / final cleanup canonical runtime truth plane */
  overall_health?: string;
  overall_reason?: string;
  runtime_truth?: RuntimeTruthSnapshot;
  processes?: RuntimeTruthProcess[];
  pipeline_engines?: RuntimeTruthEngine[];
  datasets?: RuntimeTruthDataset[];
  multi_timeframe?: RuntimeTruthTimeframe[];
  context_chain?: RuntimeTruthContextChain;
  paper?: RuntimeTruthPaper;
  known_limitations?: RuntimeTruthLimitation[];
  legacy_components?: RuntimeTruthLegacy[];
  timeframe_traders?: RuntimeTruthTimeframeTraders;
}

export interface RuntimeTruthProcess {
  process_id: string;
  display_name?: string;
  pid?: number | null;
  health?: string;
  health_reason?: string;
  process_state?: string;
  command?: string | null;
  required?: boolean;
}

export interface RuntimeTruthEngine {
  engine_id: string;
  display_name?: string;
  pipeline_order?: number;
  last_result?: string;
  health?: string;
  required?: boolean;
}

export interface RuntimeTruthDataset {
  dataset_id?: string;
  health?: string;
  health_reason?: string;
  path?: string;
}

export interface RuntimeTruthTimeframe {
  timeframe: string;
  support?: string;
  availability_status?: string;
  availability_reason?: string | null;
  display_status?: string | null;
  requirement?: string | null;
  detail?: string | null;
  state_asof?: string | null;
  source_bar_close?: string | null;
  is_new_event?: boolean | null;
  age_bars?: number | null;
}

export interface RuntimeTruthContextChain {
  process_health?: string;
  last_result?: string;
  health?: string;
  health_reason?: string;
  safe_upstream_tip?: string | null;
  final_context_tip?: string | null;
  lifecycle_tip?: string | null;
  decision_tip?: string | null;
  last_poll?: string | null;
}

export interface RuntimeTruthPaper {
  process_health?: string;
  representation?: string;
  display_status?: string;
  requirement?: string;
  detail?: string;
  is_controller_failure?: boolean;
  health?: string;
  health_reason?: string;
  last_cycle_result?: string | null;
  skip_refresh?: boolean;
  real_execution?: boolean;
  exchange_enabled?: boolean;
}

export interface RuntimeTruthLimitation {
  id?: string;
  detail?: string;
  classification?: string;
  display_status?: string;
  requirement?: string;
}

export interface RuntimeTruthTrader {
  timeframe: string;
  book_exists?: boolean;
  direction?: string;
  status?: string | null;
  open_position_id?: string | null;
  entry_price?: number | null;
  entry_fill_price?: number | null;
  entry_fill_timestamp?: string | null;
  quantity?: number | null;
  position_notional?: number | null;
  risk_amount_usd?: number | null;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  risk_reward_ratio?: number | null;
  context_event_id?: string | null;
  lifecycle_episode_id?: string | null;
  context_started_at?: string | null;
  context_price?: number | null;
  context_price_timestamp?: string | null;
  mark_price?: number | null;
  mark_timestamp?: string | null;
  mark_side?: string | null;
  mark_source?: string | null;
  open_risk_usd?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  initial_equity_usd?: number | null;
  current_equity_usd?: number | null;
  risk_pct_per_trade?: number | null;
  next_risk_budget_usd?: number | null;
  available_risk_usd?: number | null;
  open_position_count?: number | null;
  closed_trades?: number | null;
  trade_count?: number | null;
  last_command_intent?: string | null;
  last_command_timestamp?: string | null;
  last_reason?: string | null;
  manager_command_id?: string | null;
  process_health?: string;
  health?: string;
  health_reason?: string;
}

export interface RuntimeTruthCommandBus {
  exists?: boolean;
  rows?: number | null;
  duplicate_command_ids?: number | null;
  latest_evaluation_timestamp?: string | null;
  latest_evaluation_period?: string | null;
  health?: string;
}

export interface RuntimeTruthPortfolio {
  open_positions?: number | null;
  open_position_count?: number | null;
  gross_open_risk_usd?: number | null;
  available_risk_usd?: number | null;
  portfolio_max_risk_usd?: number | null;
  gross_open_notional_usd?: number | null;
  net_notional?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  initial_equity_usd?: number | null;
  closed_equity_usd?: number | null;
  capital_model?: string | null;
  master_initial_equity_usd?: number | null;
  master_current_equity_usd?: number | null;
  master_realized_net_pnl_usd?: number | null;
  master_unrealized_pnl_usd?: number | null;
  master_open_risk_usd?: number | null;
  master_risk_capacity_usd?: number | null;
  master_available_risk_usd?: number | null;
  master_open_notional_usd?: number | null;
  mark_price?: number | null;
  mark_timestamp?: string | null;
  mark_side?: string | null;
  mark_source?: string | null;
  mark_status?: string | null;
}

export interface RuntimeTruthTimeframeTraders {
  activated?: boolean;
  d1_trader?: boolean;
  command_bus?: RuntimeTruthCommandBus;
  portfolio?: RuntimeTruthPortfolio;
  traders?: RuntimeTruthTrader[];
}

export interface RuntimeTruthLegacy {
  component_id?: string;
  classification?: string;
  display_status?: string;
  active?: boolean;
  reason?: string;
}

export interface RuntimeTruthSnapshot {
  generated_at?: string;
  schema_version?: string;
  overall_health?: string;
  overall_reason?: string;
  processes?: RuntimeTruthProcess[];
  pipeline_engines?: RuntimeTruthEngine[];
  multi_timeframe?: RuntimeTruthTimeframe[];
  context_chain?: RuntimeTruthContextChain;
  paper?: RuntimeTruthPaper;
  known_limitations?: RuntimeTruthLimitation[];
  legacy_components?: RuntimeTruthLegacy[];
  timeframe_traders?: RuntimeTruthTimeframeTraders;
  shadow_economic_correlation?: Record<string, unknown> | null;
}


export interface RuntimeFailureAuditRecord {
  timestamp?: string | null;
  engine?: string | null;
  status?: string | null;
  duration_s?: number | null;
  error?: string | null;
  exit_code?: number | null;
  cycle?: number | null;
}

export interface RuntimeFailureAuditSummary {
  exists: boolean;
  path: string;
  total_count: number;
  recent_count: number;
  active_count?: number;
  historical_count?: number;
  malformed_count?: number;
  status?: string;
  status_label?: string;
  affects_health?: boolean;
  latest?: RuntimeFailureAuditRecord | null;
  recent: RuntimeFailureAuditRecord[];
  active?: RuntimeFailureAuditRecord[];
  error?: string;
}

export interface RuntimeSkippedDependencySnapshot {
  resolved_path?: string | null;
  exists?: boolean | null;
  mtime?: number | null;
  mtime_iso?: string | null;
}

export interface RuntimeSkippedEngineAuditRecord {
  timestamp?: string | null;
  engine?: string | null;
  status?: string | null;
  reason?: string | null;
  dependencies?: Record<string, RuntimeSkippedDependencySnapshot>;
}

export interface RuntimeSkippedEngineAuditSummary {
  exists: boolean;
  path: string;
  total_count: number;
  recent_count: number;
  malformed_count?: number;
  latest?: RuntimeSkippedEngineAuditRecord | null;
  recent: RuntimeSkippedEngineAuditRecord[];
  error?: string;
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
  restart_count?: number | null;
  disconnect_count?: number | null;
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
  level?: OpsLevel;
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
  current_cycle?: number | null;
  average_cycle_duration_s?: number | null;
  last_cycle_duration_s?: number | null;
  uptime_seconds?: number | null;
  failed_engine_count?: number | null;
  failed_required_engine_count?: number | null;
  failed_optional_engine_count?: number | null;
  timeout_count?: number | null;
  timeout_optional_count?: number | null;
  stalled_engine_count?: number | null;
  current_stalled_engine_count?: number;
  historical_stalled_engine_count?: number;
  latest_historical_stall_at?: string | null;
  latest_current_stall_at?: string | null;
  current_stalls_timeouts?: number;
  historical_stalls_timeouts?: number;
  heartbeat_level: OpsLevel;
  active_state: string;
}

export interface HealthSummary {
  level: "HEALTHY" | "DEGRADED" | "CRITICAL" | "UNKNOWN" | "FAILED";
  primary_reason: string;
  reasons: string[];
  critical_reasons?: string[];
  degraded_reasons?: string[];
  cpu_percent?: number | null;
  memory_percent?: number | null;
  disk_percent?: number | null;
  deferred_engine_count?: number;
  optional_offline_count?: number;
  display_status?: string;
  health_dimensions?: HealthDimensions;
  resources?: ResourceHealthDimension;
}

export interface ResourceHealthDimension {
  status: string;
  cpu_pct: number;
  memory_pct: number;
  disk_pct: number;
  reason: string;
  reasons?: string[];
}

export interface HealthDimensions {
  runtime: {
    status: string;
    reason: string;
    current_failures_count: number;
    failed_engine_count: number;
    required_datasets_stale_count: number;
    collectors_status: string;
    websocket_status: string;
    pipeline_status: string;
  };
  resources: ResourceHealthDimension;
  research_validation: {
    status: string;
    reason: string;
    governance_status: string;
    economic_status: string;
    shadow_status: string;
    toxic_status: string;
  };
  historical_audit: {
    status: string;
    historical_failures_count: number;
    historical_stalls_count: number;
    latest_historical_failure_at?: string | null;
    latest_historical_stall_at?: string | null;
    reason: string;
  };
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

export interface ResearchPipelineSnapshot {
  generated_at?: string;
  pipeline: PipelineSyncStatus;
  decision_layer: DecisionLayerSnapshot;
  model_governance: ModelGovernanceSnapshot;
  economic_validation: EconomicValidationSnapshot;
  shadow_inference: ShadowInferenceSnapshot;
  toxic_box: ToxicBoxSnapshot;
  drift_monitoring?: DriftMonitoringSnapshot;
  model_summary?: ModelSummarySnapshot;
  /** Canonical MODEL-9 unified assurance payload (replace on each refresh). */
  model_assurance?: ModelAssuranceSnapshot;
  ribbon_extensions?: RibbonItem[];
}

export interface ModelAssuranceModuleSection {
  module_id?: string;
  status?: string | null;
  health_status?: string;
  runtime_impact?: string;
  summary?: Record<string, unknown>;
  updated_at?: string | null;
  source_path?: string;
}

export interface ModelAssuranceSnapshot {
  status?: string;
  schema_version?: string;
  generated_at?: string;
  scope?: string;
  overall_assurance_status?: string;
  overall_cause?: string | null;
  runtime_safety_status?: string;
  runtime_impact?: string;
  promotion_control?: string;
  active_runtime?: {
    status?: string;
    registry_record_id?: string;
    model_id?: string;
    model_version?: string;
    model_type?: string;
    runtime_fingerprint?: string;
    paper_epoch_id?: string;
    paper_epoch_activated_at?: string;
    paper_only?: boolean;
    real_execution?: boolean;
  };
  behavioral_validation?: ModelAssuranceModuleSection;
  external_data?: ModelAssuranceModuleSection;
  economic_validation?: ModelAssuranceModuleSection;
  current_toxicity?: ModelAssuranceModuleSection;
  incident_correlation?: ModelAssuranceModuleSection;
  drift_monitoring?: ModelAssuranceModuleSection;
  candidate_shadow?: ModelAssuranceModuleSection;
  governance_promotion?: ModelAssuranceModuleSection;
  service_health?: Record<string, string>;
  promotion_blockers?: string[];
  environment_blockers?: string[];
  warnings?: string[];
  informational_conditions?: string[];
  source_snapshot_timestamps?: Record<string, string | null>;
  stale_sources?: string[];
  missing_sources?: string[];
  current_blockers?: string[];
  current_incidents?: unknown[];
  current_toxic_events?: unknown[];
  historical_counters_excluded?: boolean;
}

export interface PipelineSyncStatus {
  step_count: number;
  expected_step_count: number;
  in_sync: boolean;
  engines: string[];
  last_cycle_duration_s?: number | null;
  average_cycle_duration_s?: number | null;
}

export interface TimeframeTradingState {
  timeframe: string;
  provisional_market_context?: string | null;
  active_market_context?: string | null;
  trading_state?: string | null;
  market_state?: string | null;
  directional_bias?: string | null;
  lifecycle_state?: string | null;
  lifecycle_episode_id?: string | null;
  context_event_id?: string | null;
  context_started_at?: string | null;
  context_price?: number | null;
  open_position_id?: string | null;
  open_position_side?: string | null;
  entry_eligible?: boolean | null;
  intent?: string | null;
  decision_reason?: string | null;
  causal_cutoff_timestamp?: string | null;
  last_evaluated_at?: string | null;
  source?: string | null;
  stale?: boolean | null;
  level?: string | null;
  source_lag_seconds?: number | null;
}

export interface TradingStatesPanel {
  source?: string | null;
  directional_timeframes?: number | null;
  active_directional_contexts?: number | null;
  current_directional_evaluations?: number | null;
  total_timeframes?: number | null;
  timeframes?: Record<string, TimeframeTradingState>;
}

export interface DecisionLayerSnapshot {
  level: OpsLevel;
  status_label?: string;
  market_state?: string;
  market_bias?: string;
  rule_id?: string;
  market_state_confidence?: number;
  trend_confidence?: number;
  trading_state?: string;
  trading_states?: TradingStatesPanel;
  confidence_band?: string;
  entry_eligible?: boolean;
  execution_posture?: string;
  snapshot_id?: string;
  timestamp?: string;
  rows?: Record<string, number>;
  /** LIVE1A lineage (OPS1.4 / OPS1.6) */
  source?: string;
  source_name?: string;
  source_timestamp?: string | null;
  source_stale?: boolean;
  stale?: boolean;
  timeframe?: string | null;
  lifecycle_state?: string | null;
  lifecycle_episode_id?: string | null;
  context_event_id?: string | null;
  context_started_at?: string | null;
  causal_cutoff_timestamp?: string | null;
  context_source_timestamp?: string | null;
  decision_reason?: string | null;
  active_market_context?: string | null;
  paper_action_candidate?: string | null;
  intended_side?: string | null;
  by_timeframe?: Record<string, TimeframeTradingState>;
}

export interface ArtifactFreshness {
  source_path?: string | null;
  source_timestamp?: string | null;
  source_mtime?: string | null;
  age_hours?: number | null;
  age_days?: number | null;
  is_stale?: boolean;
  stale_reason?: string | null;
  max_age_hours?: number;
  freshness_status?: string;
  metrics_scope?: "current" | "historical" | "missing" | "unknown" | string;
  warning?: string | null;
  refresh_hint?: string | null;
}

export interface ModelSummarySources {
  diagnostics_primary?: {
    source_path?: string | null;
    generated_at?: string | null;
    freshness_status?: string;
    age_hours?: number | null;
    age_days?: number | null;
    is_stale?: boolean;
    used_as_primary?: boolean;
  };
  governance?: {
    source_path?: string | null;
    status?: string;
    missing_reason?: string | null;
  };
  legacy_monitoring?: {
    source_path?: string | null;
    timestamp?: string | null;
    age_days?: number | null;
    used_as_primary?: boolean;
    is_stale?: boolean;
    freshness_status?: string;
  };
}

export interface MetricSourceMeta {
  metric_source?: string | null;
  metric_freshness?: string;
  metric_is_legacy?: boolean;
  status?: string;
  legacy_value?: number | null;
  legacy_source_timestamp?: string | null;
  legacy_is_stale?: boolean;
}

export interface ModelGovernanceSnapshot {
  level: OpsLevel;
  governance_status?: string;
  governance_status_base?: string;
  active_model?: string;
  candidate_model?: string;
  active_model_display?: string;
  candidate_model_display?: string;
  shadow_model?: string;
  last_retrain_at?: string;
  last_validation_at?: string;
  governance_validation_at?: string | null;
  latest_diagnostics_at?: string | null;
  diagnostics_status?: string;
  missing_reason?: string | null;
  shadow_macro_f1?: number;
  shadow_balanced_accuracy?: number;
  shadow_loss_recall?: number;
  shadow_rows?: number;
  rollback_warning?: boolean;
  rollback_reasons?: string | string[];
  promotion_eligible?: boolean;
  promotion_eligible_label?: string;
  promotion_reasons?: string | string[];
  monitoring_rows?: number;
  last_promotion_at?: string;
  active_model_registered_at?: string;
  active_model_age_days?: number | null;
  next_retrain_note?: string;
  action?: string | null;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
}

export interface EconomicValidationSnapshot {
  level: OpsLevel;
  status?: string;
  rows: number;
  validation_rows?: number;
  complete_h4h: number;
  pending_h4h?: number;
  rolling_window?: number;
  rolling_complete_count?: number;
  win_pct?: number | null;
  neutral_pct?: number | null;
  loss_pct?: number | null;
  win_count?: number;
  neutral_count?: number;
  loss_count?: number;
  outcome_distribution?: Record<string, number>;
  latest_completed_at?: string;
  source_path?: string | null;
  missing_reason?: string | null;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
}

export interface ShadowInferenceSnapshot {
  level: OpsLevel;
  validation_status?: string;
  rows: number;
  evaluated_rows: number;
  pending_rows?: number;
  macro_f1?: number | null;
  balanced_accuracy?: number | null;
  loss_recall?: number | null;
  last_validation_time?: string | null;
  latest_diagnostics_at?: string | null;
  registry_id?: string;
  model_version?: string;
  prediction_distribution?: Record<string, number>;
  latest_prediction_at?: string;
  metric_is_legacy?: boolean;
  legacy_macro_f1?: number | null;
  legacy_source_timestamp?: string | null;
  legacy_is_stale?: boolean | null;
  metric_source?: string | null;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
  source_freshness?: string;
  metric_availability?: string;
  status_note?: string | null;
}

export interface ToxicBoxSnapshot {
  level: OpsLevel;
  severity_label?: string;
  status?: string;
  rows: number;
  events: number;
  events_last_7d?: number;
  events_prior_7d?: number;
  events_last_30d?: number;
  events_t0_last_7d?: number;
  events_t0_last_30d?: number;
  toxic_rate_7d?: number;
  toxic_rate_30d?: number;
  monitoring_mode?: string;
  hours_since_last_routed?: number | null;
  trend?: string;
  type_distribution?: Record<string, number>;
  latest_timestamp?: string;
  source_path?: string | null;
  missing_reason?: string | null;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
  display_status?: string;
  display_reason?: string | null;
  current?: {
    status?: string;
    source_path?: string | null;
    generated_at?: string | null;
    metrics_available?: boolean;
  };
  historical?: {
    status?: string;
    source_path?: string | null;
    timestamp?: string | null;
    age_days?: number | null;
    metrics_available?: boolean;
  };
  historical_source_path?: string | null;
  historical_timestamp?: string | null;
  historical_age_days?: number | null;
}

export interface DriftMonitoringSnapshot {
  level: OpsLevel;
  severity_label?: string;
  psi?: number | null;
  psi_feature_max?: number | null;
  macro_f1?: number | null;
  loss_recall?: number | null;
  macro_f1_trend?: number | null;
  loss_recall_trend?: number | null;
  last_monitoring_at?: string | null;
  latest_diagnostics_at?: string | null;
  monitoring_rows?: number;
  metric_source?: string | null;
  legacy_psi?: number | null;
  legacy_source_timestamp?: string | null;
  legacy_is_stale?: boolean | null;
  benchmark_drift_severity?: string | null;
  cognition_health?: string | null;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
  source_freshness?: string;
  metric_availability?: string;
  status_note?: string | null;
}

export interface ModelSummarySnapshot {
  level: OpsLevel;
  status?: string;
  model?: string;
  shadow_macro_f1?: number | null;
  loss_recall?: number | null;
  psi?: number | null;
  governance_status?: string;
  last_validation_at?: string | null;
  latest_diagnostics_at?: string | null;
  governance_validation_at?: string | null;
  diagnostics_status?: string;
  attention_reason?: string | null;
  status_reason?: string | null;
  freshness_status?: string;
  freshness?: ArtifactFreshness;
  metrics_scope?: string;
  stale_warning?: string | null;
  refresh_hint?: string | null;
  promotion_eligible?: boolean;
  promotion_eligible_label?: string;
  model_summary_source_version?: string;
  model_summary_sources?: ModelSummarySources;
  psi_meta?: MetricSourceMeta;
  macro_f1_meta?: MetricSourceMeta;
  loss_recall_meta?: MetricSourceMeta;
  legacy_metrics?: {
    psi?: number | null;
    macro_f1?: number | null;
    loss_recall?: number | null;
    source_timestamp?: string | null;
    is_stale?: boolean | null;
  };
  source_freshness?: string;
  metric_availability?: string;
}
