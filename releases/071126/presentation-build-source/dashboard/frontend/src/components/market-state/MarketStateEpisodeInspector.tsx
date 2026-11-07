import type { ReactNode } from "react";
import type { MarketStateSelection } from "./marketStateSelection";
import {
  confidenceDeltaTone,
  confidenceLevelColor,
  formatConfidenceDeltaText,
  formatConfidenceDeltaValue,
  formatConfidenceScore,
  transitionReasonText,
} from "./marketStateChartStyles";

function formatTime(value?: string | null): string {
  if (!value) return "N/A";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMetric(value?: number | null, digits = 3): string {
  return value == null || Number.isNaN(value) ? "N/A" : value.toFixed(digits);
}

function formatBool(value?: boolean | null): string {
  if (value == null) return "N/A";
  return value ? "Yes" : "No";
}

function DetailRow({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const toneClass =
    tone === "good"
      ? "text-ds-status-healthy"
      : tone === "warn"
        ? "text-ds-status-warning"
        : tone === "bad"
          ? "text-ds-status-error"
          : "text-ds-text-primary";

  return (
    <div className="border-b border-ds-border/35 py-2 last:border-0">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">{label}</div>
      <div className={`mt-0.5 break-words font-mono text-[12px] ${toneClass}`}>{value || "N/A"}</div>
    </div>
  );
}

function SectionShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">{title}</h3>
      <p className="mt-0.5 text-[10px] text-ds-text-tertiary">{subtitle}</p>
      <div className="mt-3 space-y-0">{children}</div>
    </div>
  );
}

function RegimeDetails({ selection }: { selection: Extract<MarketStateSelection, { type: "market_state_regime" }> }) {
  const regime = selection.payload;
  const levelTone =
    regime.confidence_level === "HIGH" ? "good" : regime.confidence_level === "LOW" ? "bad" : regime.confidence_level === "MEDIUM" ? "warn" : "default";

  return (
    <SectionShell title="Market State Regime" subtitle="Engine-level market_state segment · not a trade signal">
      <DetailRow label="Market State" value={regime.market_state} />
      <DetailRow label="Start Timestamp" value={formatTime(regime.start_timestamp)} />
      <DetailRow label="End Timestamp" value={formatTime(regime.end_timestamp)} />
      <DetailRow label="Duration" value={`${regime.duration_bars} bars`} />
      <DetailRow
        label="Confidence"
        value={
          regime.confidence_level
            ? `${regime.confidence_level} · ${formatConfidenceScore(regime.market_state_confidence)}`
            : formatConfidenceScore(regime.market_state_confidence)
        }
        tone={levelTone}
      />
      <DetailRow label="Average Confidence" value={formatConfidenceScore(regime.avg_confidence)} />
      <DetailRow label="Rule" value={regime.rule_id ?? "N/A"} />
      <DetailRow label="Previous Market State" value={regime.previous_market_state ?? "N/A"} />
      <DetailRow label="Active" value={regime.is_active ? "Yes" : "No"} tone={regime.is_active ? "good" : "default"} />
    </SectionShell>
  );
}

function TransitionDetails({ selection }: { selection: Extract<MarketStateSelection, { type: "market_state_transition" }> }) {
  const transition = selection.payload;
  const deltaTone = confidenceDeltaTone(transition.confidence_delta);

  return (
    <SectionShell title="Market State Transition" subtitle="Engine state change · not a trade signal">
      <DetailRow label="From → To" value={`${transition.from_market_state} → ${transition.to_market_state}`} />
      <DetailRow label="Timestamp" value={formatTime(transition.timestamp)} />
      <DetailRow label="Rule" value={transition.rule_id ?? "N/A"} />
      <DetailRow label="Rule Description" value={transition.rule_description ?? "N/A"} />
      <DetailRow label="Transition Type" value={transition.transition_type ?? "N/A"} />
      <DetailRow label="Transition Class" value={transition.transition_class ?? "N/A"} />
      <DetailRow label="Confidence Before" value={formatConfidenceScore(transition.confidence_before)} />
      <DetailRow label="Confidence After" value={formatConfidenceScore(transition.confidence_after ?? transition.market_state_confidence)} />
      <DetailRow
        label="Confidence Delta"
        value={`${formatConfidenceDeltaValue(transition.confidence_delta)} · ${formatConfidenceDeltaText(transition.confidence_delta)}`}
        tone={deltaTone}
      />
      <DetailRow label="Reason" value={transitionReasonText(transition)} />
      {transition.trader_read ? <DetailRow label="Trader Read" value={transition.trader_read} /> : null}
      {transition.confidence_explanation ? (
        <>
          <DetailRow
            label="After-state Confidence Level"
            value={`${transition.confidence_explanation.level} · ${formatConfidenceScore(transition.confidence_explanation.score)}`}
            tone={
              transition.confidence_explanation.level === "HIGH"
                ? "good"
                : transition.confidence_explanation.level === "LOW"
                  ? "bad"
                  : transition.confidence_explanation.level === "MEDIUM"
                    ? "warn"
                    : "default"
            }
          />
          <div className="rounded-lg border border-ds-border/45 bg-ds-surface/70 p-2.5 text-[11px] leading-relaxed text-ds-text-primary">
            {transition.confidence_explanation.summary}
          </div>
        </>
      ) : null}
    </SectionShell>
  );
}

