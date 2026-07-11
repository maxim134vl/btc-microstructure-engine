import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteManualAnchor,
  deleteManualLink,
  deleteManualReaction,
  exportManualAnnotations,
  fetchAnnotationBootstrap,
  fetchAnnotationContext,
  saveManualAnnotation,
  saveManualAnchor,
  saveManualLink,
  saveManualReaction,
  updateManualAnchor,
  updateManualLinkLifecycle,
} from "../../api/annotationClient";
import type {
  AnchorLabelRu,
  AnnotationBootstrap,
  AnnotationContext,
  AnnotationReviewStatus,
  HumanEventClassRu,
  LinkCompletionReasonRu,
  LinkStatusRu,
  ManualAnchor,
  ManualAnnotation,
  ManualEventLink,
  ManualReaction,
  RelationshipTypeRu,
} from "../../types/manualAnnotations";
import {
  ANCHOR_LABELS_RU,
  HUMAN_EVENT_CLASSES_RU,
  LINK_COMPLETION_REASONS_RU,
  LINK_STATUS_LABEL,
  LINK_STATUSES_RU,
  RELATIONSHIP_TYPES_RU,
} from "../../types/manualAnnotations";
import type { Stage1AuditEvent, Stage1EventClass, WindowOverlayEvent } from "../../types/eventReview";
import {
  DEFAULT_CLASS_SELECTION,
  EVENT_CLASS_COLORS,
  STAGE1_EVENT_CLASSES,
  displayRaw,
} from "../../types/eventReview";
import { formatTime } from "../visual-cognition/chartUtils";
import { AnnotationChart, type AnnotationChartHandle } from "./AnnotationChart";
import {
  computeMeasurement,
  formatReturnPct,
  formatUsdChange,
  reactionToMeasurement,
  type MeasurementPreview,
} from "./measurementUtils";
import { buildWindowOverlayEvents } from "./windowOverlayEvents";
import { anchorTimeLabel } from "./AnchorOverlay";
import { anchorColor } from "./anchorUtils";
import { anchorLabelForEventClass } from "./eventAnchorMapping";
import {
  snapshotAnnotation,
  undoAnnotationChange,
  undoCreateAnchor,
  undoCreateLink,
  undoCreateReaction,
  undoDeleteAnnotation,
  undoDeleteAnchor,
  undoDeleteLink,
  undoDeleteReaction,
  undoLinkLifecycle,
  undoUpdateAnchor,
} from "./annotationUndoActions";
import { useAnnotationUndo } from "./useAnnotationUndo";
import { useTranslation } from "../../i18n";
import {
  ChartFormSurface,
  ChartInlineForm,
  EventTimeline,
  InfoRow,
  InspectorHint,
  InspectorListItem,
  InspectorMicroButton,
  InspectorSection,
  ModeHint,
  ReviewCheckbox,
  ReviewField,
  ReviewSelect,
  ReviewStatusButton,
  ReviewCheckboxInput,
  WorkflowActionButton,
  WorkflowSection,
  WorkspaceRailButton,
  WorkspaceToolbarButton,
} from "./Stage1ReviewChrome";

type AnchorDraft = {
  barIndex: number;
  timestamp: string;
  close: number;
};

type AnchorMode = "single" | "range" | null;

type MeasureMode = "none" | "measure" | "fixate";

function filterEventsByClasses(
  events: Stage1AuditEvent[],
  selection: Record<Stage1EventClass, boolean>,
): Stage1AuditEvent[] {
  return events.filter((event) => selection[event.event_class]);
}

function selectedOverlayClasses(selection: Record<Stage1EventClass, boolean>): Stage1EventClass[] {
  return STAGE1_EVENT_CLASSES.filter((eventClass) => selection[eventClass]);
}

function linkStatusColor(status: LinkStatusRu | string): string {
  if (status === "Завершенная") return "text-ds-status-healthy";
  if (status === "Разорванная") return "text-ds-status-error";
  return "text-ds-text-secondary";
}

function normalizeLink(link: ManualEventLink): ManualEventLink {
  return {
    ...link,
    link_status: (link.link_status ?? "Активная") as LinkStatusRu,
    completion_reason_ru: link.completion_reason_ru ?? "",
    completion_note_ru: link.completion_note_ru ?? "",
    completed_at: link.completed_at ?? null,
  };
}

function findModelAnnotation(
  annotations: ManualAnnotation[],
  event: Stage1AuditEvent,
): ManualAnnotation | undefined {
  return annotations.find(
    (item) =>
      item.review_type === "MODEL_EVENT" &&
      item.timestamp === event.timestamp &&
      item.model_event_class === event.event_class,
  );
}

