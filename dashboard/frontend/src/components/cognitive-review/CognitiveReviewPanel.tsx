import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCognitiveDynamics,
  fetchCognitiveReviewBootstrap,
  fetchCognitiveReviewContext,
  fetchCognitiveSnapshot,
  postCognitiveCompare,
} from "../../api/cognitiveReviewClient";
import type {
  CognitiveCompareResult,
  CognitiveEventClass,
  CognitiveReviewBootstrap,
  CognitiveReviewContext,
  CognitiveReviewEvent,
  CognitiveSnapshot,
} from "../../types/cognitiveReview";
import {
  COGNITIVE_EVENT_CLASSES,
  COGNITIVE_EVENT_COLORS,
  DEFAULT_COGNITIVE_CLASS_SELECTION,
  asFeatureGroups,
  asFeatureMeta,
  cognitiveEventKey,
} from "../../types/cognitiveReview";
import { formatTime } from "../visual-cognition/chartUtils";
import { AnnotationChart, type AnnotationChartHandle } from "../stage1-review/AnnotationChart";
import {
  computeMeasurement,
  formatReturnPct,
  formatUsdChange,
  reactionToMeasurement,
  type MeasurementPreview,
} from "../stage1-review/measurementUtils";
import { buildCognitiveWindowOverlayEvents } from "./cognitiveOverlayEvents";
import { useTranslation } from "../../i18n";
import { CognitiveCompareChart, CognitiveDynamicsChart } from "./CognitiveDynamicsChart";
import { CognitiveDynamicsFeaturePicker, CognitiveSignalGroups } from "./CognitiveFeatureGroups";
import {
  CompareEventRow,
  EventLibraryGroupHeader,
  EventLibraryItem,
  InfoRow,
  InspectorEmpty,
  InspectorHint,
  InspectorSection,
  KpiChip,
  ReviewCheckbox,
  ReviewStatusBadge,
  WorkflowActionButton,
  WorkflowSection,
  WorkspaceToolbarButton,
} from "./CognitiveReviewChrome";
import type { ManualReaction } from "../../types/manualAnnotations";

const SIDEBAR_GROUPS: Array<{ key: CognitiveEventClass; label: string }> = [
  { key: "BUYING_CLIMAX", label: "BUYING_CLIMAX" },
  { key: "SELLING_CLIMAX", label: "SELLING_CLIMAX" },
  { key: "STOPPING_VOLUME", label: "STOPPING_VOLUME" },
  { key: "MISSED_EVENT", label: "MISSED_EVENT" },
];

function filterEventsByClasses(
  events: CognitiveReviewEvent[],
  selection: Record<CognitiveEventClass, boolean>,
): CognitiveReviewEvent[] {
  return events.filter((event) => selection[event.event_class]);
}

function selectedOverlayClasses(selection: Record<CognitiveEventClass, boolean>): CognitiveEventClass[] {
  return COGNITIVE_EVENT_CLASSES.filter((eventClass) => selection[eventClass]);
}

