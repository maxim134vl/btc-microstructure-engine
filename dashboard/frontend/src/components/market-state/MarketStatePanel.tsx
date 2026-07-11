import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fetchMarketStateSnapshot } from "../../api/marketStateClient";
import type { HistoryRange, MarketStateSnapshot, Timeframe, TimelineEvent, ViewMode } from "../../types/marketState";
import { decisionColor, decisionLabel, confidenceLevelColor, formatConfidenceDeltaText, formatConfidenceDeltaValue, formatConfidenceScore, marketStateRegimeColor, transitionReasonText } from "./marketStateChartStyles";
import { MarketStateChart } from "./MarketStateChart";
import { MarketStateEpisodeInspector } from "./MarketStateEpisodeInspector";
import { MarketStateInspector } from "./MarketStateInspector";
import {
  isMarketStateSelection,
  selectableRowClass,
  selectableSurfaceClass,
  timelineEventKey,
  type ChartViewAction,
  type ChartViewCommand,
  type MarketStateSelection,
} from "./marketStateSelection";

const DEFAULT_BAR_LIMIT = 500;
const TIMEFRAMES: Timeframe[] = ["M15", "M30", "H1", "H4", "D1"];
const MODES: ViewMode[] = ["latest", "replay", "range"];
const HISTORY_RANGES: Array<{ value: HistoryRange; label: string }> = [
  { value: "100", label: "Last 100 bars" },
  { value: "250", label: "Last 250 bars" },
  { value: "500", label: "Last 500 bars" },
  { value: "all", label: "Full available history" },
];
const TIMELINE_FILTERS = ["All", "Setups", "Exits", "Regime Changes", "Warnings"] as const;
type TimelineFilter = (typeof TIMELINE_FILTERS)[number];

function formatMetric(value?: number | null, digits = 3): string {
  return value == null || Number.isNaN(value) ? "N/A" : value.toFixed(digits);
}

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

function ToggleButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-3 py-1.5 text-[11px] transition ${
        active
          ? "border-ds-accent bg-ds-accent/10 text-ds-text-primary"
          : "border-ds-border bg-ds-surface-secondary/50 text-ds-text-secondary hover:border-ds-border-strong"
      }`}
    >
      {children}
    </button>
  );
}

function EmptyPanel({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-ds-border/60 bg-ds-surface-secondary/25 px-4 py-6 text-center text-[12px] leading-relaxed text-ds-text-secondary">
      {message}
    </div>
  );
}

function eventColor(event: TimelineEvent): string {
  if (event.event_type === "REGIME_START" || event.event_type === "REGIME_CHANGE") return "var(--ds-status-running)";
  if (event.event_type === "WARNING") return "var(--ds-status-idle)";
  if (event.event_type === "LONG_SETUP") return "var(--ds-status-healthy)";
  if (event.event_type === "SHORT_SETUP" || event.decision === "SHORT_SETUP") return "var(--ds-status-error)";
  if (event.event_type.startsWith("EXIT")) return "var(--ds-status-warning)";
  if (event.event_type === "INVALIDATED") return "var(--ds-status-idle)";
  return decisionColor(event.decision ?? event.event_type);
}

function eventMatchesFilter(event: TimelineEvent, filter: TimelineFilter): boolean {
  if (filter === "All") return true;
  if (filter === "Setups") return event.event_type === "LONG_SETUP" || event.event_type === "SHORT_SETUP";
  if (filter === "Exits") return event.event_type.startsWith("EXIT") || event.event_type === "INVALIDATED";
  if (filter === "Regime Changes") return event.event_type === "REGIME_START" || event.event_type === "REGIME_CHANGE";
  if (filter === "Warnings") return event.event_type === "WARNING";
  return true;
}

function TimelineTable({
  events,
  selection,
  onSelect,
}: {
  events: TimelineEvent[];
  selection: MarketStateSelection | null;
  onSelect: (selection: MarketStateSelection) => void;
}) {
  const [filter, setFilter] = useState<TimelineFilter>("All");
  const rows = events
    .map((event, index) => ({ event, id: timelineEventKey(event, index) }))
    .filter(({ event }) => eventMatchesFilter(event, filter))
    .reverse();
  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface">
      <div className="border-b border-ds-border/50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Decision Timeline</h3>
            <p className="mt-0.5 text-[11px] text-ds-text-secondary">Event history: setups, exits, regime changes and warnings</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {TIMELINE_FILTERS.map((item) => (
              <ToggleButton key={item} active={filter === item} onClick={() => setFilter(item)}>
                {item}
              </ToggleButton>
            ))}
          </div>
        </div>
      </div>
      <div className="max-h-[360px] overflow-auto">
        <table className="w-full min-w-[920px] border-collapse text-left text-[11px]">
          <thead className="sticky top-0 z-10 bg-ds-surface-secondary text-[10px] uppercase tracking-wide text-ds-text-secondary">
            <tr>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">Event Type</th>
              <th className="px-3 py-2">Decision</th>
              <th className="px-3 py-2">Direction</th>
              <th className="px-3 py-2">Regime</th>
              <th className="px-3 py-2">Reason</th>
              <th className="px-3 py-2">Confidence</th>
              <th className="px-3 py-2">Bars Active</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ event, id }) => (
              <tr
                key={id}
                className={selectableRowClass(isMarketStateSelection(selection, "timeline_event", id))}
                onClick={() => onSelect({ type: "timeline_event", id, payload: event })}
              >
                <td className="px-3 py-2 font-mono text-ds-text-secondary">{formatTime(event.time)}</td>
                <td className="px-3 py-2 font-semibold" style={{ color: eventColor(event) }}>
                  {event.event_type}
                </td>
                <td className="px-3 py-2 font-mono text-ds-text-primary">{event.decision ?? "N/A"}</td>
                <td className="px-3 py-2 font-mono text-ds-text-secondary">{event.direction ?? "—"}</td>
                <td className="max-w-[220px] truncate px-3 py-2 text-ds-text-primary" title={event.regime ?? event.to_state ?? undefined}>
                  {event.regime ?? event.to_state ?? "N/A"}
                </td>
                <td className="max-w-[320px] truncate px-3 py-2 text-ds-text-secondary" title={event.reason ?? undefined}>
                  {event.reason ?? "N/A"}
                </td>
                <td className="px-3 py-2 font-mono">{formatMetric(event.conviction)}</td>
                <td className="px-3 py-2 font-mono text-ds-text-secondary">{event.bars_active ?? "—"}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-ds-text-secondary">
                  No important timeline events in the selected range.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ActiveMarketStateBanner({ snapshot }: { snapshot: MarketStateSnapshot }) {
  const current = snapshot.current_state;
  const regime = current.active_market_state_regime;
  const explanation = current.confidence_explanation;
  const context = current.active_directional_context_episode;
  const latestTransition = current.latest_market_state_transition;
  const level = explanation?.level ?? regime?.confidence_level ?? "UNKNOWN";
  const score = explanation?.score ?? regime?.market_state_confidence ?? current.conviction;

  if (!regime && !explanation && !context && !latestTransition) return null;

  return (
    <section className="shrink-0 border-b border-ds-border/50 bg-gradient-to-r from-ds-surface-secondary/70 via-ds-surface to-ds-surface-secondary/40 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-[240px] flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-ds-text-secondary">Active Market State Regime</div>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h2 className="font-ds-display text-[22px] font-semibold text-ds-text-primary">
              {regime?.market_state ?? current.current_market_phase ?? "N/A"}
            </h2>
            {regime?.is_active ? (
              <span className="rounded-full border border-ds-color-accent/35 bg-ds-accent/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-wide text-ds-accent">
                Active
              </span>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ds-text-secondary">
            <span>
              Since <span className="font-mono text-ds-text-primary">{formatTime(regime?.start_timestamp)}</span>
            </span>
            <span>
              Duration <span className="font-mono text-ds-text-primary">{regime?.duration_bars ?? "N/A"} bars</span>
            </span>
            {regime?.rule_id ? (
              <span>
                Rule <span className="font-mono text-ds-text-primary">{regime.rule_id}</span>
              </span>
            ) : null}
          </div>
          {explanation?.summary ? (
            <p className="mt-2 max-w-4xl text-[12px] leading-relaxed text-ds-text-primary">{explanation.summary}</p>
          ) : null}
        </div>

        <div className="flex min-w-[220px] flex-col items-end gap-2">
          <div
            className="rounded-xl border px-4 py-3 text-right shadow-sm"
            style={{
              borderColor: `color-mix(in srgb, ${confidenceLevelColor(level)} 30%, transparent)`,
              background: `color-mix(in srgb, ${confidenceLevelColor(level)} 10%, var(--ds-color-surface))`,
            }}
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">Confidence</div>
            <div className="mt-1 font-mono text-[28px] font-semibold leading-none" style={{ color: confidenceLevelColor(level) }}>
              {formatConfidenceScore(score)}
            </div>
            <div className="mt-1 text-[11px] font-black uppercase tracking-wide" style={{ color: confidenceLevelColor(level) }}>
              {level}
            </div>
          </div>
        </div>
      </div>

      {context ? (
        <div
          className="mt-3 rounded-lg border px-3 py-2 text-[11px]"
          style={{
            borderColor: context.direction === "LONG" ? "color-mix(in srgb, var(--ds-status-healthy) 30%, transparent)" : "color-mix(in srgb, var(--ds-status-error) 30%, transparent)",
            background: context.direction === "LONG" ? "color-mix(in srgb, var(--ds-status-healthy) 8%, transparent)" : "color-mix(in srgb, var(--ds-status-error) 8%, transparent)",
          }}
        >
          <span className="font-semibold uppercase tracking-wide text-ds-text-secondary">Directional Context · </span>
          <span className="font-mono text-ds-text-primary">
            {context.context_state} · {context.duration_bars} bars · {context.human_message}
          </span>
        </div>
      ) : null}

      {latestTransition ? (
        <div className="mt-3 rounded-lg border border-ds-color-accent/25 bg-ds-accent/5 px-3 py-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">Latest Market State Transition · Engine state change</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
            <span className="font-mono font-semibold text-ds-text-primary">
              {latestTransition.from_market_state} → {latestTransition.to_market_state}
            </span>
            <span className="text-ds-text-secondary">{formatTime(latestTransition.timestamp)}</span>
            {latestTransition.rule_id ? <span className="font-mono text-ds-text-secondary">Rule {latestTransition.rule_id}</span> : null}
            <span className="text-ds-text-secondary">
              {formatConfidenceDeltaValue(latestTransition.confidence_delta)} · {formatConfidenceDeltaText(latestTransition.confidence_delta)}
            </span>
          </div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-ds-text-primary">{transitionReasonText(latestTransition)}</p>
        </div>
      ) : null}
    </section>
  );
}

function MarketStateTransitionsTable({
  snapshot,
  selection,
  onSelect,
}: {
  snapshot: MarketStateSnapshot;
  selection: MarketStateSelection | null;
  onSelect: (selection: MarketStateSelection) => void;
}) {
  const transitions = (snapshot.market_state_transitions ?? []).slice(-20).reverse();

  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface">
      <div className="border-b border-ds-border/50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Market State Transitions</h3>
            <p className="mt-0.5 text-[11px] text-ds-text-secondary">Engine-level state changes · not trade signals</p>
          </div>
          <span className="rounded-full bg-ds-surface-secondary px-2 py-1 text-[10px] text-ds-text-secondary">
            {transitions.length} shown
          </span>
        </div>
      </div>
      {!transitions.length ? (
        <div className="p-4">
          <EmptyPanel message="No market state transitions in the selected range. Engine state may be unchanged across these bars." />
        </div>
      ) : (
      <div className="max-h-[360px] overflow-auto">
        <table className="w-full min-w-[920px] border-collapse text-left text-[11px]">
          <thead className="sticky top-0 z-10 bg-ds-surface-secondary text-[10px] uppercase tracking-wide text-ds-text-secondary">
            <tr>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">From → To</th>
              <th className="px-3 py-2">Rule</th>
              <th className="px-3 py-2">Conf. Delta</th>
              <th className="px-3 py-2">Class</th>
              <th className="px-3 py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {transitions.map((transition) => (
              <tr
                key={transition.transition_id}
                className={selectableRowClass(isMarketStateSelection(selection, "market_state_transition", transition.transition_id))}
                onClick={() =>
                  onSelect({
                    type: "market_state_transition",
                    id: transition.transition_id,
                    payload: transition,
                  })
                }
              >
                <td className="px-3 py-2 font-mono text-ds-text-secondary">{formatTime(transition.timestamp)}</td>
                <td className="px-3 py-2 font-mono font-semibold text-ds-color-accent">
                  {transition.from_market_state} → {transition.to_market_state}
                </td>
                <td className="px-3 py-2 font-mono text-ds-text-primary">{transition.rule_id ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-ds-text-primary" title={formatConfidenceDeltaText(transition.confidence_delta)}>
                  {formatConfidenceDeltaValue(transition.confidence_delta)}
                </td>
                <td className="px-3 py-2 text-ds-text-secondary">{transition.transition_class ?? transition.transition_type ?? "—"}</td>
                <td className="max-w-[360px] truncate px-3 py-2 text-ds-text-secondary" title={transitionReasonText(transition)}>
                  {transitionReasonText(transition)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </section>
  );
}

function RegimeFlow({ snapshot }: { snapshot: MarketStateSnapshot }) {
  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Cognitive Regime Flow</h3>
          <p className="text-[11px] text-ds-text-secondary">Debounced consecutive cognitive/probabilistic regimes</p>
        </div>
        <span className="rounded-full bg-ds-surface-secondary px-2 py-1 text-[10px] text-ds-text-secondary">
          {snapshot.regimes.length} regimes
        </span>
      </div>
      <div className="flex h-10 overflow-hidden rounded-lg border border-ds-border/50">
        {snapshot.regimes.map((regime, index) => (
          <div
            key={regime.regime_id}
            className="h-full min-w-[4px]"
            title={`${regime.regime_id}: ${regime.primary_state} · ${regime.duration_bars} bars`}
            style={{
              width: `${Math.max(4, regime.duration_bars * 10)}px`,
              background: `linear-gradient(180deg, ${decisionColor(regime.dominant_decision_state)}, transparent)`,
            }}
          >
            <span className="sr-only">{index}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-2 text-[11px]">
        {snapshot.regimes.slice(-4).map((regime) => (
          <div key={regime.regime_id} className="rounded-lg border border-ds-border/45 bg-ds-surface-secondary/40 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-semibold text-ds-text-primary">{regime.primary_state}</span>
              <span className="font-mono text-ds-text-secondary">{regime.duration_bars} bars</span>
            </div>
            <div className="mt-1 truncate text-ds-text-secondary">{regime.transition_reason}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function MarketStateRegimeFlow({
  snapshot,
  selection,
  onSelect,
}: {
  snapshot: MarketStateSnapshot;
  selection: MarketStateSelection | null;
  onSelect: (selection: MarketStateSelection) => void;
}) {
  const regimes = snapshot.market_state_regimes ?? [];

  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Market State Regime Flow</h3>
          <p className="text-[11px] text-ds-text-secondary">Engine-level market_state segments</p>
        </div>
        <span className="rounded-full bg-ds-surface-secondary px-2 py-1 text-[10px] text-ds-text-secondary">{regimes.length} regimes</span>
      </div>
      {!regimes.length ? (
        <EmptyPanel message="No engine market state regimes in the selected range." />
      ) : (
        <>
      <div className="flex h-10 overflow-hidden rounded-lg border border-ds-border/50">
        {regimes.map((regime) => {
          const selected = isMarketStateSelection(selection, "market_state_regime", regime.regime_id);
          return (
            <button
              key={regime.regime_id}
              type="button"
              className="h-full min-w-[4px] border-r border-ds-border/20 last:border-r-0"
              title={`${regime.regime_id}: ${regime.market_state} · ${regime.duration_bars} bars`}
              onClick={() => onSelect({ type: "market_state_regime", id: regime.regime_id, payload: regime })}
              style={{
                width: `${Math.max(4, regime.duration_bars * 10)}px`,
                background: marketStateRegimeColor(regime.market_state, regime.is_active),
                boxShadow: selected
                  ? "inset 0 0 0 2px color-mix(in srgb, var(--ds-color-accent) 70%, transparent)"
                  : regime.is_active
                    ? "inset 0 0 0 2px color-mix(in srgb, var(--ds-color-accent) 45%, transparent)"
                    : undefined,
              }}
            />
          );
        })}
      </div>
      <div className="mt-3 grid max-h-[240px] gap-2 overflow-auto text-[11px]">
        {regimes.map((regime) => {
          const selected = isMarketStateSelection(selection, "market_state_regime", regime.regime_id);
          return (
            <button
              key={regime.regime_id}
              type="button"
              className={`w-full rounded-lg border p-2 text-left text-[11px] ${selectableSurfaceClass(selected)}`}
              onClick={() => onSelect({ type: "market_state_regime", id: regime.regime_id, payload: regime })}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold text-ds-text-primary">
                  {regime.market_state}
                  {regime.is_active ? " · active" : ""}
                </span>
                <span className="font-mono text-ds-text-secondary">{regime.duration_bars} bars</span>
              </div>
              <div className="mt-1 truncate text-ds-text-secondary">
                {regime.confidence_level ?? "UNKNOWN"} · {formatConfidenceScore(regime.market_state_confidence)}
                {regime.rule_id ? ` · ${regime.rule_id}` : ""}
              </div>
            </button>
          );
        })}
      </div>
        </>
      )}
    </section>
  );
}

function DirectionalContextPanel({
  snapshot,
  selection,
  onSelect,
}: {
  snapshot: MarketStateSnapshot;
  selection: MarketStateSelection | null;
  onSelect: (selection: MarketStateSelection) => void;
}) {
  const episodes = snapshot.directional_context_episodes ?? [];

  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface p-4">
      <div className="mb-3">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Directional Context</h3>
        <p className="text-[11px] text-ds-text-secondary">LONG_CONTEXT / SHORT_CONTEXT episodes</p>
      </div>
      {!episodes.length ? (
        <EmptyPanel message="No directional context episodes in the selected range." />
      ) : (
      <div className="grid gap-2">
        {episodes.slice(-8).reverse().map((episode) => {
          const selected = isMarketStateSelection(selection, "directional_context_episode", episode.episode_id);
          return (
            <button
              key={episode.episode_id}
              type="button"
              className={`w-full rounded-lg border p-3 text-left text-[11px] ${selectableSurfaceClass(selected)}`}
              onClick={() =>
                onSelect({
                  type: "directional_context_episode",
                  id: episode.episode_id,
                  payload: episode,
                })
              }
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-ds-text-primary">
                  {episode.direction === "LONG" ? "Long context" : "Short context"}
                  {episode.is_active ? " · active" : ""}
                </span>
                <span className="font-mono text-ds-text-secondary">{episode.duration_bars} bars</span>
              </div>
              <div className="mt-1 text-ds-text-secondary">{episode.human_message}</div>
              <div className="mt-2 font-mono text-[10px] text-ds-text-tertiary">
                {formatTime(episode.start_timestamp)} → {formatTime(episode.end_timestamp)}
              </div>
            </button>
          );
        })}
      </div>
      )}
    </section>
  );
}

function LifecyclePanel({ snapshot }: { snapshot: MarketStateSnapshot }) {
  const lifecycles = snapshot.setup_lifecycles.slice(-6).reverse();
  return (
    <section className="rounded-xl border border-ds-border/60 bg-ds-surface p-4">
      <div className="mb-3">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-primary">Setup Lifecycle</h3>
        <p className="text-[11px] text-ds-text-secondary">Entry → exit/invalidation duration and excursion</p>
      </div>
      <div className="grid gap-2">
        {lifecycles.map((setup) => (
          <div key={setup.setup_id} className="rounded-lg border border-ds-border/45 bg-ds-surface-secondary/40 p-3 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-mono font-semibold" style={{ color: setup.setup_direction === "LONG" ? "var(--ds-status-healthy)" : "var(--ds-status-error)" }}>
                {setup.setup_id}
              </span>
              <span className="text-ds-text-secondary">{setup.duration_bars ?? "N/A"} bars</span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-[10px] text-ds-text-secondary">
              <span>MFE {formatMetric(setup.max_favorable_move, 2)}</span>
              <span>MAE {formatMetric(setup.max_adverse_move, 2)}</span>
            </div>
            <div className="mt-2 text-ds-text-secondary">{setup.exit_reason ?? "Active / no exit yet"}</div>
          </div>
        ))}
        {lifecycles.length === 0 ? <div className="py-6 text-center text-[12px] text-ds-text-secondary">No closed setups in current range.</div> : null}
      </div>
    </section>
  );
}

function SummaryCard({
  label,
  value,
  subvalue,
  tone,
}: {
  label: string;
  value: string;
  subvalue?: string;
  tone?: string;
}) {
  return (
    <div className="h-[92px] overflow-hidden rounded-xl border border-ds-border/60 bg-ds-surface p-2.5 shadow-sm">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">{label}</div>
      <div className="mt-1 truncate font-mono text-[14px] font-semibold text-ds-text-primary" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      {subvalue ? <div className="mt-1 truncate text-[11px] text-ds-text-secondary">{subvalue}</div> : null}
    </div>
  );
}

function DecisionHistoryStrip({ snapshot }: { snapshot: MarketStateSnapshot }) {
  const latestEvents = snapshot.timeline_events.slice(-8).reverse();
  const current = snapshot.current_state;
  const decision = current.active_decision ?? "NO_SETUP";
  const health = current.runtime_health;
  const healthText = health?.is_feed_stale || health?.is_runtime_stale || (health?.failed_engine_count ?? 0) > 0 ? "DEGRADED" : "HEALTHY";
  const windowText = snapshot.range === "all" ? "All Available" : `${snapshot.bar_count.toLocaleString()} bars`;

  return (
    <section className="shrink-0 border-b border-ds-border/50 bg-ds-surface-secondary/30 px-4 py-2">
      <div className="grid gap-2 xl:grid-cols-[130px_170px_180px_130px_minmax(280px,1fr)]">
        <SummaryCard
          label="History Window"
          value={windowText}
          subvalue={`${snapshot.timeline_events.length} events · ${snapshot.decisions.length} markers`}
        />
        <SummaryCard
          label="Trade Decision"
          value={decisionLabel(decision)}
          subvalue={current.active_cognitive_state ? `State: ${String(current.active_cognitive_state).replaceAll("_", " ")}` : "State: N/A"}
          tone={decisionColor(decision)}
        />
        <SummaryCard
          label="Market Phase"
          value={current.current_market_phase ?? "N/A"}
          subvalue={
            current.active_market_state_regime?.market_state
              ? `Market State Regime: ${current.active_market_state_regime.market_state}`
              : `Cognitive Regime: ${current.active_cognitive_regime ?? "N/A"}`
          }
        />
        <SummaryCard
          label="Runtime"
          value={healthText}
          subvalue={`${health?.active_engine_count ?? 0} active · ${health?.failed_engine_count ?? 0} failed`}
          tone={healthText === "HEALTHY" ? "var(--ds-status-healthy)" : "var(--ds-status-error)"}
        />

        <div className="h-[92px] min-w-0 overflow-hidden rounded-xl border border-ds-border/60 bg-ds-surface p-2.5 shadow-sm">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-primary">Decision Event History</h3>
              <p className="truncate text-[10px] text-ds-text-secondary">Regime/setup/exit events from runtime memories</p>
            </div>
            <span className="shrink-0 rounded-full bg-ds-surface-secondary px-2 py-1 font-mono text-[10px] text-ds-text-secondary">
              {snapshot.time_range?.start ? formatTime(snapshot.time_range.start) : "N/A"} → {snapshot.time_range?.end ? formatTime(snapshot.time_range.end) : "N/A"}
            </span>
          </div>
          {latestEvents.length ? (
            <div className="flex gap-2 overflow-x-auto pb-0.5">
              {latestEvents.map((event, index) => {
                const color = eventColor(event);
                return (
                  <div key={`${event.time}-${event.event_type}-${index}`} className="h-[48px] min-w-[140px] overflow-hidden rounded-lg border border-ds-border/50 bg-ds-surface-secondary/40 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[10px] font-black uppercase tracking-wide" style={{ color }}>
                        {event.event_type}
                      </span>
                      <span className="font-mono text-[10px] text-ds-text-tertiary">{event.bars_active ?? "—"} bars</span>
                    </div>
                    <div className="truncate font-mono text-[10px] text-ds-text-primary">
                      {decisionLabel(event.decision ?? "NO_SETUP")} {event.direction ? `· ${event.direction}` : ""}
                    </div>
                    <div className="truncate text-[9px] text-ds-text-secondary" title={event.reason ?? undefined}>
                      {formatTime(event.time)} · {event.regime ?? event.to_state ?? "N/A"}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-ds-status-warning/30 bg-ds-status-warning/10 p-3 text-[11px] text-ds-status-warning">
              No decision history events were returned for this selected range.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export function MarketStatePanel() {
  const [snapshot, setSnapshot] = useState<MarketStateSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("M15");
  const [mode, setMode] = useState<ViewMode>("latest");
  const [historyRange, setHistoryRange] = useState<HistoryRange>("500");
  const [showMarketStateRegimes, setShowMarketStateRegimes] = useState(true);
  const [showCognitiveRegimes, setShowCognitiveRegimes] = useState(true);
  const [showTransitions, setShowTransitions] = useState(true);
  const [showDirectionalContext, setShowDirectionalContext] = useState(true);
  const [showDecisions, setShowDecisions] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showOverlayLabels, setShowOverlayLabels] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [selection, setSelection] = useState<MarketStateSelection | null>(null);
  const [viewCommand, setViewCommand] = useState<ChartViewCommand | null>(null);
  const refreshTimerRef = useRef<number | null>(null);

  const dispatchChartView = useCallback((action: ChartViewAction) => {
    setViewCommand({ token: Date.now(), action });
  }, []);

  const loadSnapshot = useCallback(async () => {
    try {
      setError(null);
      const numericLimit =
        historyRange === "100" || historyRange === "250" || historyRange === "500"
          ? Number(historyRange)
          : DEFAULT_BAR_LIMIT;
      const data = await fetchMarketStateSnapshot({
        timeframe,
        limit: numericLimit,
        mode,
        range: historyRange === "all" ? "all" : undefined,
      });
      setSnapshot(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Market State snapshot.");
    } finally {
      setLoading(false);
    }
  }, [historyRange, mode, timeframe]);

  useEffect(() => {
    setLoading(true);
    void loadSnapshot();
  }, [loadSnapshot]);

  useEffect(() => {
    if (refreshTimerRef.current) window.clearInterval(refreshTimerRef.current);
    refreshTimerRef.current = window.setInterval(() => void loadSnapshot(), 15_000);
    return () => {
      if (refreshTimerRef.current) window.clearInterval(refreshTimerRef.current);
    };
  }, [loadSnapshot]);

  const warnings = useMemo(() => snapshot?.warnings ?? [], [snapshot]);
  const isReplayTodo = mode === "replay";

  if (loading && !snapshot) {
    return (
      <div className="ops-surface flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <div className="text-[15px] font-medium text-ds-text-primary">Loading Market State snapshot…</div>
        <div className="max-w-md text-[12px] text-ds-text-secondary">Fetching engine regimes, transitions, and directional context for the selected range.</div>
      </div>
    );
  }

  if (error && !snapshot) {
    return (
      <div className="ops-surface flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="text-[15px] font-medium text-ds-status-error">Failed to load Market State snapshot</div>
        <div className="max-w-md text-[12px] text-ds-text-secondary">{error}</div>
        <button
          type="button"
          onClick={() => void loadSnapshot()}
          className="rounded-lg border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[11px] text-ds-text-primary hover:border-ds-border-strong"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="ops-surface flex h-full items-center justify-center p-6 text-[15px] text-ds-text-secondary">
        No Market State snapshot is available for the current selection.
      </div>
    );
  }

  return (
    <div className="ops-surface panel-scroll flex h-full min-h-0 flex-col overflow-auto">
      <div className="shrink-0 border-b border-ds-border/50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-ds-display text-[18px] font-semibold text-ds-text-primary">Market State</h1>
            <p className="text-[12px] text-ds-text-secondary">Engine state, context episodes, and runtime timeline</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-ds-text-secondary">Timeframe</span>
            {TIMEFRAMES.map((item) => (
              <ToggleButton key={item} active={timeframe === item} onClick={() => setTimeframe(item)}>
                {item}
              </ToggleButton>
            ))}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-ds-text-secondary">Mode</span>
            {MODES.map((item) => (
              <ToggleButton key={item} active={mode === item} onClick={() => setMode(item)}>
                {item.toUpperCase()}
              </ToggleButton>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-ds-text-secondary">Range</span>
            {HISTORY_RANGES.map((item) => (
              <ToggleButton key={item.value} active={historyRange === item.value} onClick={() => setHistoryRange(item.value)}>
                {item.label}
              </ToggleButton>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-ds-text-secondary">Layers</span>
            <ToggleButton active={showMarketStateRegimes} onClick={() => setShowMarketStateRegimes((value) => !value)}>
              Market State Regimes
            </ToggleButton>
            <ToggleButton active={showCognitiveRegimes} onClick={() => setShowCognitiveRegimes((value) => !value)}>
              Cognitive Regimes
            </ToggleButton>
            <ToggleButton active={showTransitions} onClick={() => setShowTransitions((value) => !value)}>
              Market State Transitions
            </ToggleButton>
            <ToggleButton active={showDirectionalContext} onClick={() => setShowDirectionalContext((value) => !value)}>
              Directional Context
            </ToggleButton>
            <ToggleButton active={showDecisions} onClick={() => setShowDecisions((value) => !value)}>
              Decisions / Setups
            </ToggleButton>
            <ToggleButton active={showVolume} onClick={() => setShowVolume((value) => !value)}>
              Volume
            </ToggleButton>
            <ToggleButton active={showOverlayLabels} onClick={() => setShowOverlayLabels((value) => !value)}>
              Overlay Labels
            </ToggleButton>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-ds-text-secondary">Chart</span>
            <button
              type="button"
              onClick={() => dispatchChartView("fit")}
              className="rounded-lg border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[11px] text-ds-text-primary hover:border-ds-border-strong"
            >
              Fit content
            </button>
            <button
              type="button"
              onClick={() => dispatchChartView("latest")}
              className="rounded-lg border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[11px] text-ds-text-primary hover:border-ds-border-strong"
            >
              Scroll to latest
            </button>
            <button
              type="button"
              onClick={() => dispatchChartView("reset")}
              className="rounded-lg border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[11px] text-ds-text-primary hover:border-ds-border-strong"
            >
              Reset view
            </button>
            <ToggleButton active={autoScroll} onClick={() => setAutoScroll((value) => !value)}>
              Auto-scroll {autoScroll ? "On" : "Off"}
            </ToggleButton>
          </div>
          <button
            type="button"
            onClick={() => void loadSnapshot()}
            className="rounded-lg border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[11px] text-ds-text-primary hover:border-ds-border-strong"
          >
            Refresh
          </button>
        </div>

        {warnings.length || error || isReplayTodo ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {warnings.map((warning) => (
              <span key={warning} className="rounded-lg border border-ds-status-warning/30 bg-ds-status-warning/10 px-3 py-1 text-[11px] font-semibold text-ds-status-warning">
                {warning}
              </span>
            ))}
            {error ? <span className="rounded-lg border border-ds-status-error/30 bg-ds-status-error/10 px-3 py-1 text-[11px] text-ds-status-error">{error}</span> : null}
            {isReplayTodo ? (
              <span className="rounded-lg border border-ds-status-running/30 bg-ds-status-running/10 px-3 py-1 text-[11px] text-ds-status-running">
                Replay TODO: current viewer remains read-only and does not mutate runtime memory.
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      <DecisionHistoryStrip snapshot={snapshot} />
      <ActiveMarketStateBanner snapshot={snapshot} />

      <div className="flex min-h-[620px] shrink-0 border-b border-ds-border/50">
        <div className="min-w-0 flex-1 p-3 pr-0">
          <MarketStateChart
            snapshot={snapshot}
            showMarketStateRegimes={showMarketStateRegimes}
            showCognitiveRegimes={showCognitiveRegimes}
            showTransitions={showTransitions}
            showDirectionalContext={showDirectionalContext}
            showDecisions={showDecisions}
            showVolume={showVolume}
            showOverlayLabels={showOverlayLabels}
            autoScroll={autoScroll}
            viewCommand={viewCommand}
          />
        </div>
        <MarketStateInspector current={snapshot.current_state} />
      </div>

      <div className="grid shrink-0 gap-3 p-3">
        <div className="grid xl:grid-cols-[minmax(0,1fr)_360px]">
          <TimelineTable events={snapshot.timeline_events} selection={selection} onSelect={setSelection} />
          <div className="grid content-start gap-3">
            <MarketStateEpisodeInspector selection={selection} />
            <MarketStateRegimeFlow snapshot={snapshot} selection={selection} onSelect={setSelection} />
            <DirectionalContextPanel snapshot={snapshot} selection={selection} onSelect={setSelection} />
            <RegimeFlow snapshot={snapshot} />
            <LifecyclePanel snapshot={snapshot} />
          </div>
        </div>
        <MarketStateTransitionsTable snapshot={snapshot} selection={selection} onSelect={setSelection} />
      </div>
    </div>
  );
}