export function Stage1EventReviewPanel() {
  const { t } = useTranslation();
  const [bootstrap, setBootstrap] = useState<AnnotationBootstrap | null>(null);
  const [annotations, setAnnotations] = useState<ManualAnnotation[]>([]);
  const [anchors, setAnchors] = useState<ManualAnchor[]>([]);
  const [links, setLinks] = useState<ManualEventLink[]>([]);
  const [reactions, setReactions] = useState<ManualReaction[]>([]);
  const [classSelection, setClassSelection] = useState(DEFAULT_CLASS_SELECTION);
  const [showAllInWindow, setShowAllInWindow] = useState(true);
  const [index, setIndex] = useState(0);
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: 0, count: 0 });
  const chartRef = useRef<AnnotationChartHandle>(null);
  const [context, setContext] = useState<AnnotationContext | null>(null);
  const [loadingContext, setLoadingContext] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [noteRu, setNoteRu] = useState("");
  const [isKeyEvent, setIsKeyEvent] = useState(false);
  const [addEventMode, setAddEventMode] = useState(false);
  const [anchorMode, setAnchorMode] = useState<AnchorMode>(null);
  const [anchorDraftStart, setAnchorDraftStart] = useState<AnchorDraft | null>(null);
  const [anchorDraftEnd, setAnchorDraftEnd] = useState<AnchorDraft | null>(null);
  const [anchorLabelRu, setAnchorLabelRu] = useState<AnchorLabelRu>(ANCHOR_LABELS_RU[0]);
  const [anchorNoteRu, setAnchorNoteRu] = useState("");
  const [linkMode, setLinkMode] = useState(false);
  const [linkSourceAnchorId, setLinkSourceAnchorId] = useState<string | null>(null);
  const [linkTargetAnchorId, setLinkTargetAnchorId] = useState<string | null>(null);
  const [pendingMissedBar, setPendingMissedBar] = useState<{
    timestamp: string;
    barIndex: number;
    close: number;
  } | null>(null);
  const [missedClass, setMissedClass] = useState<HumanEventClassRu>(HUMAN_EVENT_CLASSES_RU[0]);
  const [linkType, setLinkType] = useState<RelationshipTypeRu>(RELATIONSHIP_TYPES_RU[0]);
  const [linkNoteRu, setLinkNoteRu] = useState("");
  const [linkStatusFilter, setLinkStatusFilter] = useState<"all" | LinkStatusRu>("all");
  const [lifecycleLinkId, setLifecycleLinkId] = useState<string | null>(null);
  const [lifecycleTargetStatus, setLifecycleTargetStatus] = useState<LinkStatusRu | null>(null);
  const [linkCompletionReason, setLinkCompletionReason] = useState<LinkCompletionReasonRu>(
    LINK_COMPLETION_REASONS_RU[0],
  );
  const [linkCompletionNote, setLinkCompletionNote] = useState("");
  const [measureMode, setMeasureMode] = useState<MeasureMode>("none");
  const [measureStartIndex, setMeasureStartIndex] = useState<number | null>(null);
  const [activeMeasurement, setActiveMeasurement] = useState<MeasurementPreview | null>(null);
  const [reactionNoteRu, setReactionNoteRu] = useState("");
  const [reactionEventContext, setReactionEventContext] = useState<{
    timestamp: string;
    event_class: string;
  } | null>(null);
  const [editingAnchorId, setEditingAnchorId] = useState<string | null>(null);
  const [editAnchorLabelRu, setEditAnchorLabelRu] = useState<AnchorLabelRu>(ANCHOR_LABELS_RU[0]);
  const [editAnchorNoteRu, setEditAnchorNoteRu] = useState("");
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);

  const reloadBootstrap = useCallback(async () => {
    const payload = await fetchAnnotationBootstrap();
    setBootstrap(payload);
    setAnnotations(payload.annotations ?? []);
    setAnchors(payload.anchors ?? []);
    setLinks((payload.links ?? []).map(normalizeLink));
    setReactions(payload.reactions ?? []);
  }, []);

  const { pushUndo, undoLast, canUndo, lastActionLabel } = useAnnotationUndo(reloadBootstrap);
  const savingRef = useRef(false);

  const recordUndo = useCallback(
    (label: string, revert: () => Promise<void>) => {
      pushUndo(label, revert);
    },
    [pushUndo],
  );

  useEffect(() => {
    reloadBootstrap().catch((err) => setError(String(err)));
  }, [reloadBootstrap]);

  const modelEvents = bootstrap?.model_events ?? [];
  const filteredEvents = useMemo(
    () => filterEventsByClasses(modelEvents, classSelection),
    [modelEvents, classSelection],
  );
  const overlayClasses = useMemo(() => selectedOverlayClasses(classSelection), [classSelection]);
  const overlayClassesKey = overlayClasses.join(",");

  const currentEvent = filteredEvents[index] ?? null;
  const currentAnnotation = currentEvent ? findModelAnnotation(annotations, currentEvent) : undefined;

  const displayWindowEvents = useMemo(() => {
    if (!context || !currentEvent || !bootstrap) return [];
    return buildWindowOverlayEvents({
      allEvents: bootstrap.model_events,
      context,
      classSelection,
      currentEvent,
      apiWindowEvents: context.window_events,
    });
  }, [bootstrap, context, classSelection, currentEvent]);

  const windowTimeline = useMemo(() => {
    const inView = displayWindowEvents.filter(
      (event) =>
        event.bar_index_in_window >= visibleRange.start &&
        event.bar_index_in_window <= visibleRange.end,
    );
    return [...inView].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }, [displayWindowEvents, visibleRange]);

  const savedMeasurements = useMemo(() => {
    if (!context?.bars?.length) return [];
    return reactions
      .map((reaction) => reactionToMeasurement(context.bars, reaction))
      .filter((item): item is MeasurementPreview => item != null);
  }, [context?.bars, reactions]);

  const anchorById = useMemo(() => {
    const map = new Map<string, ManualAnchor>();
    for (const anchor of anchors) map.set(anchor.anchor_id, anchor);
    return map;
  }, [anchors]);

  const filteredLinks = useMemo(() => {
    if (linkStatusFilter === "all") return links;
    return links.filter((link) => link.link_status === linkStatusFilter);
  }, [links, linkStatusFilter]);

  const lifecycleLink = lifecycleLinkId
    ? links.find((link) => link.link_id === lifecycleLinkId) ?? null
    : null;

  useEffect(() => {
    if (index >= filteredEvents.length) {
      setIndex(Math.max(0, filteredEvents.length - 1));
    }
  }, [filteredEvents.length, index]);

  useEffect(() => {
    setNoteRu(currentAnnotation?.review_note_ru ?? "");
    setIsKeyEvent(currentAnnotation?.is_key_event ?? false);
  }, [currentAnnotation?.annotation_id, currentAnnotation?.review_note_ru, currentAnnotation?.is_key_event]);

  // Load entire M15 history once; zoom/pan is client-side (TradingView-style).
  useEffect(() => {
    const anchor = filteredEvents[0];
    if (!anchor?.bar_index && anchor?.bar_index !== 0) {
      setContext(null);
      return;
    }
    const controller = new AbortController();
    setLoadingContext(true);
    fetchAnnotationContext(
      anchor.bar_index!,
      {
        zoomLevel: "FULL",
        eventClass: anchor.event_class,
        overlayClasses,
        primaryTimestamp: anchor.timestamp,
      },
      controller.signal,
    )
      .then((payload) => {
        if (!controller.signal.aborted) setContext(payload);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingContext(false);
      });
    return () => controller.abort();
  }, [overlayClassesKey, bootstrap?.total_model_events]);

  const upsertAnnotationLocal = useCallback((row: ManualAnnotation) => {
    setAnnotations((prev) => {
      const next = prev.filter((item) => item.annotation_id !== row.annotation_id);
      const same = prev.find(
        (item) =>
          item.timestamp === row.timestamp &&
          item.review_type === row.review_type &&
          item.model_event_class === row.model_event_class &&
          item.human_event_class === row.human_event_class,
      );
      if (same) {
        return prev.map((item) => (item.annotation_id === same.annotation_id ? row : item));
      }
      return [...next, row];
    });
  }, []);

  async function persistModelAnnotation(
    reviewStatus: AnnotationReviewStatus,
    overrides?: { review_note_ru?: string; is_key_event?: boolean },
    undoLabel = t("stage1.undoActions.updateAnnotation"),
  ) {
    if (!currentEvent?.bar_index && currentEvent?.bar_index !== 0) return;
    const before = snapshotAnnotation(currentAnnotation);
    const eventSnapshot = {
      timestamp: currentEvent.timestamp,
      bar_index: currentEvent.bar_index!,
      event_class: currentEvent.event_class,
      close: currentEvent.close,
    };
    setSaving(true);
    savingRef.current = true;
    try {
      const { annotation } = await saveManualAnnotation({
        timestamp: currentEvent.timestamp,
        bar_index: currentEvent.bar_index!,
        review_type: "MODEL_EVENT",
        model_event_class: currentEvent.event_class,
        review_status: reviewStatus,
        price_level: Number(currentEvent.close) || null,
        review_note_ru: overrides?.review_note_ru ?? noteRu,
        zoom_level: "FULL",
        is_key_event: overrides?.is_key_event ?? isKeyEvent,
        annotation_id: currentAnnotation?.annotation_id,
      });
      upsertAnnotationLocal(annotation);
      await reloadBootstrap();
      recordUndo(undoLabel, async () => {
        await undoAnnotationChange(before, annotation, eventSnapshot);
        if (before.kind === "saved") {
          setNoteRu(before.annotation.review_note_ru);
          setIsKeyEvent(before.annotation.is_key_event);
        } else {
          setNoteRu("");
          setIsKeyEvent(false);
        }
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function saveNoteAndKeyEvent() {
    if (!currentEvent) return;
    const status = currentAnnotation?.review_status ?? "UNCERTAIN";
    await persistModelAnnotation(status, { review_note_ru: noteRu, is_key_event: isKeyEvent }, t("stage1.undoActions.saveNote"));
  }

  async function handleMissedEventSave() {
    if (!pendingMissedBar) return;
    const savedBar = { ...pendingMissedBar };
    setSaving(true);
    savingRef.current = true;
    try {
      const { annotation } = await saveManualAnnotation({
        timestamp: savedBar.timestamp,
        bar_index: savedBar.barIndex,
        review_type: "MISSED_EVENT",
        human_event_class: missedClass,
        price_level: savedBar.close,
        review_note_ru: noteRu,
        zoom_level: "FULL",
        is_key_event: isKeyEvent,
      });
      upsertAnnotationLocal(annotation);
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.addMissed"), async () => {
        await undoDeleteAnnotation(annotation.annotation_id);
      });
      setPendingMissedBar(null);
      setAddEventMode(false);
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleLinkSave() {
    if (!linkSourceAnchorId || !linkTargetAnchorId) return;
    setSaving(true);
    savingRef.current = true;
    try {
      const { link } = await saveManualLink({
        source_anchor_id: linkSourceAnchorId,
        target_anchor_id: linkTargetAnchorId,
        relationship_type_ru: linkType,
        relationship_note_ru: linkNoteRu,
      });
      const savedLink = normalizeLink(link);
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.createLink"), async () => {
        await undoCreateLink(savedLink.link_id);
      });
      setLinkTargetAnchorId(null);
      setLinkNoteRu("");
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleCreateAnchorFromEvent() {
    if (!currentEvent || !context?.bars?.length) return;
    if (currentEvent.bar_index == null) return;
    const bar =
      context.bars.find((item) => item.timestamp === currentEvent.timestamp) ??
      context.bars[currentEvent.bar_index];
    if (!bar) return;
    const label = anchorLabelForEventClass(currentEvent.event_class);
    setSaving(true);
    savingRef.current = true;
    try {
      const { anchor } = await saveManualAnchor({
        anchor_type: "single",
        start_timestamp: bar.timestamp,
        end_timestamp: bar.timestamp,
        start_price: bar.close,
        end_price: bar.close,
        anchor_label_ru: label,
        anchor_note_ru: currentEvent.event_class,
      });
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.anchorFromEvent"), async () => {
        await undoCreateAnchor(anchor.anchor_id);
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleAnchorSave() {
    if (!anchorDraftStart || !context?.bars?.length) return;
    const endDraft =
      anchorMode === "range" && anchorDraftEnd ? anchorDraftEnd : anchorDraftStart;
    setSaving(true);
    savingRef.current = true;
    try {
      const { anchor } = await saveManualAnchor({
        anchor_type: anchorMode === "range" ? "range" : "single",
        start_timestamp: anchorDraftStart.timestamp,
        end_timestamp: endDraft.timestamp,
        start_price: anchorDraftStart.close,
        end_price: endDraft.close,
        anchor_label_ru: anchorLabelRu,
        anchor_note_ru: anchorNoteRu,
      });
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.createAnchor"), async () => {
        await undoCreateAnchor(anchor.anchor_id);
      });
      setAnchorMode(null);
      setAnchorDraftStart(null);
      setAnchorDraftEnd(null);
      setAnchorNoteRu("");
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleDeleteAnchor(anchorId: string) {
    const before = anchors.find((item) => item.anchor_id === anchorId);
    if (!before) return;
    const linkedBefore = links.filter(
      (item) => item.source_anchor_id === anchorId || item.target_anchor_id === anchorId,
    );
    setSaving(true);
    savingRef.current = true;
    try {
      await deleteManualAnchor(anchorId);
      if (editingAnchorId === anchorId) setEditingAnchorId(null);
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.deleteAnchor"), async () => {
        await undoDeleteAnchor(before);
        for (const link of linkedBefore) {
          await undoDeleteLink(link);
        }
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  function startEditAnchor(anchor: ManualAnchor) {
    setEditingAnchorId(anchor.anchor_id);
    setEditAnchorLabelRu(anchor.anchor_label_ru);
    setEditAnchorNoteRu(anchor.anchor_note_ru ?? "");
  }

  async function handleAnchorEditSave() {
    if (!editingAnchorId) return;
    const before = anchors.find((item) => item.anchor_id === editingAnchorId);
    if (!before) return;
    setSaving(true);
    savingRef.current = true;
    try {
      const { anchor } = await updateManualAnchor({
        anchor_id: editingAnchorId,
        anchor_label_ru: editAnchorLabelRu,
        anchor_note_ru: editAnchorNoteRu,
      });
      setAnchors((prev) => prev.map((item) => (item.anchor_id === anchor.anchor_id ? anchor : item)));
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.updateAnchor"), async () => {
        await undoUpdateAnchor(before);
      });
      setEditingAnchorId(null);
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleDeleteLink(linkId: string) {
    const before = links.find((item) => item.link_id === linkId);
    if (!before) return;
    setSaving(true);
    savingRef.current = true;
    try {
      await deleteManualLink(linkId);
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.deleteLink"), async () => {
        await undoDeleteLink(before);
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleDeleteReaction(reactionId: string) {
    const before = reactions.find((item) => item.reaction_id === reactionId);
    if (!before) return;
    setSaving(true);
    savingRef.current = true;
    try {
      await deleteManualReaction(reactionId);
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.deleteReaction"), async () => {
        await undoDeleteReaction(before);
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  function openLinkLifecycleForm(linkId: string, targetStatus: LinkStatusRu) {
    setLifecycleLinkId(linkId);
    setLifecycleTargetStatus(targetStatus);
    setLinkCompletionReason(LINK_COMPLETION_REASONS_RU[0]);
    setLinkCompletionNote("");
  }

  function closeLinkLifecycleForm() {
    setLifecycleLinkId(null);
    setLifecycleTargetStatus(null);
    setLinkCompletionNote("");
  }

  async function handleLinkLifecycleSave() {
    if (!lifecycleLinkId || !lifecycleTargetStatus) return;
    if (lifecycleTargetStatus === "Активная") return;
    const before = links.find((item) => item.link_id === lifecycleLinkId);
    if (!before) return;
    setSaving(true);
    savingRef.current = true;
    try {
      await updateManualLinkLifecycle({
        link_id: lifecycleLinkId,
        link_status: lifecycleTargetStatus,
        completion_reason_ru: linkCompletionReason,
        completion_note_ru: linkCompletionNote,
      });
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.linkLifecycle"), async () => {
        await undoLinkLifecycle(before);
      });
      closeLinkLifecycleForm();
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function handleLinkReactivate(linkId: string) {
    const before = links.find((item) => item.link_id === linkId);
    if (!before) return;
    setSaving(true);
    savingRef.current = true;
    try {
      await updateManualLinkLifecycle({
        link_id: linkId,
        link_status: "Активная",
      });
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.restoreLink"), async () => {
        await undoLinkLifecycle(before);
      });
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const navigateToWindowEvent = useCallback(
    (windowEvent: WindowOverlayEvent) => {
      const targetIndex = filteredEvents.findIndex(
        (event) =>
          event.timestamp === windowEvent.timestamp && event.event_class === windowEvent.event_class,
      );
      if (targetIndex >= 0) setIndex(targetIndex);
    },
    [filteredEvents],
  );

  const clearInteractionModes = useCallback(() => {
    setAddEventMode(false);
    setAnchorMode(null);
    setAnchorDraftStart(null);
    setAnchorDraftEnd(null);
    setLinkMode(false);
    setLinkSourceAnchorId(null);
    setLinkTargetAnchorId(null);
    setPendingMissedBar(null);
    setMeasureMode("none");
    setMeasureStartIndex(null);
  }, []);

  const startAnchorMode = useCallback(
    (mode: "single" | "range") => {
      clearInteractionModes();
      setAnchorMode(mode);
      setAnchorDraftStart(null);
      setAnchorDraftEnd(null);
      setAnchorNoteRu("");
      setAnchorLabelRu(ANCHOR_LABELS_RU[0]);
    },
    [clearInteractionModes],
  );

  const startLinkMode = useCallback(() => {
    clearInteractionModes();
    setLinkMode(true);
    setLinkSourceAnchorId(null);
    setLinkTargetAnchorId(null);
    setLinkNoteRu("");
    setLinkType(RELATIONSHIP_TYPES_RU[0]);
  }, [clearInteractionModes]);

  const startMeasureMode = useCallback(() => {
    clearInteractionModes();
    setActiveMeasurement(null);
    setReactionEventContext(null);
    setReactionNoteRu("");
    setMeasureMode("measure");
  }, [clearInteractionModes]);

  const startFixateReaction = useCallback(() => {
    if (!currentEvent?.bar_index && currentEvent?.bar_index !== 0) return;
    clearInteractionModes();
    setActiveMeasurement(null);
    setReactionNoteRu("");
    setReactionEventContext({
      timestamp: currentEvent.timestamp,
      event_class: currentEvent.event_class,
    });
    setMeasureMode("fixate");
    setMeasureStartIndex(currentEvent.bar_index!);
  }, [clearInteractionModes, currentEvent]);

  const handleBarClick = useCallback(
    (barIndex: number, bar: { timestamp: string; close: number }) => {
      if (!context?.bars?.length) return;

      if (anchorMode) {
        const fullBar = context.bars[barIndex];
        if (!fullBar) return;
        const draft: AnchorDraft = {
          barIndex,
          timestamp: fullBar.timestamp,
          close: fullBar.close,
        };
        if (anchorMode === "single") {
          setAnchorDraftStart(draft);
          setAnchorDraftEnd(null);
          return;
        }
        if (!anchorDraftStart) {
          setAnchorDraftStart(draft);
          setAnchorDraftEnd(null);
          return;
        }
        if (anchorDraftStart.barIndex === barIndex) return;
        setAnchorDraftEnd(draft);
        return;
      }

      if (linkMode) return;

      if (addEventMode) {
        const globalBarIndex = context.window_start + barIndex;
        setPendingMissedBar({
          timestamp: bar.timestamp,
          barIndex: globalBarIndex,
          close: bar.close,
        });
        return;
      }

      if (measureMode === "measure") {
        if (measureStartIndex == null) {
          setMeasureStartIndex(barIndex);
          return;
        }
        const measurement = computeMeasurement(context.bars, measureStartIndex, barIndex);
        setActiveMeasurement(measurement);
        setReactionEventContext(null);
        setMeasureMode("none");
        setMeasureStartIndex(null);
        return;
      }

      if (measureMode === "fixate" && measureStartIndex != null) {
        const measurement = computeMeasurement(context.bars, measureStartIndex, barIndex);
        setActiveMeasurement(measurement);
        setMeasureMode("none");
        setMeasureStartIndex(null);
      }
    },
    [addEventMode, anchorMode, anchorDraftStart, context, linkMode, measureMode, measureStartIndex],
  );

  const handleAnchorClick = useCallback(
    (anchorId: string) => {
      if (!linkMode) return;
      if (!linkSourceAnchorId) {
        setLinkSourceAnchorId(anchorId);
        setLinkTargetAnchorId(null);
        return;
      }
      if (linkSourceAnchorId === anchorId) {
        setLinkSourceAnchorId(null);
        setLinkTargetAnchorId(null);
        return;
      }
      if (linkTargetAnchorId === anchorId) {
        setLinkTargetAnchorId(null);
        return;
      }
      setLinkTargetAnchorId(anchorId);
    },
    [linkMode, linkSourceAnchorId, linkTargetAnchorId],
  );

  const handleUndo = useCallback(async () => {
    if (savingRef.current) return;
    setSaving(true);
    savingRef.current = true;
    try {
      await undoLast();
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [undoLast]);

  async function handleSaveReaction() {
    if (!activeMeasurement) return;
    setSaving(true);
    savingRef.current = true;
    try {
      const { reaction } = await saveManualReaction({
        start_timestamp: activeMeasurement.start_timestamp,
        end_timestamp: activeMeasurement.end_timestamp,
        start_price: activeMeasurement.start_price,
        end_price: activeMeasurement.end_price,
        return_pct: activeMeasurement.return_pct,
        absolute_price_change: activeMeasurement.absolute_price_change,
        bars_count: activeMeasurement.bars_count,
        max_favorable_excursion: activeMeasurement.max_favorable_excursion,
        max_adverse_excursion: activeMeasurement.max_adverse_excursion,
        reaction_significance: activeMeasurement.reaction_significance,
        event_timestamp: reactionEventContext?.timestamp,
        event_class: reactionEventContext?.event_class,
        note_ru: reactionNoteRu,
      });
      await reloadBootstrap();
      recordUndo(t("stage1.undoActions.saveReaction"), async () => {
        await undoCreateReaction(reaction.reaction_id);
      });
      setActiveMeasurement(null);
      setReactionEventContext(null);
      setReactionNoteRu("");
    } catch (err) {
      setError(String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const handleEventClick = useCallback(
    (event: WindowOverlayEvent) => {
      navigateToWindowEvent(event);
    },
    [navigateToWindowEvent],
  );

  const anchorReadyToSave =
    anchorDraftStart != null &&
    (anchorMode === "single" || (anchorMode === "range" && anchorDraftEnd != null));

  const goPrevious = useCallback(() => setIndex((value) => Math.max(0, value - 1)), []);
  const goNext = useCallback(
    () => setIndex((value) => Math.min(filteredEvents.length - 1, value + 1)),
    [filteredEvents.length],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "z" && !event.shiftKey) {
        event.preventDefault();
        if (canUndo && !savingRef.current) void handleUndo();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goPrevious();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goNext();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canUndo, goNext, goPrevious, handleUndo]);

  function toggleClass(eventClass: Stage1EventClass) {
    setClassSelection((prev) => {
      const next = { ...prev, [eventClass]: !prev[eventClass] };
      if (!STAGE1_EVENT_CLASSES.some((cls) => next[cls])) return prev;
      return next;
    });
    setIndex(0);
  }

  if (error && !bootstrap) {
    return (
      <div className="ops-surface flex h-full items-center justify-center p-6 text-sm text-ds-status-error">
        {t("stage1.loadError", { error })}
      </div>
    );
  }

  if (!bootstrap) {
    return (
      <div className="ops-surface flex h-full items-center justify-center text-sm text-ds-text-secondary">
        {t("stage1.loading")}
      </div>
    );
  }

  const positionLabel =
    filteredEvents.length > 0 ? `${index + 1} / ${filteredEvents.length}` : "0 / 0";
  const focusBarIndex = currentEvent?.bar_index ?? context?.event_index ?? null;

  return (
    <div className="ops-surface flex h-full min-h-0 flex-col gap-2 p-2 sm:p-3">
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-4 border-b border-ds-border/60 pb-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ds-text-tertiary">{t("stage1.eyebrow")}</p>
          <h1 className="font-ds-display text-[20px] font-semibold tracking-tight text-ds-text-primary sm:text-[22px]">
            {t("stage1.title")}
          </h1>
          <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{t("stage1.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="ops-card flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[10px] tabular-nums text-ds-text-tertiary">
            <span>{t("stage1.stats.events", { count: bootstrap.total_model_events })}</span>
            <span className="hidden h-1 w-1 rounded-full bg-ds-text-tertiary sm:inline-block" aria-hidden />
            <span>{t("stage1.stats.annotations", { count: annotations.length })}</span>
            <span className="hidden h-1 w-1 rounded-full bg-ds-text-tertiary sm:inline-block" aria-hidden />
            <span>{t("stage1.stats.anchors", { count: anchors.length })}</span>
            <span className="hidden h-1 w-1 rounded-full bg-ds-text-tertiary sm:inline-block" aria-hidden />
            <span>{t("stage1.stats.reactions", { count: reactions.length })}</span>
          </div>
          <WorkspaceToolbarButton
            disabled={!canUndo || saving}
            onClick={() => handleUndo().catch((err) => setError(String(err)))}
            title="Ctrl+Z / Cmd+Z"
          >
            {t("stage1.undo")}{lastActionLabel ? ` · ${lastActionLabel}` : ""}
          </WorkspaceToolbarButton>
          <WorkspaceToolbarButton onClick={() => exportManualAnnotations().catch((err) => setError(String(err)))}>
            {t("stage1.export")}
          </WorkspaceToolbarButton>
        </div>
      </header>

      {error ? (
        <div className="ops-card shrink-0 border border-red-500/20 px-3 py-2 text-[11px] text-ds-status-error">{error}</div>
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 gap-2">
        <aside className="panel-scroll flex w-[240px] shrink-0 flex-col gap-3 overflow-y-auto pr-0.5">
          <WorkflowSection title={t("stage1.navigation.title")} subtitle={t("stage1.navigation.subtitle")}>
            <InspectorHint>
              {t("stage1.navigation.wheelZoom")}
              <br />
              {t("stage1.navigation.shiftPan")}
            </InspectorHint>
            <p className="text-[10px] tabular-nums text-ds-text-tertiary">
              {t("stage1.navigation.stats", {
                bars: context?.bars?.length ?? 0,
                position: positionLabel,
                visible: visibleRange.count,
                markers: displayWindowEvents.length,
              })}
            </p>
            <WorkflowActionButton disabled={focusBarIndex == null} variant="warning" onClick={() => chartRef.current?.centerOnEvent()}>
              {t("stage1.navigation.goToEvent")}
            </WorkflowActionButton>
            <WorkflowActionButton disabled={!context?.bars?.length} onClick={() => chartRef.current?.zoomToFitAll()}>
              {t("stage1.navigation.fullHistory")}
            </WorkflowActionButton>
            <div className="grid grid-cols-2 gap-2">
              <WorkflowActionButton disabled={index <= 0} onClick={goPrevious}>
                {t("stage1.navigation.prev")}
              </WorkflowActionButton>
              <WorkflowActionButton disabled={index >= filteredEvents.length - 1} onClick={goNext}>
                {t("stage1.navigation.next")}
              </WorkflowActionButton>
            </div>
          </WorkflowSection>

          <WorkflowSection title={t("stage1.visibility.title")} subtitle={t("stage1.visibility.subtitle")}>
            <div className="space-y-2">
              {STAGE1_EVENT_CLASSES.map((eventClass) => (
                <ReviewCheckbox
                  key={eventClass}
                  checked={classSelection[eventClass]}
                  onChange={() => toggleClass(eventClass)}
                  swatch={EVENT_CLASS_COLORS[eventClass]}
                  label={eventClass}
                />
              ))}
            </div>
            <ReviewCheckbox
              checked={showAllInWindow}
              onChange={() => setShowAllInWindow((v) => !v)}
              label={t("stage1.visibility.allInWindow")}
            />
          </WorkflowSection>

          <WorkflowSection title={t("stage1.events.title")} subtitle={t("stage1.events.subtitle")}>
            <WorkflowActionButton
              active={addEventMode}
              variant="warning"
              onClick={() => {
                if (addEventMode) {
                  setAddEventMode(false);
                  setPendingMissedBar(null);
                } else {
                  clearInteractionModes();
                  setAddEventMode(true);
                }
              }}
            >
              {t("stage1.events.addEvent")}
            </WorkflowActionButton>
          </WorkflowSection>

          <WorkflowSection title={t("stage1.measurements.title")} subtitle={t("stage1.measurements.subtitle")}>
            <WorkflowActionButton
              active={measureMode === "measure"}
              variant="violet"
              disabled={!context?.bars?.length}
              onClick={() => (measureMode === "measure" ? clearInteractionModes() : startMeasureMode())}
            >
              {t("stage1.measurements.measure")}
            </WorkflowActionButton>
            <WorkflowActionButton
              active={measureMode === "fixate"}
              variant="emerald"
              disabled={!currentEvent?.bar_index && currentEvent?.bar_index !== 0}
              onClick={() => (measureMode === "fixate" ? clearInteractionModes() : startFixateReaction())}
            >
              {t("stage1.measurements.fixateReaction")}
            </WorkflowActionButton>
          </WorkflowSection>

          <WorkflowSection title={t("stage1.anchorsLinks.title")} subtitle={t("stage1.anchorsLinks.subtitle")}>
            <WorkflowActionButton
              variant="emerald"
              disabled={!currentEvent || saving}
              onClick={() => handleCreateAnchorFromEvent().catch((err) => setError(String(err)))}
            >
              {t("stage1.anchorsLinks.anchorFromEvent")}
            </WorkflowActionButton>
            <WorkflowActionButton
              active={anchorMode === "single"}
              variant="warning"
              disabled={!context?.bars?.length}
              onClick={() => (anchorMode === "single" ? clearInteractionModes() : startAnchorMode("single"))}
            >
              {t("stage1.anchorsLinks.anchorSingle")}
            </WorkflowActionButton>
            <WorkflowActionButton
              active={anchorMode === "range"}
              variant="warning"
              disabled={!context?.bars?.length}
              onClick={() => (anchorMode === "range" ? clearInteractionModes() : startAnchorMode("range"))}
            >
              {t("stage1.anchorsLinks.anchorRange")}
            </WorkflowActionButton>
            <WorkflowActionButton
              active={linkMode}
              variant="sky"
              disabled={!context?.bars?.length || anchors.length === 0}
              onClick={() => (linkMode ? clearInteractionModes() : startLinkMode())}
            >
              {t("stage1.anchorsLinks.createLink")}
            </WorkflowActionButton>
            {anchorMode ? (
              <ModeHint variant="warning">
                {anchorMode === "single"
                  ? t("stage1.anchorsLinks.modeSingle")
                  : anchorDraftStart && !anchorDraftEnd
                    ? t("stage1.anchorsLinks.modeRangeEnd")
                    : t("stage1.anchorsLinks.modeRange")}
                <button type="button" onClick={clearInteractionModes} className="mt-1 block text-ds-text-secondary underline">
                  {t("common.cancel")}
                </button>
              </ModeHint>
            ) : null}
            {linkMode ? (
              <ModeHint variant="sky">
                {!linkSourceAnchorId
                  ? t("stage1.anchorsLinks.linkSelectSource")
                  : !linkTargetAnchorId
                    ? t("stage1.anchorsLinks.linkSelectTarget")
                    : t("stage1.anchorsLinks.linkSelectType")}
                {linkSourceAnchorId ? (
                  <button
                    type="button"
                    onClick={() => {
                      setLinkSourceAnchorId(null);
                      setLinkTargetAnchorId(null);
                    }}
                    className="mt-1 block text-ds-text-secondary underline"
                  >
                    {t("stage1.anchorsLinks.changeSource")}
                  </button>
                ) : null}
                <button type="button" onClick={clearInteractionModes} className="mt-1 block text-ds-text-secondary underline">
                  {t("common.cancel")}
                </button>
              </ModeHint>
            ) : null}
          </WorkflowSection>
        </aside>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="ops-card flex min-h-0 flex-1 flex-col p-2 sm:p-3">
            <div className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-2 px-0.5 text-[11px] text-ds-text-tertiary">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <WorkspaceToolbarButton
                  onClick={() => setRightSidebarOpen((open) => !open)}
                  aria-expanded={rightSidebarOpen}
                  title={rightSidebarOpen ? t("stage1.focus.hideInspector") : t("stage1.focus.showInspector")}
                >
                  {rightSidebarOpen ? "▸" : "◂"} {t("stage1.focus.showInspector")}
                </WorkspaceToolbarButton>
                <span className="hidden h-3 w-px bg-ds-border/80 sm:inline-block" aria-hidden />
                <span className="min-w-0 truncate">{t("stage1.chartChrome")}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2 tabular-nums">
                <span className="text-ds-text-tertiary">{positionLabel}</span>
                {currentEvent ? (
                  <span className="hidden text-ds-text-primary md:inline">
                    <span style={{ color: EVENT_CLASS_COLORS[currentEvent.event_class] }}>{currentEvent.event_class}</span>
                    {" · "}
                    {formatTime(currentEvent.timestamp)}
                  </span>
                ) : null}
              </div>
            </div>

            <div className="min-h-0 flex-1">
            {loadingContext ? (
              <div className="flex h-full items-center justify-center text-sm text-ds-text-tertiary">{t("stage1.chartLoading")}</div>
            ) : context?.bars?.length ? (
              <AnnotationChart
                ref={chartRef}
                bars={context.bars}
                focusBarIndex={focusBarIndex}
                windowEvents={displayWindowEvents}
                manualAnnotations={annotations}
                manualAnchors={anchors}
                manualLinks={links}
                showAllInWindow={showAllInWindow}
                addEventMode={addEventMode}
                anchorMode={anchorMode}
                anchorRangeStart={anchorDraftStart?.barIndex ?? null}
                anchorRangeEnd={anchorDraftEnd?.barIndex ?? null}
                measureKind={measureMode === "none" ? null : measureMode}
                measureStartIndex={measureStartIndex}
                linkMode={linkMode}
                linkSourceAnchorId={linkSourceAnchorId}
                linkTargetAnchorId={linkTargetAnchorId}
                activeMeasurement={activeMeasurement}
                savedMeasurements={savedMeasurements}
                onBarClick={handleBarClick}
                onEventClick={handleEventClick}
                onAnchorClick={handleAnchorClick}
                onVisibleRangeChange={(start, end, count) => setVisibleRange({ start, end, count })}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-ds-text-tertiary">{t("stage1.noChartData")}</div>
            )}
          </div>

            <ChartFormSurface>
            <div className="flex flex-wrap justify-center gap-2">
              {(Object.entries({ CORRECT: "CORRECT", INCORRECT: "INCORRECT", UNCERTAIN: "UNCERTAIN" }) as [AnnotationReviewStatus, AnnotationReviewStatus][]).map(([status]) => (
                <ReviewStatusButton
                  key={status}
                  disabled={!currentEvent || saving}
                  active={currentAnnotation?.review_status === status}
                  onClick={() => persistModelAnnotation(status)}
                >
                  {t(`stage1.reviewStatus.${status}`)}
                </ReviewStatusButton>
              ))}
            </div>

            <label className="flex cursor-pointer items-center gap-2 px-1 text-[11px] text-ds-text-primary">
              <ReviewCheckboxInput checked={isKeyEvent} onChange={(e) => setIsKeyEvent(e.target.checked)} />
              {t("stage1.review.keyEvent")}
            </label>

            <ReviewField value={noteRu} onChange={setNoteRu} placeholder={t("stage1.review.notePlaceholder")} rows={3} />
            <WorkspaceToolbarButton disabled={!currentEvent || saving} onClick={saveNoteAndKeyEvent}>
              {t("stage1.review.saveNote")}
            </WorkspaceToolbarButton>
          </ChartFormSurface>

          {pendingMissedBar ? (
            <ChartInlineForm tone="warning" title={t("stage1.review.missedEvent", { time: formatTime(pendingMissedBar.timestamp) })}>
              <ReviewSelect value={missedClass} onChange={(value) => setMissedClass(value as HumanEventClassRu)} className="mb-2">
                {HUMAN_EVENT_CLASSES_RU.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </ReviewSelect>
              <div className="flex gap-2">
                <WorkspaceToolbarButton onClick={handleMissedEventSave} disabled={saving}>
                  {t("stage1.review.saveMissed")}
                </WorkspaceToolbarButton>
                <button type="button" onClick={() => setPendingMissedBar(null)} className="text-[11px] text-ds-text-tertiary">
                  {t("common.cancel")}
                </button>
              </div>
            </ChartInlineForm>
          ) : null}

          {activeMeasurement ? (
            <ChartInlineForm tone="violet" title={t("stage1.review.measurement")}>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-ds-text-secondary">
                <span>{t("stage1.review.start")}</span>
                <span className="text-ds-text-primary">{formatTime(activeMeasurement.start_timestamp)}</span>
                <span>{t("stage1.review.end")}</span>
                <span className="text-ds-text-primary">{formatTime(activeMeasurement.end_timestamp)}</span>
                <span>{t("stage1.review.change")}</span>
                <span className={activeMeasurement.return_pct >= 0 ? "text-ds-status-healthy" : "text-ds-status-error"}>
                  {formatReturnPct(activeMeasurement.return_pct)}
                </span>
                <span>{t("stage1.review.absolute")}</span>
                <span className="text-ds-text-primary">{formatUsdChange(activeMeasurement.absolute_price_change)}</span>
                <span>{t("stage1.review.bars")}</span>
                <span className="text-ds-text-primary">{activeMeasurement.bars_count} bars</span>
                <span>MFE</span>
                <span className="text-ds-text-primary">{formatReturnPct(activeMeasurement.max_favorable_excursion)}</span>
                <span>MAE</span>
                <span className="text-ds-text-primary">{formatReturnPct(activeMeasurement.max_adverse_excursion)}</span>
              </div>
              <div className="mt-2 rounded-xl border border-ds-border bg-ds-surface-secondary/50 px-2 py-1.5 text-[11px] text-ds-text-primary">
                {activeMeasurement.reaction_significance}
              </div>
              {reactionEventContext ? (
                <div className="mt-2 text-[10px] text-ds-text-primary">
                  {t("stage1.review.event")} {reactionEventContext.event_class} · {formatTime(reactionEventContext.timestamp)}
                </div>
              ) : null}
              <ReviewField value={reactionNoteRu} onChange={setReactionNoteRu} placeholder={t("stage1.review.reactionNotePlaceholder")} rows={2} />
              <div className="mt-2 flex gap-2">
                <WorkspaceToolbarButton onClick={handleSaveReaction} disabled={saving}>
                  {t("stage1.review.saveMeasurement")}
                </WorkspaceToolbarButton>
                <button
                  type="button"
                  onClick={() => {
                    setActiveMeasurement(null);
                    setReactionEventContext(null);
                    setReactionNoteRu("");
                  }}
                  className="text-[11px] text-ds-text-tertiary"
                >
                  {t("common.cancel")}
                </button>
              </div>
            </ChartInlineForm>
          ) : null}

          {anchorReadyToSave ? (
            <ChartInlineForm
              tone="warning"
              title={t("stage1.review.newAnchor", {
                type: anchorMode === "single" ? t("stage1.review.anchorTypeSingle") : t("stage1.review.anchorTypeRange"),
              })}
            >
              <div className="mb-2 text-[10px] text-ds-text-secondary">
                {formatTime(anchorDraftStart!.timestamp)}
                {anchorDraftEnd ? ` → ${formatTime(anchorDraftEnd.timestamp)}` : ""}
              </div>
              <ReviewSelect value={anchorLabelRu} onChange={(value) => setAnchorLabelRu(value as AnchorLabelRu)} className="mb-2">
                {ANCHOR_LABELS_RU.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </ReviewSelect>
              <ReviewField value={anchorNoteRu} onChange={setAnchorNoteRu} placeholder={t("stage1.review.anchorNotePlaceholder")} rows={2} />
              <div className="mt-2 flex gap-2">
                <WorkspaceToolbarButton onClick={handleAnchorSave} disabled={saving}>
                  {t("stage1.review.saveAnchor")}
                </WorkspaceToolbarButton>
                <button
                  type="button"
                  onClick={() => {
                    setAnchorDraftStart(null);
                    setAnchorDraftEnd(null);
                  }}
                  className="text-[11px] text-ds-text-tertiary"
                >
                  {t("common.cancel")}
                </button>
              </div>
            </ChartInlineForm>
          ) : null}

          {linkSourceAnchorId && linkTargetAnchorId ? (
            <ChartInlineForm tone="sky" title={t("stage1.review.linkAnchors")}>
              <div className="mb-2 grid grid-cols-2 gap-1 text-[9px] text-ds-text-tertiary">
                <span>{t("stage1.review.source")}</span>
                <span className="text-ds-text-primary">
                  {anchorById.get(linkSourceAnchorId)?.anchor_label_ru ?? linkSourceAnchorId}
                </span>
                <span>{t("stage1.review.target")}</span>
                <span className="text-ds-text-primary">
                  {anchorById.get(linkTargetAnchorId)?.anchor_label_ru ?? linkTargetAnchorId}
                </span>
              </div>
              <ReviewSelect value={linkType} onChange={(value) => setLinkType(value as RelationshipTypeRu)} className="mb-2">
                {RELATIONSHIP_TYPES_RU.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </ReviewSelect>
              <ReviewField value={linkNoteRu} onChange={setLinkNoteRu} placeholder={t("stage1.review.linkNotePlaceholder")} rows={2} />
              <div className="mt-2 flex flex-wrap gap-2">
                <WorkspaceToolbarButton onClick={handleLinkSave} disabled={saving}>
                  {t("stage1.review.saveLink")}
                </WorkspaceToolbarButton>
                <button type="button" onClick={() => setLinkTargetAnchorId(null)} className="text-[11px] text-ds-text-tertiary">
                  {t("stage1.review.changeTarget")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setLinkSourceAnchorId(null);
                    setLinkTargetAnchorId(null);
                  }}
                  className="text-[11px] text-ds-text-tertiary"
                >
                  {t("stage1.anchorsLinks.changeSource")}
                </button>
              </div>
            </ChartInlineForm>
          ) : null}
          </div>
        </section>

        {rightSidebarOpen ? (
          <aside className="panel-scroll flex w-[320px] shrink-0 flex-col gap-3 overflow-y-auto pr-0.5">
            <div className="flex shrink-0 justify-end px-0.5">
              <WorkspaceRailButton
                onClick={() => setRightSidebarOpen(false)}
                title={t("stage1.focus.hideInspector")}
                aria-expanded={true}
                aria-label={t("stage1.focus.hideInspector")}
              >
                ›
              </WorkspaceRailButton>
            </div>
          <InspectorSection title={t("stage1.inspector.selectedEvent")} meta={currentEvent ? currentEvent.event_class : undefined}>
            {currentEvent ? (
              <div className="space-y-3">
                <WorkflowActionButton
                  variant="emerald"
                  disabled={saving || currentEvent.bar_index == null}
                  onClick={() => handleCreateAnchorFromEvent().catch((err) => setError(String(err)))}
                >
                  {t("stage1.anchorsLinks.anchorFromEvent")}
                </WorkflowActionButton>
                <InfoRow label="timestamp" value={displayRaw(currentEvent.timestamp)} />
                <InfoRow label="event_class" value={displayRaw(currentEvent.event_class)} />
                <InfoRow label="bar_index" value={displayRaw(currentEvent.bar_index)} />
                <InfoRow label="close" value={displayRaw(currentEvent.close)} />
                <InfoRow label="volume_zscore" value={displayRaw(currentEvent.volume)} />
                {currentAnnotation?.review_status ? (
                  <InspectorHint>
                    {t("stage1.inspector.annotation")}{" "}
                    <span className="text-ds-text-primary">
                      {t(`stage1.reviewStatus.${currentAnnotation.review_status}`)}
                    </span>
                  </InspectorHint>
                ) : null}
              </div>
            ) : (
              <p className="text-[11px] text-ds-text-tertiary">{t("stage1.inspector.noEventsFilter")}</p>
            )}
          </InspectorSection>

          <InspectorSection title={t("stage1.inspector.windowEvents")} meta={`${windowTimeline.length}`}>
            <EventTimeline events={windowTimeline} currentEvent={currentEvent} onSelect={handleEventClick} />
          </InspectorSection>

          <InspectorSection title={t("stage1.inspector.anchors")} meta={String(anchors.length)}>
            <ul className="panel-scroll max-h-40 space-y-1.5 overflow-y-auto text-[10px] text-ds-text-secondary">
              {[...anchors].reverse().map((anchor) => {
                const isSource = linkSourceAnchorId === anchor.anchor_id;
                const isTarget = linkTargetAnchorId === anchor.anchor_id;
                return (
                  <InspectorListItem
                    key={anchor.anchor_id}
                    highlight={isSource ? "source" : isTarget ? "target" : "active"}
                    interactive={linkMode}
                    onClick={() => linkMode && handleAnchorClick(anchor.anchor_id)}
                    onKeyDown={(event) => {
                      if (linkMode && (event.key === "Enter" || event.key === " ")) {
                        event.preventDefault();
                        handleAnchorClick(anchor.anchor_id);
                      }
                    }}
                  >
                    <span style={{ color: anchorColor(anchor.anchor_label_ru) }}>{anchor.anchor_label_ru}</span>
                    <br />
                    {anchorTimeLabel(anchor)}
                    {anchor.anchor_type === "range" ? ` · ${t("stage1.inspector.range")}` : ` · ${t("stage1.inspector.candle")}`}
                    {!linkMode ? (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        <InspectorMicroButton
                          disabled={saving}
                          onClick={(event) => {
                            event.stopPropagation();
                            startEditAnchor(anchor);
                          }}
                        >
                          {t("common.edit")}
                        </InspectorMicroButton>
                        <InspectorMicroButton
                          tone="danger"
                          disabled={saving}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDeleteAnchor(anchor.anchor_id);
                          }}
                        >
                          {t("common.delete")}
                        </InspectorMicroButton>
                      </div>
                    ) : null}
                  </InspectorListItem>
                );
              })}
              {anchors.length === 0 ? <li className="text-[11px] text-ds-text-tertiary">{t("stage1.inspector.noAnchors")}</li> : null}
            </ul>

            {editingAnchorId ? (
              <ChartInlineForm tone="warning" title={t("stage1.inspector.editAnchor")}>
                <ReviewSelect
                  value={editAnchorLabelRu}
                  onChange={(value) => setEditAnchorLabelRu(value as AnchorLabelRu)}
                  className="mb-2"
                >
                  {ANCHOR_LABELS_RU.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </ReviewSelect>
                <ReviewField value={editAnchorNoteRu} onChange={setEditAnchorNoteRu} placeholder={t("stage1.inspector.anchorCommentPlaceholder")} rows={2} />
                <div className="mt-2 flex gap-2">
                  <InspectorMicroButton disabled={saving} onClick={() => void handleAnchorEditSave()}>
                    {t("common.save")}
                  </InspectorMicroButton>
                  <button type="button" onClick={() => setEditingAnchorId(null)} className="text-[10px] text-ds-text-tertiary">
                    {t("common.cancel")}
                  </button>
                </div>
              </ChartInlineForm>
            ) : null}
          </InspectorSection>

          <InspectorSection title={t("stage1.inspector.links")} meta={String(links.length)}>
            <ReviewSelect
              value={linkStatusFilter}
              onChange={(value) => setLinkStatusFilter(value as "all" | LinkStatusRu)}
              className="mb-2"
            >
              <option value="all">{t("common.allStatuses")}</option>
              {LINK_STATUSES_RU.map((status) => (
                <option key={status} value={status}>
                  {LINK_STATUS_LABEL[status]}
                </option>
              ))}
            </ReviewSelect>
            <ul className="panel-scroll max-h-56 space-y-1.5 overflow-y-auto text-[10px] text-ds-text-secondary">
              {filteredLinks.map((link) => (
                <InspectorListItem key={link.link_id}>
                  <span className={linkStatusColor(link.link_status)}>{LINK_STATUS_LABEL[link.link_status]}</span>
                  <br />
                  <span className="text-ds-text-primary">{link.relationship_type_ru}</span>
                  <br />
                  {anchorById.get(link.source_anchor_id) && anchorById.get(link.target_anchor_id) ? (
                    <>
                      {anchorById.get(link.source_anchor_id)!.anchor_label_ru}
                      {" → "}
                      {anchorById.get(link.target_anchor_id)!.anchor_label_ru}
                    </>
                  ) : (
                    <>
                      {link.source_anchor_id.slice(0, 10)} → {link.target_anchor_id.slice(0, 10)}
                    </>
                  )}
                  {link.completion_reason_ru ? (
                    <>
                      <br />
                      <span className="text-ds-text-tertiary">{link.completion_reason_ru}</span>
                    </>
                  ) : null}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {link.link_status === "Активная" ? (
                      <>
                        <InspectorMicroButton
                          tone="success"
                          disabled={saving}
                          onClick={() => openLinkLifecycleForm(link.link_id, "Завершенная")}
                        >
                          {t("stage1.inspector.completeLink")}
                        </InspectorMicroButton>
                        <InspectorMicroButton
                          tone="danger"
                          disabled={saving}
                          onClick={() => openLinkLifecycleForm(link.link_id, "Разорванная")}
                        >
                          {t("stage1.inspector.breakLink")}
                        </InspectorMicroButton>
                      </>
                    ) : (
                      <InspectorMicroButton
                        tone="sky"
                        disabled={saving}
                        onClick={() => handleLinkReactivate(link.link_id)}
                      >
                        {t("stage1.inspector.restoreLink")}
                      </InspectorMicroButton>
                    )}
                    <InspectorMicroButton tone="danger" disabled={saving} onClick={() => void handleDeleteLink(link.link_id)}>
                      {t("common.delete")}
                    </InspectorMicroButton>
                  </div>
                </InspectorListItem>
              ))}
              {filteredLinks.length === 0 ? (
                <li className="text-[11px] text-ds-text-tertiary">
                  {links.length === 0 ? t("stage1.inspector.noLinks") : t("stage1.inspector.noLinksFilter")}
                </li>
              ) : null}
            </ul>

            {lifecycleLink && lifecycleTargetStatus && lifecycleTargetStatus !== "Активная" ? (
              <ChartInlineForm
                title={
                  lifecycleTargetStatus === "Завершенная"
                    ? t("stage1.inspector.completeLinkTitle")
                    : t("stage1.inspector.breakLinkTitle")
                }
              >
                <div className="mb-2 text-[9px] text-ds-text-tertiary">
                  {lifecycleLink.relationship_type_ru} ·{" "}
                  {anchorById.get(lifecycleLink.source_anchor_id)?.anchor_label_ru ?? "—"}
                  {" → "}
                  {anchorById.get(lifecycleLink.target_anchor_id)?.anchor_label_ru ?? "—"}
                </div>
                <ReviewSelect
                  value={linkCompletionReason}
                  onChange={(value) => setLinkCompletionReason(value as LinkCompletionReasonRu)}
                  className="mb-2"
                >
                  {LINK_COMPLETION_REASONS_RU.map((reason) => (
                    <option key={reason} value={reason}>
                      {reason}
                    </option>
                  ))}
                </ReviewSelect>
                <ReviewField value={linkCompletionNote} onChange={setLinkCompletionNote} placeholder={t("stage1.inspector.anchorCommentPlaceholder")} rows={2} />
                <div className="mt-2 flex gap-2">
                  <InspectorMicroButton
                    tone={lifecycleTargetStatus === "Завершенная" ? "success" : "danger"}
                    disabled={saving}
                    onClick={handleLinkLifecycleSave}
                  >
                    {t("common.save")}
                  </InspectorMicroButton>
                  <button type="button" onClick={closeLinkLifecycleForm} className="text-[10px] text-ds-text-tertiary">
                    {t("common.cancel")}
                  </button>
                </div>
              </ChartInlineForm>
            ) : null}
          </InspectorSection>

          <InspectorSection title={t("stage1.inspector.reactions")} meta={String(reactions.length)}>
            <ul className="panel-scroll max-h-48 space-y-1.5 overflow-y-auto text-[10px] text-ds-text-secondary">
              {[...reactions].reverse().map((reaction) => (
                <InspectorListItem key={reaction.reaction_id}>
                  <span className={reaction.return_pct >= 0 ? "text-ds-status-healthy" : "text-ds-status-error"}>
                    {formatReturnPct(reaction.return_pct)}
                  </span>
                  {" · "}
                  {reaction.bars_count} bars
                  <br />
                  <span className="text-ds-text-tertiary">{reaction.reaction_significance}</span>
                  {reaction.event_class ? (
                    <>
                      <br />
                      <span className="text-ds-status-healthy">{reaction.event_class}</span>
                    </>
                  ) : null}
                  <div className="mt-1.5">
                    <InspectorMicroButton tone="danger" disabled={saving} onClick={() => void handleDeleteReaction(reaction.reaction_id)}>
                      {t("common.delete")}
                    </InspectorMicroButton>
                  </div>
                </InspectorListItem>
              ))}
              {reactions.length === 0 ? <li className="text-[11px] text-ds-text-tertiary">{t("stage1.inspector.noReactions")}</li> : null}
            </ul>
          </InspectorSection>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
