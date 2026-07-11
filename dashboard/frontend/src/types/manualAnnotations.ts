export type ZoomLevel = "MICRO" | "STRUCTURE" | "FULL";

export type ReviewType = "MODEL_EVENT" | "MISSED_EVENT";

export type AnnotationReviewStatus = "CORRECT" | "INCORRECT" | "UNCERTAIN";

export const REVIEW_STATUS_RU: Record<AnnotationReviewStatus, string> = {
  CORRECT: "✓ Событие определено верно",
  INCORRECT: "✗ Событие определено неверно",
  UNCERTAIN: "? Не уверен",
};

export const HUMAN_EVENT_CLASSES_RU = [
  "Кульминация покупок",
  "Кульминация продаж",
  "Останавливающий объем",
  "Поглощение",
  "Тест",
  "Нет спроса",
  "Нет предложения",
  "Другое",
] as const;

export type HumanEventClassRu = (typeof HUMAN_EVENT_CLASSES_RU)[number];

export const RELATIONSHIP_TYPES_RU = [
  "Источник реакции",
  "Следствие",
  "Подтверждает",
  "Продолжение",
  "Уперлось в этот объем",
  "Пропущено системой",
  "Модель ошиблась",
] as const;

export type RelationshipTypeRu = (typeof RELATIONSHIP_TYPES_RU)[number];

export const ANCHOR_LABELS_RU = [
  "Источник объема",
  "Поглощение",
  "Накопление",
  "Распределение",
  "Зона реакции",
  "Тест",
  "Кульминация покупок",
  "Кульминация продаж",
  "Останавливающий объем",
  "Другое",
] as const;

export type AnchorLabelRu = (typeof ANCHOR_LABELS_RU)[number];

export type AnchorType = "single" | "range";

export const LINK_STATUSES_RU = ["Активная", "Завершенная", "Разорванная"] as const;

export type LinkStatusRu = (typeof LINK_STATUSES_RU)[number];

export const LINK_COMPLETION_REASONS_RU = [
  "Смена контекста",
  "Новая фаза рынка",
  "Разворот подтвержден",
  "Потеря причинности",
  "Связь ошибочна",
  "Другое",
] as const;

export type LinkCompletionReasonRu = (typeof LINK_COMPLETION_REASONS_RU)[number];

export const LINK_STATUS_LABEL: Record<LinkStatusRu, string> = {
  Активная: "Активная связь",
  Завершенная: "Завершенная связь",
  Разорванная: "Разорванная связь",
};

export const ZOOM_LABELS_RU: Record<ZoomLevel, string> = {
  MICRO: "MICRO · 100+100",
  STRUCTURE: "STRUCTURE · 500+500",
  FULL: "FULL · вся история",
};

export interface ManualAnnotation {
  annotation_id: string;
  timestamp: string;
  bar_index: number;
  review_type: ReviewType;
  model_event_class: string | null;
  human_event_class: string | null;
  review_status: AnnotationReviewStatus | null;
  price_level: number | null;
  review_note_ru: string;
  zoom_level: ZoomLevel;
  is_key_event: boolean;
  created_at: string;
}

export interface ManualAnchor {
  anchor_id: string;
  anchor_type: AnchorType;
  start_timestamp: string;
  end_timestamp: string;
  start_price: number;
  end_price: number;
  anchor_label_ru: AnchorLabelRu;
  anchor_note_ru: string;
  created_at: string;
}

export interface ManualEventLink {
  link_id: string;
  source_anchor_id: string;
  target_anchor_id: string;
  relationship_type_ru: RelationshipTypeRu;
  relationship_note_ru: string;
  link_status: LinkStatusRu;
  completion_reason_ru: string;
  completion_note_ru: string;
  completed_at: string | null;
  created_at: string;
}

export interface ManualReaction {
  reaction_id: string;
  event_timestamp: string;
  event_class: string;
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
  note_ru: string;
  created_at: string;
}

import type { Stage1AuditEvent } from "./eventReview";

export interface AnnotationBootstrap {
  status: string;
  model_events: Stage1AuditEvent[];
  counts: Record<string, number>;
  total_model_events: number;
  annotations: ManualAnnotation[];
  anchors: ManualAnchor[];
  links: ManualEventLink[];
  reactions: ManualReaction[];
  missed_events: ManualAnnotation[];
  human_event_classes_ru: HumanEventClassRu[];
  anchor_labels_ru: AnchorLabelRu[];
  relationship_types_ru: RelationshipTypeRu[];
  link_statuses_ru: LinkStatusRu[];
  link_completion_reasons_ru: LinkCompletionReasonRu[];
  review_statuses: AnnotationReviewStatus[];
  zoom_levels: ZoomLevel[];
}

import type { Stage1ReviewContext } from "./eventReview";

export interface AnnotationContext extends Stage1ReviewContext {
  zoom_level: ZoomLevel;
  context_before: number;
  context_after: number;
  manual_annotations: ManualAnnotation[];
  manual_anchors: ManualAnchor[];
  manual_links: ManualEventLink[];
}

export function annotationKey(timestamp: string, eventClass: string): string {
  return `${timestamp}|${eventClass}`;
}

export function eventClassLabel(event: {
  event_class?: string;
  model_event_class?: string | null;
  human_event_class?: string | null;
}): string {
  return (
    event.human_event_class ??
    event.model_event_class ??
    event.event_class ??
    "—"
  );
}
