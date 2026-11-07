import type { CognitiveSignal, IntelligenceTimelineEntry, MarketContextSlice, MarketStateCategory } from "../../types/marketIntelligence";
import { useTranslation } from "../../i18n";
import { MtfChart, TimeframeSwitcher } from "./MtfChart";
import type { MtfSection } from "../../types/visualCognition";

const STATE_ACCENT: Record<MarketStateCategory, string> = {
  Accumulation: "text-emerald-400",
  Distribution: "text-amber-400",
  Continuation: "text-sky-400",
  Exhaustion: "text-orange-400",
  Transition: "text-violet-400",
  Neutral: "text-ds-text-secondary",
};

function SignalIcon({ id }: { id: string }) {
  const paths: Record<string, string> = {
    participation: "M12 4.5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Zm0 3a1 1 0 1 1 0 2 1 1 0 0 1 0-2Zm-3.5 6.5a3.5 3.5 0 0 1 7 0",
    persistence: "M5 12h14M12 5v14M7 7l10 10M17 7 7 17",
    effort_result: "M6 16h12M8 12h8M10 8h4",
    auction_regime: "M12 3l7 4v10l-7 4-7-4V7l7-4Z",
    trend_continuation: "M4 16l4-6 4 3 8-10",
  };
  const d = paths[id] ?? paths.participation;
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function formatCursorTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso.replace("T", " ").slice(0, 16);
  }
}

function formatTimelineTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso.replace("T", " ").slice(0, 16);
  }
}

function confidenceLabel(value: number | null, t: (key: string) => string): string {
  if (value == null) return "—";
  if (value >= 75) return t("marketIntelligence.confidenceHigh");
  if (value >= 55) return t("marketIntelligence.confidenceModerate");
  return t("marketIntelligence.confidenceLow");
}

