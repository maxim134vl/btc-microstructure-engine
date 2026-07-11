import type {
  AnnotationBootstrap,
  AnnotationContext,
  AnnotationReviewStatus,
  ManualEventLink,
  ReviewType,
  ZoomLevel,
} from "../types/manualAnnotations";
import type { Stage1EventClass } from "../types/eventReview";

const API = "/api/v1";

export async function fetchAnnotationBootstrap(): Promise<AnnotationBootstrap> {
  const response = await fetch(`${API}/stage1-annotations/bootstrap`);
  if (!response.ok) throw new Error(`annotation bootstrap ${response.status}`);
  return response.json();
}

export async function fetchAnnotationContext(
  barIndex: number,
  options: {
    zoomLevel: ZoomLevel;
    eventClass?: string;
    overlayClasses?: Stage1EventClass[];
    primaryTimestamp?: string;
  },
  signal?: AbortSignal,
): Promise<AnnotationContext> {
  const params = new URLSearchParams({
    bar_index: String(barIndex),
    zoom_level: options.zoomLevel,
  });
  if (options.eventClass) params.set("event_class", options.eventClass);
  if (options.overlayClasses?.length) {
    params.set("overlay_classes", options.overlayClasses.join(","));
  }
  if (options.primaryTimestamp) params.set("primary_timestamp", options.primaryTimestamp);
  const response = await fetch(`${API}/stage1-annotations/context?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`annotation context ${response.status}`);
  return response.json();
}

export async function saveManualAnnotation(payload: {
  timestamp: string;
  bar_index: number;
  review_type: ReviewType;
  model_event_class?: string | null;
  human_event_class?: string | null;
  review_status?: AnnotationReviewStatus | null;
  price_level?: number | null;
  review_note_ru?: string;
  zoom_level?: ZoomLevel;
  is_key_event?: boolean;
  annotation_id?: string | null;
}): Promise<{ annotation: import("../types/manualAnnotations").ManualAnnotation }> {
  const params = new URLSearchParams({
    timestamp: payload.timestamp,
    bar_index: String(payload.bar_index),
    review_type: payload.review_type,
    zoom_level: payload.zoom_level ?? "MICRO",
    is_key_event: String(payload.is_key_event ?? false),
  });
  if (payload.model_event_class) params.set("model_event_class", payload.model_event_class);
  if (payload.human_event_class) params.set("human_event_class", payload.human_event_class);
  if (payload.review_status) params.set("review_status", payload.review_status);
  if (payload.price_level != null) params.set("price_level", String(payload.price_level));
  if (payload.review_note_ru != null) params.set("review_note_ru", payload.review_note_ru);
  if (payload.annotation_id) params.set("annotation_id", payload.annotation_id);

  const response = await fetch(`${API}/stage1-annotations/save?${params.toString()}`, { method: "POST" });
  if (!response.ok) throw new Error(`annotation save ${response.status}`);
  return response.json();
}

export async function saveManualAnchor(payload: {
  anchor_type: "single" | "range";
  start_timestamp: string;
  end_timestamp: string;
  start_price: number;
  end_price: number;
  anchor_label_ru: string;
  anchor_note_ru?: string;
  anchor_id?: string;
}): Promise<{ anchor: import("../types/manualAnnotations").ManualAnchor }> {
  const params = new URLSearchParams({
    anchor_type: payload.anchor_type,
    start_timestamp: payload.start_timestamp,
    end_timestamp: payload.end_timestamp,
    start_price: String(payload.start_price),
    end_price: String(payload.end_price),
    anchor_label_ru: payload.anchor_label_ru,
  });
  if (payload.anchor_note_ru) params.set("anchor_note_ru", payload.anchor_note_ru);
  if (payload.anchor_id) params.set("anchor_id", payload.anchor_id);
  const response = await fetch(`${API}/stage1-annotations/anchor?${params.toString()}`, { method: "POST" });
  if (!response.ok) throw new Error(`anchor save ${response.status}`);
  return response.json();
}

export async function deleteManualAnnotation(annotationId: string): Promise<void> {
  const response = await fetch(
    `${API}/stage1-annotations/annotation/${encodeURIComponent(annotationId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(`annotation delete ${response.status}`);
}

export async function deleteManualAnchor(anchorId: string): Promise<void> {
  const response = await fetch(`${API}/stage1-annotations/anchor/${encodeURIComponent(anchorId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`anchor delete ${response.status}`);
}

export async function updateManualAnchor(payload: {
  anchor_id: string;
  anchor_label_ru?: string;
  anchor_note_ru?: string;
}): Promise<{ anchor: import("../types/manualAnnotations").ManualAnchor }> {
  const params = new URLSearchParams();
  if (payload.anchor_label_ru) params.set("anchor_label_ru", payload.anchor_label_ru);
  if (payload.anchor_note_ru != null) params.set("anchor_note_ru", payload.anchor_note_ru);
  const response = await fetch(
    `${API}/stage1-annotations/anchor/${encodeURIComponent(payload.anchor_id)}?${params.toString()}`,
    { method: "PATCH" },
  );
  if (!response.ok) throw new Error(`anchor update ${response.status}`);
  return response.json();
}

export async function deleteManualReaction(reactionId: string): Promise<void> {
  const response = await fetch(`${API}/stage1-annotations/reaction/${encodeURIComponent(reactionId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`reaction delete ${response.status}`);
}

export async function saveManualLink(payload: {
  source_anchor_id: string;
  target_anchor_id: string;
  relationship_type_ru: string;
  relationship_note_ru?: string;
  link_id?: string;
}): Promise<{ link: ManualEventLink }> {
  const params = new URLSearchParams({
    source_anchor_id: payload.source_anchor_id,
    target_anchor_id: payload.target_anchor_id,
    relationship_type_ru: payload.relationship_type_ru,
  });
  if (payload.relationship_note_ru) params.set("relationship_note_ru", payload.relationship_note_ru);
  if (payload.link_id) params.set("link_id", payload.link_id);
  const response = await fetch(`${API}/stage1-annotations/link?${params.toString()}`, { method: "POST" });
  if (!response.ok) throw new Error(`annotation link ${response.status}`);
  return response.json();
}

export async function deleteManualLink(linkId: string): Promise<void> {
  const response = await fetch(`${API}/stage1-annotations/link/${encodeURIComponent(linkId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`annotation link delete ${response.status}`);
}

export async function updateManualLinkLifecycle(payload: {
  link_id: string;
  link_status: string;
  completion_reason_ru?: string;
  completion_note_ru?: string;
}): Promise<{ link: ManualEventLink }> {
  const params = new URLSearchParams({
    link_status: payload.link_status,
  });
  if (payload.completion_reason_ru) params.set("completion_reason_ru", payload.completion_reason_ru);
  if (payload.completion_note_ru) params.set("completion_note_ru", payload.completion_note_ru);
  const response = await fetch(
    `${API}/stage1-annotations/link/${encodeURIComponent(payload.link_id)}/lifecycle?${params.toString()}`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`link lifecycle ${response.status}`);
  return response.json();
}

export async function saveManualReaction(payload: {
  start_timestamp: string;
  end_timestamp: string;
  start_price: number;
  end_price: number;
  return_pct: number;
  absolute_price_change: number;
  bars_count: number;
  max_favorable_excursion: number;
  max_adverse_excursion: number;
  reaction_significance: string;
  event_timestamp?: string;
  event_class?: string;
  note_ru?: string;
  reaction_id?: string;
}): Promise<{ reaction: import("../types/manualAnnotations").ManualReaction }> {
  const params = new URLSearchParams({
    start_timestamp: payload.start_timestamp,
    end_timestamp: payload.end_timestamp,
    start_price: String(payload.start_price),
    end_price: String(payload.end_price),
    return_pct: String(payload.return_pct),
    absolute_price_change: String(payload.absolute_price_change),
    bars_count: String(payload.bars_count),
    max_favorable_excursion: String(payload.max_favorable_excursion),
    max_adverse_excursion: String(payload.max_adverse_excursion),
    reaction_significance: payload.reaction_significance,
  });
  if (payload.event_timestamp) params.set("event_timestamp", payload.event_timestamp);
  if (payload.event_class) params.set("event_class", payload.event_class);
  if (payload.note_ru) params.set("note_ru", payload.note_ru);
  if (payload.reaction_id) params.set("reaction_id", payload.reaction_id);
  const response = await fetch(`${API}/stage1-annotations/reaction?${params.toString()}`, { method: "POST" });
  if (!response.ok) throw new Error(`reaction save ${response.status}`);
  return response.json();
}

export async function exportManualAnnotations(): Promise<{ paths: Record<string, string> }> {
  const response = await fetch(`${API}/stage1-annotations/export`, { method: "POST" });
  if (!response.ok) throw new Error(`annotation export ${response.status}`);
  return response.json();
}
