import {
  deleteManualAnchor,
  deleteManualAnnotation,
  deleteManualLink,
  deleteManualReaction,
  saveManualAnchor,
  saveManualAnnotation,
  saveManualLink,
  saveManualReaction,
  updateManualAnchor,
  updateManualLinkLifecycle,
} from "../../api/annotationClient";
import type {
  AnnotationReviewStatus,
  ManualAnchor,
  ManualAnnotation,
  ManualEventLink,
  ManualReaction,
} from "../../types/manualAnnotations";

export async function undoCreateAnchor(anchorId: string): Promise<void> {
  await deleteManualAnchor(anchorId);
}

export async function undoDeleteAnchor(anchor: ManualAnchor): Promise<void> {
  await saveManualAnchor({
    anchor_id: anchor.anchor_id,
    anchor_type: anchor.anchor_type,
    start_timestamp: anchor.start_timestamp,
    end_timestamp: anchor.end_timestamp,
    start_price: anchor.start_price,
    end_price: anchor.end_price,
    anchor_label_ru: anchor.anchor_label_ru,
    anchor_note_ru: anchor.anchor_note_ru,
  });
}

export async function undoUpdateAnchor(before: ManualAnchor): Promise<void> {
  await updateManualAnchor({
    anchor_id: before.anchor_id,
    anchor_label_ru: before.anchor_label_ru,
    anchor_note_ru: before.anchor_note_ru,
  });
}

export async function undoCreateLink(linkId: string): Promise<void> {
  await deleteManualLink(linkId);
}

export async function undoDeleteLink(link: ManualEventLink): Promise<void> {
  await saveManualLink({
    link_id: link.link_id,
    source_anchor_id: link.source_anchor_id,
    target_anchor_id: link.target_anchor_id,
    relationship_type_ru: link.relationship_type_ru,
    relationship_note_ru: link.relationship_note_ru,
  });
  if (link.link_status !== "Активная") {
    await updateManualLinkLifecycle({
      link_id: link.link_id,
      link_status: link.link_status,
      completion_reason_ru: link.completion_reason_ru,
      completion_note_ru: link.completion_note_ru,
    });
  }
}

export async function undoLinkLifecycle(before: ManualEventLink): Promise<void> {
  if (before.link_status === "Активная") {
    await updateManualLinkLifecycle({
      link_id: before.link_id,
      link_status: "Активная",
    });
    return;
  }
  await updateManualLinkLifecycle({
    link_id: before.link_id,
    link_status: before.link_status,
    completion_reason_ru: before.completion_reason_ru,
    completion_note_ru: before.completion_note_ru,
  });
}

export async function undoCreateReaction(reactionId: string): Promise<void> {
  await deleteManualReaction(reactionId);
}

export async function undoDeleteAnnotation(annotationId: string): Promise<void> {
  await deleteManualAnnotation(annotationId);
}

export async function undoDeleteReaction(reaction: ManualReaction): Promise<void> {
  await saveManualReaction({
    reaction_id: reaction.reaction_id,
    start_timestamp: reaction.start_timestamp,
    end_timestamp: reaction.end_timestamp,
    start_price: reaction.start_price,
    end_price: reaction.end_price,
    return_pct: reaction.return_pct,
    absolute_price_change: reaction.absolute_price_change,
    bars_count: reaction.bars_count,
    max_favorable_excursion: reaction.max_favorable_excursion,
    max_adverse_excursion: reaction.max_adverse_excursion,
    reaction_significance: reaction.reaction_significance,
    event_timestamp: reaction.event_timestamp || undefined,
    event_class: reaction.event_class || undefined,
    note_ru: reaction.note_ru,
  });
}

export type AnnotationSnapshot =
  | { kind: "none" }
  | { kind: "saved"; annotation: ManualAnnotation };

export function snapshotAnnotation(annotation: ManualAnnotation | undefined): AnnotationSnapshot {
  if (!annotation) return { kind: "none" };
  return {
    kind: "saved",
    annotation: {
      ...annotation,
      review_note_ru: annotation.review_note_ru ?? "",
      is_key_event: annotation.is_key_event ?? false,
    },
  };
}

export async function undoAnnotationChange(
  snapshot: AnnotationSnapshot,
  created: ManualAnnotation,
  event: {
    timestamp: string;
    bar_index: number;
    event_class: string;
    close: number | string | null;
  },
): Promise<void> {
  if (snapshot.kind === "none") {
    await deleteManualAnnotation(created.annotation_id);
    return;
  }
  const previous = snapshot.annotation;
  await saveManualAnnotation({
    timestamp: event.timestamp,
    bar_index: event.bar_index,
    review_type: "MODEL_EVENT",
    model_event_class: event.event_class,
    review_status: (previous.review_status ?? "UNCERTAIN") as AnnotationReviewStatus,
    price_level: Number(event.close) || null,
    review_note_ru: previous.review_note_ru,
    zoom_level: previous.zoom_level ?? "FULL",
    is_key_event: previous.is_key_event,
    annotation_id: previous.annotation_id,
  });
}
