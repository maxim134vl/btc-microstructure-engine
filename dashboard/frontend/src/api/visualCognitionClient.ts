import type { VisualCognitionSnapshot } from "../types/visualCognition";

const API = "/api/v1";

export async function fetchVisualCognitionSnapshot(params?: {
  lookbackDays?: number;
  maxBars?: number;
  timestamp?: string;
  eventIndex?: number;
}): Promise<VisualCognitionSnapshot> {
  const search = new URLSearchParams();
  if (params?.lookbackDays) search.set("lookback_days", String(params.lookbackDays));
  if (params?.maxBars) search.set("max_bars", String(params.maxBars));
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
