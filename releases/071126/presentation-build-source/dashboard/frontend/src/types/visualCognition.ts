export type VolumeClassLabel =
  | "BUYING_CLIMAX"
  | "SELLING_CLIMAX"
  | "STOPPING_VOLUME"
  | "HIGH_VARIANCE_VOLUME"
  | "ABSORPTION"
  | "NORMAL"
  | "LOW_SMALL";

export type MajorVolumeMarker = "BUYING_CLIMAX" | "SELLING_CLIMAX" | "STOPPING_VOLUME";

export interface VolumeLocationMarker {
  event: VolumeClassLabel;
  price: number;
  zone_low?: number;
  zone_high?: number;
  color?: string;
}

export interface CognitionBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  delta?: number | null;
  volume_class_raw?: string | null;
  volume_class_label?: VolumeClassLabel;
  volume_bar_color?: string;
  volume_events?: VolumeClassLabel[];
  major_volume_markers?: MajorVolumeMarker[];
  volume_location_markers?: VolumeLocationMarker[];
  primary_volume_event?: MajorVolumeMarker | null;
  marker_color?: string;
}

export interface VolumeMarker {
  timestamp: string;
  bar_index: number;
  volume_events: VolumeClassLabel[];
  primary_volume_event?: MajorVolumeMarker | null;
  marker_color?: string;
  high?: number;
  low?: number;
}

export interface ChartAnnotation {
  timestamp: string;
  bar_index: number;
  label: string;
  source: "stage2" | "stage2_5" | "stage1_benchmark" | string;
  color?: string;
  verdict?: string;
}

export interface MtfSection {
  timeframe: string;
  bars: CognitionBar[];
  bar_count?: number;
  cursor_index?: number | null;
  marker_counts?: Record<string, number>;
  volume_markers?: VolumeMarker[];
  annotations?: ChartAnnotation[];
  start?: string;
  end?: string;
}

export interface CognitionFlowStep {
  step: number;
  label: string;
  detail: string;
  behavior?: string | null;
  timeframe?: string;
}

export interface PropagationState {
  timeframe: string;
  timestamp?: string;
  initiative?: string;
  behaviors?: string[];
  continuation_health?: number;
  synthesis_state?: string;
  trigger_event?: string;
  climax_state?: string;
  status?: string;
}

export interface TimelineEvent {
  timeline_index?: number;
  event_index?: number;
  timestamp: string;
  type?: string;
  label?: string;
  verdict?: string;
  source?: string;
  behaviors?: string[];
  confidence?: number;
  severity?: string;
  anchor_stage2_state?: string;
  overlay_color?: string;
}

export interface VisualCognitionSnapshot {
  status: string;
  message?: string;
  cursor_timestamp?: string;
  event_index?: number | null;
  timeline_index?: number | null;
  lookback_days?: number;
  timeframes?: string[];
  mtf_map: Record<string, MtfSection>;
  cursor_indices?: Record<string, number | null>;
  cognition_flow?: CognitionFlowStep[];
  propagation?: {
    chain?: string[];
    states?: PropagationState[];
    inheritance?: { from: string; to: string; signal: string; parent_health: number; child_health: number }[];
    summary?: string;
  };
  timeline?: TimelineEvent[];
  interpretation?: string | null;
  colors?: Record<string, string>;
  candle_colors?: Record<string, string>;
  volume_class_colors?: Record<string, string>;
  volume_event_colors?: Record<string, string>;
  annotation_colors?: Record<string, string>;
  meta?: Record<string, number | string | boolean | string[]>;
  stage1_stats?: Record<string, { bar_count: number; marker_counts: Record<string, number> }>;
  validation?: Record<string, unknown>;
}

export const VOLUME_CLASS_LEGEND: { key: VolumeClassLabel; label: string; color: string }[] = [
  { key: "SELLING_CLIMAX", label: "SELLING_CLIMAX", color: "#ef4444" },
  { key: "BUYING_CLIMAX", label: "BUYING_CLIMAX", color: "#22c55e" },
  { key: "STOPPING_VOLUME", label: "STOPPING_VOLUME", color: "#eab308" },
  { key: "HIGH_VARIANCE_VOLUME", label: "HIGH_AVERAGE_VOLUME", color: "#06b6d4" },
  { key: "ABSORPTION", label: "ABSORPTION", color: "#a855f7" },
];

export const ANNOTATION_LEGEND: { key: string; label: string; color: string }[] = [
  { key: "stage2", label: "Stage 2 narrative", color: "#38bdf8" },
];

/** @deprecated use VOLUME_CLASS_LEGEND */
export const VOLUME_EVENT_LEGEND = VOLUME_CLASS_LEGEND;

export interface Stage1EventMapBar {
  bar_index: number;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  volume_class_raw?: string;
}

export interface Stage1EventMapEvent {
  bar_index: number;
  timestamp: string;
  volume_class: string;
  event: VolumeClassLabel;
  price: number;
  zone_low?: number;
  zone_high?: number;
  color?: string;
}

export interface Stage1EventMapSummary {
  climax: number;
  stopping: number;
  high_average: number;
  low_small?: number;
  total_bars: number;
  total_markers: number;
  climax_buying?: number;
  climax_selling?: number;
}

export interface Stage1EventMapSnapshot {
  status: string;
  message?: string;
  bars: Stage1EventMapBar[];
  events: Stage1EventMapEvent[];
  summary: Stage1EventMapSummary;
  start?: string;
  end?: string;
}
