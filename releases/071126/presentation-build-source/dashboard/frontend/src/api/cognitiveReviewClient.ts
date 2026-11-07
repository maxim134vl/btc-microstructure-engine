import type {
  CognitiveCompareResult,
  CognitiveDynamics,
  CognitiveReviewBootstrap,
  CognitiveReviewContext,
  CognitiveSnapshot,
  CognitiveEventClass,
} from "../types/cognitiveReview";
import { normalizeCognitiveBootstrap } from "../types/cognitiveReview";

const API = "/api/v1";

export async function fetchCognitiveReviewBootstrap(): Promise<CognitiveReviewBootstrap> {
  const response = await fetch(`${API}/cognitive-review/bootstrap`);
  if (!response.ok) throw new Error(`cognitive bootstrap ${response.status}`);
  const payload = (await response.json()) as CognitiveReviewBootstrap;
  return normalizeCognitiveBootstrap(payload);
}

export async function fetchCognitiveReviewContext(
  barIndex: number,
  options: {
    zoomLevel?: string;
    eventClass?: string;
    overlayClasses?: CognitiveEventClass[];
    primaryTimestamp?: string;
  },
  signal?: AbortSignal,
): Promise<CognitiveReviewContext> {
  const params = new URLSearchParams({
    bar_index: String(barIndex),
    zoom_level: options.zoomLevel ?? "FULL",
  });
  if (options.eventClass) params.set("event_class", options.eventClass);
  if (options.overlayClasses?.length) {
    params.set("overlay_classes", options.overlayClasses.join(","));
  }
  if (options.primaryTimestamp) params.set("primary_timestamp", options.primaryTimestamp);
  const response = await fetch(`${API}/cognitive-review/context?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`cognitive context ${response.status}`);
  return response.json();
}

export async function fetchCognitiveSnapshot(
  options: { barIndex?: number; timestamp?: string },
  signal?: AbortSignal,
): Promise<CognitiveSnapshot> {
  const params = new URLSearchParams();
  if (options.barIndex != null) params.set("bar_index", String(options.barIndex));
  if (options.timestamp) params.set("timestamp", options.timestamp);
  const response = await fetch(`${API}/cognitive-review/snapshot?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`cognitive snapshot ${response.status}`);
  return response.json();
}

export async function fetchCognitiveDynamics(
  options: { barIndex?: number; timestamp?: string; features?: string[] },
  signal?: AbortSignal,
): Promise<CognitiveDynamics> {
  const params = new URLSearchParams();
  if (options.barIndex != null) params.set("bar_index", String(options.barIndex));
  if (options.timestamp) params.set("timestamp", options.timestamp);
  if (options.features?.length) params.set("features", options.features.join(","));
  const response = await fetch(`${API}/cognitive-review/dynamics?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`cognitive dynamics ${response.status}`);
  return response.json();
}

export async function postCognitiveCompare(payload: {
  annotation_ids?: string[];
  groups?: Array<{ label: string; annotation_ids: string[] }>;
  features?: string[];
}): Promise<CognitiveCompareResult> {
  const response = await fetch(`${API}/cognitive-review/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`cognitive compare ${response.status}`);
  return response.json();
}
