import type { ManualAnchor, ManualEventLink, ManualReaction } from "./manualAnnotations";
import type { ReviewCandleBar, Stage1EventClass, WindowOverlayEvent } from "./eventReview";

export type CognitiveEventClass =
  | Stage1EventClass
  | "MISSED_EVENT";

export const COGNITIVE_EVENT_CLASSES: CognitiveEventClass[] = [
  "BUYING_CLIMAX",
  "SELLING_CLIMAX",
  "STOPPING_VOLUME",
  "HIGH_AVERAGE_VOLUME",
  "MISSED_EVENT",
];

export const DEFAULT_COGNITIVE_CLASS_SELECTION: Record<CognitiveEventClass, boolean> = {
  BUYING_CLIMAX: true,
  SELLING_CLIMAX: true,
  STOPPING_VOLUME: true,
  HIGH_AVERAGE_VOLUME: false,
  MISSED_EVENT: true,
};

export const COGNITIVE_EVENT_COLORS: Record<CognitiveEventClass, string> = {
  BUYING_CLIMAX: "#22c55e",
  SELLING_CLIMAX: "#ef4444",
  STOPPING_VOLUME: "#eab308",
  HIGH_AVERAGE_VOLUME: "#06b6d4",
  MISSED_EVENT: "#a855f7",
};

export interface CognitiveFeatureMeta {
  name: string;
  label: string;
  dtype: "numeric" | "boolean" | "categorical";
  group_id?: string;
}

export interface CognitiveFeatureGroup {
  id: string;
  label: string;
  features: string[];
}

export interface CognitiveReviewEvent {
  annotation_id: string;
  timestamp: string;
  bar_index: number | null;
  event_class: CognitiveEventClass;
  display_class: string;
  review_type: "MODEL_EVENT" | "MISSED_EVENT";
  review_status: string;
  human_event_class: string | null;
  review_note_ru: string;
  is_key_event: boolean;
  open: number | string | null;
  high: number | string | null;
  low: number | string | null;
  close: number | string | null;
  volume: number | string | null;
  delta: number | string | null;
  spread: number | string | null;
  close_position: number | string | null;
  volume_percentile: number | string | null;
  delta_percentile: number | string | null;
  effort_result_state: string | null;
  auction_regime: string | null;
}

export interface CognitiveComparePreset {
  label: string;
  event_class: CognitiveEventClass;
  annotation_ids: string[];
}

export interface CognitiveReviewBootstrap {
  status: string;
  events: CognitiveReviewEvent[];
  counts: Record<CognitiveEventClass, number>;
  total_events: number;
  supported_classes: CognitiveEventClass[];
  cognitive_features: CognitiveFeatureMeta[];
  feature_groups: CognitiveFeatureGroup[];
  dynamics_priority_features: string[];
  anchors: ManualAnchor[];
  links: ManualEventLink[];
  reactions: ManualReaction[];
  dynamics_before_bars: number;
  dynamics_after_bars: number;
  compare_presets: CognitiveComparePreset[];
}

export interface CognitiveReviewContext {
  status: string;
  timeframe: string;
  bar_index: number;
  event_index: number | null;
  window_start: number;
  window_end: number;
  bars: ReviewCandleBar[];
  volume_location_markers?: import("./eventReview").VolumeLocationMarker[];
  window_events?: WindowOverlayEvent[];
  zoom_level?: string;
}

export interface CognitiveSnapshot {
  status: string;
  bar_index: number;
  timestamp: string;
  features: Record<string, unknown>;
}

export interface CognitiveDynamicsPoint {
  bar_offset: number;
  value: number | string | boolean | null;
}

export interface CognitiveDynamics {
  status: string;
  bar_index: number;
  event_bar_offset: number;
  before_bars: number;
  after_bars: number;
  series: Record<string, CognitiveDynamicsPoint[]>;
}

export interface CognitiveCompareTrajectoryPoint {
  bar_offset: number;
  mean: number;
  count: number;
}

export interface CognitiveCompareGroup {
  label: string;
  event_count: number;
  trajectories: Record<string, CognitiveCompareTrajectoryPoint[]>;
}

export interface CognitiveCompareResult {
  status: string;
  before_bars: number;
  after_bars: number;
  features: string[];
  groups: CognitiveCompareGroup[];
}

export function cognitiveEventKey(event: Pick<CognitiveReviewEvent, "annotation_id">): string {
  return event.annotation_id;
}

/** Coerce bootstrap / prop feature metadata to a safe array (avoids crash on stale bundles or malformed API). */
export function asFeatureMeta(value: unknown): CognitiveFeatureMeta[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is CognitiveFeatureMeta =>
      item != null &&
      typeof item === "object" &&
      typeof (item as CognitiveFeatureMeta).name === "string" &&
      typeof (item as CognitiveFeatureMeta).label === "string",
  );
}

export function asFeatureGroups(value: unknown): CognitiveFeatureGroup[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is CognitiveFeatureGroup =>
      item != null &&
      typeof item === "object" &&
      typeof (item as CognitiveFeatureGroup).id === "string" &&
      typeof (item as CognitiveFeatureGroup).label === "string" &&
      Array.isArray((item as CognitiveFeatureGroup).features),
  );
}

export function normalizeCognitiveBootstrap(payload: CognitiveReviewBootstrap): CognitiveReviewBootstrap {
  return {
    ...payload,
    events: Array.isArray(payload.events) ? payload.events : [],
    cognitive_features: asFeatureMeta(payload.cognitive_features),
    feature_groups: asFeatureGroups(payload.feature_groups),
    dynamics_priority_features: Array.isArray(payload.dynamics_priority_features)
      ? payload.dynamics_priority_features
      : [],
    compare_presets: Array.isArray(payload.compare_presets) ? payload.compare_presets : [],
  };
}
