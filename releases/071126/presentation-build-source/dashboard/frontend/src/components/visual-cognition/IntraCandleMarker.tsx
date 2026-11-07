import type { VolumeClassLabel } from "../../types/visualCognition";

/** Stage 1 volume level colors — volume_class mapping only. */
export const EVENT_MARKER_COLORS: Record<VolumeClassLabel, string> = {
  BUYING_CLIMAX: "#22c55e",
  SELLING_CLIMAX: "#ef4444",
  STOPPING_VOLUME: "#eab308",
  HIGH_VARIANCE_VOLUME: "#06b6d4",
  ABSORPTION: "#a855f7",
  NORMAL: "#475569",
  LOW_SMALL: "#334155",
};

const CLASSIFIED: VolumeClassLabel[] = [
  "BUYING_CLIMAX",
  "SELLING_CLIMAX",
  "STOPPING_VOLUME",
  "HIGH_VARIANCE_VOLUME",
  "ABSORPTION",
];

export function isClassifiedEvent(event: string): event is VolumeClassLabel {
  return (CLASSIFIED as string[]).includes(event);
}

export function markerColorForEvent(event: VolumeClassLabel, override?: string): string {
  return override ?? EVENT_MARKER_COLORS[event] ?? EVENT_MARKER_COLORS.NORMAL;
}
