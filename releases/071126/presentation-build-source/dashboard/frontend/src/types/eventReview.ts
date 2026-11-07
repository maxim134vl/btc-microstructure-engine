export type Stage1EventClass =
  | "BUYING_CLIMAX"
  | "SELLING_CLIMAX"
  | "STOPPING_VOLUME"
  | "HIGH_AVERAGE_VOLUME";

export type ReviewStatus = "GOOD" | "BAD" | "UNCLEAR";

export const STAGE1_EVENT_CLASSES: Stage1EventClass[] = [
  "BUYING_CLIMAX",
  "SELLING_CLIMAX",
  "STOPPING_VOLUME",
  "HIGH_AVERAGE_VOLUME",
];

export const DEFAULT_CLASS_SELECTION: Record<Stage1EventClass, boolean> = {
  BUYING_CLIMAX: true,
  SELLING_CLIMAX: true,
  STOPPING_VOLUME: true,
  HIGH_AVERAGE_VOLUME: false,
};

export interface Stage1AuditEvent {
  timestamp: string;
  bar_index: number | null;
  event_class: Stage1EventClass;
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

export interface Stage1ReviewBootstrap {
  status: string;
  events: Stage1AuditEvent[];
  reviews: Record<string, ReviewStatus>;
  counts: Record<Stage1EventClass, number>;
  total_events: number;
  supported_classes: Stage1EventClass[];
}

export interface ReviewCandleBar {
  index: number;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface VolumeLocationMarker {
  price: number;
  zone_low?: number | null;
  zone_high?: number | null;
  event_class: Stage1EventClass | "ABSORPTION" | "HIGH_VARIANCE_VOLUME" | string;
}

export interface WindowOverlayEvent {
  timestamp: string;
  event_class: Stage1EventClass;
  bar_index_in_window: number;
  volume_location_markers: VolumeLocationMarker[];
  is_primary: boolean;
}

export interface Stage1ReviewContext {
  status: string;
  timeframe: string;
  bar_index: number;
  event_index: number | null;
  window_start: number;
  window_end: number;
  bars: ReviewCandleBar[];
  volume_location_markers?: VolumeLocationMarker[];
  window_events?: WindowOverlayEvent[];
}

export const EVENT_CLASS_COLORS: Record<Stage1EventClass, string> = {
  BUYING_CLIMAX: "#22c55e",
  SELLING_CLIMAX: "#ef4444",
  STOPPING_VOLUME: "#eab308",
  HIGH_AVERAGE_VOLUME: "#06b6d4",
};

export function reviewKey(timestamp: string, eventClass: string): string {
  return `${timestamp}|${eventClass}`;
}

export function displayRaw(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}
