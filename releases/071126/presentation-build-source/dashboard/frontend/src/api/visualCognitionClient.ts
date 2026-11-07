import type { VisualCognitionSnapshot, Stage1EventMapSnapshot } from "../types/visualCognition";

const API = "/api/v1";

export async function fetchVisualCognitionSnapshot(params?: {
  timestamp?: string;
  eventIndex?: number;
}): Promise<VisualCognitionSnapshot> {
  const search = new URLSearchParams();
  if (params?.timestamp) search.set("timestamp", params.timestamp);
  if (params?.eventIndex != null) search.set("event_index", String(params.eventIndex));
  const query = search.toString();
  const response = await fetch(`${API}/visual-cognition/snapshot${query ? `?${query}` : ""}`);
  if (!response.ok) throw new Error(`visual cognition snapshot ${response.status}`);
  return response.json();
}

export async function fetchVisualCognitionEvents(lookbackDays = 7): Promise<{ events: VisualCognitionSnapshot["timeline"] }> {
  const response = await fetch(`${API}/visual-cognition/events?lookback_days=${lookbackDays}`);
  if (!response.ok) throw new Error(`visual cognition events ${response.status}`);
  return response.json();
}

export async function fetchStage1EventMap(): Promise<Stage1EventMapSnapshot> {
  const response = await fetch(`${API}/visual-cognition/stage1-event-map`);
  if (!response.ok) throw new Error(`stage1 event map ${response.status}`);
  return response.json();
}