export function CognitiveReviewPanel() {
  const { t } = useTranslation();
  const [bootstrap, setBootstrap] = useState<CognitiveReviewBootstrap | null>(null);
  const [classSelection, setClassSelection] = useState(DEFAULT_COGNITIVE_CLASS_SELECTION);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [context, setContext] = useState<CognitiveReviewContext | null>(null);
  const [loadingContext, setLoadingContext] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<CognitiveSnapshot | null>(null);
  const [dynamicsFeatures, setDynamicsFeatures] = useState<string[]>([]);
  const [dynamics, setDynamics] = useState<Awaited<ReturnType<typeof fetchCognitiveDynamics>> | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareSelection, setCompareSelection] = useState<Set<string>>(new Set());
  const [compareResult, setCompareResult] = useState<CognitiveCompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);
  const [measureStartIndex, setMeasureStartIndex] = useState<number | null>(null);
  const [activeMeasurement, setActiveMeasurement] = useState<MeasurementPreview | null>(null);
  const chartRef = useRef<AnnotationChartHandle>(null);

  const reloadBootstrap = useCallback(async () => {
    const payload = await fetchCognitiveReviewBootstrap();
    setBootstrap(payload);
    if (payload.dynamics_priority_features?.length) {
      setDynamicsFeatures(payload.dynamics_priority_features);
    }
    setSelectedId((prev) =>
      prev ?? (payload.events.length > 0 ? payload.events[0].annotation_id : null),
    );
  }, []);

  useEffect(() => {
    reloadBootstrap().catch((err) => setError(String(err)));
  }, [reloadBootstrap]);

  const filteredEvents = useMemo(
    () => filterEventsByClasses(bootstrap?.events ?? [], classSelection),
    [bootstrap?.events, classSelection],
  );

  const currentEvent = useMemo(() => {
    if (!filteredEvents.length) return null;
    if (selectedId) {
      const found = filteredEvents.find((event) => event.annotation_id === selectedId);
      if (found) return found;
    }
    return filteredEvents[0];
  }, [filteredEvents, selectedId]);

  const overlayClasses = useMemo(() => selectedOverlayClasses(classSelection), [classSelection]);
  const overlayClassesKey = overlayClasses.join(",");

  const featureMeta = useMemo(
    () => asFeatureMeta(bootstrap?.cognitive_features),
    [bootstrap?.cognitive_features],
  );
  const featureGroups = useMemo(
    () => asFeatureGroups(bootstrap?.feature_groups),
    [bootstrap?.feature_groups],
  );

  const featureLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const feature of featureMeta) map[feature.name] = feature.label;
    return map;
  }, [featureMeta]);

  const numericFeatures = useMemo(
    () => featureMeta.filter((feature) => feature.dtype === "numeric" || feature.dtype === "boolean").map((f) => f.name),
    [featureMeta],
  );

  const orderedDynamicsFeatures = useMemo(() => {
    const priority = bootstrap?.dynamics_priority_features ?? [];
    const priorityIndex = new Map(priority.map((name, index) => [name, index]));
    return [...dynamicsFeatures].sort((a, b) => {
      const left = priorityIndex.get(a) ?? 999;
      const right = priorityIndex.get(b) ?? 999;
      return left - right;
    });
  }, [dynamicsFeatures, bootstrap?.dynamics_priority_features]);

  const displayWindowEvents = useMemo(() => {
    if (!context || !currentEvent || !bootstrap) return [];
    return buildCognitiveWindowOverlayEvents({
      allEvents: bootstrap.events,
      context,
      classSelection,
      currentEvent,
      apiWindowEvents: context.window_events,
    });
  }, [bootstrap, context, classSelection, currentEvent]);

  const focusBarIndex = useMemo(() => {
    if (!context || (currentEvent?.bar_index == null)) return null;
    return currentEvent.bar_index - context.window_start;
  }, [context, currentEvent]);

  const savedMeasurements = useMemo(() => {
    if (!context?.bars?.length || !bootstrap?.reactions) return [];
    return (bootstrap.reactions as ManualReaction[])
      .map((reaction) => reactionToMeasurement(context.bars, reaction))
      .filter((item): item is MeasurementPreview => item != null);
  }, [context?.bars, bootstrap?.reactions]);

  useEffect(() => {
    const anchor = filteredEvents[0];
    if (anchor?.bar_index == null) {
      setContext(null);
      return;
    }
    const controller = new AbortController();
    setLoadingContext(true);
    fetchCognitiveReviewContext(
      anchor.bar_index,
      {
        zoomLevel: "FULL",
        eventClass: anchor.event_class !== "MISSED_EVENT" ? anchor.event_class : undefined,
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
  }, [overlayClassesKey, bootstrap?.total_events]);

  useEffect(() => {
    if (!currentEvent?.bar_index && currentEvent?.bar_index !== 0) return;
    chartRef.current?.centerOnEvent();
  }, [currentEvent?.annotation_id]);

  useEffect(() => {
    if (!currentEvent) {
      setSnapshot(null);
      setDynamics(null);
      return;
    }
    const controller = new AbortController();
    const barIndex = currentEvent.bar_index ?? undefined;
    Promise.all([
      fetchCognitiveSnapshot({ barIndex, timestamp: currentEvent.timestamp }, controller.signal),
      fetchCognitiveDynamics(
        { barIndex, timestamp: currentEvent.timestamp, features: dynamicsFeatures },
        controller.signal,
      ),
    ])
      .then(([snap, dyn]) => {
        if (!controller.signal.aborted) {
          setSnapshot(snap);
          setDynamics(dyn);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(String(err));
      });
    return () => controller.abort();
  }, [currentEvent?.annotation_id, currentEvent?.bar_index, currentEvent?.timestamp, dynamicsFeatures.join(",")]);

  function selectEvent(event: CognitiveReviewEvent) {
    setSelectedId(event.annotation_id);
    setMeasureMode(false);
    setMeasureStartIndex(null);
    setActiveMeasurement(null);
    requestAnimationFrame(() => chartRef.current?.centerOnEvent());
  }

  function goPrevious() {
    if (!currentEvent) return;
    const idx = filteredEvents.findIndex((event) => event.annotation_id === currentEvent.annotation_id);
    if (idx > 0) selectEvent(filteredEvents[idx - 1]);
  }

  function goNext() {
    if (!currentEvent) return;
    const idx = filteredEvents.findIndex((event) => event.annotation_id === currentEvent.annotation_id);
    if (idx >= 0 && idx < filteredEvents.length - 1) selectEvent(filteredEvents[idx + 1]);
  }

  function handleBarClick(barIndexInWindow: number) {
    if (!measureMode || !context?.bars) return;
    if (measureStartIndex == null) {
      setMeasureStartIndex(barIndexInWindow);
      setActiveMeasurement(null);
      return;
    }
    const measurement = computeMeasurement(context.bars, measureStartIndex, barIndexInWindow);
    setActiveMeasurement(measurement);
    setMeasureStartIndex(null);
  }

  function handleEventClick(event: { timestamp: string; event_class: string }) {
    const match = bootstrap?.events.find(
      (item) => item.timestamp === event.timestamp && item.event_class === event.event_class,
    );
    if (match) selectEvent(match);
  }

  function toggleCompareId(id: string) {
    setCompareSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runCompare(mode: "selection" | "presets") {
    setCompareLoading(true);
    setCompareResult(null);
    try {
      if (mode === "selection") {
        const result = await postCognitiveCompare({
          annotation_ids: Array.from(compareSelection),
          features: dynamicsFeatures.filter((name) => numericFeatures.includes(name)),
        });
        setCompareResult(result);
      } else {
        const groups = (bootstrap?.compare_presets ?? []).map((preset) => ({
          label: preset.label,
          annotation_ids: preset.annotation_ids,
        }));
        const result = await postCognitiveCompare({ groups, features: dynamicsFeatures.filter((name) => numericFeatures.includes(name)) });
        setCompareResult(result);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setCompareLoading(false);
    }
  }

  const eventsByGroup = useMemo(() => {
    const map = new Map<CognitiveEventClass, CognitiveReviewEvent[]>();
    for (const group of SIDEBAR_GROUPS) map.set(group.key, []);
    for (const event of filteredEvents) {
      map.get(event.event_class)?.push(event);
    }
    return map;
  }, [filteredEvents]);

  const currentIdx = currentEvent
    ? filteredEvents.findIndex((e) => e.annotation_id === currentEvent.annotation_id)
    : -1;

  const keyEventCount = useMemo(
    () => (bootstrap?.events ?? []).filter((event) => event.is_key_event).length,
    [bootstrap?.events],
  );

  return (
    <div className="ops-surface flex h-full min-h-0 flex-col gap-3 p-3 sm:p-4 text-ds-text-primary">
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-4 border-b border-ds-border/60 pb-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ds-text-tertiary">{t("cognitiveReview.eyebrow")}</p>
          <h1 className="font-ds-display text-[20px] font-semibold tracking-tight text-ds-text-primary sm:text-[22px]">
            {t("cognitiveReview.title")}
          </h1>
          <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{t("cognitiveReview.subtitle")}</p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <KpiChip label={t("cognitiveReview.kpi.events")} value={bootstrap?.total_events ?? 0} />
          <KpiChip label={t("cognitiveReview.kpi.visible")} value={filteredEvents.length} />
          <KpiChip label={t("cognitiveReview.kpi.anchors")} value={bootstrap?.anchors.length ?? 0} />
          <KpiChip label={t("cognitiveReview.kpi.links")} value={bootstrap?.links.length ?? 0} />
          <KpiChip label={t("cognitiveReview.kpi.keyEvents")} value={keyEventCount} accent="#0a84ff" />
        </div>
      </header>

      {error ? (
        <div className="ops-card shrink-0 border border-red-500/20 px-3 py-2 text-[11px] text-ds-status-error">{error}</div>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_320px] gap-3">
        <aside className="panel-scroll flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5">
          <WorkflowSection title={t("cognitiveReview.library.title")} subtitle={t("cognitiveReview.library.subtitle")}>
            <div className="space-y-2">
              {COGNITIVE_EVENT_CLASSES.map((eventClass) => (
                <ReviewCheckbox
                  key={eventClass}
                  checked={classSelection[eventClass]}
                  onChange={() =>
                    setClassSelection((prev) => ({ ...prev, [eventClass]: !prev[eventClass] }))
                  }
                  swatch={COGNITIVE_EVENT_COLORS[eventClass]}
                  label={
                    <>
                      {eventClass}
                      <span className="ml-1 text-ds-text-tertiary">({bootstrap?.counts[eventClass] ?? 0})</span>
                    </>
                  }
                />
              ))}
            </div>
          </WorkflowSection>

          {SIDEBAR_GROUPS.map((group) => {
            const items = eventsByGroup.get(group.key) ?? [];
            if (!classSelection[group.key] || items.length === 0) return null;
            return (
              <section key={group.key}>
                <EventLibraryGroupHeader eventClass={group.key} label={group.label} count={items.length} />
                <div className="ops-card p-2">
                  <ul className="panel-scroll max-h-52 space-y-1.5 overflow-y-auto">
                    {items.map((event) => (
                      <EventLibraryItem
                        key={cognitiveEventKey(event)}
                        event={event}
                        active={currentEvent?.annotation_id === event.annotation_id}
                        onSelect={() => selectEvent(event)}
                      />
                    ))}
                  </ul>
                </div>
              </section>
            );
          })}

          <WorkflowSection title={t("cognitiveReview.browse.title")} subtitle={t("cognitiveReview.browse.subtitle")}>
            <WorkflowActionButton disabled={!currentEvent} variant="warning" onClick={() => chartRef.current?.centerOnEvent()}>
              {t("cognitiveReview.browse.goToEvent")}
            </WorkflowActionButton>
            <div className="grid grid-cols-2 gap-2">
              <WorkflowActionButton disabled={!currentEvent || currentIdx <= 0} onClick={goPrevious}>
                {t("cognitiveReview.browse.prev")}
              </WorkflowActionButton>
              <WorkflowActionButton
                disabled={!currentEvent || currentIdx >= filteredEvents.length - 1}
                onClick={goNext}
              >
                {t("cognitiveReview.browse.next")}
              </WorkflowActionButton>
            </div>
            <WorkflowActionButton
              active={measureMode}
              variant="violet"
              disabled={!context?.bars?.length}
              onClick={() => {
                setMeasureMode((prev) => !prev);
                setMeasureStartIndex(null);
                setActiveMeasurement(null);
              }}
            >
              {t("cognitiveReview.browse.measure")}
            </WorkflowActionButton>
            <WorkflowActionButton active={compareOpen} variant="sky" onClick={() => setCompareOpen((prev) => !prev)}>
              {t("cognitiveReview.browse.compare")}
            </WorkflowActionButton>
          </WorkflowSection>
        </aside>

        <section className="flex min-h-0 flex-col">
          <div className="ops-card flex min-h-0 flex-1 flex-col p-2 sm:p-3">
            <div className="mb-2 flex shrink-0 items-center justify-between px-0.5 text-[11px] text-ds-text-tertiary">
              <span>{t("cognitiveReview.chartChrome")}</span>
              {currentEvent ? (
                <span className="text-ds-text-primary">
                  <span style={{ color: COGNITIVE_EVENT_COLORS[currentEvent.event_class] }}>
                    {currentEvent.display_class}
                  </span>
                  {" · "}
                  {formatTime(currentEvent.timestamp)}
                </span>
              ) : null}
            </div>

            <div className="min-h-0 flex-1">
              {loadingContext ? (
                <div className="flex h-full items-center justify-center text-sm text-ds-text-tertiary">{t("cognitiveReview.chartLoading")}</div>
              ) : context?.bars?.length ? (
                <AnnotationChart
                  ref={chartRef}
                  bars={context.bars}
                  focusBarIndex={focusBarIndex}
                  windowEvents={displayWindowEvents}
                  manualAnnotations={[]}
                  manualAnchors={bootstrap?.anchors ?? []}
                  manualLinks={bootstrap?.links ?? []}
                  showAllInWindow
                  measureKind={measureMode ? "measure" : null}
                  measureStartIndex={measureStartIndex}
                  activeMeasurement={activeMeasurement}
                  savedMeasurements={savedMeasurements}
                  onBarClick={handleBarClick}
                  onEventClick={handleEventClick}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-ds-text-tertiary">{t("cognitiveReview.noChartData")}</div>
              )}
            </div>

            {activeMeasurement ? (
              <InspectorHint>
                {formatUsdChange(activeMeasurement.absolute_price_change)} · {formatReturnPct(activeMeasurement.return_pct)}
              </InspectorHint>
            ) : null}
          </div>
        </section>

        <aside className="panel-scroll flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5">
          <InspectorSection title={t("cognitiveReview.inspector.context")} meta={currentEvent ? formatTime(currentEvent.timestamp) : undefined}>
            {currentEvent ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ReviewStatusBadge status={currentEvent.review_status} />
                  {currentEvent.is_key_event ? (
                    <span className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-400">
                      {t("cognitiveReview.inspector.keyEvent")}
                    </span>
                  ) : null}
                </div>
                <InfoRow label="timestamp" value={currentEvent.timestamp} />
                <InfoRow label="event_class" value={currentEvent.display_class} />
                <InfoRow label="review_type" value={currentEvent.review_type} />
                {currentEvent.human_event_class ? (
                  <InfoRow label="human_class" value={currentEvent.human_event_class} />
                ) : null}
                {currentEvent.review_note_ru ? (
                  <InspectorHint>{currentEvent.review_note_ru}</InspectorHint>
                ) : null}
              </div>
            ) : (
              <InspectorEmpty>{t("cognitiveReview.inspector.selectEvent")}</InspectorEmpty>
            )}
          </InspectorSection>

          <InspectorSection title={t("cognitiveReview.inspector.signals")} meta="T = 0">
            {snapshot?.features && featureGroups.length ? (
              <div className="panel-scroll max-h-72 overflow-y-auto">
                <CognitiveSignalGroups
                  groups={featureGroups}
                  featureMeta={featureMeta}
                  features={snapshot.features}
                />
              </div>
            ) : (
              <InspectorEmpty>{t("cognitiveReview.inspector.noCognition")}</InspectorEmpty>
            )}
          </InspectorSection>

          <InspectorSection
            title={t("cognitiveReview.inspector.dynamics")}
            meta={`−${bootstrap?.dynamics_before_bars ?? 128} / +${bootstrap?.dynamics_after_bars ?? 64}`}
          >
            <div className="panel-scroll mb-3 max-h-40 overflow-y-auto">
              <CognitiveDynamicsFeaturePicker
                groups={featureGroups}
                featureMeta={featureMeta}
                selected={dynamicsFeatures}
                onChange={setDynamicsFeatures}
              />
            </div>

            {dynamics?.series ? (
              <CognitiveDynamicsChart
                series={dynamics.series}
                selectedFeatures={orderedDynamicsFeatures}
                featureMeta={featureMeta}
                beforeBars={dynamics.before_bars}
                afterBars={dynamics.after_bars}
              />
            ) : (
              <InspectorEmpty>{t("cognitiveReview.inspector.loadingDynamics")}</InspectorEmpty>
            )}
          </InspectorSection>

          {compareOpen ? (
            <InspectorSection title={t("cognitiveReview.inspector.compare")} meta={t("cognitiveReview.inspector.selected", { count: compareSelection.size })}>
              <div className="panel-scroll mb-3 max-h-36 space-y-1 overflow-y-auto">
                {filteredEvents.map((event) => (
                  <CompareEventRow
                    key={event.annotation_id}
                    event={event}
                    checked={compareSelection.has(event.annotation_id)}
                    onToggle={() => toggleCompareId(event.annotation_id)}
                  />
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <WorkspaceToolbarButton
                  disabled={compareSelection.size === 0 || compareLoading}
                  onClick={() => runCompare("selection")}
                >
                  {t("cognitiveReview.inspector.aggregate")}
                </WorkspaceToolbarButton>
                <WorkspaceToolbarButton disabled={compareLoading} onClick={() => runCompare("presets")}>
                  {t("cognitiveReview.inspector.byClass")}
                </WorkspaceToolbarButton>
              </div>
              {compareLoading ? <p className="mt-2 text-[10px] text-ds-text-tertiary">{t("common.computing")}</p> : null}
              {compareResult?.groups?.length ? (
                <div className="mt-3 space-y-2">
                  {orderedDynamicsFeatures
                    .filter((name) => numericFeatures.includes(name))
                    .map((name) => (
                      <CognitiveCompareChart
                        key={name}
                        groups={compareResult.groups}
                        featureName={name}
                        featureLabel={featureLabels[name] ?? name}
                        beforeBars={compareResult.before_bars}
                        afterBars={compareResult.after_bars}
                      />
                    ))}
                </div>
              ) : null}
            </InspectorSection>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
