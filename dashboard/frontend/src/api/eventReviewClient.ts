import type {
  ReviewStatus,
  Stage1AuditEvent,
  Stage1EventClass,
  Stage1ReviewBootstrap,
  Stage1ReviewContext,
} from "../types/eventReview";

const API = "/api/v1";

export async function fetchStage1ReviewBootstrap(): Promise<Stage1ReviewBootstrap> {
  const response = await fetch(`${API}/stage1-review/bootstrap`);
  if (!response.ok) throw new Error(`stage1 review bootstrap ${response.status}`);
  return response.json();
}

export async function fetchStage1ReviewContext(
  barIndex: number,
  eventClass: string,
  options?: {
    overlayClasses?: Stage1EventClass[];
    primaryTimestamp?: string;
  },
  signal?: AbortSignal,
): Promise<Stage1ReviewContext> {
  const params = new URLSearchParams({
    bar_index: String(barIndex),
    event_class: eventClass,
  });
  if (options?.overlayClasses?.length) {
    params.set("overlay_classes", options.overlayClasses.join(","));
  }
  if (options?.primaryTimestamp) {
    params.set("primary_timestamp", options.primaryTimestamp);
  }
  const response = await fetch(`${API}/stage1-review/context?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`stage1 review context ${response.status}`);
  return response.json();
}

export async function submitStage1Review(event: Stage1AuditEvent, reviewStatus: ReviewStatus): Promise<void> {
  const params = new URLSearchParams({
    timestamp: event.timestamp,
    event_class: event.event_class,
    review_status: reviewStatus,
  });
  const response = await fetch(`${API}/stage1-review/review?${params.toString()}`, { method: "POST" });
  if (!response.ok) throw new Error(`stage1 review submit ${response.status}`);
}
