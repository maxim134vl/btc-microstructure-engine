import { useMemo, useState, type ReactNode } from "react";
import {
  StatusDot,
  StatusIndicator,
  translateActiveService,
  translateFailedEngineCount,
  translateOpenAlerts,
  translateOpsLevel,
  translatePipelineState,
  translateResourceUsage,
  translateStallCount,
  translateSystemHealth,
  formatSourceTimestamp,
  type ResolvedStatus,
} from "../status";
import type {
  EngineRow,
  OpsAlert,
  OpsSnapshot,
  RuntimeTruthProcess,
  RuntimeTruthTimeframe,
} from "../../types/ops";
import {
  REQUIRED_PROCESS_ORDER,
  formatLiveMetric,
  isPhantomProcessId,
  unavailableCaption,
} from "./unifiedDisplay";
import {
  mapActiveRuntimeSeverity,
  mapOverallAssuranceSeverity,
  mapPromotionSeverity,
  mapRuntimeSafetySeverity,
} from "./assuranceCardSeverity";
import { mapTradingStateTimeframeSeverity } from "./tradingStateCardSeverity";
import {
  displayActiveContext,
  displayLifecycleState,
  displayProvisionalContext,
} from "./tradingStateLifecycleDisplay";
import type { TimeframeTradingState } from "../../types/ops";
import { TradingMetricsPanel } from "./TradingMetricsPanel";

const TRADING_STATE_TIMEFRAMES = ["M15", "M30", "H1", "H4"] as const;

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-ds-text-tertiary">
      {children}
    </h2>
  );
}

/** Existing project card shell (`ops-card` from index.css). */
function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <article className={`ops-card ${className}`}>{children}</article>;
}

/** Outer sectional wrapper — visual only. */
function SectionCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Card className={`space-y-3.5 p-3.5 sm:p-4 ${className}`}>{children}</Card>;
}

function Panel({
  title,
  children,
  status,
  empty,
}: {
  title: string;
  children?: ReactNode;
  status?: ResolvedStatus;
  empty?: string;
}) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-ds-border/35 px-3.5 py-3">
        <h3 className="text-[14px] font-semibold text-ds-text-primary">{title}</h3>
        {status ? <StatusIndicator status={status} size="sm" /> : null}
      </div>
      <div className="divide-y divide-ds-border/25">
        {empty ? <p className="px-3.5 py-3 text-[12px] text-ds-text-secondary">{empty}</p> : children}
      </div>
    </Card>
  );
}

function MetricLine({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-3 px-3.5 py-2 text-[12px]">
      <span className="text-ds-text-secondary">{label}</span>
      <div className="text-right">
        <div className="font-medium tabular-nums text-ds-text-primary">{value}</div>
        {hint ? <div className="mt-0.5 text-[11px] text-ds-text-tertiary">{hint}</div> : null}
      </div>
    </div>
  );
}

function SummaryCard({
  title,
  status,
  children,
}: {
  title: string;
  status: ResolvedStatus;
  children: ReactNode;
}) {
  return (
    <Card className="relative p-3.5">
      <div className="ops-card-shimmer" aria-hidden />
      <div className="relative">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-ds-text-tertiary">{title}</h3>
          <StatusIndicator status={status} size="sm" />
        </div>
        <div className="space-y-1 text-[13px] text-ds-text-primary">{children}</div>
      </div>
    </Card>
  );
}

/** Model Assurance top cards — show mapping label as-is (do not inherit overall CRITICAL). */
function AssuranceSummaryCard({
  title,
  status,
  children,
}: {
  title: string;
  status: ResolvedStatus;
  children: ReactNode;
}) {
  return (
    <Card className="relative p-3.5">
      <div className="ops-card-shimmer" aria-hidden />
      <div className="relative">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-ds-text-tertiary">{title}</h3>
          <span className="inline-flex items-center gap-2 text-[13px] font-medium text-ds-text-primary">
            <StatusDot tone={status.tone} className="h-2.5 w-2.5" />
            <span>{status.label}</span>
          </span>
        </div>
        <div className="space-y-1 text-[13px] text-ds-text-primary">{children}</div>
      </div>
    </Card>
  );
}

function MiniCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Card className={`p-3 ${className}`}>{children}</Card>;
}

function usd(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(2)}` : "—";
}

function formatBtcQty(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(8).replace(/\.?0+$/, "");
}

function formatPrice(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`;
}