export function MarketStateHero({
  category,
  headline,
  narrative,
  cursorTimestamp,
  propagationSummary,
}: {
  category: MarketStateCategory;
  headline: string;
  narrative: string;
  cursorTimestamp: string | null;
  propagationSummary: string | null;
}) {
  const { t } = useTranslation();
  return (
    <article className="ops-card relative overflow-hidden p-6 sm:p-8">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          background: "radial-gradient(ellipse 80% 60% at 20% 0%, var(--ds-color-accent), transparent 70%)",
        }}
        aria-hidden
      />
      <div className="relative">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ds-text-tertiary">{t("marketIntelligence.currentMarketState")}</p>
        <p className={`mt-3 font-ds-display text-[13px] font-semibold uppercase tracking-[0.2em] ${STATE_ACCENT[category]}`}>
          {category}
        </p>
        <h2 className="mt-1 font-ds-display text-[clamp(1.75rem,4vw,2.75rem)] font-semibold leading-[1.1] tracking-tight text-ds-text-primary">
          {headline}
        </h2>
        <p className="mt-4 max-w-3xl text-[15px] leading-relaxed text-ds-text-secondary">{narrative}</p>
        <div className="mt-6 flex flex-wrap items-center gap-4 text-[12px] text-ds-text-tertiary">
          <span>{t("marketIntelligence.observed", { time: formatCursorTime(cursorTimestamp) })}</span>
          {propagationSummary ? (
            <>
              <span className="hidden h-1 w-1 rounded-full bg-ds-text-tertiary sm:inline-block" aria-hidden />
              <span className="max-w-xl truncate">{propagationSummary}</span>
            </>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function CognitiveSignalGrid({ signals }: { signals: CognitiveSignal[] }) {
  const { t } = useTranslation();
  return (
    <section aria-label={t("marketIntelligence.activeSignals")}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{t("marketIntelligence.activeSignals")}</h3>
        <p className="text-[11px] text-ds-text-tertiary">{t("marketIntelligence.activeSignalsSubtitle")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {signals.map((signal) => (
          <article key={signal.id} className="ops-card flex min-h-[148px] flex-col p-4">
            <div className="flex items-start justify-between gap-2">
              <span className="text-ds-text-secondary">
                <SignalIcon id={signal.id} />
              </span>
              {signal.confidence != null ? (
                <span className="rounded-ds-pill bg-ds-surface-secondary px-2 py-0.5 text-[10px] font-medium tabular-nums text-ds-text-tertiary">
                  {signal.confidence}%
                </span>
              ) : null}
            </div>
            <p className="mt-3 text-[11px] font-medium uppercase tracking-[0.08em] text-ds-text-tertiary">{signal.label}</p>
            <p className="mt-1 font-ds-display text-[18px] font-semibold leading-tight text-ds-text-primary">{signal.state}</p>
            <p className="mt-auto pt-2 text-[11px] text-ds-text-secondary">
              Confidence · {confidenceLabel(signal.confidence, t)}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

const KIND_DOT: Record<IntelligenceTimelineEntry["kind"], string> = {
  transition: "bg-violet-400",
  signal: "bg-sky-400",
  event: "bg-ds-text-tertiary",
};

export function CognitionEvolutionTimeline({
  entries,
  onSelect,
}: {
  entries: IntelligenceTimelineEntry[];
  onSelect: (entry: IntelligenceTimelineEntry) => void;
}) {
  const { t } = useTranslation();
  if (entries.length === 0) {
    return (
      <div className="ops-card flex min-h-[120px] items-center justify-center p-6 text-[13px] text-ds-text-secondary">
        {t("marketIntelligence.noEvolution")}
      </div>
    );
  }

  return (
    <section aria-label={t("marketIntelligence.recentEvolution")}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{t("marketIntelligence.recentEvolution")}</h3>
        <p className="text-[11px] text-ds-text-tertiary">{t("marketIntelligence.evolutionSubtitle")}</p>
      </div>
      <div className="ops-card overflow-hidden p-4">
        <div className="panel-scroll flex gap-3 overflow-x-auto pb-1">
          {entries.map((entry, index) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => onSelect(entry)}
              className={`group relative min-w-[200px] max-w-[240px] shrink-0 rounded-2xl px-4 py-3 text-left transition-all duration-ds ${
                entry.active
                  ? "bg-ds-surface-secondary shadow-ds-md ring-1 ring-ds-border"
                  : "bg-ds-surface-secondary/40 hover:bg-ds-surface-secondary/80"
              }`}
            >
              {index < entries.length - 1 ? (
                <span
                  className="pointer-events-none absolute right-[-10px] top-1/2 z-10 hidden h-px w-5 bg-ds-border sm:block"
                  aria-hidden
                />
              ) : null}
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${KIND_DOT[entry.kind]}`} aria-hidden />
                <span className="text-[10px] tabular-nums text-ds-text-tertiary">{formatTimelineTime(entry.timestamp)}</span>
              </div>
              <p className="mt-2 line-clamp-2 text-[13px] font-medium leading-snug text-ds-text-primary">{entry.title}</p>
              <p className="mt-1 line-clamp-2 text-[11px] text-ds-text-secondary">{entry.subtitle}</p>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

export function MarketContextRow({ slices }: { slices: MarketContextSlice[] }) {
  const { t } = useTranslation();
  return (
    <section aria-label={t("marketIntelligence.marketContext")}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{t("marketIntelligence.marketContext")}</h3>
        <p className="text-[11px] text-ds-text-tertiary">{t("marketIntelligence.contextSubtitle")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {slices.map((slice) => (
          <article key={slice.id} className="ops-card p-4">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-ds-text-tertiary">{slice.label}</p>
            <p className="mt-2 font-ds-display text-[17px] font-semibold leading-snug text-ds-text-primary">{slice.value}</p>
            {slice.detail ? <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-ds-text-secondary">{slice.detail}</p> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

export function StructureChartPanel({
  className,
  activeTf,
  timeframes,
  onTfChange,
  section,
  cursorIndices,
  stage1Stats,
}: {
  className?: string;
  activeTf: string;
  timeframes: string[];
  onTfChange: (tf: string) => void;
  section: MtfSection | undefined;
  cursorIndices?: Record<string, number | null>;
  stage1Stats?: Record<string, { bar_count: number; marker_counts: Record<string, number> }>;
}) {
  const { t } = useTranslation();
  return (
    <section aria-label={t("marketIntelligence.priceStructure")} className={`flex min-h-0 flex-col ${className ?? ""}`}>
      <div className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{t("marketIntelligence.priceStructure")}</h3>
          <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{t("marketIntelligence.priceStructureSubtitle")}</p>
        </div>
        <TimeframeSwitcher timeframes={timeframes} active={activeTf} onChange={onTfChange} />
      </div>
      <div className="ops-card flex min-h-0 flex-1 flex-col overflow-hidden p-2">
        <MtfChart
          key={activeTf}
          timeframe={activeTf}
          bars={section?.bars ?? []}
          cursorIndex={section?.cursor_index ?? cursorIndices?.[activeTf]}
          annotations={section?.annotations ?? []}
          barCount={section?.bar_count ?? stage1Stats?.[activeTf]?.bar_count}
          markerCounts={section?.marker_counts ?? stage1Stats?.[activeTf]?.marker_counts}
        />
      </div>
    </section>
  );
}
