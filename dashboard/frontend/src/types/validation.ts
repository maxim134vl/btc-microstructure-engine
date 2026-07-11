export interface ValidationStageSnapshot {
  purpose: string;
  auto_run_due: boolean;
  latest_run?: ValidationRun | null;
  validation_targets: string[];
  verdict_types: string[];
}

export interface ConformanceSnapshot extends ValidationStageSnapshot {
  cognition_health?: string | null;
  health_emoji?: string | null;
}

export interface EvolutionTrustSummary {
  current_trust_level?: string | null;
  stability_score?: number | null;
  overconfident_rate?: number | null;
  validated_records?: number;
  toxic_records?: number;
  failed_records?: number;
  stable_vs_toxic_ratio?: number | null;
  trustworthy_share?: number | null;
}

export interface EvolutionComparisonRow {
  metric?: string;
  key?: string;
  label: string;
  current?: number;
  previous?: number;
  rolling_average?: number | null;
  delta_vs_previous?: number | null;
  delta_vs_baseline?: number | null;
  trend?: string;
}

export interface EvolutionSnapshot {
  purpose: string;
  auto_run_due: boolean;
  latest_run?: EvolutionRun | null;
  history_length?: number;
  trust?: EvolutionTrustSummary;
  regression?: {
    verdict?: string;
    improvement_count?: number;
    regression_count?: number;
    events?: { type: string; note?: string }[];
  } | null;
  comparison?: {
    status?: string;
    previous_cycle_id?: string | null;
    comparisons?: EvolutionComparisonRow[];
    rolling_average?: Record<string, number | null>;
  } | null;
  evolution?: {
    trends?: Record<string, string>;
    cycle_count?: number;
  } | null;
  calibration_evolution?: { note?: string; signal?: string } | null;
  ontology_evolution?: { signal?: string; note?: string } | null;
  dataset_totals?: Record<string, number>;
  dataset_buckets?: string[];
}

export interface EvolutionRun {
  run_id: string;
  cycle_id?: string;
  generated_at: string;
  status: string;
  trust?: EvolutionTrustSummary & { trust_level?: string };
  regression?: EvolutionSnapshot["regression"];
  comparison?: EvolutionSnapshot["comparison"];
  evolution?: EvolutionSnapshot["evolution"];
  report_markdown?: string;
  history_length?: number;
}

export interface IntermediateCognitionRow {
  timestamp?: string;
  intermediate_state?: string;
  confidence?: number;
  severity?: string;
  anchor_stage2_state?: string;
  anchor_timestamp?: string;
  reason?: string;
}

export interface IntermediateCognitionSnapshot {
  purpose: string;
  latest?: IntermediateCognitionRow;
  timeline: IntermediateCognitionRow[];
  distribution: Record<string, number>;
  event_count: number;
  linked_stage2_anchor?: string;
  anchor_timestamp?: string;
}

export interface Stage2_5Comparison {
  status: string;
  run_id?: string;
  summary?: ValidationSummary;
  comparisons?: {
    timestamp?: string;
    intermediate_state?: string;
    interpretation?: string;
    observed_outcome?: string;
    verdict?: string;
    confirmation_horizon?: number | null;
  }[];
  narrative_confirmation_rate?: number;
  by_state?: Record<string, ValidationSummary>;
}

export interface Stage2_5CalibrationState {
  status?: string;
  event_count?: number;
  metrics?: Record<string, number | null>;
  trends?: Record<string, { current?: number | null; previous?: number | null; trend?: string }>;
}

export interface Stage2_5CalibrationSnapshot {
  purpose: string;
  auto_run_due?: boolean;
  latest_run?: {
    run_id?: string;
    generated_at?: string;
    overall_status?: string;
    overall_metrics?: Record<string, number | null>;
    overall_trends?: Record<string, { current?: number | null; previous?: number | null; trend?: string }>;
    states?: Record<string, Stage2_5CalibrationState>;
    report_markdown?: string;
    status?: string;
  } | null;
  live_assessment?: {
    overall_status?: string;
    overall_metrics?: Record<string, number | null>;
    overall_trends?: Record<string, { current?: number | null; previous?: number | null; trend?: string }>;
    states?: Record<string, Stage2_5CalibrationState>;
  };
  weekly_history?: {
    run_id?: string;
    generated_at?: string;
    overall_status?: string;
    states?: Record<string, string>;
    overall_metrics?: Record<string, number | null>;
  }[];
  status_definitions?: string[];
}

export interface ValidationSnapshot {
  status?: "OK" | "UNAVAILABLE";
  message?: string;
  framework: string;
  stage1: ValidationStageSnapshot;
  stage2: ValidationStageSnapshot;
  stage2_5: ValidationStageSnapshot;
  stage2_5_calibration?: Stage2_5CalibrationSnapshot;
  integrated: ValidationStageSnapshot;
  conformance: ConformanceSnapshot;
  evolution: EvolutionSnapshot;
  intermediate_cognition?: IntermediateCognitionSnapshot;
  exports: {
    reports_dir: string;
    exports_dir: string;
    visuals_dir: string;
    conformance_reports_dir?: string;
    memory_reports_dir?: string;
    memory_exports_dir?: string;
    memory_datasets_dir?: string;
  };
}

export interface ValidationRun {
  run_id: string;
  generated_at: string;
  status: string;
  summary?: ValidationSummary;
  report_markdown?: string;
  export_json?: string;
  export_csv?: string;
  visuals?: string[];
}

export interface ValidationSummary {
  event_count: number;
  confirmed_rate?: number;
  false_positive_rate?: number;
  climax_confirmation_rate?: number;
  stopping_quality_rate?: number;
  initiative_accuracy?: number;
  market_structure_coherence?: number;
  reasoning_accuracy?: number;
  probabilistic_calibration_quality?: number;
  contradiction_frequency?: number;
  synthesis_stability?: number;
  narrative_coherence?: number;
  confidence_drift?: number;
  regime_interpretation_accuracy?: number;
  transition_logic_quality?: number;
  overconfident_rate?: number;
  context_failure_rate?: number;
  fully_confirmed_rate?: number;
  cross_stage_alignment?: number;
  cognition_drift_frequency?: number;
  confidence_realism?: number;
  ontology_coherence?: number;
  market_confirmation_rate?: number;
  verdict_distribution: Record<string, number>;
  root_cause_distribution?: Record<string, number>;
  cognition_stability_score?: number;
  ontology_integrity_score?: number;
  calibration_health_score?: number;
  confidence_realism_score?: number;
  transition_stability_score?: number;
  contradiction_pressure_score?: number;
  drift_severity_score?: number;
  cognition_health?: string;
  failed_count?: number;
  metric_count?: number;
}

export interface ValidationReport {
  status: string;
  stage?: string;
  run_id?: string;
  summary?: ValidationSummary;
  markdown?: string | null;
  paths?: ValidationRun;
}

export interface StageComparison {
  status: string;
  stage1_summary?: ValidationSummary | null;
  stage2_summary?: ValidationSummary | null;
  integrated_summary?: ValidationSummary | null;
  stage1_run_id?: string | null;
  stage2_run_id?: string | null;
  integrated_run_id?: string | null;
  drift?: {
    health?: string;
    signals?: string[];
  } | null;
}

export interface EvolutionReport {
  status: string;
  run_id?: string;
  cycle_id?: string;
  trust?: EvolutionTrustSummary & { trust_level?: string };
  regression?: EvolutionSnapshot["regression"];
  evolution?: EvolutionSnapshot["evolution"];
  markdown?: string | null;
  paths?: EvolutionRun;
}
