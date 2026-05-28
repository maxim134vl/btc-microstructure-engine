export interface CognitionBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  delta?: number | null;
  initiative?: string;
  behaviors?: string[];
  primary_behavior?: string;
  overlay_color?: string;
  continuation_health?: number;
  confidence?: number;
}

export interface MtfSection {
  timeframe: string;
  bars: CognitionBar[];
  bar_count?: number;
  cursor_index?: number | null;
  event_markers?: CognitionBar[];
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
  ontology_transitions?: { timestamp: string; label: string; transition_state?: string }[];
  interpretation?: string | null;
  colors?: Record<string, string>;
  meta?: Record<string, number>;
}

export const COGNITION_COLOR_LEGEND: { key: string; label: string; color: string }[] = [
  { key: "buyer_initiative", label: "Buyer initiative", color: "#22c55e" },
  { key: "seller_initiative", label: "Seller initiative", color: "#ef4444" },
  { key: "instability", label: "Instability / deterioration", color: "#eab308" },
  { key: "absorption", label: "Absorption / compression", color: "#06b6d4" },
  { key: "climax", label: "Climax / exhaustion", color: "#f97316" },
  { key: "contradiction", label: "Contradiction / conflict", color: "#a855f7" },
  { key: "neutral_rotation", label: "Neutral rotation", color: "#f8fafc" },
  { key: "dormant", label: "Dormant / low confidence", color: "#64748b" },
];