function formatUptime(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function processStatus(row: RuntimeTruthProcess): ResolvedStatus {
  if (row.health === "RUNNING") return translateActiveService();
  if (row.required === false && row.health === "STOPPED") return translateOpsLevel("NOT_REQUIRED", "engine");
  if (row.health === "STOPPED" || row.health === "BROKEN") return translateOpsLevel("RED", "engine");
  return translateOpsLevel("UNKNOWN", "engine");
}

function mtfStatus(row: RuntimeTruthTimeframe): ResolvedStatus {
  const notLive =
    row.timeframe === "D1" ||
    row.availability_status === "TIMEFRAME_NOT_LIVE" ||
    row.display_status === "NOT_LIVE";
  if (notLive) return translateOpsLevel("NOT_LIVE", "engine");
  if (row.availability_status === "FRESH_EVENT" || row.availability_status === "AVAILABLE_LAST_CONFIRMED") {
    return translateOpsLevel("GREEN", "engine");
  }
  return translateOpsLevel("YELLOW", "engine");
}

export function OpsUnifiedDashboard({
  snapshot,
  liveConnected,
  acknowledged,
  onAckAlert,
}: {
  snapshot: OpsSnapshot;
  liveConnected: boolean;
  acknowledged: Set<string>;
  onAckAlert: (id: string) => void;
}) {
  const [showAllEngines, setShowAllEngines] = useState(false);
  const [showLegacy, setShowLegacy] = useState(false);
  const [showHistFailures, setShowHistFailures] = useState(false);
  const [showHistSkipped, setShowHistSkipped] = useState(false);

  const generatedAt = snapshot.generated_at ?? null;
  const health = snapshot.health;
  const pipeline = snapshot.pipeline;
  const research = snapshot.research_pipeline;
  // Full replace each refresh — never merge with prior assurance arrays.
  const assurance = research?.model_assurance ?? null;
  const toxic = research?.toxic_box;
  const traders = snapshot.timeframe_traders;
  const commandBus = traders?.command_bus;
  const portfolio = traders?.portfolio;
  const tradingPerformance =
    snapshot.runtime_truth?.trading_operations?.performance ?? null;
  const decision = research?.decision_layer;

  const actionableAlerts = useMemo(() => {
    const base =
      snapshot.alert_groups?.actionable ??
      (snapshot.alerts || []).filter((a) => a.actionable !== false && !a.ignored_by_health);
    return base.filter((a) => !acknowledged.has(a.id));
  }, [snapshot.alert_groups, snapshot.alerts, acknowledged]);

  const displayHealth = liveConnected
    ? snapshot.overall_health || health.display_status || health.level || "UNKNOWN"
    : "LIVE_DATA_UNAVAILABLE";

  const healthStatus = liveConnected
    ? translateSystemHealth(health.level, displayHealth)
    : {
        domain: "system" as const,
        key: "offline" as const,
        label: "LIVE DATA UNAVAILABLE",
        tone: "offline" as const,
      };

  const pipelineStatus = liveConnected
    ? translatePipelineState(pipeline.active_state)
    : translateOpsLevel("GREY", "engine");

  const alertsStatus = liveConnected
    ? translateOpenAlerts(
        actionableAlerts.length,
        actionableAlerts.some((a) => a.severity === "CRITICAL"),
      )
    : translateOpsLevel("GREY", "engine");

  const memoryStatus = liveConnected
    ? translateResourceUsage(health.memory_percent)
    : translateOpsLevel("GREY", "engine");

  const cycleMetric = formatLiveMetric(pipeline.current_cycle, {
    liveConnected,
    lastKnownAt: generatedAt,
    zeroIsValid: false,
  });
  const avgCycleMetric = formatLiveMetric(pipeline.average_cycle_duration_s, {
    liveConnected,
    lastKnownAt: generatedAt,
    format: (v) => `${Number(v).toFixed(2)}s`,
  });
  const lastCycleMetric = formatLiveMetric(pipeline.last_cycle_duration_s, {
    liveConnected,
    lastKnownAt: generatedAt,
    format: (v) => `${Number(v).toFixed(2)}s`,
  });
  const cpuMetric = formatLiveMetric(health.cpu_percent, {
    liveConnected,
    lastKnownAt: generatedAt,
    format: (v) => `${Number(v).toFixed(0)}%`,
    zeroIsValid: true,
  });
  const memMetric = formatLiveMetric(health.memory_percent, {
    liveConnected,
    lastKnownAt: generatedAt,
    format: (v) => `${Number(v).toFixed(0)}%`,
    zeroIsValid: true,
  });
  const diskMetric = formatLiveMetric(health.disk_percent, {
    liveConnected,
    lastKnownAt: generatedAt,
    format: (v) => `${Number(v).toFixed(0)}%`,
    zeroIsValid: true,
  });

  const processMap = new Map((snapshot.processes || []).map((p) => [p.process_id, p]));
  const orderedProcesses = REQUIRED_PROCESS_ORDER.map((id) => {
    if (id === "visual_refresher") {
      return processMap.get("visual_refresher") || processMap.get("dashboard_refresher");
    }
    if (id === "dashboard_refresher") return undefined;
    return processMap.get(id);
  }).filter(Boolean) as RuntimeTruthProcess[];

  // de-dupe visual/dashboard refresher
  const seen = new Set<string>();
  const processRows = orderedProcesses.filter((row) => {
    const key = row.process_id === "dashboard_refresher" ? "visual_refresher" : row.process_id;
    if (seen.has(key) || isPhantomProcessId(row.process_id)) return false;
    seen.add(key);
    return true;
  });

  const paper = snapshot.paper;
  const migrated =
    paper?.representation === "MIGRATED_TO_TIMEFRAME_TRADERS" ||
    paper?.display_status === "MIGRATED" ||
    (Boolean(traders?.activated) && !paper?.is_controller_failure);

  const engines = (snapshot.engines || []).filter((e) => !e.ignored_by_health);
  const problemEngines = engines.filter((e) =>
    ["FAILED", "TIMEOUT", "STALLED", "DEFERRED"].includes(String(e.status || "").toUpperCase()),
  );
  const visibleEngines = showAllEngines
    ? engines
    : problemEngines.length > 0
      ? problemEngines.slice(0, 8)
      : engines.slice(0, 5);

  const limits = (snapshot.known_limitations || []).filter((row) => {
    const id = (row.id || "").toUpperCase();
    return id.includes("D1") || id.includes("AUCTION") || row.display_status === "KNOWN_LIMITATION" || row.display_status === "NOT_LIVE";
  });

  const legacy = (snapshot.legacy_components || []).filter(
    (c) => c.classification === "PHANTOM" || c.display_status === "NOT_IN_CANONICAL_RUNTIME",
  );

  const assuranceOverall = String(assurance?.overall_assurance_status || assurance?.status || "MISSING_SOURCE");
  const overallCardStatus: ResolvedStatus = liveConnected
    ? mapOverallAssuranceSeverity(assuranceOverall)
    : translateOpsLevel("GREY", "engine");
  const activeRuntimeCardStatus: ResolvedStatus = liveConnected
    ? mapActiveRuntimeSeverity(assurance?.active_runtime)
    : translateOpsLevel("GREY", "engine");
  const runtimeSafetyCardStatus: ResolvedStatus = liveConnected
    ? mapRuntimeSafetySeverity(assurance?.runtime_safety_status)
    : translateOpsLevel("GREY", "engine");

  const driftSummary = (assurance?.drift_monitoring?.summary || {}) as Record<string, unknown>;
  const shadowSummary = (assurance?.candidate_shadow?.summary || {}) as Record<string, unknown>;
  const govSummary = (assurance?.governance_promotion?.summary || {}) as Record<string, unknown>;
  const envBlockers = Array.isArray(assurance?.environment_blockers)
    ? assurance!.environment_blockers!
    : [];
  const promoBlockers = Array.isArray(assurance?.promotion_blockers)
    ? assurance!.promotion_blockers!
    : [];
  const promotionCardStatus: ResolvedStatus = liveConnected
    ? mapPromotionSeverity({
        promotion_execution_status: String(govSummary.promotion_execution_status || "DISABLED"),
        promotion_control: assurance?.promotion_control,
        candidate_status: String(shadowSummary.candidate_status || assurance?.candidate_shadow?.status || "NONE_REGISTERED"),
        eligibility_status: String(govSummary.eligibility_status || "NOT_APPLICABLE"),
        environment_blockers: envBlockers,
        blockers: promoBlockers,
        active_model_change_performed: Boolean(govSummary.active_model_change_performed),
        gate_status: assurance?.governance_promotion?.status,
      })
    : translateOpsLevel("GREY", "engine");

  const activeFailures =
    snapshot.health_dimensions?.runtime?.current_failures_count ??
    snapshot.runtime_failure_audit?.active_count ??
    null;
  const historicalFailures =
    snapshot.health_dimensions?.historical_audit?.historical_failures_count ??
    snapshot.runtime_failure_audit?.historical_count ??
    snapshot.runtime_failure_audit?.total_count ??
    null;
  const currentStalls =
    pipeline.current_stalls_timeouts ??
    (pipeline.current_stalled_engine_count ?? pipeline.stalled_engine_count ?? null);
  const historicalStalls =
    snapshot.health_dimensions?.historical_audit?.historical_stalls_count ??
    pipeline.historical_stalls_timeouts ??
    pipeline.historical_stalled_engine_count ??
    null;

  const highestAlert = actionableAlerts[0] as OpsAlert | undefined;
  const engineCount = engines.length;
  const healthyEngineCount = engines.filter((e) => String(e.status).toUpperCase() === "HEALTHY").length;

  return (
    <div className="ops-surface min-h-full">
      <div className="mx-auto max-w-[1120px] space-y-5 p-5">
        {!liveConnected ? (
          <Card className="border-ds-border/70 bg-ds-surface px-4 py-3">
            <div className="flex items-center gap-2">
              <StatusDot tone="offline" className="h-2.5 w-2.5" />
              <div>
                <p className="text-[13px] font-semibold text-ds-text-primary">LIVE DATA UNAVAILABLE</p>
                <p className="text-[12px] text-ds-text-secondary">
                  OPS API disconnected · Showing last-known snapshot
                  {generatedAt ? ` · Last known at: ${formatSourceTimestamp(generatedAt)}` : ""}
                </p>
              </div>
            </div>
          </Card>
        ) : null}

        {/* 1. Live Operations Summary — single instance */}
        <section className="space-y-2.5" data-section="live-operations-summary">
          <SectionLabel>Live Operations Summary</SectionLabel>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard title="System Health" status={healthStatus}>
              <p className="font-semibold">{healthStatus.label}</p>
              <p className="text-[12px] text-ds-text-secondary">
                {liveConnected
                  ? snapshot.overall_reason || health.primary_reason || "—"
                  : "OPS API disconnected"}
              </p>
            </SummaryCard>

            <SummaryCard title="Pipeline" status={pipelineStatus}>
              <p className="font-semibold tabular-nums">
                Cycle {cycleMetric.text}
                {cycleMetric.isUnavailable && cycleMetric.lastKnownAt
                  ? ` · ${unavailableCaption(cycleMetric.lastKnownAt)}`
                  : ""}
              </p>
              <p className="text-[12px] text-ds-text-secondary">
                avg {avgCycleMetric.text}
                {lastCycleMetric.text !== "—" ? ` · last ${lastCycleMetric.text}` : ""}
                {liveConnected && engineCount > 0 ? ` · ${healthyEngineCount}/${engineCount} engines` : ""}
              </p>
              <p className="text-[11px] text-ds-text-tertiary">
                tip {snapshot.context_chain?.final_context_tip || snapshot.context_chain?.safe_upstream_tip || "—"}
              </p>
            </SummaryCard>

            <SummaryCard title="Active Alerts" status={alertsStatus}>
              <p className="font-semibold tabular-nums">
                {liveConnected ? actionableAlerts.length : "—"}
              </p>
              <p className="text-[12px] text-ds-text-secondary">
                {liveConnected
                  ? highestAlert
                    ? `${highestAlert.severity} · ${highestAlert.message}`
                    : "Nothing requires immediate action"
                  : unavailableCaption(generatedAt)}
              </p>
            </SummaryCard>

            <SummaryCard title="Resources" status={memoryStatus}>
              <p className="font-semibold tabular-nums">
                CPU {cpuMetric.text} · Mem {memMetric.text} · Disk {diskMetric.text}
              </p>
              <p className="text-[12px] text-ds-text-secondary">
                {liveConnected
                  ? `Runtime ${formatUptime(snapshot.stability?.runtime_uptime_s)} · Collectors ${formatUptime(snapshot.stability?.collector_uptime_s)}`
                  : unavailableCaption(generatedAt)}
              </p>
            </SummaryCard>
          </div>
        </section>

        {/* 2. Runtime Processes */}
        <section className="space-y-2.5" data-section="runtime-processes">
          <SectionLabel>Runtime Processes</SectionLabel>
          <SectionCard>
            <Panel
              title="Required Processes"
              empty={!liveConnected ? "Live process data unavailable" : processRows.length === 0 ? "No process truth" : undefined}
            >
              {liveConnected
                ? processRows.map((row) => (
                    <div key={row.process_id} className="flex items-start justify-between gap-3 px-3.5 py-2.5">
                      <div>
                        <p className="text-[13px] font-medium text-ds-text-primary">
                          {row.display_name || row.process_id}
                        </p>
                        <p className="text-[11px] text-ds-text-secondary">
                          pid {row.pid ?? "—"}
                          {row.health_reason ? ` · ${row.health_reason}` : ""}
                        </p>
                      </div>
                      <StatusIndicator status={processStatus(row)} size="sm" />
                    </div>
                  ))
                : null}
            </Panel>
            <Panel
              title="Legacy Paper Controller"
              status={
                paper?.is_controller_failure
                  ? translateOpsLevel("RED", "engine")
                  : migrated
                    ? translateOpsLevel("MIGRATED", "engine")
                    : translateOpsLevel("GREY", "engine")
              }
            >
              <p className="px-3.5 py-2.5 text-[11px] text-ds-text-secondary">
                {migrated
                  ? "MIGRATED · NOT REQUIRED · Replaced by timeframe traders"
                  : paper?.detail || "—"}
              </p>
            </Panel>
          </SectionCard>
        </section>

        {/* 3. Trading Operations */}
        <section className="space-y-2.5" data-section="trading-operations">
          <SectionLabel>Trading Operations</SectionLabel>
          <SectionCard>
            <div className="grid gap-3.5 xl:grid-cols-2">
              <Panel title="Manager / Portfolio">
                <MetricLine
                  label="Master capital"
                  value={
                    liveConnected
                      ? `${usd(portfolio?.master_current_equity_usd ?? portfolio?.closed_equity_usd)} / ${usd(portfolio?.master_initial_equity_usd ?? portfolio?.initial_equity_usd)}`
                      : "—"
                  }
                  hint={
                    liveConnected
                      ? `risk capacity ${usd(portfolio?.master_risk_capacity_usd ?? portfolio?.portfolio_max_risk_usd)} · open risk ${usd(portfolio?.master_open_risk_usd ?? portfolio?.gross_open_risk_usd)} · available ${usd(portfolio?.master_available_risk_usd ?? portfolio?.available_risk_usd)}`
                      : unavailableCaption(generatedAt)
                  }
                />
                <MetricLine
                  label="Command bus"
                  value={liveConnected ? commandBus?.health || "—" : "—"}
                  hint={
                    liveConnected
                      ? `${commandBus?.rows ?? "—"} commands · ${commandBus?.duplicate_command_ids ?? "—"} duplicates`
                      : unavailableCaption(generatedAt)
                  }
                />
                <MetricLine
                  label="Command tip"
                  value={liveConnected ? commandBus?.latest_evaluation_period || commandBus?.latest_evaluation_timestamp || "—" : "—"}
                />
                <MetricLine
                  label="Gross open risk"
                  value={liveConnected ? `${usd(portfolio?.gross_open_risk_usd)} / ${usd(portfolio?.portfolio_max_risk_usd)}` : "—"}
                  hint={
                    liveConnected
                      ? `available ${usd(portfolio?.available_risk_usd)} · open ${portfolio?.open_positions ?? "—"} · notional ${usd(portfolio?.gross_open_notional_usd ?? portfolio?.master_open_notional_usd)}`
                      : unavailableCaption(generatedAt)
                  }
                />
                <MetricLine
                  label="Realized / Unrealized"
                  value={
                    liveConnected
                      ? `${usd(portfolio?.realized_pnl)} / ${usd(portfolio?.unrealized_pnl)}`
                      : "—"
                  }
                />
              </Panel>
              <Panel
                title="Timeframe Traders"
                empty={!liveConnected ? "Live trader data unavailable" : !(traders?.traders || []).length ? "No traders" : undefined}
              >
                {liveConnected ? (
                  <div className="grid gap-2.5 p-3 sm:grid-cols-2">
                    {(traders?.traders || []).map((row) => (
                      <MiniCard key={row.timeframe}>
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-[13px] font-medium text-ds-text-primary">
                            {row.timeframe} · {row.direction || "FLAT"}
                          </p>
                          <StatusIndicator
                            status={
                              row.health === "BROKEN" || row.process_health === "STOPPED"
                                ? translateOpsLevel("RED", "engine")
                                : translateOpsLevel("GREEN", "engine")
                            }
                            size="sm"
                          />
                        </div>
                        <p className="mt-1 text-[11px] text-ds-text-secondary">
                          equity {usd(row.current_equity_usd ?? row.initial_equity_usd)}
                          {row.next_risk_budget_usd != null ? ` · next risk ${usd(row.next_risk_budget_usd)}` : ""}
                          {row.risk_pct_per_trade != null ? ` · ${row.risk_pct_per_trade}%` : ""}
                        </p>
                        {row.direction && row.direction !== "FLAT" ? (
                          <div className="mt-1 space-y-0.5 text-[11px] text-ds-text-secondary">
                            <p>
                              risk {usd(row.open_risk_usd ?? row.risk_amount_usd)} · realized {usd(row.realized_pnl_usd)} · unrealized{" "}
                              {usd(row.unrealized_pnl_usd)}
                            </p>
                            {row.open_position_id ? <p>Position {row.open_position_id}</p> : null}
                            <p>
                              Entry {usd(row.entry_fill_price ?? row.entry_price)}
                              {row.quantity != null ? ` · Qty ${formatBtcQty(row.quantity)} BTC` : ""}
                            </p>
                            {row.position_notional != null ? <p>Notional {usd(row.position_notional)}</p> : null}
                            <p>
                              Stop {formatPrice(row.stop_loss_price)} · Take {formatPrice(row.take_profit_price)}
                            </p>
                          </div>
                        ) : (
                          <p className="mt-1 text-[11px] text-ds-text-secondary">
                            risk {usd(row.open_risk_usd)} · realized {usd(row.realized_pnl_usd)} · unrealized{" "}
                            {usd(row.unrealized_pnl_usd)}
                            {row.last_command_intent ? ` · cmd ${row.last_command_intent}` : ""}
                            {row.last_command_timestamp ? ` · ${row.last_command_timestamp}` : ""}
                          </p>
                        )}
                      </MiniCard>
                    ))}
                  </div>
                ) : null}
              </Panel>
            </div>
            <TradingMetricsPanel
              performance={tradingPerformance}
              liveConnected={liveConnected}
              generatedAt={generatedAt}
              capital={{
                currentMasterEquity:
                  portfolio?.master_current_equity_usd ?? portfolio?.closed_equity_usd,
                initialMasterCapital:
                  portfolio?.master_initial_equity_usd ?? portfolio?.initial_equity_usd,
                epochStartedAt: traders?.activation_timestamp,
                currentTimestamp: generatedAt,
              }}
            />
          </SectionCard>
        </section>

        {/* 3b2. Structural Stop/Take Shadow (read-only research) */}
        <section className="space-y-2.5" data-section="shadow-structural-protection">
          <SectionLabel>Structural Stop/Take Shadow</SectionLabel>
          <SectionCard>
            <Panel title="Observe-only structural research">
              {(() => {
                const sh = (snapshot as { shadow_structural_protection?: Record<string, unknown> })
                  .shadow_structural_protection;
                return (
                  <>
                    <MetricLine label="Mode" value={String(sh?.mode || "OBSERVE_ONLY")} />
                    <MetricLine
                      label="Process"
                      value={`${String(sh?.process_health || (sh?.alive ? "RUNNING" : "STOPPED"))} · PID ${String(sh?.pid ?? "—")}`}
                    />
                    <MetricLine
                      label="Binding"
                      value={`${String(sh?.binding_status || "—")} · epoch ${sh?.epoch_match === true ? "MATCH" : sh?.epoch_match === false ? "MISMATCH" : "—"} · fp ${sh?.fingerprint_match === true ? "MATCH" : sh?.fingerprint_match === false ? "MISMATCH" : "—"}`}
                    />
                    <MetricLine label="Source epoch" value={String(sh?.source_epoch_id || "—")} />
                    <MetricLine
                      label="Trading fingerprint"
                      value={(() => {
                        const fp = String(sh?.active_trading_fingerprint || "—");
                        return fp === "—" ? fp : `${fp.slice(0, 16)}${fp.length > 16 ? "…" : ""}`;
                      })()}
                    />
                    <MetricLine label="STP generation" value={String(sh?.stp_generation || "—")} />
                    <MetricLine
                      label="Classification"
                      value={`${String(sh?.classification_model || "—")} / ${String(sh?.classification_mode || "—")}`}
                    />
                    <MetricLine label="Exact intrabar data" value={String(sh?.exact_intrabar_data ?? "—")} />
                    <MetricLine label="Candidates" value={String(sh?.candidate_count ?? "—")} />
                    <MetricLine
                      label="Bars by TF (window sum)"
                      value={(() => {
                        const b = (sh?.candidate_window_bars_sum_by_timeframe ||
                          sh?.bars_built_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Unique closed bars by TF"
                      value={(() => {
                        const cov = (sh?.bar_coverage || {}) as Record<string, unknown>;
                        const b = (cov.unique_closed_bars_by_timeframe ||
                          sh?.unique_closed_bars_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Unique zones detected/proven/usable"
                      value={(() => {
                        const d = (sh?.unique_detected_zones_by_timeframe || {}) as Record<string, unknown>;
                        const p = (sh?.unique_reaction_proven_zones_by_timeframe || {}) as Record<string, unknown>;
                        const u = (sh?.unique_usable_zones_by_timeframe || {}) as Record<string, unknown>;
                        const sum = (x: Record<string, unknown>) =>
                          Number(x.M15 || 0) + Number(x.M30 || 0) + Number(x.H1 || 0) + Number(x.H4 || 0);
                        return `${sum(d)} / ${sum(p)} / ${sum(u)} (policy-expanded prot ${sh?.policy_expanded_protective_evidence_instances ?? "—"})`;
                      })()}
                    />
                    <MetricLine
                      label="Significant candles"
                      value={(() => {
                        const b = (sh?.significant_candles_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Exact profiles by TF"
                      value={(() => {
                        const b = (sh?.exact_profiles_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine label="Exact profiles" value={String(sh?.exact_profile_count ?? "—")} />
                    <MetricLine
                      label="Detected zones"
                      value={(() => {
                        const b = (sh?.zones_detected_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Reaction-proven zones"
                      value={(() => {
                        const b = (sh?.zones_reaction_proven_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Protective zones"
                      value={`${sh?.protective_zone_detected_count ?? "—"} detected / ${sh?.protective_zone_usable_count ?? sh?.protective_zone_found_count ?? "—"} usable`}
                    />
                    <MetricLine
                      label="Target zones"
                      value={`${sh?.target_zone_detected_count ?? "—"} detected / ${sh?.target_zone_usable_count ?? sh?.target_zone_found_count ?? "—"} usable`}
                    />
                    <MetricLine
                      label="Usable protective by TF"
                      value={(() => {
                        const b = (sh?.protective_usable_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Usable target by TF"
                      value={(() => {
                        const b = (sh?.target_usable_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="Reaction proof"
                      value={`${sh?.reaction_proven_count ?? "—"} proven / ${sh?.reaction_missing_count ?? "—"} missing`}
                    />
                    <MetricLine
                      label="Structural EXECUTE by TF"
                      value={(() => {
                        const b = (sh?.structural_execute_by_timeframe || {}) as Record<string, unknown>;
                        return `M15 ${b.M15 ?? "—"} · M30 ${b.M30 ?? "—"} · H1 ${b.H1 ?? "—"} · H4 ${b.H4 ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="EXECUTE by family"
                      value={(() => {
                        const fam = ((sh?.execute_breakdown as { by_policy_family?: Record<string, unknown> } | undefined)
                          ?.by_policy_family || {}) as Record<string, unknown>;
                        return `base ${fam.BASELINE ?? "—"} · SL ${fam.STRUCTURAL_SL_ONLY ?? "—"} · TP ${fam.STRUCTURAL_TP_ONLY ?? "—"} · full ${fam.FULL_STRUCTURAL ?? "—"}`;
                      })()}
                    />
                    <MetricLine
                      label="M15 parity"
                      value={(() => {
                        const p = (sh?.m15_parity || {}) as Record<string, unknown>;
                        return `${String(p.status || "—")} (compared ${p.compared ?? "—"})`;
                      })()}
                    />
                    <MetricLine label="Virtual positions" value={String(sh?.virtual_positions_open ?? "—")} />
                    <MetricLine
                      label="Invalidated virtual"
                      value={String(sh?.virtual_positions_invalidated ?? "—")}
                    />
                    <MetricLine label="Virtual trades" value={String(sh?.virtual_trades_closed ?? "—")} />
                    <MetricLine
                      label="Economic execute/skip"
                      value={`${sh?.economic_execute_count ?? "—"} / ${sh?.economic_skip_count ?? "—"}`}
                    />
                    <MetricLine
                      label="Baseline parity"
                      value={`${sh?.baseline_match_count ?? "—"} match / ${sh?.baseline_divergence_count ?? "—"} divergence`}
                    />
                    <MetricLine label="Lookahead violations" value={String(sh?.lookahead_violation_count ?? "—")} />
                    <MetricLine
                      label="Research status"
                      value={String(sh?.research_status || sh?.status || "—")}
                    />
                    <p className="px-3.5 pb-2.5 text-[11px] text-ds-text-secondary">
                      Structural levels are VIRTUAL / NOT ACTIVE research-only and never sent to LIVE1B or paper books.
                    </p>
                  </>
                );
              })()}
            </Panel>
          </SectionCard>
        </section>

        {/* STP_BE33: independent observe-only partial-take / break-even shadow */}
        <section className="space-y-2.5" data-section="shadow-stp-be33">
          <SectionLabel>STP_BE33 Shadow</SectionLabel>
          <SectionCard>
            <Panel title="1/3 partial take + economic break-even research">
              {(() => {
                const sh = (snapshot as { shadow_stp_be33?: Record<string, unknown> }).shadow_stp_be33;
                const metrics = (sh?.metrics || {}) as Record<string, unknown>;
                const manifest = (sh?.policy_manifest || {}) as Record<string, unknown>;
                const eventCounts = (sh?.event_counts || {}) as Record<string, unknown>;
                const eventsByTf = (sh?.events_by_timeframe || {}) as Record<string, unknown>;
                const outcomesByTf = (sh?.outcomes_by_timeframe || {}) as Record<string, unknown>;
                const latestEvent = (sh?.latest_event || {}) as Record<string, unknown>;
                const violations = (sh?.violations || []) as unknown[];
                const tf = (values: Record<string, unknown>) =>
                  `M15 ${values.M15 ?? 0} · M30 ${values.M30 ?? 0} · H1 ${values.H1 ?? 0} · H4 ${values.H4 ?? 0}`;
                const fp = String(sh?.policy_fingerprint || "—");
                return <>
                  <MetricLine label="Mode" value={String(sh?.mode || "SHADOW_OBSERVE_ONLY")} />
                  <MetricLine label="Process / ownership" value={`${String(sh?.process_health || "STOPPED")} · ${String(sh?.ownership || "INDEPENDENT_RUNNER")}${sh?.pid != null ? ` · PID ${String(sh.pid)}` : ""}`} />
                  <MetricLine label="Binding" value={`${String(sh?.binding_status || "—")} · epoch ${sh?.epoch_match === true ? "MATCH" : "MISMATCH"} · policy fp ${sh?.policy_fingerprint_match === true ? "MATCH" : "MISMATCH"}`} />
                  <MetricLine label="Epoch" value={String(sh?.source_epoch_id || "—")} />
                  <MetricLine label="Generation / version" value={`${String(sh?.policy_id || "—")} / ${String(sh?.policy_version || "—")}`} />
                  <MetricLine label="Policy fingerprint" value={fp === "—" ? fp : `${fp.slice(0, 16)}…`} />
                  <MetricLine label="Effective since" value={String(sh?.policy_effective_at || "—")} />
                  <MetricLine label="Trigger rule" value="At 1/3 of entry→TP distance" />
                  <MetricLine label="Partial / remaining" value={`${String(manifest.partial_fraction || "—")} close / ${String(manifest.remaining_fraction || "—")} moved to economic BE`} />
                  <MetricLine label="Intrabar / WAL provenance" value={`${String(sh?.trigger_source || "—")} · processed ${String(sh?.last_processed_wal_offset ?? "—")} / WAL ${String(sh?.wal_last_offset ?? "—")}`} />
                  <MetricLine label="Observed / partial / BE stops / TP after partial" value={`${metrics.positions_observed ?? "—"} / ${metrics.partial_trigger_reached ?? "—"} / ${metrics.be_stops_hit ?? "—"} / ${metrics.tp_after_partial ?? "—"}`} />
                  <MetricLine label="Events / outcomes" value={`${String(sh?.event_count ?? 0)} / ${String(sh?.outcome_count ?? 0)}`} />
                  <MetricLine label="Events by TF" value={tf(eventsByTf)} />
                  <MetricLine label="Outcomes by TF" value={tf(outcomesByTf)} />
                  <MetricLine label="Partial + stop-move events" value={String(eventCounts.STP_BE33_STOP_MOVED ?? 0)} />
                  <MetricLine label="Last event / update" value={`${String(latestEvent.event_type || "—")} · ${String(latestEvent.recorded_at || sh?.updated_at || "—")}`} />
                  <MetricLine label="Errors / violations" value={violations.length ? violations.join(", ") : "none"} />
                  <MetricLine label="Research / safety" value={String(sh?.research_safety_status || "—")} />
                  <p className="px-3.5 pb-2.5 text-[11px] text-ds-text-secondary">
                    Observe-only: canonical writes, LIVE1B commands and real execution are disabled by the runtime policy manifest and health state.
                  </p>
                </>;
              })()}
            </Panel>
          </SectionCard>
        </section>

        {/* 3b. Economic Quality & Correlation Shadow (read-only research) */}
        <section className="space-y-2.5" data-section="shadow-economic-correlation">
          <SectionLabel>Economic Quality &amp; Correlation Shadow</SectionLabel>
          <SectionCard>
            <Panel title="Observe-only research layer">
              {(() => {
                const sh = (snapshot as { shadow_economic_correlation?: Record<string, unknown> })
                  .shadow_economic_correlation;
                const clusters = (sh?.same_direction_clusters || {}) as Record<string, unknown>;
                return (
                  <>
                    <MetricLine label="Mode" value={String(sh?.mode || "OBSERVE_ONLY")} />
                    <MetricLine
                      label="Process"
                      value={`${String(sh?.process_health || (sh?.alive ? "RUNNING" : "STOPPED"))} · PID ${String(sh?.pid ?? "—")}`}
                    />
                    <MetricLine
                      label="Binding"
                      value={`${String(sh?.binding_status || "—")} · epoch ${sh?.epoch_match === true ? "MATCH" : sh?.epoch_match === false ? "MISMATCH" : "—"} · fp ${sh?.fingerprint_match === true ? "MATCH" : sh?.fingerprint_match === false ? "MISMATCH" : "—"}`}
                    />
                    <MetricLine label="Source epoch" value={String(sh?.source_epoch_id || "—")} />
                    <MetricLine
                      label="Trading fingerprint"
                      value={(() => {
                        const fp = String(sh?.active_trading_fingerprint || "—");
                        return fp === "—" ? fp : `${fp.slice(0, 16)}${fp.length > 16 ? "…" : ""}`;
                      })()}
                    />
                    <MetricLine label="Candidates" value={String(sh?.candidate_count ?? "—")} />
                    <MetricLine label="Closed outcomes" value={String(sh?.closed_outcome_count ?? "—")} />
                    <MetricLine
                      label="Baseline parity"
                      value={`${sh?.baseline_match_count ?? "—"} match / ${sh?.baseline_divergence_count ?? "—"} divergence`}
                    />
                    <MetricLine label="Open virtual positions" value={String(sh?.open_virtual_positions ?? "—")} />
                    <MetricLine
                      label="Same-direction clusters"
                      value={`LONG ${String(clusters.BTC_LONG ?? "—")} · SHORT ${String(clusters.BTC_SHORT ?? "—")}`}
                    />
                    <MetricLine
                      label="Research status"
                      value={String(sh?.research_status || sh?.status || "—")}
                    />
                    <MetricLine label="Lookahead violations" value={String(sh?.lookahead_violation_count ?? "—")} />
                    <MetricLine
                      label="Cognition enrichment"
                      value={String(sh?.cognition_enrichment || (sh?.feature_enrichment_enabled ? "ACTIVE" : "—"))}
                    />
                    <MetricLine label="Candidates enriched" value={String(sh?.enriched_candidate_count ?? "—")} />
                    <MetricLine label="Valid features" value={String(sh?.valid_feature_count ?? "—")} />
                    <MetricLine label="Stale features" value={String(sh?.stale_feature_count ?? "—")} />
                    <MetricLine label="Missing features" value={String(sh?.missing_feature_count ?? "—")} />
                    <MetricLine label="Future rows rejected" value={String(sh?.future_row_rejected_count ?? "—")} />
                    <p className="px-3.5 pb-2.5 text-[11px] text-ds-text-secondary">
                      Virtual PnL/risk are research-only and never mixed with live paper books.
                    </p>
                  </>
                );
              })()}
            </Panel>
          </SectionCard>
        </section>

        {/* 3b2. Shadow Auction research observer */}
        <section className="space-y-2.5" data-section="shadow-auction">
          <SectionLabel>Shadow Auction</SectionLabel>
          <SectionCard>
            <Panel title="Research observer · no execution">
              {(() => {
                const sh = (snapshot as { shadow_auction?: Record<string, unknown> }).shadow_auction || {};
                const tfs = (sh.timeframes || {}) as Record<string, Record<string, unknown>>;
                const hier = (sh.hierarchy || {}) as Record<string, unknown>;
                const funnel = (sh.funnel || {}) as Record<string, unknown>;
                const verdicts = (sh.verdicts || {}) as Record<string, unknown>;
                const integrity = (sh.integrity || {}) as Record<string, unknown>;
                const resources = (sh.resources || {}) as Record<string, unknown>;
                const research = (sh.research_checkpoint || {}) as Record<string, unknown>;
                const economic = (sh.economic_research || {}) as Record<string, unknown>;
                const postmortem = (sh.postmortem || {}) as Record<string, unknown>;
                const lagMs = sh.source_lag_ms;
                const uptime = sh.uptime_seconds;
                const bytes = Number(resources.shadow_total_bytes ?? NaN);
                const free = Number(resources.disk_free_bytes ?? NaN);
                const mb = (n: number) =>
                  Number.isFinite(n) ? `${(n / (1024 * 1024)).toFixed(1)} MB` : "—";
                const tfLine = (tf: string) => {
                  const row = tfs[tf] || {};
                  return `${String(row.auction_family || "—")} · ${String(row.episode_phase || "—")} · lag ${String(row.source_lag_sec ?? "—")}s`;
                };
                const lookahead = Number(integrity.lookahead_violations ?? 0);
                return (
                  <>
                    <MetricLine
                      label="Status"
                      value={`${String(sh.status || sh.process_health || "—")} · ${String(sh.mode || "RESEARCH_OBSERVER")}`}
                    />
                    <MetricLine
                      label="Observer"
                      value={`observer_only=${String(sh.observer_only ?? true)} · enforcement=${String(sh.enforcement_enabled ?? false)} · NO EXECUTION`}
                    />
                    <MetricLine
                      label="Process"
                      value={`PID ${String(sh.pid ?? "—")} · uptime ${uptime == null ? "—" : `${Math.floor(Number(uptime))}s`} · updated ${String(sh.updated_at || "—")}`}
                    />
                    <MetricLine
                      label="Source lag"
                      value={`${lagMs == null ? "—" : `${lagMs} ms`} · last ${String(sh.last_source_timestamp || "—")}`}
                    />
                    <MetricLine label="M15" value={tfLine("M15")} />
                    <MetricLine label="M30" value={tfLine("M30")} />
                    <MetricLine label="H1" value={tfLine("H1")} />
                    <MetricLine label="H4" value={tfLine("H4")} />
                    <MetricLine
                      label="Hierarchy"
                      value={`${String(hier.hierarchy_state || "—")} · depth ${String(hier.propagation_depth ?? "—")} · dir ${String(hier.propagation_direction || "—")}`}
                    />
                    <MetricLine
                      label="TF relations"
                      value={`M15↔M30 ${String(hier.m15_m30_relation || "—")} · M30↔H1 ${String(hier.m30_h1_relation || "—")} · H1↔H4 ${String(hier.h1_h4_relation || "—")}`}
                    />
                    <MetricLine
                      label="Local vs structural"
                      value={`${String(hier.local_vs_structural_state || "—")} · conflict ${String(hier.conflict_state || "—")}`}
                    />
                    <MetricLine
                      label="Research comparison"
                      value={
                        research.checkpoint_verdict
                          ? `${String(research.checkpoint_verdict)} · ${String(research.checkpoint_type || "—")} · ${String(research.canonical_timeframe || "—")} ${String(research.canonical_side || "")} · coverage ${String(research.coverage_status || "—")}`
                          : "—"
                      }
                    />
                    <MetricLine
                      label="Research funnel"
                      value={`ckp ${String(funnel.canonical_checkpoints ?? "—")} · verdicts ${String(funnel.checkpoint_verdicts ?? "—")} · closed ${String(funnel.closed_cases_evaluated ?? "—")} · open ${String(funnel.open_cases_waiting_close ?? "—")}`}
                    />
                    <MetricLine
                      label="Coverage"
                      value={`complete ${String(funnel.coverage_complete ?? "—")} · partial ${String(funnel.coverage_partial ?? "—")} · stale ${String(funnel.coverage_stale ?? "—")} · missing ${String(funnel.coverage_missing ?? "—")}`}
                    />
                    <MetricLine
                      label="Post-mortem funnel"
                      value={`complete ${String(funnel.postmortem_complete ?? "—")} · waiting ${String(funnel.postmortem_waiting ?? "—")} · expired ${String(funnel.postmortem_expired ?? "—")}`}
                    />
                    <MetricLine
                      label="Verdict counts"
                      value={`SUPPORT ${String(verdicts.SUPPORT ?? "—")} · WAIT ${String(verdicts.WAIT ?? "—")} · REJECT ${String(verdicts.REJECT ?? "—")} · OPPOSITE ${String(verdicts.OPPOSITE ?? "—")} · UNRESOLVED ${String(verdicts.UNRESOLVED ?? "—")}`}
                    />
                    {economic && Object.keys(economic).length > 0 ? (
                      <MetricLine
                        label="Economic research"
                        value={`AVOIDED_LOSS ${String(economic.SHADOW_AVOIDED_LOSS ?? "—")} · MISSED_WIN ${String(economic.SHADOW_MISSED_WIN ?? "—")} · BETTER_ENTRY ${String(economic.SHADOW_BETTER_ENTRY ?? "—")} · CANONICAL_BETTER ${String(economic.CANONICAL_BETTER_ENTRY ?? "—")}`}
                      />
                    ) : null}
                    {postmortem && postmortem.retrospective_structure_label ? (
                      <MetricLine
                        label="Post-mortem"
                        value={`${String(postmortem.retrospective_structure_label)} · ${String(postmortem.eventual_resolution || "—")} · depth ${String(postmortem.max_propagation_depth ?? "—")}`}
                      />
                    ) : null}
                    <MetricLine
                      label="Integrity"
                      value={`${String(integrity.status || "—")}${lookahead > 0 ? " · LOOKAHEAD CRITICAL" : ""} · lookahead ${String(integrity.lookahead_violations ?? "—")} · dup ${String(integrity.duplicates ?? "—")} · conflicts ${String(integrity.payload_conflicts ?? "—")} · broken ${String(integrity.broken_references ?? "—")} · order warn ${String(integrity.ordering_warnings ?? "—")}`}
                      hint={lookahead > 0 ? "lookahead violation is critical" : undefined}
                    />
                    <MetricLine
                      label="Resources"
                      value={`RSS ${String(resources.rss_memory_mb ?? "—")} MB · store ${mb(bytes)} · free SSD ${mb(free)} · ${String(resources.storage_status || "—")} · mounted=${String(resources.storage_mounted ?? "—")} writable=${String(resources.storage_writable ?? "—")}`}
                    />
                    <p className="px-3.5 pb-2.5 text-[11px] text-ds-text-secondary">
                      RESEARCH OBSERVER · NO EXECUTION. Verdicts are research comparisons only and never control trades.
                    </p>
                  </>
                );
              })()}
            </Panel>
          </SectionCard>
        </section>

        {/* 3b3. Cross-Layer Outcome Reconciliation (read-only audit) */}
        <section className="space-y-2.5" data-section="cross-layer-outcome-reconciliation">
          <SectionLabel>Cross-Layer Outcome Reconciliation</SectionLabel>
          <SectionCard>
            <Panel title="Read-only paper ↔ sleeve ↔ EQCORR ↔ STP audit">
              {(() => {
                const sh = (snapshot as { cross_layer_outcome_reconciliation?: Record<string, unknown> })
                  .cross_layer_outcome_reconciliation;
                return (
                  <>
                    <MetricLine label="Last audit status" value={String(sh?.status || "NO_AUDIT_YET")} />
                    <MetricLine label="Last audit timestamp" value={String(sh?.audit_timestamp || "—")} />
                    <MetricLine label="Active paper epoch" value={String(sh?.active_paper_epoch || "—")} />
                    <MetricLine
                      label="Active trading fingerprint"
                      value={String(sh?.active_trading_fingerprint || "—").slice(0, 16) + (String(sh?.active_trading_fingerprint || "").length > 16 ? "…" : "")}
                    />
                    <MetricLine
                      label="Active STP manifest"
                      value={`${String(sh?.active_stp_manifest_version || "—")} / ${String(sh?.active_stp_manifest || "—").slice(0, 12)}…`}
                    />
                    <MetricLine label="Closed paper trades" value={String(sh?.closed_paper_trades ?? "—")} />
                    <MetricLine label="Fully reconciled" value={String(sh?.fully_reconciled_trades ?? "—")} />
                    <MetricLine
                      label="Pending EQCORR / STP"
                      value={`${sh?.pending_eqcorr_outcomes ?? "—"} / ${sh?.pending_stp_outcomes ?? "—"}`}
                    />
                    <MetricLine
                      label="Paper lifecycle / PnL / sleeves / master"
                      value={`${sh?.paper_lifecycle_ok ?? "—"} / ${sh?.paper_pnl_ok ?? "—"} / ${sh?.sleeve_ok ?? "—"} / ${sh?.master_ok ?? "—"}`}
                    />
                    <MetricLine
                      label="EQCORR / STP baseline divergences"
                      value={`${sh?.eqcorr_baseline_divergences ?? "—"} / ${sh?.stp_baseline_divergences ?? "—"}`}
                    />
                    <MetricLine
                      label="Immutability / lookahead"
                      value={`${sh?.immutability_ok ?? "—"} / ${sh?.lookahead_ok ?? "—"}`}
                    />
                    <MetricLine label="Last reconciled trade" value={String(sh?.last_reconciled_trade || "—")} />
                    <MetricLine
                      label="Last reconciled exit"
                      value={String(sh?.last_reconciled_exit_timestamp || "—")}
                    />
                    <p className="px-3.5 pb-2.5 text-[11px] text-ds-text-secondary">
                      Diagnostic only — does not rewrite paper books, shadow decisions, or recommend policies.
                    </p>
                  </>
                );
              })()}
            </Panel>
          </SectionCard>
        </section>

        {/* 4. Market Context */}
        <section className="space-y-2.5" data-section="market-context">
          <SectionLabel>Market Context</SectionLabel>
          <SectionCard>
            <div className="grid gap-3.5 xl:grid-cols-2">
              <Panel title="MTF Availability" empty={!liveConnected ? "Unavailable" : undefined}>
                {liveConnected
                  ? (snapshot.multi_timeframe || []).map((row) => {
                      const notLive =
                        row.timeframe === "D1" ||
                        row.availability_status === "TIMEFRAME_NOT_LIVE" ||
                        row.display_status === "NOT_LIVE";
                      return (
                        <div key={row.timeframe} className="flex items-start justify-between gap-2 px-3.5 py-2">
                          <div>
                            <p className="text-[13px] font-medium text-ds-text-primary">{row.timeframe}</p>
                            <p className="text-[11px] text-ds-text-secondary">
                              {notLive
                                ? "NOT LIVE · EXPECTED"
                                : [row.availability_status, row.source_bar_close ? `close ${row.source_bar_close}` : null]
                                    .filter(Boolean)
                                    .join(" · ")}
                            </p>
                          </div>
                          <StatusIndicator status={mtfStatus(row)} size="sm" />
                        </div>
                      );
                    })
                  : null}
              </Panel>
              <Panel title="Context Chain">
                <MetricLine label="Last result" value={liveConnected ? snapshot.context_chain?.last_result || "—" : "—"} />
                <MetricLine label="Context tip" value={liveConnected ? snapshot.context_chain?.final_context_tip || "—" : "—"} />
                <MetricLine label="Lifecycle tip" value={liveConnected ? snapshot.context_chain?.lifecycle_tip || "—" : "—"} />
                <MetricLine label="Decision tip" value={liveConnected ? snapshot.context_chain?.decision_tip || "—" : "—"} />
              </Panel>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2 px-0.5">
                <h3 className="text-[14px] font-semibold text-ds-text-primary">Trading State</h3>
                <p className="text-[11px] text-ds-text-secondary">
                  {liveConnected
                    ? `Active directional contexts: ${
                        decision?.trading_states?.active_directional_contexts ??
                        decision?.trading_states?.directional_timeframes ??
                        0
                      } / 4 · Current directional evaluations: ${
                        decision?.trading_states?.current_directional_evaluations ?? 0
                      } / 4`
                    : unavailableCaption(generatedAt)}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {TRADING_STATE_TIMEFRAMES.map((tf) => {
                  const row: TimeframeTradingState | undefined = liveConnected
                    ? decision?.trading_states?.timeframes?.[tf] || decision?.by_timeframe?.[tf]
                    : undefined;
                  const status = liveConnected
                    ? mapTradingStateTimeframeSeverity(row)
                    : translateOpsLevel("GREY", "engine");
                  return (
                    <Panel
                      key={tf}
                      title={tf}
                      status={status}
                      empty={!liveConnected ? "Unavailable" : !row ? "UNAVAILABLE" : undefined}
                    >
                      {liveConnected && row ? (
                        <>
                          <MetricLine label="Текущая оценка" value={displayProvisionalContext(row)} />
                          <MetricLine label="Активный контекст" value={displayActiveContext(row)} />
                          <MetricLine label="Жизненный цикл" value={displayLifecycleState(row)} />
                          <MetricLine label="Направление" value={row.directional_bias || "—"} />
                          <MetricLine
                            label="Новый вход"
                            value={row.entry_eligible == null ? "—" : row.entry_eligible ? "YES" : "NO"}
                            hint={row.decision_reason || undefined}
                          />
                          <MetricLine label="Эпизод" value={row.lifecycle_episode_id || "—"} />
                          <MetricLine label="Событие контекста" value={row.context_event_id || "—"} />
                          <MetricLine
                            label="Открытая позиция"
                            value={row.open_position_side || "—"}
                            hint={row.open_position_id || undefined}
                          />
                          <MetricLine
                            label="Последняя оценка"
                            value={
                              row.last_evaluated_at ? formatSourceTimestamp(row.last_evaluated_at) : "—"
                            }
                          />
                        </>
                      ) : null}
                    </Panel>
                  );
                })}
              </div>
            </div>
          </SectionCard>
        </section>

        {/* 5. Pipeline Detail */}
        <section className="space-y-2.5" data-section="pipeline-detail">
          <SectionLabel>Pipeline Detail</SectionLabel>
          <SectionCard>
            <div className="grid gap-3.5 xl:grid-cols-3">
              <Panel
                title="Canonical Engines"
                empty={!liveConnected ? "Unavailable" : engines.length === 0 ? "No engines" : undefined}
              >
                {liveConnected
                  ? visibleEngines.map((row: EngineRow) => (
                      <div key={row.engine} className="px-3.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-[12px] font-medium text-ds-text-primary">
                            {row.short_name || row.engine}
                          </p>
                          <StatusIndicator status={translateOpsLevel(row.level || "GREY", "engine")} size="sm" />
                        </div>
                        <p className="text-[11px] text-ds-text-secondary">
                          {row.last_run_ago || row.last_run || "—"}
                          {row.duration_s != null ? ` · ${row.duration_s}s` : ""}
                          {row.status ? ` · ${row.status}` : ""}
                        </p>
                      </div>
                    ))
                  : null}
                {liveConnected && engines.length > visibleEngines.length ? (
                  <button
                    type="button"
                    className="w-full px-3.5 py-2 text-left text-[12px] font-medium text-ds-accent"
                    onClick={() => setShowAllEngines((v) => !v)}
                  >
                    {showAllEngines ? "Hide full engine list" : `Show all ${engines.length} engines`}
                  </button>
                ) : null}
              </Panel>
              <Panel title="Collectors">
                <MetricLine
                  label="Live feed"
                  value={
                    liveConnected
                      ? snapshot.collectors?.collectors?.[0]?.status || snapshot.collectors?.level || "—"
                      : "—"
                  }
                  hint={
                    liveConnected
                      ? snapshot.collectors?.collectors?.[0]?.last_message || undefined
                      : unavailableCaption(generatedAt)
                  }
                />
                <MetricLine
                  label="Freshness"
                  value={
                    liveConnected && snapshot.collectors?.collectors?.[0]?.age_seconds != null
                      ? `${snapshot.collectors.collectors[0].age_seconds}s`
                      : "—"
                  }
                />
              </Panel>
              <Panel title="Data Stores">
                <MetricLine
                  label="Required datasets"
                  value={
                    liveConnected
                      ? `live ${snapshot.parquet?.live_count ?? "—"} · stale ${snapshot.parquet?.stale_count ?? "—"} · delayed ${snapshot.parquet?.delayed_count ?? "—"}`
                      : "—"
                  }
                />
              </Panel>
            </div>
          </SectionCard>
        </section>

        {/* 6. Known Limitations */}
        <section className="space-y-2.5" data-section="known-limitations">
          <SectionLabel>Known Limitations</SectionLabel>
          <SectionCard>
            <Panel title="Known Limitations" empty={limits.length === 0 ? "None" : undefined}>
              {limits.length > 0 ? (
                <div className="grid gap-2.5 p-3 md:grid-cols-2">
                  {limits.map((row) => (
                    <MiniCard key={row.id || row.detail}>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-[13px] font-medium text-ds-text-primary">{row.id}</p>
                          <p className="mt-1 text-[11px] text-ds-text-secondary">
                            {[row.display_status, row.requirement, row.detail].filter(Boolean).join(" · ")}
                          </p>
                        </div>
                        <StatusIndicator
                          status={translateOpsLevel(row.display_status || "KNOWN_LIMITATION", "engine")}
                          size="sm"
                        />
                      </div>
                    </MiniCard>
                  ))}
                </div>
              ) : null}
            </Panel>
          </SectionCard>
        </section>

        {/* 7. MODEL ASSURANCE (canonical MODEL-9 payload — full replace each refresh) */}
        <section className="space-y-2.5" data-section="model-assurance">
          <SectionLabel>Model Assurance</SectionLabel>
          <SectionCard>
            <p className="px-0.5 text-[12px] text-ds-text-secondary">
              CURRENT PAPER REGISTRY · Model Assurance stopped · not required before 400 closed trades
            </p>
            <div className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-4">
              <AssuranceSummaryCard title="Overall" status={overallCardStatus}>
                <p>{liveConnected ? assuranceOverall : "—"}</p>
                <p className="text-[12px] text-ds-text-secondary">
                  Cause: {liveConnected ? assurance?.overall_cause || envBlockers[0] || "—" : "—"}
                </p>
              </AssuranceSummaryCard>
              <AssuranceSummaryCard title="Active Runtime" status={activeRuntimeCardStatus}>
                <p>{liveConnected ? assurance?.active_runtime?.model_id || "—" : "—"}</p>
                <p className="text-[12px] text-ds-text-secondary">
                  {liveConnected
                    ? `${assurance?.active_runtime?.model_version || "—"} · ${assurance?.active_runtime?.paper_epoch_id || "—"}`
                    : "—"}
                </p>
                <p className="text-[12px] text-ds-text-secondary">
                  {liveConnected
                    ? `${assurance?.active_runtime_binding_status || "—"} · registry=${assurance?.active_runtime?.registry_record_id || "—"}`
                    : "—"}
                </p>
              </AssuranceSummaryCard>
              <AssuranceSummaryCard title="Runtime Safety" status={runtimeSafetyCardStatus}>
                <p>{liveConnected ? assurance?.runtime_safety_status || "—" : "—"}</p>
                <p className="text-[12px] text-ds-text-secondary">
                  paper_only={String(liveConnected ? assurance?.active_runtime?.paper_only ?? true : "—")} · real_execution=
                  {String(liveConnected ? assurance?.active_runtime?.real_execution ?? false : "—")}
                </p>
              </AssuranceSummaryCard>
              <AssuranceSummaryCard title="Promotion" status={promotionCardStatus}>
                <p>
                  {liveConnected
                    ? String(govSummary.promotion_execution_status || "DISABLED")
                    : "—"}
                </p>
                <p className="text-[12px] text-ds-text-secondary">
                  {liveConnected
                    ? `control=${assurance?.promotion_control || "GOVERNANCE_GATE"} · impact=${assurance?.runtime_impact || "NON_BLOCKING"}`
                    : "—"}
                </p>
              </AssuranceSummaryCard>
            </div>
            <div className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-4">
              <Panel title="Behavioral Validation">
                <MetricLine label="Status" value={liveConnected ? String(assurance?.behavioral_validation?.status || "—") : "—"} />
              </Panel>
              <Panel title="Economic Validation">
                <MetricLine label="Status" value={liveConnected ? String(assurance?.economic_validation?.status || "—") : "—"} />
              </Panel>
              <Panel title="External Data">
                <MetricLine label="Status" value={liveConnected ? String(assurance?.external_data?.status || "—") : "—"} />
              </Panel>
              <Panel title="Toxic Box">
                <MetricLine label="Status" value={liveConnected ? String(assurance?.current_toxicity?.status || "—") : "—"} />
              </Panel>
              <Panel title="Incident Correlation">
                <MetricLine label="Status" value={liveConnected ? String(assurance?.incident_correlation?.status || "—") : "—"} />
              </Panel>
              <Panel title="Drift Monitoring">
                <MetricLine label="Input" value={liveConnected ? String(driftSummary.input_drift_status || "—") : "—"} />
                <MetricLine label="Feature" value={liveConnected ? String(driftSummary.feature_drift_status || "—") : "—"} />
                <MetricLine label="Context" value={liveConnected ? String(driftSummary.context_drift_status || "—") : "—"} />
                <MetricLine label="Performance" value={liveConnected ? String(driftSummary.performance_drift_status || "—") : "—"} />
              </Panel>
              <Panel title="Shadow Model">
                <MetricLine
                  label="Operational"
                  value={
                    liveConnected
                      ? String(
                          shadowSummary.unified_operational_status ||
                            (assurance?.unified_shadow_model as Record<string, unknown> | null | undefined)
                              ?.operational_status ||
                            shadowSummary.shadow_status ||
                            "—",
                        )
                      : "—"
                  }
                />
                <MetricLine
                  label="Evidence"
                  value={
                    liveConnected
                      ? String(
                          shadowSummary.unified_evidence_status ||
                            (assurance?.unified_shadow_model as Record<string, unknown> | null | undefined)
                              ?.evidence_status ||
                            "—",
                        )
                      : "—"
                  }
                />
                <MetricLine
                  label="Runtime impact"
                  value={liveConnected ? String(shadowSummary.runtime_impact || "NONE") : "—"}
                />
                <MetricLine
                  label="Promotion"
                  value={
                    liveConnected
                      ? shadowSummary.promotion_eligible === true
                        ? "ELIGIBLE"
                        : `NOT ELIGIBLE — ${String(shadowSummary.promotion_ineligibility_reason || "NO_PROMOTABLE_CANDIDATE_MODEL")}`
                      : "—"
                  }
                />
                <MetricLine
                  label="EQCORR / STP"
                  value={
                    liveConnected
                      ? `${String(shadowSummary.eqcorr_process_status || "—")} / ${String(shadowSummary.stp_process_status || "—")}`
                      : "—"
                  }
                />
                <MetricLine
                  label="Cross-layer coverage"
                  value={
                    liveConnected
                      ? shadowSummary.cross_layer_total != null
                        ? `${String(shadowSummary.cross_layer_covered ?? 0)}/${String(shadowSummary.cross_layer_total)}`
                        : "—"
                      : "—"
                  }
                />
                <MetricLine label="Candidate (MODEL-7)" value={liveConnected ? String(shadowSummary.candidate_status || "NONE_REGISTERED") : "—"} />
              </Panel>
              <Panel title="Governance">
                <MetricLine label="Eligibility" value={liveConnected ? String(govSummary.eligibility_status || "—") : "—"} />
                <MetricLine label="Governance" value={liveConnected ? String(govSummary.governance_status || "NONE") : "—"} />
                <MetricLine
                  label="Environment blocker"
                  value={liveConnected ? (envBlockers[0] || promoBlockers[0] || "—") : "—"}
                />
                <MetricLine
                  label="Active model changed"
                  value={liveConnected ? String(Boolean(govSummary.active_model_change_performed)) : "—"}
                />
              </Panel>
            </div>
            {liveConnected && toxic?.display_status && String(toxic.display_status).toUpperCase().includes("HISTORICAL") ? (
              <p className="px-0.5 text-[11px] text-ds-text-tertiary">
                HISTORICAL BASELINE — NOT CURRENT (legacy toxic panel retained outside current Model Assurance)
              </p>
            ) : null}
          </SectionCard>
        </section>

        {/* 9. Historical Audit */}
        <section className="space-y-2.5" data-section="historical-audit">
          <SectionLabel>Historical Audit</SectionLabel>
          <SectionCard>
            <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
              <Card className="relative p-3.5">
                <div className="ops-card-shimmer" aria-hidden />
                <div className="relative">
                  <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">Active failures</p>
                  <p className="mt-1 font-ds-display text-[28px] font-semibold tabular-nums">
                    {liveConnected ? activeFailures ?? 0 : "—"}
                  </p>
                  {liveConnected ? (
                    <StatusIndicator status={translateFailedEngineCount(Number(activeFailures || 0))} size="sm" />
                  ) : null}
                </div>
              </Card>
              <Card className="relative p-3.5">
                <div className="ops-card-shimmer" aria-hidden />
                <div className="relative">
                  <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">Current stalls</p>
                  <p className="mt-1 font-ds-display text-[28px] font-semibold tabular-nums">
                    {liveConnected ? currentStalls ?? 0 : "—"}
                  </p>
                  {liveConnected ? (
                    <StatusIndicator status={translateStallCount(Number(currentStalls || 0))} size="sm" />
                  ) : null}
                </div>
              </Card>
              <Card className="relative p-3.5">
                <div className="ops-card-shimmer" aria-hidden />
                <div className="relative">
                  <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">Historical failures</p>
                  <p className="mt-1 font-ds-display text-[28px] font-semibold tabular-nums">
                    {liveConnected ? historicalFailures ?? "—" : "—"}
                  </p>
                </div>
              </Card>
              <Card className="relative p-3.5">
                <div className="ops-card-shimmer" aria-hidden />
                <div className="relative">
                  <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">Historical stalls</p>
                  <p className="mt-1 font-ds-display text-[28px] font-semibold tabular-nums">
                    {liveConnected ? historicalStalls ?? "—" : "—"}
                  </p>
                </div>
              </Card>
            </div>
            <Panel title="Historical records">
              <button
                type="button"
                className="w-full px-3.5 py-2 text-left text-[12px] text-ds-text-primary"
                onClick={() => setShowHistFailures((v) => !v)}
              >
                Historical failures ({liveConnected ? historicalFailures ?? 0 : "—"}) {showHistFailures ? "▾" : "▸"}
              </button>
              {showHistFailures && liveConnected ? (
                <p className="px-3.5 pb-2 text-[11px] text-ds-text-secondary">
                  Retained for audit only · not counted as active incidents
                </p>
              ) : null}
              <button
                type="button"
                className="w-full px-3.5 py-2 text-left text-[12px] text-ds-text-primary"
                onClick={() => setShowHistSkipped((v) => !v)}
              >
                Historical skipped engines ({liveConnected ? snapshot.runtime_skipped_engine_audit?.total_count ?? 0 : "—"}){" "}
                {showHistSkipped ? "▾" : "▸"}
              </button>
              {showHistSkipped && liveConnected ? (
                <p className="px-3.5 pb-2 text-[11px] text-ds-text-secondary">
                  Historical skipped/deferred engine records · non-blocking
                </p>
              ) : null}
            </Panel>
          </SectionCard>
        </section>

        {/* Legacy / phantoms — collapsed */}
        <section className="space-y-2.5" data-section="legacy-excluded">
          <Card className="overflow-hidden">
            <button
              type="button"
              className="w-full px-3.5 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.1em] text-ds-text-tertiary"
              onClick={() => setShowLegacy((v) => !v)}
            >
              Legacy / Excluded Modules {showLegacy ? "▾" : "▸"}
            </button>
            {showLegacy ? (
              <div className="border-t border-ds-border/35 p-3">
                <Panel title="NOT_IN_CANONICAL_RUNTIME" empty={legacy.length === 0 ? "None" : undefined}>
                  {legacy.map((row) => (
                    <div key={row.component_id} className="flex items-start justify-between gap-2 px-3.5 py-2">
                      <div>
                        <p className="text-[13px] text-ds-text-primary">{row.component_id}</p>
                        <p className="text-[11px] text-ds-text-secondary">
                          {[row.display_status || "NOT_IN_CANONICAL_RUNTIME", row.reason].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      <StatusIndicator
                        status={translateOpsLevel(row.display_status || "NOT_IN_CANONICAL_RUNTIME", "engine")}
                        size="sm"
                      />
                    </div>
                  ))}
                </Panel>
              </div>
            ) : null}
          </Card>
        </section>

        {/* Active alerts detail once */}
        {liveConnected && actionableAlerts.length > 0 ? (
          <section className="space-y-2.5" data-section="active-alerts-detail">
            <SectionLabel>Active Alerts Detail</SectionLabel>
            <Panel title="Actionable alerts">
              {actionableAlerts.map((alert) => (
                <div key={alert.id} className="flex items-start justify-between gap-3 px-3.5 py-2.5">
                  <div>
                    <p className="text-[13px] font-medium text-ds-text-primary">
                      {alert.severity} · {alert.type || alert.id}
                    </p>
                    <p className="text-[12px] text-ds-text-secondary">{alert.message}</p>
                  </div>
                  <button
                    type="button"
                    className="text-[12px] font-medium text-ds-accent"
                    onClick={() => onAckAlert(alert.id)}
                  >
                    Ack
                  </button>
                </div>
              ))}
            </Panel>
          </section>
        ) : null}
      </div>
    </div>
  );
}
