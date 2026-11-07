import type { ConfidenceExplanation, CurrentMarketState, MarketStateTransition, RuntimeHealth } from "../../types/marketState";
import {
  confidenceDeltaTone,
  confidenceLevelColor,
  formatConfidenceDeltaText,
  formatConfidenceDeltaValue,
  formatConfidenceScore,
  transitionReasonText,
} from "./marketStateChartStyles";

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

function formatAge(seconds?: number | null): string {
  if (seconds == null) return "N/A";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 7200) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function StateRow({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" | "warn" | "bad" }) {
  const toneClass =
    tone === "good"
      ? "text-ds-status-healthy"
      : tone === "warn"
        ? "text-ds-status-warning"
        : tone === "bad"
          ? "text-ds-status-error"
          : "text-ds-text-primary";

  return (
    <div className="border-b border-ds-border/35 py-2.5 last:border-0">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">{label}</div>
      <div className={`mt-0.5 break-words font-mono text-[12px] ${toneClass}`}>{value || "N/A"}</div>
    </div>
  );
}

function MetricBar({ label, value }: { label: string; value?: number | null }) {
  const pct = Math.max(0, Math.min(100, (value ?? 0) * 100));
  const tone = pct >= 60 ? "var(--ds-status-healthy)" : pct >= 35 ? "var(--ds-status-warning)" : "var(--ds-status-error)";
  return (
    <div className="rounded-lg border border-ds-border/50 bg-ds-surface-secondary/40 p-3">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-ds-text-secondary">
        <span>{label}</span>
        <span className="font-mono text-ds-text-primary">{formatMetric(value)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ds-surface">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: tone }} />
      </div>
    </div>
  );
}

function ConfidenceExplanationCard({ explanation }: { explanation: ConfidenceExplanation }) {
  const levelTone =
    explanation.level === "HIGH" ? "good" : explanation.level === "MEDIUM" ? "warn" : explanation.level === "LOW" ? "bad" : "default";

  return (
    <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Confidence Explanation</h3>
          <p className="mt-0.5 text-[10px] text-ds-text-tertiary">Structured read from available source fields</p>
        </div>
        <span
          className="rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-wide"
          style={{
            color: confidenceLevelColor(explanation.level),
            background: `color-mix(in srgb, ${confidenceLevelColor(explanation.level)} 14%, transparent)`,
            border: `1px solid color-mix(in srgb, ${confidenceLevelColor(explanation.level)} 28%, transparent)`,
          }}
        >
          {explanation.level}
        </span>
      </div>

      <div className="mt-3 space-y-2">
        <StateRow label="Confidence Score" value={formatConfidenceScore(explanation.score)} tone={levelTone} />
        <div className="rounded-lg border border-ds-border/45 bg-ds-surface/70 p-2.5 text-[12px] leading-relaxed text-ds-text-primary">
          {explanation.summary}
        </div>
      </div>

      {explanation.drivers.length ? (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-status-healthy">Drivers</div>
          <ul className="mt-1.5 space-y-1 text-[11px] text-ds-text-primary">
            {explanation.drivers.map((driver) => (
              <li key={driver} className="rounded-md border border-ds-status-healthy/20 bg-ds-status-healthy/8 px-2 py-1">
                {driver}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {explanation.suppressors.length ? (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-status-warning">Suppressors</div>
          <ul className="mt-1.5 space-y-1 text-[11px] text-ds-text-primary">
            {explanation.suppressors.map((suppressor) => (
              <li key={suppressor} className="rounded-md border border-ds-status-warning/20 bg-ds-status-warning/8 px-2 py-1">
                {suppressor}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function LatestMarketStateTransitionCard({ transition }: { transition: MarketStateTransition }) {
  const deltaTone = confidenceDeltaTone(transition.confidence_delta);
  const reason = transitionReasonText(transition);

  return (
    <div className="rounded-xl border border-ds-color-accent/25 bg-ds-surface-secondary/40 p-3">
      <div className="mb-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Latest Market State Transition</h3>
        <p className="mt-0.5 text-[10px] text-ds-text-tertiary">Engine state change · not a trade signal</p>
      </div>

      <div className="rounded-lg border border-ds-border/45 bg-ds-surface/70 px-3 py-2">
        <div className="font-mono text-[13px] font-semibold text-ds-text-primary">
          {transition.from_market_state} → {transition.to_market_state}
        </div>
        <div className="mt-1 text-[11px] text-ds-text-secondary">{formatTime(transition.timestamp)}</div>
      </div>

      <div className="mt-3 space-y-0">
        <StateRow label="Transition Type" value={transition.transition_type ?? "N/A"} />
        <StateRow label="Transition Class" value={transition.transition_class ?? "N/A"} />
        <StateRow label="Rule" value={transition.rule_id ?? "N/A"} />
        {transition.rule_description ? <StateRow label="Rule Description" value={transition.rule_description} /> : null}
        <StateRow label="Confidence Before" value={formatConfidenceScore(transition.confidence_before)} />
        <StateRow label="Confidence After" value={formatConfidenceScore(transition.confidence_after ?? transition.market_state_confidence)} />
        <StateRow
          label="Confidence Delta"
          value={`${formatConfidenceDeltaValue(transition.confidence_delta)} · ${formatConfidenceDeltaText(transition.confidence_delta)}`}
          tone={deltaTone}
        />
        <StateRow label="Why State Changed" value={reason} />
        {transition.trader_read && transition.trader_read !== reason ? (
          <StateRow label="Trader Read" value={transition.trader_read} />
        ) : null}
      </div>

      {transition.confidence_explanation ? (
        <div className="mt-3 rounded-lg border border-ds-border/45 bg-ds-surface/70 p-2.5 text-[11px] leading-relaxed text-ds-text-primary">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-ds-text-secondary">After-state confidence</div>
          <p className="mt-1">{transition.confidence_explanation.summary}</p>
        </div>
      ) : null}
    </div>
  );
}

function RuntimeHealthCard({ health }: { health: RuntimeHealth }) {
  const unhealthy = health.is_feed_stale || health.is_runtime_stale || health.failed_engine_count > 0;
  return (
    <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Runtime Health</h3>
        <span className={`rounded-full px-2 py-0.5 text-[10px] ${unhealthy ? "bg-ds-status-error/15 text-ds-status-error" : "bg-ds-status-healthy/15 text-ds-status-healthy"}`}>
          {unhealthy ? "DEGRADED" : "HEALTHY"}
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        <StateRow label="Feed Freshness" value={`${health.is_feed_stale ? "STALE" : "LIVE"} · ${formatAge(health.feed_age_seconds)}`} tone={health.is_feed_stale ? "bad" : "good"} />
        <StateRow label="Runtime Freshness" value={`${health.is_runtime_stale ? "STALE" : "LIVE"} · ${formatAge(health.runtime_age_seconds)}`} tone={health.is_runtime_stale ? "bad" : "good"} />
        <StateRow label="Engines" value={`${health.active_engine_count} active · ${health.failed_engine_count} failed`} tone={health.failed_engine_count ? "bad" : "good"} />
      </div>
      {health.warnings.length ? (
        <div className="mt-3 space-y-1">
          {health.warnings.map((warning) => (
            <div key={warning} className="rounded-md border border-ds-status-warning/30 bg-ds-status-warning/10 px-2 py-1 text-[10px] font-semibold text-ds-status-warning">
              {warning}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function MarketStateInspector({ current }: { current: CurrentMarketState }) {
  const health = current.runtime_health;
  const decision = current.active_decision ?? "NO_SETUP";
  const decisionTone = decision === "LONG_SETUP" ? "good" : decision === "SHORT_SETUP" || decision === "INVALIDATED" ? "bad" : decision.includes("EXIT") ? "warn" : "default";
  const marketRegime = current.active_market_state_regime;
  const contextEpisode = current.active_directional_context_episode;
  const latestTransition = current.latest_market_state_transition;

  return (
    <aside className="panel-scroll w-[340px] shrink-0 overflow-y-auto border-l border-ds-border/60 bg-ds-surface">
      <div className="border-b border-ds-border/50 px-4 py-3">
        <h2 className="font-ds-display text-[13px] font-semibold text-ds-text-primary">Current Market State</h2>
        <p className="mt-0.5 text-[11px] text-ds-text-secondary">Engine regime, directional context, and confidence context</p>
      </div>

      <div className="space-y-3 p-4">
        <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Market State Regime</h3>
          <div className="mt-2">
            <StateRow label="Current Market Phase" value={current.current_market_phase ?? marketRegime?.market_state ?? "N/A"} />
            <StateRow label="Active Market State" value={marketRegime?.market_state ?? "N/A"} />
            <StateRow label="Regime Started" value={formatTime(marketRegime?.start_timestamp)} />
            <StateRow label="Duration" value={marketRegime?.duration_bars == null ? "N/A" : `${marketRegime.duration_bars} bars`} />
            <StateRow label="Rule" value={marketRegime?.rule_id ?? "N/A"} />
            <StateRow
              label="Regime Confidence"
              value={
                marketRegime?.confidence_level
                  ? `${marketRegime.confidence_level} · ${formatConfidenceScore(marketRegime.market_state_confidence)}`
                  : formatConfidenceScore(marketRegime?.market_state_confidence)
              }
              tone={
                marketRegime?.confidence_level === "HIGH" ? "good" : marketRegime?.confidence_level === "LOW" ? "bad" : marketRegime?.confidence_level === "MEDIUM" ? "warn" : "default"
              }
            />
          </div>
        </div>

        {contextEpisode ? (
          <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Directional Context</h3>
            <div className="mt-2">
              <StateRow label="Context State" value={contextEpisode.context_state} tone={contextEpisode.direction === "LONG" ? "good" : "bad"} />
              <StateRow label="Direction" value={contextEpisode.direction} />
              <StateRow label="Started" value={formatTime(contextEpisode.start_timestamp)} />
              <StateRow label="Duration" value={`${contextEpisode.duration_bars} bars`} />
              <StateRow label="Message" value={contextEpisode.human_message} />
            </div>
          </div>
        ) : null}

        {current.confidence_explanation ? <ConfidenceExplanationCard explanation={current.confidence_explanation} /> : null}

        {latestTransition ? <LatestMarketStateTransitionCard transition={latestTransition} /> : null}

        <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Cognitive Regime</h3>
          <div className="mt-2">
            <StateRow label="Active Cognitive Regime" value={current.active_cognitive_regime ?? "N/A"} />
            <StateRow label="Cognitive State" value={current.active_cognitive_state ?? "N/A"} tone={current.active_cognitive_state === "LOW_CONFIDENCE_MODE" ? "warn" : "default"} />
          </div>
        </div>

        <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Runtime Decision</h3>
          <div className="mt-2">
            <StateRow label="Trade Decision" value={decision} tone={decisionTone} />
            <StateRow label="Setup Status" value={current.setup_status ?? "N/A"} />
            <StateRow label="Setup Age" value={current.setup_age == null ? "N/A" : `${current.setup_age} bars`} />
            <StateRow label="Entry Timestamp" value={formatTime(current.entry_timestamp)} />
            <StateRow label="Exit / Invalidation Condition" value={current.exit_or_invalidation_condition ?? "N/A"} />
          </div>
        </div>

        <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ds-text-secondary">Current Interpretation</h3>
          <div className="mt-3 space-y-2 text-[12px] leading-relaxed text-ds-text-primary">
            {(current.interpretation?.length ? current.interpretation : ["No interpretation available for the latest state."]).map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        </div>

        <div className="grid gap-2">
          <MetricBar label="Conviction" value={current.conviction} />
          <MetricBar label="Alignment" value={current.alignment} />
          <MetricBar label="Persistence" value={current.persistence} />
          <MetricBar label="Absorption Probability" value={current.absorption_probability} />
          <MetricBar label="Distribution Probability" value={current.distribution_probability} />
        </div>

        <div className="rounded-xl border border-ds-border/60 bg-ds-surface-secondary/40 p-3">
          <StateRow label="Belief State" value={current.belief_state ?? "N/A"} />
          <StateRow label="Location Bias" value={current.location_bias ?? "N/A"} />
          <StateRow label="Last Regime Change" value={formatTime(current.last_regime_change)} />
          <StateRow label="Last Decision Change" value={formatTime(current.last_decision_change)} />
        </div>

        {health ? <RuntimeHealthCard health={health} /> : null}
      </div>
    </aside>
  );
}