function ContextEpisodeDetails({
  selection,
}: {
  selection: Extract<MarketStateSelection, { type: "directional_context_episode" }>;
}) {
  const episode = selection.payload;

  return (
    <SectionShell title="Directional Context Episode" subtitle="LONG_CONTEXT / SHORT_CONTEXT orientation · not a trade signal">
      <DetailRow label="Direction" value={episode.direction} tone={episode.direction === "LONG" ? "good" : "bad"} />
      <DetailRow label="Context State" value={episode.context_state} />
      <DetailRow label="Start Timestamp" value={formatTime(episode.start_timestamp)} />
      <DetailRow label="End Timestamp" value={formatTime(episode.end_timestamp)} />
      <DetailRow label="Duration" value={`${episode.duration_bars} bars`} />
      <DetailRow label="Active" value={episode.is_active ? "Yes" : "No"} tone={episode.is_active ? "good" : "default"} />
      <DetailRow label="Source" value={episode.source} />
      <DetailRow label="Start Price" value={formatMetric(episode.start_price, 2)} />
      <DetailRow label="End Price" value={formatMetric(episode.end_price, 2)} />
      <DetailRow label="Price Change" value={formatMetric(episode.price_change, 2)} />
      <DetailRow label="Price Change %" value={episode.price_change_pct == null ? "N/A" : `${formatMetric(episode.price_change_pct, 2)}%`} />
      <DetailRow label="Average Confidence" value={formatConfidenceScore(episode.avg_confidence)} />
      <DetailRow label="Max Confidence" value={formatConfidenceScore(episode.max_confidence)} />
      <DetailRow label="Entry Eligible (engine field)" value={formatBool(episode.entry_eligible)} />
      <DetailRow label="Context / Setup Status" value={episode.setup_status ?? "N/A"} />
      <DetailRow label="Human Message" value={episode.human_message} />
    </SectionShell>
  );
}

function TimelineEventDetails({ selection }: { selection: Extract<MarketStateSelection, { type: "timeline_event" }> }) {
  const event = selection.payload;

  return (
    <SectionShell title="Timeline Event" subtitle="Runtime timeline record · inspect only">
      <DetailRow label="Event Type" value={event.event_type} />
      <DetailRow label="Timestamp" value={formatTime(event.time)} />
      <DetailRow label="From State" value={event.from_state ?? "N/A"} />
      <DetailRow label="To State" value={event.to_state ?? event.regime ?? "N/A"} />
      <DetailRow label="Reason" value={event.reason ?? "N/A"} />
      <DetailRow label="Conviction / Confidence" value={formatMetric(event.confidence_after ?? event.conviction)} />
      {event.confidence_before != null ? <DetailRow label="Confidence Before" value={formatMetric(event.confidence_before)} /> : null}
      {event.confidence_delta != null ? (
        <DetailRow
          label="Confidence Delta"
          value={`${formatConfidenceDeltaValue(event.confidence_delta)} · ${formatConfidenceDeltaText(event.confidence_delta)}`}
          tone={confidenceDeltaTone(event.confidence_delta)}
        />
      ) : null}
      {event.rule_id ? <DetailRow label="Rule" value={event.rule_id} /> : null}
      {event.rule_description ? <DetailRow label="Rule Description" value={event.rule_description} /> : null}
      {event.transition_type ? <DetailRow label="Transition Type" value={event.transition_type} /> : null}
      {event.transition_class ? <DetailRow label="Transition Class" value={event.transition_class} /> : null}
      {event.source ? <DetailRow label="Source" value={event.source} /> : null}
      {event.decision ? <DetailRow label="Decision Field" value={event.decision} /> : null}
      {event.direction ? <DetailRow label="Direction Field" value={event.direction} /> : null}
      {event.bars_active != null ? <DetailRow label="Bars Active" value={String(event.bars_active)} /> : null}
    </SectionShell>
  );
}

export function MarketStateEpisodeInspector({ selection }: { selection: MarketStateSelection | null }) {
  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h2 className="font-ds-display text-[13px] font-semibold text-ds-text-primary">Selection Details</h2>
          <p className="mt-0.5 text-[11px] text-ds-text-secondary">Click a regime, transition, or context episode to inspect it</p>
        </div>
        {selection ? (
          <span
            className="rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-wide"
            style={{
              color: confidenceLevelColor("MEDIUM"),
              background: "color-mix(in srgb, var(--ds-color-accent) 12%, transparent)",
              border: "1px solid color-mix(in srgb, var(--ds-color-accent) 24%, transparent)",
            }}
          >
            {selection.type.replaceAll("_", " ")}
          </span>
        ) : null}
      </div>

      {!selection ? (
        <div className="rounded-lg border border-dashed border-ds-border/60 bg-ds-surface-secondary/30 px-4 py-8 text-center text-[12px] leading-relaxed text-ds-text-secondary">
          Select a regime, transition, or context episode to inspect details.
        </div>
      ) : selection.type === "market_state_regime" ? (
        <RegimeDetails selection={selection} />
      ) : selection.type === "market_state_transition" ? (
        <TransitionDetails selection={selection} />
      ) : selection.type === "directional_context_episode" ? (
        <ContextEpisodeDetails selection={selection} />
      ) : (
        <TimelineEventDetails selection={selection} />
      )}
    </section>
  );
}
