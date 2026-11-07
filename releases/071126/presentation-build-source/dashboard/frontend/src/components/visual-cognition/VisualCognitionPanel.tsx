import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchVisualCognitionSnapshot } from "../../api/visualCognitionClient";
import { useTranslation } from "../../i18n";
import type { IntelligenceTimelineEntry } from "../../types/marketIntelligence";
import type { VisualCognitionSnapshot } from "../../types/visualCognition";
import {
  CognitionEvolutionTimeline,
  CognitiveSignalGrid,
  MarketContextRow,
  MarketStateHero,
  StructureChartPanel,
} from "./MarketIntelligenceViews";
import { parseMarketIntelligence } from "./parseMarketIntelligence";

const DEFAULT_TF = "M15";
const TF_STORAGE_KEY = "visual-cognition-active-tf";

function readStoredTf(fallback: string): string {
  try {
    return localStorage.getItem(TF_STORAGE_KEY) ?? fallback;
  } catch {
    return fallback;
  }
}

export function VisualCognitionPanel() {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<VisualCognitionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTf, setActiveTf] = useState(DEFAULT_TF);

  const load = useCallback(async (params?: { timestamp?: string; eventIndex?: number }) => {
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await fetchVisualCognitionSnapshot(params));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!snapshot?.timeframes?.length) return;
    const stored = readStoredTf(DEFAULT_TF);
    const valid = snapshot.timeframes.includes(stored)
      ? stored
      : snapshot.timeframes.includes(DEFAULT_TF)
        ? DEFAULT_TF
        : snapshot.timeframes[0];
    setActiveTf(valid);
  }, [snapshot?.timeframes]);

  const intelligence = useMemo(
    () => (snapshot && snapshot.status === "OK" ? parseMarketIntelligence(snapshot, activeTf) : null),
    [snapshot, activeTf],
  );

  function handleSelectTimeline(entry: IntelligenceTimelineEntry) {
    const payload: { timestamp?: string; eventIndex?: number } = { timestamp: entry.timestamp };
    if (entry.eventIndex != null) payload.eventIndex = entry.eventIndex;
    else if (entry.timelineIndex != null) payload.eventIndex = entry.timelineIndex;
    load(payload);
  }

  function handleTfChange(tf: string) {
    setActiveTf(tf);
    try {
      localStorage.setItem(TF_STORAGE_KEY, tf);
    } catch {
      /* ignore */
    }
  }

  if (!snapshot && loading) {
    return (
      <div className="ops-surface flex h-64 items-center justify-center text-[15px] text-ds-text-secondary">
        {t("visualCognition.loading")}
      </div>
    );
  }

  if (!snapshot || snapshot.status === "NO_DATA") {
    return (
      <div className="ops-surface flex h-64 items-center justify-center p-6 text-[15px] text-ds-text-secondary">
        {snapshot?.message ?? t("visualCognition.noData")}
      </div>
    );
  }

  if (snapshot.status !== "OK" || !intelligence) {
    return (
      <div className="ops-surface rounded-ds-card border border-ds-border bg-ds-surface p-6 text-[13px] text-ds-status-error">
        {snapshot.message ?? t("visualCognition.renderError")}
      </div>
    );
  }

  const timeframes = snapshot.timeframes ?? ["D1", "H4", "H1", "M15"];
  const section = snapshot.mtf_map[activeTf];

  return (
    <div className="ops-surface flex min-h-full flex-col p-4 sm:p-5">
      <header className="mb-3 shrink-0 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ds-text-tertiary">{t("visualCognition.eyebrow")}</p>
          <h1 className="font-ds-display text-[22px] font-semibold tracking-tight text-ds-text-primary sm:text-[26px]">
            {t("visualCognition.title")}
          </h1>
        </div>
        <button
          type="button"
          onClick={() => load()}
          disabled={loading}
          className="rounded-ds-button border border-ds-border bg-ds-surface px-3 py-1.5 text-[12px] font-medium text-ds-text-secondary transition-colors hover:bg-ds-surface-secondary hover:text-ds-text-primary disabled:opacity-50"
        >
          {loading ? t("common.refreshing") : t("common.refresh")}
        </button>
      </header>

      <div className="panel-scroll mb-2 flex max-h-[min(28vh,380px)] min-h-0 shrink-0 flex-col gap-3 overflow-y-auto">
        <MarketStateHero
          category={intelligence.marketState}
          headline={intelligence.headline}
          narrative={intelligence.narrative}
          cursorTimestamp={intelligence.cursorTimestamp}
          propagationSummary={intelligence.propagationSummary}
        />

        <CognitiveSignalGrid signals={intelligence.signals} />

        <CognitionEvolutionTimeline entries={intelligence.timeline} onSelect={handleSelectTimeline} />
      </div>

      <div className="mb-2 shrink-0">
        <MarketContextRow slices={intelligence.context} />
      </div>

      <StructureChartPanel
        className="min-h-[min(56vh,760px)] flex-1"
        activeTf={activeTf}
        timeframes={timeframes}
        onTfChange={handleTfChange}
        section={section}
        cursorIndices={snapshot.cursor_indices}
        stage1Stats={snapshot.stage1_stats}
      />

      {error ? <p className="mt-2 text-xs text-ds-status-error">{error}</p> : null}
    </div>
  );
}
