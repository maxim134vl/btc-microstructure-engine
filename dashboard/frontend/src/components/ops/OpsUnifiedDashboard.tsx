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
                      ? `available ${usd(portfolio?.available_risk_usd)} · open ${portfolio?.open_positions ?? "—"}`
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
                          risk {usd(row.open_risk_usd)} · realized {usd(row.realized_pnl_usd)} · unrealized{" "}
                          {usd(row.unrealized_pnl_usd)}
                          {row.last_command_intent ? ` · cmd ${row.last_command_intent}` : ""}
                          {row.last_command_timestamp ? ` · ${row.last_command_timestamp}` : ""}
                        </p>
                      </MiniCard>
                    ))}
                  </div>
                ) : null}
              </Panel>
            </div>
          </SectionCard>
        </section>

        {/* 4. Market Context */}
        <section className="space-y-2.5" data-section="market-context">
          <SectionLabel>Market Context</SectionLabel>
          <SectionCard>
            <div className="grid gap-3.5 xl:grid-cols-3">
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
              <Panel title="Trading State">
                <MetricLine label="Trading state" value={liveConnected ? decision?.trading_state || "—" : "—"} />
                <MetricLine label="Market state" value={liveConnected ? decision?.market_state || "—" : "—"} />
                <MetricLine label="Directional bias" value={liveConnected ? decision?.market_bias || "—" : "—"} />
                <MetricLine
                  label="Entry eligible"
                  value={
                    liveConnected
                      ? decision?.entry_eligible == null
                        ? "—"
                        : decision.entry_eligible
                          ? "YES"
                          : "NO"
                      : "—"
                  }
                  hint={liveConnected ? decision?.execution_posture || decision?.status_label || undefined : unavailableCaption(generatedAt)}
                />
              </Panel>
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
              CURRENT ACTIVE MODEL · observational · non-blocking for paper runtime · promotion controlled by governance gate
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
              <Panel title="Candidate / Shadow">
                <MetricLine label="Candidate" value={liveConnected ? String(shadowSummary.candidate_status || "NONE_REGISTERED") : "—"} />
                <MetricLine label="Shadow" value={liveConnected ? String(shadowSummary.shadow_status || "—") : "—"} />
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
