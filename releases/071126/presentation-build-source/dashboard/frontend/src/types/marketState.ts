export type Timeframe = "M15" | "M30" | "H1" | "H4" | "D1";
export type ViewMode = "latest" | "replay" | "range";
export type DensityMode = "clean" | "detailed" | "debug";
export type HistoryRange = "100" | "250" | "500" | "1000" | "3d" | "7d" | "all" | "custom";

export type DecisionState =
  | "NO_SETUP"
  | "LONG_SETUP"
  | "SHORT_SETUP"
  | "EXIT_LONG"
  | "EXIT_SHORT"
  | "INVALIDATED";

export type CognitiveState =
  | "LOW_CONFIDENCE_MODE"
  | "NEUTRAL_CONVICTION"
  | "MODERATE_CONVICTION"
  | "HIGH_CONVICTION"
  | "REVERSAL_WATCH"
  | string;

export interface MarketStateCandle {
  time: number;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface MarketStateVolume {
  time: number;
  timestamp: string;
  value: number;
  color?: string;
}

export interface MarketStateRow {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  synthesis_state?: string | null;
  auction_state?: string | null;
  cognition_state?: string | null;
  probabilistic_regime?: string | null;
  reinforcement_state?: string | null;
  belief_state?: string | null;
  market_state?: string | null;
  market_bias?: string | null;
  market_state_confidence?: number | null;
  trading_state?: string | null;
  confidence_band?: string | null;
  entry_eligible?: boolean | null;
  human_message?: string | null;
  execution_posture?: string | null;
  rule_id?: string | null;
  rule_description?: string | null;
  trader_read?: string | null;
  chart_read?: string | null;
  transition_type?: string | null;
  transition_class?: string | null;
  alignment_score?: number | null;
  persistence_score?: number | null;
  structural_rank?: number | null;
  conviction_probability?: number | null;
  conviction_strength?: number | null;
  absorption_probability?: number | null;
  distribution_probability?: number | null;
  location_bias?: string | null;
  trigger_event?: string | null;
  unfinished_auction?: string | boolean | null;
  effort_result_state?: string | null;
  localized_behavior?: string | null;
  decision_action?: string | null;
  trade_decision?: DecisionState | string | null;
  cognitive_state?: CognitiveState | string | null;
  decision_state?: DecisionState | string | null;
  decision_reason?: string | null;
  setup_id?: string | null;
  setup_direction?: string | null;
  setup_status?: string | null;
  setup_start_timestamp?: string | null;
  setup_end_timestamp?: string | null;
  setup_age_bars?: number | null;
  entry_price?: number | null;
  max_favorable_move?: number | null;
  max_adverse_move?: number | null;
  exit_reason?: string | null;
  regime_id?: string | null;
  regime_start_timestamp?: string | null;
  regime_age_bars?: number | null;
  regime_transition?: boolean | null;
  previous_regime?: string | null;
  new_regime?: string | null;
  is_entry_event?: boolean | null;
  is_exit_event?: boolean | null;
  is_regime_change_event?: boolean | null;
  is_warning_event?: boolean | null;
  confidence_explanation?: ConfidenceExplanation | null;
}

export interface ConfidenceExplanation {
  level: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
  score?: number | null;
  summary: string;
  drivers: string[];
  suppressors: string[];
  source_fields: Record<string, unknown>;
}

export interface CognitiveRegime {
  regime_id: string;
  start_timestamp: string;
  end_timestamp: string;
  duration_bars: number;
  primary_state: string;
  probabilistic_regime?: string | null;
  location_bias?: string | null;
  avg_conviction?: number | null;
  avg_alignment?: number | null;
  avg_persistence?: number | null;
  dominant_decision_state?: string | null;
  transition_reason?: string | null;
  previous_regime?: string | null;
  new_regime?: string | null;
}

/** Engine-level market_state segments (from market_state_memory), not cognitive composite regimes. */
export interface MarketStateRegime {
  regime_id: string;
  market_state: string;
  start_timestamp: string;
  end_timestamp: string;
  duration_bars: number;
  avg_confidence?: number | null;
  market_state_confidence?: number | null;
  rule_id?: string | null;
  previous_market_state?: string | null;
  is_active: boolean;
  confidence_level?: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
}

/** Engine-level market_state transition at a bar where state changed. */
export interface MarketStateTransition {
  transition_id: string;
  timestamp: string;
  from_market_state: string;
  to_market_state: string;
  previous_market_state?: string | null;
  market_state: string;
  rule_id?: string | null;
  rule_description?: string | null;
  transition_type?: string | null;
  transition_class?: string | null;
  confidence_before?: number | null;
  confidence_after?: number | null;
  market_state_confidence?: number | null;
  confidence_delta?: number | null;
  trader_read?: string | null;
  transition_reason?: string | null;
  reason?: string | null;
  confidence_explanation?: ConfidenceExplanation | null;
}

/** Directional context episode from trading_state_memory (LONG_CONTEXT / SHORT_CONTEXT). */
export interface DirectionalContextEpisode {
  episode_id: string;
  direction: "LONG" | "SHORT";
  context_state: "LONG_CONTEXT" | "SHORT_CONTEXT";
  start_timestamp: string;
  end_timestamp: string;
  duration_bars: number;
  is_active: boolean;
  source: "trading_state_memory" | "derived_heuristic";
  start_price?: number | null;
  end_price?: number | null;
  price_change?: number | null;
  price_change_pct?: number | null;
  avg_confidence?: number | null;
  max_confidence?: number | null;
  entry_eligible?: boolean | null;
  setup_status?: string | null;
  human_message: string;
}

export interface DecisionMarker {
  time: number;
  timestamp: string;
  decision_action?: string | null;
  trade_decision?: DecisionState | string | null;
  decision_state: DecisionState | string;
  decision_reason?: string | null;
  setup_id?: string | null;
  direction?: string | null;
  setup_direction?: string | null;
  setup_status?: string | null;
  setup_age_bars?: number | null;
  exit_reason?: string | null;
  cognitive_state?: CognitiveState | string | null;
  cognition_state?: string | null;
  market_state?: string | null;
  trading_state?: string | null;
  confidence_band?: string | null;
  market_state_confidence?: number | null;
  synthesis_state?: string | null;
  probabilistic_regime?: string | null;
  location_bias?: string | null;
  alignment_score?: number | null;
  persistence_score?: number | null;
  conviction_probability?: number | null;
  absorption_probability?: number | null;
  distribution_probability?: number | null;
  price?: number | null;
}

export interface SetupLifecycle {
  setup_id: string;
  setup_direction: string;
  start_timestamp: string;
  end_timestamp?: string | null;
  duration_bars?: number | null;
  entry_price?: number | null;
  exit_price?: number | null;
  max_favorable_move?: number | null;
  max_adverse_move?: number | null;
  exit_reason?: string | null;
}

export interface TimelineEvent {
  time: string;
  event_type: string;
  decision?: string | null;
  direction?: string | null;
  regime?: string | null;
  setup_id?: string | null;
  from_state?: string | null;
  to_state?: string | null;
  reason?: string | null;
  conviction?: number | null;
  alignment?: number | null;
  persistence?: number | null;
  location_bias?: string | null;
  bars_active?: number | null;
  bars_since_previous_event?: number | null;
  rule_id?: string | null;
  rule_description?: string | null;
  transition_type?: string | null;
  transition_class?: string | null;
  confidence_before?: number | null;
  confidence_after?: number | null;
  confidence_delta?: number | null;
  source?: string | null;
}

export interface RuntimeHealth {
  feed_latest_timestamp?: string | null;
  runtime_latest_timestamp?: string | null;
  market_state_latest_timestamp?: string | null;
  feed_age_seconds?: number | null;
  runtime_age_seconds?: number | null;
  failed_engine_count: number;
  active_engine_count: number;
  is_feed_stale: boolean;
  is_runtime_stale: boolean;
  warnings: string[];
}

export interface CurrentMarketState {
  current_market_phase?: string | null;
  active_cognitive_regime?: string | null;
  active_cognitive_state?: CognitiveState | string | null;
  active_decision?: string | null;
  setup_status?: string | null;
  setup_id?: string | null;
  setup_age?: number | null;
  entry_timestamp?: string | null;
  exit_or_invalidation_condition?: string | null;
  belief_state?: string | null;
  conviction?: number | null;
  alignment?: number | null;
  persistence?: number | null;
  location_bias?: string | null;
  absorption_probability?: number | null;
  distribution_probability?: number | null;
  last_regime_change?: string | null;
  last_decision_change?: string | null;
  active_market_state_regime?: MarketStateRegime | null;
  latest_market_state_transition?: MarketStateTransition | null;
  active_directional_context_episode?: DirectionalContextEpisode | null;
  confidence_explanation?: ConfidenceExplanation | null;
  runtime_health?: RuntimeHealth;
  feed_freshness?: string | null;
  interpretation?: string[];
}

export interface SourceStatus {
  file: string;
  path: string;
  exists: boolean;
  row_count: number;
  latest_timestamp?: string | null;
  mtime?: string | null;
  age_seconds?: number | null;
  stale: boolean;
  missing_columns?: string[];
  read_error?: string | null;
}

export interface MarketStateSnapshot {
  generated_at: string;
  timeframe: Timeframe;
  limit: number;
  range?: string | null;
  mode: ViewMode | string;
  normalized_columns: string[];
  dashboard_market_state_df: MarketStateRow[];
  candles: MarketStateCandle[];
  volume: MarketStateVolume[];
  regimes: CognitiveRegime[];
  market_state_regimes: MarketStateRegime[];
  market_state_transitions?: MarketStateTransition[];
  directional_context_episodes?: DirectionalContextEpisode[];
  decisions: DecisionMarker[];
  setup_lifecycles: SetupLifecycle[];
  timeline_events: TimelineEvent[];
  current_state: CurrentMarketState;
  runtime_health: RuntimeHealth;
  source_status: Record<string, SourceStatus>;
  warnings: string[];
  time_range?: { start: string; end: string } | null;
  bar_count: number;
  bar_limit: number | null;
  bars: MarketStateRow[];
}

export interface MarketStateQuery {
  timeframe?: Timeframe;
  limit?: number;
  range?: HistoryRange | string;
  mode?: ViewMode;
  from?: string;
  to?: string;
}
