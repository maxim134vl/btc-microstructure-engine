import { Children, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "../../i18n";
import {
  SymbolAntenna,
  SymbolBell,
  SymbolClock,
  SymbolCpu,
  SymbolDatabase,
  SymbolEngine,
  SymbolHeart,
  SymbolLayers,
  SymbolMemory,
  SymbolPipeline,
  SymbolWaveform,
  SymbolWifi,
} from "../icons/Symbols";
import { IconChip } from "../shell/ShellPrimitives";
import {
  RAW_STATUS_PATTERN,
  StatusCardAccent,
  StatusDot,
  StatusIndicator,
  TONE_ICON_CHIP,
  translateActiveService,
  translateAlertSeverity,
  translateEngineState,
  translateFailedEngineCount,
  translateFeedConnection,
  translateFreshness,
  translateOpenAlerts,
  translateOpsLevel,
  translateParquetSummary,
  translatePipelineState,
  translateResourceUsage,
  translateRibbonItem,
  translateResearchRibbonItem,
  translateStabilityRestarts,
  translateStallCount,
  translateRuntimeStability,
  translateHealthDimensionStatus,
  translateSystemHealth,
  translateValidationLevel,
  isResearchRibbonKey,
  resolveDecisionStatus,
  resolveEconomicStatus,
  resolveGovernanceStatus,
  resolveLocalTokenStatus,
  resolveModelSummaryStatus,
  resolvePipelineSyncStatus,
  resolveToxicStatus,
  formatModelSummarySourceLines,
  formatDriftLegacyPsiLine,
  formatToxicBoxDisplay,
  formatSourceTimestamp,
  useSimulatedStatus,
  statusStripeClass,
  type ResolvedStatus,
} from "../status";
import type {
  CollectorRow,
  EngineRow,
  OpsAlert,
  OpsLevel,
  OpsSnapshot,
  ParquetRow,
  ResearchPipelineSnapshot,
  RuntimeFailureAuditSummary,
  RuntimeSkippedEngineAuditSummary,
  RibbonItem,
  HealthDimensions,
} from "../../types/ops";
import { RingGauge, StatusOrb } from "./OpsVisuals";

type SymbolComponent = ComponentType<{ className?: string }>;

function healthScore(level: string): number {
  if (level === "HEALTHY") return 100;
  if (level === "DEGRADED") return 58;
  return 28;
}

function progressTone(percent: number): string {
  if (percent >= 90) return "bg-ds-status-error";
  if (percent >= 75) return "bg-ds-status-warning";
  return "bg-ds-status-healthy";
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-ds-text-tertiary">
      {children}
    </h2>
  );
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <article className={`ops-card ${className}`}>{children}</article>;
}

function CardIcon({ icon: Icon, status }: { icon: SymbolComponent; status?: ResolvedStatus }) {
  const display = useSimulatedStatus(
    status ?? { domain: "system", key: "operational", label: "", tone: "operational" },
  );
  const toneClass = status ? TONE_ICON_CHIP[display.tone] : "";

  return (
    <IconChip accent={!status} className={toneClass}>
      <Icon className="h-[15px] w-[15px]" />
    </IconChip>
  );
}

function KpiCard({
  title,
  icon: Icon,
  status,
  renderVisual,
  hint,
}: {
  title: string;
  icon: SymbolComponent;
  status: ResolvedStatus;
  renderVisual: (tone: ResolvedStatus["tone"]) => ReactNode;
  hint?: string;
}) {
  const display = useSimulatedStatus(status);

  return (
    <Card className="relative">
      <StatusCardAccent tone={display.tone} />
      <div className="relative flex min-h-[168px] flex-col p-4">
        <div className="flex items-center gap-2">
          <CardIcon icon={Icon} status={status} />
          <p className="text-[13px] font-medium text-ds-text-secondary">{title}</p>
        </div>
        <div className="flex flex-1 items-center justify-center py-2">{renderVisual(display.tone)}</div>
        <div className="mt-auto space-y-0.5">
          <StatusIndicator status={status} icon={Icon} size="md" />
          {hint ? <p className="truncate pl-[18px] text-[11px] text-ds-text-secondary">{hint}</p> : null}
        </div>
      </div>
    </Card>
  );
}

function MetricTile({
  label,
  icon: Icon,
  value,
  status,
}: {
  label: string;
  icon: SymbolComponent;
  value: ReactNode;
  status: ResolvedStatus;
}) {
  return (
    <Card className="relative overflow-hidden p-3.5">
      <div className="ops-card-shimmer" aria-hidden />
      <div className="relative">
        <div className="flex items-center gap-2">
          <CardIcon icon={Icon} status={status} />
          <p className="text-[12px] font-medium text-ds-text-secondary">{label}</p>
        </div>
        <div className="mt-2">{value}</div>
        <div className="mt-2.5">
          <StatusIndicator status={status} icon={Icon} size="sm" />
        </div>
      </div>
    </Card>
  );
}

function StatusTile({
  label,
  icon: Icon,
  status,
}: {
  label: string;
  icon: SymbolComponent;
  status: ResolvedStatus;
}) {
  const display = useSimulatedStatus(status);

  return (
    <Card className="flex flex-col items-center justify-center p-3.5 text-center">
      <CardIcon icon={Icon} status={status} />
      <p className="mt-2 text-[12px] font-medium text-ds-text-secondary">{label}</p>
      <div className="my-2.5">
        <StatusOrb tone={display.tone} size="lg" />
      </div>
      <StatusIndicator status={status} icon={Icon} size="sm" />
    </Card>
  );
}

function RibbonTile({
  label,
  icon: Icon,
  status,
}: {
  label: string;
  icon: SymbolComponent;
  status: ResolvedStatus;
}) {
  const display = useSimulatedStatus(status);

  return (
    <Card className="relative flex min-h-[76px] flex-col justify-center py-3 pl-5 pr-3.5">
      <div className={`absolute inset-y-2.5 left-0 w-[3px] rounded-r-full ${statusStripeClass(display.tone)}`} aria-hidden />
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-ds-text-secondary" />
        <p className="text-[12px] font-medium text-ds-text-secondary">{label}</p>
      </div>
      <div className="mt-1.5 pl-6">
        <StatusIndicator status={status} icon={Icon} size="sm" />
      </div>
    </Card>
  );
}

function ProgressBar({ value, label, icon: Icon }: { value: number; label: string; icon: SymbolComponent }) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-[12px]">
        <span className="inline-flex items-center gap-1.5 font-medium text-ds-text-primary">
          <Icon className="h-3.5 w-3.5 text-ds-text-secondary" />
          {label}
        </span>
        <span className="tabular-nums text-ds-text-secondary">{clamped.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-ds-pill bg-ds-surface-secondary">
        <div
          className={`h-full rounded-ds-pill transition-all duration-ds ease-ds ${progressTone(clamped)}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

function PanelCard({
  title,
  icon: Icon,
  status,
  children,
  empty,
}: {
  title: string;
  icon: SymbolComponent;
  status?: ResolvedStatus;
  children: ReactNode;
  empty?: string;
}) {
  const hasContent = Children.count(children) > 0;

  return (
    <Card>
      <header className="flex items-center justify-between gap-3 border-b border-ds-border/35 px-3.5 py-3">
        <div className="flex items-center gap-2">
          <CardIcon icon={Icon} status={status} />
          <h3 className="text-[14px] font-semibold text-ds-text-primary">{title}</h3>
        </div>
        {status ? <StatusIndicator status={status} icon={Icon} size="sm" /> : null}
      </header>
      {hasContent ? <div className="divide-y divide-ds-border/25 px-0.5 py-0.5">{children}</div> : null}
      {!hasContent && empty ? <p className="px-3.5 py-4 text-[13px] text-ds-text-secondary">{empty}</p> : null}
    </Card>
  );
}

function ListRow({
  primary,
  secondary,
  icon: Icon,
  status,
  muted,
}: {
  primary: string;
  secondary?: string;
  icon: SymbolComponent;
  status?: ResolvedStatus;
  muted?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-xl px-2.5 py-2.5 transition-colors duration-ds hover:bg-ds-surface-secondary/80 ${
        muted ? "opacity-50" : ""
      }`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-ds-surface-secondary text-ds-text-secondary">
          <Icon className="h-[14px] w-[14px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-ds-text-primary">{primary}</div>
          {secondary ? <div className="mt-0.5 truncate text-[11px] text-ds-text-secondary">{secondary}</div> : null}
        </div>
      </div>
      {status ? <StatusIndicator status={status} icon={Icon} size="sm" /> : null}
    </div>
  );
}

function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function validationRibbonLevel(ribbon: RibbonItem[]): OpsLevel {
  // Prefer economic validation; missing/not-evaluated must not read as system FAIL.
  const economic = ribbon.find((item) => item.key === "economic_validation");
  if (economic) return economic.level;
  const validation = ribbon.find((item) => /validation/i.test(item.key) || /validation/i.test(item.label));
  return validation?.level ?? "GREY";
}

function ribbonIcon(item: RibbonItem): SymbolComponent {
  const key = `${item.key} ${item.label}`.toLowerCase();
  if (/governance|ml|shadow|model/i.test(key)) return SymbolLayers;
  if (/decision|trading|market state/i.test(key)) return SymbolHeart;
  if (/economic|toxic|validation|check|conform/i.test(key)) return SymbolLayers;
  if (/feed|stream|ws|socket/i.test(key)) return SymbolWifi;
  if (/data|parquet|store/i.test(key)) return SymbolDatabase;
  if (/pipeline|engine|cycle|pipeline24/i.test(key)) return SymbolPipeline;
  return SymbolWaveform;
}

function formatMetric(value?: number | null, digits = 4): string {
  return value != null ? value.toFixed(digits) : "—";
}

function formatPct(value?: number | null): string {
  return value != null ? `${value.toFixed(1)}%` : "—";
}

function formatBool(value?: boolean | null): string {
  if (value == null) return "—";
  return value ? "true" : "false";
}

function formatShortTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatLastRunAgo(value?: string | null): string | null {
  if (!value) return null;
  // Backend may historically emit negative ages from timezone skew.
  if (/^-\d/.test(value.trim())) return "just now";
  return value;
}

function trendLabel(value?: number | null): string {
  if (value == null) return "—";
  if (value > 0) return `+${value.toFixed(4)}`;
  return value.toFixed(4);
}

function metricScopeLabel(scope?: string | null): string {
  if (scope === "historical") return "historical";
  if (scope === "missing") return "missing";
  if (scope === "unknown") return "unknown";
  return "current";
}

function FreshnessBadge({ freshness }: { freshness?: { is_stale?: boolean; freshness_status?: string } | null }) {
  if (!freshness?.is_stale) return null;
  return (
    <span className="ml-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ds-status-warning ring-1 ring-ds-status-warning/40">
      STALE
    </span>
  );
}

function FreshnessMeta({
  freshness,
  warning,
  refreshHint,
  asOfOverride,
  showScope = true,
}: {
  freshness?: {
    source_timestamp?: string | null;
    source_mtime?: string | null;
    age_days?: number | null;
    is_stale?: boolean;
    metrics_scope?: string;
    warning?: string | null;
    refresh_hint?: string | null;
  } | null;
  warning?: string | null;
  refreshHint?: string | null;
  asOfOverride?: string | null;
  showScope?: boolean;
}) {
  if (!freshness && !warning) return null;
  const asOf = asOfOverride || freshness?.source_timestamp || freshness?.source_mtime;
  const ageDays = freshness?.age_days;
  const warn = warning || freshness?.warning;
  const hint = refreshHint || freshness?.refresh_hint;
  return (
    <div className="space-y-1 px-2.5 py-2 text-[11px] text-ds-text-secondary">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {asOf ? <span>as of {formatShortTime(String(asOf))}</span> : null}
        {ageDays != null ? <span>age: {ageDays} days</span> : null}
        {showScope && freshness?.metrics_scope ? (
          <span>scope: {metricScopeLabel(freshness.metrics_scope)}</span>
        ) : null}
        <FreshnessBadge freshness={freshness} />
      </div>
      {warn ? <p className="text-ds-status-warning">{warn}</p> : null}
      {hint && (freshness?.is_stale || warn) ? <p>{hint}</p> : null}
    </div>
  );
}

function ResearchPipelineSection({ research }: { research: ResearchPipelineSnapshot }) {
  const { t } = useTranslation();
  const {
    decision_layer,
    model_governance,
    economic_validation,
    shadow_inference,
    toxic_box,
    pipeline,
    drift_monitoring,
    model_summary,
  } = research;

  const decisionStatus = resolveDecisionStatus(decision_layer.level, decision_layer.status_label);
  const governanceStatus = resolveGovernanceStatus(
    model_governance.level,
    model_governance.governance_status,
    model_governance.freshness,
  );
  const economicStatus = resolveEconomicStatus(
    economic_validation.level,
    economic_validation.status,
    economic_validation.freshness,
  );
  const pipelineStatus = resolvePipelineSyncStatus(pipeline.in_sync ? "GREEN" : "RED");
  const summaryStatus = resolveModelSummaryStatus(
    model_summary?.level ?? "GREY",
    model_summary?.status,
    model_summary?.freshness,
  );

  const activeModelLabel =
    model_governance.active_model_display ?? model_governance.active_model ?? "MISSING";
  const candidateModelLabel =
    model_governance.candidate_model_display ?? model_governance.candidate_model ?? "MISSING";
  const summaryModelLabel = model_summary?.model && model_summary.model !== "—" ? model_summary.model : "MISSING";
  const historicalPrefix = (scope?: string | null) => (scope === "historical" ? "historical · " : "");

  const attentionReason = model_summary?.attention_reason ?? model_summary?.status_reason ?? null;
  const sourceLines = formatModelSummarySourceLines(model_summary?.model_summary_sources, {
    version: model_summary?.model_summary_source_version ?? "benchmark_primary_v1",
    promotionEligible:
      model_summary?.promotion_eligible_label ?? model_governance.promotion_eligible_label ?? "NO",
  });
  const currentToken = resolveLocalTokenStatus(
    model_summary?.metric_availability === "AVAILABLE" ? "AVAILABLE" : "MISSING_DATA",
  );
  const legacyToken = resolveLocalTokenStatus("HISTORICAL");
  const currentTokenDrift = resolveLocalTokenStatus(
    drift_monitoring?.metric_availability === "AVAILABLE"
      ? "AVAILABLE"
      : drift_monitoring?.severity_label || "MISSING_DATA",
  );
  const shadowMetricToken = resolveLocalTokenStatus(
    shadow_inference.metric_availability || shadow_inference.validation_status || "MISSING_DATA",
  );
  const shadowSourceToken = resolveLocalTokenStatus(
    shadow_inference.source_freshness || (shadow_inference.freshness?.is_stale ? "STALE" : "CURRENT"),
  );

  return (
    <section className="space-y-4">
      <SectionLabel>{t("ops.researchPipeline")}</SectionLabel>

      {model_summary ? (
        <PanelCard title={t("ops.modelSummary")} icon={SymbolLayers} status={summaryStatus}>
          <div className="space-y-1 px-2.5 py-2.5">
            <div className="text-[13px] font-medium text-ds-text-primary">
              {summaryModelLabel} · {model_summary.status ?? "ATTENTION"}
            </div>
            {attentionReason ? (
              <p className="text-[12px] text-ds-status-warning">Reason: {attentionReason}</p>
            ) : null}
          </div>
          {sourceLines.map((line) => {
            const local = line.includes("GOVERNANCE_MISSING")
              ? resolveLocalTokenStatus("GOVERNANCE_MISSING")
              : line.includes("STALE")
                ? resolveLocalTokenStatus("STALE")
                : line.includes("Promotion")
                  ? resolveLocalTokenStatus("NO")
                  : resolveLocalTokenStatus("CURRENT");
            return <ListRow key={line} icon={SymbolClock} primary={line} status={local} />;
          })}
          <div className="px-2.5 pt-2 text-[11px] font-semibold uppercase tracking-wide text-ds-text-tertiary">
            Current ML metrics
          </div>
          <ListRow
            icon={SymbolLayers}
            primary={`PSI: ${formatMetric(model_summary.psi, 3)} · Macro F1: ${formatMetric(model_summary.shadow_macro_f1)} · Loss recall: ${formatMetric(model_summary.loss_recall)}`}
            secondary={
              model_summary.metric_availability === "AVAILABLE"
                ? undefined
                : "Status: MISSING_DATA · Classic ML metrics missing in current benchmark."
            }
            status={currentToken}
          />
          {(model_summary.legacy_metrics?.psi != null || model_summary.psi_meta?.legacy_value != null) && (
            <>
              <div className="px-2.5 pt-2 text-[11px] font-semibold uppercase tracking-wide text-ds-text-tertiary">
                Legacy / Historical
              </div>
              <ListRow
                icon={SymbolBell}
                primary={`PSI: ${formatMetric(
                  model_summary.legacy_metrics?.psi ?? model_summary.psi_meta?.legacy_value,
                  3,
                )} · STALE · not primary`}
                secondary={
                  model_summary.legacy_metrics?.source_timestamp ||
                  model_summary.model_summary_sources?.legacy_monitoring?.timestamp
                    ? formatShortTime(
                        String(
                          model_summary.legacy_metrics?.source_timestamp ??
                            model_summary.model_summary_sources?.legacy_monitoring?.timestamp,
                        ),
                      )
                    : undefined
                }
                status={legacyToken}
                muted
              />
            </>
          )}
        </PanelCard>
      ) : null}

      <div className="grid gap-3.5 xl:grid-cols-2">
        <PanelCard title={t("ops.decisionLayerCard")} icon={SymbolHeart} status={decisionStatus}>
          <ListRow
            icon={SymbolHeart}
            primary={`${t("ops.tradingState")}: ${decision_layer.trading_state ?? "—"}`}
            secondary={`${t("ops.marketState")}: ${decision_layer.market_state ?? "—"} · ${decision_layer.status_label ?? "—"}`}
            status={decisionStatus}
          />
          <ListRow
            icon={SymbolLayers}
            primary={`${t("ops.ruleId")}: ${decision_layer.rule_id ?? "—"}`}
            secondary={`${t("ops.trendConfidence")}: ${formatMetric(decision_layer.trend_confidence, 3)} · ${t("ops.marketStateConfidence")}: ${formatMetric(decision_layer.market_state_confidence, 3)}`}
            status={decisionStatus}
          />
          <ListRow
            icon={SymbolHeart}
            primary={`${t("ops.entryEligible")}: ${formatBool(decision_layer.entry_eligible)}`}
            secondary={decision_layer.execution_posture ? String(decision_layer.execution_posture) : undefined}
            status={decisionStatus}
          />
        </PanelCard>

        <PanelCard title={t("ops.economicValidation")} icon={SymbolLayers} status={economicStatus}>
          <ListRow
            icon={SymbolLayers}
            primary={`${historicalPrefix(economic_validation.metrics_scope)}${t("ops.winPct")} ${formatPct(economic_validation.win_pct)} · ${t("ops.neutralPct")} ${formatPct(economic_validation.neutral_pct)} · ${t("ops.lossPct")} ${formatPct(economic_validation.loss_pct)}`}
            secondary={
              economic_validation.rolling_window
                ? `Rolling ${economic_validation.rolling_complete_count ?? 0} / ${economic_validation.rolling_window}`
                : undefined
            }
            status={economicStatus}
          />
          <ListRow
            icon={SymbolLayers}
            primary={`${t("ops.completeCount")}: ${economic_validation.complete_h4h} · ${t("ops.pendingCount")}: ${economic_validation.pending_h4h ?? 0}`}
            status={economicStatus}
          />
          <FreshnessMeta
            freshness={economic_validation.freshness}
            warning={economic_validation.stale_warning}
            refreshHint={economic_validation.refresh_hint}
          />
        </PanelCard>

        <PanelCard title={t("ops.shadowModel")} icon={SymbolWaveform} status={shadowMetricToken}>
          <ListRow
            icon={SymbolWaveform}
            primary={`Classic shadow metrics: ${
              shadow_inference.macro_f1 == null && shadow_inference.loss_recall == null
                ? "missing in current benchmark"
                : `${formatMetric(shadow_inference.macro_f1)} / ${formatMetric(shadow_inference.loss_recall)}`
            }`}
            secondary={`${t("ops.shadowEvaluated")}: ${shadow_inference.evaluated_rows} · Legacy metrics are not used as current.`}
            status={shadowMetricToken}
          />
          <ListRow
            icon={SymbolClock}
            primary={`Latest diagnostics: ${formatShortTime(shadow_inference.latest_diagnostics_at)} · ${
              shadow_inference.source_freshness || "CURRENT"
            }`}
            secondary={`Metric availability: ${shadow_inference.metric_availability || shadow_inference.validation_status || "MISSING_DATA"}`}
            status={shadowSourceToken}
          />
        </PanelCard>

        <PanelCard title={t("ops.governance")} icon={SymbolLayers} status={governanceStatus}>
          <ListRow
            icon={SymbolLayers}
            primary={`${t("ops.activeModel")}: ${activeModelLabel}`}
            secondary={`${t("ops.candidateModel")}: ${candidateModelLabel}`}
            status={resolveLocalTokenStatus(activeModelLabel === "MISSING" ? "MISSING" : "CURRENT")}
          />
          <ListRow
            icon={SymbolLayers}
            primary={`${t("ops.promotionEligible")}: ${model_governance.promotion_eligible_label ?? "NO"}`}
            secondary={model_governance.missing_reason ? `Reason: ${model_governance.missing_reason}` : undefined}
            status={resolveLocalTokenStatus("NO")}
          />
          {(model_governance.action || model_governance.refresh_hint || model_governance.missing_reason) && (
            <div className="space-y-1 px-2.5 py-2 text-[11px] text-ds-text-secondary">
              <p>
                Action:{" "}
                {model_governance.action ||
                  model_governance.refresh_hint ||
                  "Provide exports/model_governance_dashboard.json or run manual governance export."}
              </p>
            </div>
          )}
        </PanelCard>

        {drift_monitoring ? (
          <PanelCard title={t("ops.driftMonitoring")} icon={SymbolBell} status={currentTokenDrift}>
            <ListRow
              icon={SymbolBell}
              primary={`Current PSI: ${formatMetric(drift_monitoring.psi, 3)} · Macro F1: ${formatMetric(drift_monitoring.macro_f1)} · Loss recall: ${formatMetric(drift_monitoring.loss_recall)}`}
              secondary={
                drift_monitoring.status_note ||
                (drift_monitoring.psi == null
                  ? "Current drift metrics are not present in benchmark_primary_v1."
                  : undefined)
              }
              status={currentTokenDrift}
            />
            {(() => {
              const legacyLine = formatDriftLegacyPsiLine({
                legacyPsi: drift_monitoring.legacy_psi,
                legacyTimestamp: drift_monitoring.legacy_source_timestamp
                  ? String(drift_monitoring.legacy_source_timestamp)
                  : null,
              });
              return legacyLine ? (
                <ListRow
                  icon={SymbolBell}
                  primary={legacyLine}
                  status={resolveLocalTokenStatus("not primary")}
                  muted
                />
              ) : null;
            })()}
          </PanelCard>
        ) : null}

        {(() => {
          const toxicDisplay = formatToxicBoxDisplay({
            displayStatus: toxic_box.display_status,
            severityLabel: toxic_box.severity_label,
            events: toxic_box.events,
            eventsLast7d: toxic_box.events_last_7d,
            toxicRate7d: toxic_box.toxic_rate_7d,
            toxicRate30d: toxic_box.toxic_rate_30d,
            trend: toxic_box.trend,
            sourcePath: toxic_box.source_path,
            asOf: toxic_box.freshness?.source_timestamp
              ? formatSourceTimestamp(String(toxic_box.freshness.source_timestamp))
              : toxic_box.latest_timestamp
                ? formatSourceTimestamp(String(toxic_box.latest_timestamp))
                : null,
            ageDays: toxic_box.historical_age_days ?? toxic_box.freshness?.age_days ?? null,
            isStale: Boolean(toxic_box.freshness?.is_stale) || toxic_box.display_status === "LEGACY_ONLY",
            staleWarning: toxic_box.stale_warning,
            refreshHint: toxic_box.refresh_hint,
            currentStatus: toxic_box.current?.status,
            currentSourcePath: toxic_box.current?.source_path,
            currentGeneratedAt: toxic_box.current?.generated_at,
            historicalSourcePath:
              toxic_box.historical?.source_path || toxic_box.historical_source_path || toxic_box.source_path,
            historicalTimestamp:
              toxic_box.historical?.timestamp || toxic_box.historical_timestamp || toxic_box.freshness?.source_timestamp,
            historicalAgeDays: toxic_box.historical?.age_days ?? toxic_box.historical_age_days ?? null,
          });
          const toxicHeader = resolveToxicStatus(
            toxic_box.level,
            toxic_box.severity_label,
            toxic_box.freshness,
            toxic_box.display_status,
          );
          return (
            <PanelCard title={t("ops.toxicBoxCard")} icon={SymbolBell} status={toxicHeader}>
              {toxicDisplay.currentLine ? (
                <div className="px-2.5 py-2 text-[12px] text-ds-text-secondary">{toxicDisplay.currentLine}</div>
              ) : null}
              {toxicDisplay.baselineLine ? (
                <div className="px-2.5 py-2 text-[12px] text-ds-text-secondary">{toxicDisplay.baselineLine}</div>
              ) : null}
              <ListRow
                icon={SymbolBell}
                primary={toxicDisplay.eventsLine}
                secondary={toxicDisplay.ratesLine}
                status={toxicDisplay.showRowBadges ? resolveLocalTokenStatus("CURRENT") : undefined}
                muted={!toxicDisplay.showRowBadges}
              />
              <ListRow
                icon={SymbolBell}
                primary={toxicDisplay.trendLine}
                status={undefined}
              />
              <div className="space-y-1 px-2.5 py-2 text-[11px] text-ds-text-secondary">
                {toxicDisplay.sourceLine ? <p>{toxicDisplay.sourceLine}</p> : null}
                {toxicDisplay.asOfLine ? <p>{toxicDisplay.asOfLine}</p> : null}
                {toxicDisplay.historicalSourceLine ? <p>{toxicDisplay.historicalSourceLine}</p> : null}
                {toxicDisplay.actionLine ? <p>{toxicDisplay.actionLine}</p> : null}
              </div>
            </PanelCard>
          );
        })()}

        <PanelCard title={t("ops.pipelineCard")} icon={SymbolPipeline} status={pipelineStatus}>
          <ListRow
            icon={SymbolPipeline}
            primary={`${pipeline.step_count}/${pipeline.expected_step_count}`}
            secondary={`${t("ops.lastCycleDuration")}: ${pipeline.last_cycle_duration_s != null ? `${pipeline.last_cycle_duration_s}s` : "—"} · ${t("ops.avgCycleDuration")}: ${pipeline.average_cycle_duration_s != null ? `${pipeline.average_cycle_duration_s}s` : "—"}`}
            status={pipelineStatus}
          />
        </PanelCard>
      </div>
    </section>
  );
}

function EngineList({ engines }: { engines: EngineRow[] }) {
  const { t } = useTranslation();
  const visible = engines.filter((row) => !row.ignored_by_health).slice(0, 6);
  const overflow = engines.filter((row) => !row.ignored_by_health).length - visible.length;

  return (
    <PanelCard title={t("ops.engines")} icon={SymbolEngine} empty={visible.length === 0 ? t("ops.noActiveEngines") : undefined}>
      {visible.map((row) => (
        <ListRow
          key={row.engine}
          icon={SymbolEngine}
          primary={row.short_name}
          secondary={[row.last_run_ago ? t("ops.lastRun", { time: formatLastRunAgo(row.last_run_ago) ?? row.last_run_ago }) : null, row.duration_s != null ? `${row.duration_s}s` : null]
            .filter(Boolean)
            .join(" · ")}
          status={translateEngineState(row.status)}
        />
      ))}
      {overflow > 0 ? <div className="px-2.5 py-1.5 text-[11px] text-ds-text-secondary">{t("ops.more", { count: overflow })}</div> : null}
    </PanelCard>
  );
}

function ParquetCard({
  parquet,
  expanded,
  onToggle,
}: {
  parquet: OpsSnapshot["parquet"];
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const [showOptional, setShowOptional] = useState(false);
  const optional = parquet.optional ?? parquet.all.filter((p) => p.classification === "OPTIONAL");
  const summary = translateParquetSummary(parquet.missing_count, parquet.stale_count);

  return (
    <PanelCard title={t("ops.dataStores")} icon={SymbolDatabase} status={summary}>
      <ListRow
        icon={SymbolDatabase}
        primary={t("ops.requiredDatasets")}
        secondary={t("ops.liveStale", { live: parquet.live_count, stale: parquet.stale_count })}
        status={summary}
      />
      {parquet.stale_count > 0 ? (
        <>
          <button
            type="button"
            onClick={onToggle}
            className="mx-0.5 w-[calc(100%-0.25rem)] rounded-xl px-2.5 py-2 text-left text-[13px] font-medium text-ds-accent hover:bg-ds-surface-secondary/80"
          >
            {t("ops.staleFiles", { count: parquet.stale_count })}
          </button>
          {expanded
            ? parquet.stale_files.map((row: ParquetRow) => (
                <ListRow
                  key={row.file}
                  icon={SymbolDatabase}
                  primary={row.file}
                  secondary={row.age_seconds != null ? t("ops.ageOld", { age: Math.round(row.age_seconds) }) : undefined}
                  status={translateFreshness(row.freshness)}
                  muted={row.ignored_by_health}
                />
              ))
            : null}
        </>
      ) : null}
      {optional.length > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setShowOptional(!showOptional)}
            className="mx-0.5 w-[calc(100%-0.25rem)] rounded-xl px-2.5 py-2 text-left text-[13px] font-medium text-ds-text-secondary hover:bg-ds-surface-secondary/80"
          >
            {t("ops.optional", { count: optional.length })}
          </button>
          {showOptional
            ? optional.map((row) => (
                <ListRow
                  key={row.file}
                  icon={SymbolDatabase}
                  primary={row.file}
                  status={translateFreshness(row.freshness)}
                />
              ))
            : null}
        </>
      ) : null}
    </PanelCard>
  );
}

function CollectorsCard({ collectors }: { collectors: OpsSnapshot["collectors"] }) {
  const { t } = useTranslation();
  const required = collectors.required ?? collectors.collectors.filter((c) => c.classification === "REQUIRED");
  const summary = translateOpsLevel(collectors.level, "feed");

  return (
    <PanelCard title={t("ops.collectors")} icon={SymbolAntenna} status={summary}>
      {required.map((row: CollectorRow) => (
        <ListRow
          key={row.name}
          icon={SymbolAntenna}
          primary={row.name}
          secondary={row.latency_note ?? row.last_message ?? undefined}
          status={translateFeedConnection(row.status)}
          muted={row.ignored_by_health}
        />
      ))}
    </PanelCard>
  );
}


function RuntimeFailureAuditCard({ audit }: { audit?: RuntimeFailureAuditSummary }) {
  const recent = audit?.recent ?? [];
  const latest = audit?.latest;
  const affectsHealth = Boolean(audit?.affects_health);
  const statusToken = (audit?.status || "").toUpperCase();
  const status = affectsHealth
    ? translateAlertSeverity("WARNING")
    : statusToken === "RECOVERED" || statusToken === "NONE" || (audit?.exists && (audit.active_count ?? 0) === 0)
      ? translateActiveService()
      : translateAlertSeverity("INFO");
  const statusLabel = audit?.status_label
    || (affectsHealth ? "Active failures" : audit?.exists ? "No active failures" : "No runtime failure audit sidecar yet");

  return (
    <PanelCard
      title="Runtime Failure Audit"
      icon={SymbolEngine}
      status={status}
      empty={!audit?.exists ? "No runtime failure audit sidecar yet" : recent.length === 0 ? "No recorded runtime failures" : undefined}
    >
      {audit?.exists ? (
        <div className="px-2.5 py-2">
          <p className="mb-2 text-[12px] font-medium text-ds-text-secondary">{statusLabel}</p>
          <div className="grid grid-cols-3 gap-2 text-[11px] text-ds-text-secondary">
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Total</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{audit.total_count}</p>
            </div>
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Active</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{audit.active_count ?? 0}</p>
            </div>
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Historical</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{audit.historical_count ?? audit.total_count}</p>
            </div>
          </div>

          {latest ? (
            <div className="mt-3 rounded-xl border border-ds-border/40 bg-ds-surface-secondary/50 p-2.5">
              <p className="text-[11px] uppercase tracking-[0.08em] text-ds-text-tertiary">
                {affectsHealth ? "Latest failure" : "Latest historical failure"}
              </p>
              <p className="mt-1 truncate text-[13px] font-semibold text-ds-text-primary">{latest.engine ?? "unknown engine"}</p>
              <p className="mt-1 text-[12px] text-ds-text-secondary">
                {formatShortTime(latest.timestamp)} · {latest.duration_s != null ? `${latest.duration_s.toFixed(2)}s` : "duration n/a"}
              </p>
              {latest.error ? <p className="mt-1 line-clamp-2 text-[12px] text-ds-text-secondary">{latest.error}</p> : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {recent.slice(-6).reverse().map((record, index) => (
        <ListRow
          key={`${record.timestamp ?? "no-ts"}-${record.engine ?? "engine"}-${index}`}
          icon={SymbolBell}
          primary={record.engine ?? "unknown engine"}
          secondary={`${formatShortTime(record.timestamp)}${
            record.duration_s != null ? ` · ${record.duration_s.toFixed(2)}s` : ""
          }`}
          status={translateAlertSeverity(affectsHealth && record.status === "FAILED" ? "WARNING" : "INFO")}
        />
      ))}
    </PanelCard>
  );
}

function RuntimeSkippedEngineAuditCard({ audit }: { audit?: RuntimeSkippedEngineAuditSummary }) {
  const recent = audit?.recent ?? [];
  const latest = audit?.latest;
  const dependencyCount = latest?.dependencies ? Object.keys(latest.dependencies).length : 0;

  return (
    <PanelCard
      title="Runtime Skipped Engines"
      icon={SymbolPipeline}
      status={translateAlertSeverity("INFO")}
      empty={!audit?.exists ? "No skipped-engine audit sidecar yet" : recent.length === 0 ? "No skipped engines recorded" : undefined}
    >
      {audit?.exists ? (
        <div className="px-2.5 py-2">
          <div className="grid grid-cols-3 gap-2 text-[11px] text-ds-text-secondary">
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Total</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{audit.total_count}</p>
            </div>
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Recent</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{audit.recent_count}</p>
            </div>
            <div>
              <p className="uppercase tracking-[0.08em] text-ds-text-tertiary">Deps</p>
              <p className="mt-1 font-ds-display text-[22px] font-semibold text-ds-text-primary">{dependencyCount}</p>
            </div>
          </div>

          {latest ? (
            <div className="mt-3 rounded-xl border border-ds-border/40 bg-ds-surface-secondary/50 p-2.5">
              <p className="text-[11px] uppercase tracking-[0.08em] text-ds-text-tertiary">Latest dependency gate</p>
              <p className="mt-1 truncate text-[13px] font-semibold text-ds-text-primary">{latest.engine ?? "unknown engine"}</p>
              <p className="mt-1 text-[12px] text-ds-text-secondary">
                {formatShortTime(latest.timestamp)} · {latest.reason ?? "dependencies unchanged"}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      {recent.slice(-6).reverse().map((record, index) => (
        <ListRow
          key={`${record.timestamp ?? "no-ts"}-${record.engine ?? "engine"}-${index}`}
          icon={SymbolPipeline}
          primary={record.engine ?? "unknown engine"}
          secondary={`${formatShortTime(record.timestamp)} · ${record.reason ?? "dependencies unchanged"}`}
          status={translateAlertSeverity("INFO")}
        />
      ))}
    </PanelCard>
  );
}

function AlertsCard({
  alerts,
  alertGroups,
  acknowledged,
  onAck,
}: {
  alerts: OpsAlert[];
  alertGroups?: OpsSnapshot["alert_groups"];
  acknowledged: Set<string>;
  onAck: (id: string) => void;
}) {
  const { t } = useTranslation();
  const actionable = (alertGroups?.actionable ?? alerts.filter((a) => a.actionable !== false && !a.ignored_by_health)).filter(
    (a) => !acknowledged.has(a.id),
  );
  const summary = translateOpenAlerts(
    actionable.length,
    actionable.some((a) => a.severity === "CRITICAL"),
  );

  return (
    <PanelCard title={t("ops.alerts")} icon={SymbolBell} status={summary} empty={actionable.length === 0 ? t("ops.noAlerts") : undefined}>
      {actionable.map((alert) => (
        <div key={alert.id} className="px-2.5 py-3">
          <div className="flex items-start justify-between gap-3">
            <StatusIndicator status={translateAlertSeverity(alert.severity)} icon={SymbolBell} size="sm" />
            <button type="button" onClick={() => onAck(alert.id)} className="text-[12px] font-medium text-ds-accent hover:opacity-70">
              {t("ops.acknowledge")}
            </button>
          </div>
          <p className="mt-1.5 pl-6 text-[13px] leading-relaxed text-ds-text-primary">{alert.message}</p>
        </div>
      ))}
    </PanelCard>
  );
}

export function OpsDashboard({
  snapshot,
  expandedStaleParquet,
  onToggleStaleParquet,
  acknowledged,
  onAckAlert,
}: {
  snapshot: OpsSnapshot;
  expandedStaleParquet: boolean;
  onToggleStaleParquet: () => void;
  acknowledged: Set<string>;
  onAckAlert: (id: string) => void;
}) {
  const {
    health,
    pipeline,
    ribbon,
    engines,
    parquet,
    collectors,
    alerts,
    alert_groups,
    feed_confidence,
    stability,
    research_pipeline,
    runtime_failure_audit,
    runtime_skipped_engine_audit,
    health_dimensions: topHealthDimensions,
  } = snapshot;

  const dimensions = topHealthDimensions || health.health_dimensions;
  const runtimeRibbon = ribbon.filter((item) => !isResearchRibbonKey(item.key));
  const researchRibbon = ribbon.filter((item) => isResearchRibbonKey(item.key) && item.key !== "pipeline_sync");
  const pipelineSyncRibbon = ribbon.filter((item) => item.key === "pipeline_sync");

  const actionableAlerts = (alert_groups?.actionable ?? alerts.filter((a) => a.actionable !== false && !a.ignored_by_health)).filter(
    (a) => !acknowledged.has(a.id),
  );

  const healthStatus = translateSystemHealth(health.level, health.display_status);
  const memoryStatus = translateResourceUsage(health.memory_percent);
  const pipelineStatus = translatePipelineState(pipeline.active_state);
  const alertsStatus = translateOpenAlerts(
    actionableAlerts.length,
    actionableAlerts.some((a) => a.severity === "CRITICAL"),
  );
  const currentStallCount =
    pipeline.current_stalls_timeouts ??
    (pipeline.current_stalled_engine_count ?? pipeline.stalled_engine_count ?? 0) + (pipeline.timeout_count ?? 0);
  const historicalStallCount =
    pipeline.historical_stalls_timeouts ?? pipeline.historical_stalled_engine_count ?? 0;
  const runtimeStabilityStatus = translateRuntimeStability({
    currentStalls: currentStallCount,
    restartCount: stability?.restart_count,
    runtimeStatus: dimensions?.runtime.status,
  });
  const healthDisplay = useSimulatedStatus(healthStatus);
  const { t } = useTranslation();

  const researchStatus = dimensions
    ? translateHealthDimensionStatus(dimensions.research_validation.status)
    : translateValidationLevel("YELLOW");
  const historicalStatus = dimensions
    ? translateHealthDimensionStatus(dimensions.historical_audit.status)
    : translateHealthDimensionStatus("INFORMATIONAL");

  return (
    <div className="ops-surface min-h-full">
      <div className="mx-auto max-w-[1120px] space-y-6 p-5">
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            title={t("ops.systemHealth")}
            icon={SymbolHeart}
            status={healthStatus}
            hint={health.primary_reason}
            renderVisual={(tone) => (
              <RingGauge value={healthScore(health.level)} tone={tone} size={100}>
                <StatusOrb tone={tone} size="lg" />
              </RingGauge>
            )}
          />

          <KpiCard
            title={t("ops.memoryUsage")}
            icon={SymbolMemory}
            status={memoryStatus}
            hint={t("ops.resourceHint", { cpu: health.cpu_percent.toFixed(0), disk: health.disk_percent.toFixed(0) })}
            renderVisual={(tone) => (
              <RingGauge value={health.memory_percent} tone={tone} size={100}>
                <span className="font-ds-display text-[26px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {health.memory_percent.toFixed(0)}%
                </span>
              </RingGauge>
            )}
          />

          <KpiCard
            title={t("ops.pipelineStatus")}
            icon={SymbolPipeline}
            status={pipelineStatus}
            hint={
              pipeline.average_cycle_duration_s != null
                ? t("ops.cycleHintWithAvg", { cycle: pipeline.current_cycle, avg: pipeline.average_cycle_duration_s })
                : t("ops.cycleHint", { cycle: pipeline.current_cycle })
            }
            renderVisual={() => (
              <div className="text-center">
                <p className="font-ds-display text-[48px] font-semibold leading-none tabular-nums tracking-tight text-ds-text-primary">
                  {pipeline.current_cycle}
                </p>
                <p className="mt-1.5 text-[11px] text-ds-text-secondary">{t("ops.currentCycle")}</p>
              </div>
            )}
          />

          <KpiCard
            title={t("ops.openAlerts")}
            icon={SymbolBell}
            status={alertsStatus}
            hint={actionableAlerts.length === 0 ? t("ops.nothingRequiresAction") : t("ops.waiting", { count: actionableAlerts.length })}
            renderVisual={(tone) =>
              actionableAlerts.length === 0 ? (
                <StatusOrb tone={tone} size="lg" />
              ) : (
                <p className="font-ds-display text-[48px] font-semibold leading-none tabular-nums tracking-tight text-ds-text-primary">
                  {actionableAlerts.length}
                </p>
              )
            }
          />
        </div>

        <section className="space-y-2.5">
          <SectionLabel>{t("ops.resources")}</SectionLabel>
          <div className="grid gap-3.5 lg:grid-cols-3">
            <Card className="relative col-span-2 overflow-hidden p-4">
              <div className="ops-card-shimmer" aria-hidden />
              <div className="relative">
                <div className="mb-4 flex items-center gap-2">
                  <CardIcon icon={SymbolCpu} />
                  <h3 className="text-[14px] font-semibold text-ds-text-primary">{t("ops.resources")}</h3>
                </div>
                <div className="grid gap-5 sm:grid-cols-3">
                  <ProgressBar value={health.cpu_percent} label={t("ops.cpu")} icon={SymbolCpu} />
                  <ProgressBar value={health.memory_percent} label={t("ops.memory")} icon={SymbolMemory} />
                  <ProgressBar value={health.disk_percent} label={t("ops.disk")} icon={SymbolDatabase} />
                </div>
                {(dimensions?.resources.reason || health.reasons[0]) ? (
                  <ul className="mt-4 space-y-1.5 border-t border-ds-border/30 pt-3.5">
                    <li className="flex gap-2 text-[12px] text-ds-text-secondary">
                      <StatusDot tone={memoryStatus.tone} className="mt-1.5 h-2 w-2 shrink-0" />
                      <span>{dimensions?.resources.reason || health.reasons[0]}</span>
                    </li>
                  </ul>
                ) : null}
              </div>
            </Card>

            <StatusTile
              label="Research / Validation"
              icon={SymbolLayers}
              status={researchStatus}
            />
          </div>

          {feed_confidence ? (
            <div className="grid gap-3.5 md:grid-cols-3">
              {[feed_confidence.ws, feed_confidence.write, feed_confidence.consume].map((signal) => (
                <RibbonTile
                  key={signal.label}
                  icon={SymbolWifi}
                  label={signal.label}
                  status={translateOpsLevel(signal.level, "feed")}
                />
              ))}
            </div>
          ) : null}
        </section>

        <section className="space-y-2.5">
          <SectionLabel>Runtime Health</SectionLabel>
          <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
            {runtimeRibbon.map((item) => (
              <RibbonTile
                key={item.key}
                icon={ribbonIcon(item)}
                label={item.label}
                status={translateRibbonItem(item)}
              />
            ))}
            {pipelineSyncRibbon.map((item) => (
              <RibbonTile
                key={item.key}
                icon={ribbonIcon(item)}
                label={item.label}
                status={translateResearchRibbonItem(item)}
              />
            ))}
            <RibbonTile
              key="current-failures"
              icon={SymbolEngine}
              label="CURRENT FAILURES"
              status={translateFailedEngineCount(dimensions?.runtime.current_failures_count ?? 0)}
            />
          </div>
          {dimensions?.runtime.reason ? (
            <p className="px-0.5 text-[11px] text-ds-text-secondary">{dimensions.runtime.reason}</p>
          ) : null}
        </section>

        <section className="space-y-2.5">
          <SectionLabel>Research / Validation</SectionLabel>
          <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
            {researchRibbon.map((item) => (
              <RibbonTile
                key={item.key}
                icon={ribbonIcon(item)}
                label={item.label}
                status={translateResearchRibbonItem(item)}
              />
            ))}
          </div>
          {dimensions?.research_validation.reason ? (
            <p className="px-0.5 text-[11px] text-ds-text-secondary">
              {dimensions.research_validation.status}: {dimensions.research_validation.reason}
            </p>
          ) : null}
        </section>

        <section className="space-y-2.5">
          <SectionLabel>Historical Audit</SectionLabel>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile
              label="Historical failures"
              icon={SymbolEngine}
              value={
                <p className="font-ds-display text-[32px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {dimensions?.historical_audit.historical_failures_count ??
                    runtime_failure_audit?.historical_count ??
                    runtime_failure_audit?.total_count ??
                    0}
                </p>
              }
              status={historicalStatus}
            />
            <MetricTile
              label="Active failures"
              icon={SymbolBell}
              value={
                <p className="font-ds-display text-[32px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {dimensions?.runtime.current_failures_count ?? runtime_failure_audit?.active_count ?? 0}
                </p>
              }
              status={translateFailedEngineCount(dimensions?.runtime.current_failures_count ?? 0)}
            />
            <MetricTile
              label="Historical stalls/timeouts"
              icon={SymbolWaveform}
              value={
                <p className="font-ds-display text-[32px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {dimensions?.historical_audit.historical_stalls_count ?? historicalStallCount}
                </p>
              }
              status={historicalStatus}
            />
            <StatusTile label="Historical Audit" icon={SymbolClock} status={historicalStatus} />
          </div>
          <p className="px-0.5 text-[11px] text-ds-text-secondary">
            {dimensions?.historical_audit.reason || "Informational historical events only"}
            {dimensions?.historical_audit.latest_historical_failure_at
              ? ` · Latest historical failure: ${formatSourceTimestamp(String(dimensions.historical_audit.latest_historical_failure_at))}`
              : ""}
            {dimensions?.historical_audit.latest_historical_stall_at
              ? ` · Latest historical stall: ${formatSourceTimestamp(String(dimensions.historical_audit.latest_historical_stall_at))}`
              : ""}
          </p>
        </section>

        <section className="space-y-2.5">
          <SectionLabel>{t("ops.pipelineStatus")}</SectionLabel>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile
              label={t("ops.failedEngines")}
              icon={SymbolEngine}
              value={
                <p className="font-ds-display text-[32px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {pipeline.failed_engine_count}
                </p>
              }
              status={translateFailedEngineCount(pipeline.failed_engine_count)}
            />
            <MetricTile
              label="Current stalls/timeouts"
              icon={SymbolWaveform}
              value={
                <p className="font-ds-display text-[32px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
                  {currentStallCount}
                </p>
              }
              status={translateStallCount(currentStallCount)}
            />
            <StatusTile
              label={t("ops.heartbeat")}
              icon={SymbolWaveform}
              status={translateOpsLevel(pipeline.heartbeat_level, "engine")}
            />
            <StatusTile
              label="Runtime Stability"
              icon={SymbolClock}
              status={runtimeStabilityStatus}
            />
            <StatusTile
              label={t("ops.collectors")}
              icon={SymbolAntenna}
              status={translateOpsLevel(collectors.level, "feed")}
            />
          </div>

          <div className="grid gap-3.5 xl:grid-cols-2">
            <EngineList engines={engines} />
            <CollectorsCard collectors={collectors} />
          </div>
        </section>

        {research_pipeline ? <ResearchPipelineSection research={research_pipeline} /> : null}

        <section className="space-y-2.5">
          <SectionLabel>{t("ops.systemActivity")}</SectionLabel>
          <div className="grid gap-3.5 xl:grid-cols-3">
            <ParquetCard parquet={parquet} expanded={expandedStaleParquet} onToggle={onToggleStaleParquet} />
            {stability ? (
              <PanelCard title={t("ops.stability")} icon={SymbolClock} status={runtimeStabilityStatus}>
                <ListRow
                  icon={SymbolEngine}
                  primary={t("ops.runtime")}
                  secondary={formatUptime(stability.runtime_uptime_s)}
                  status={runtimeStabilityStatus}
                />
                <ListRow
                  icon={SymbolAntenna}
                  primary={t("ops.collectors")}
                  secondary={formatUptime(stability.collector_uptime_s)}
                  status={translateActiveService()}
                />
                <ListRow
                  icon={SymbolWifi}
                  primary={t("ops.webSocket")}
                  secondary={formatUptime(stability.websocket_uptime_s)}
                  status={translateActiveService()}
                />
                <div className="space-y-1 px-2.5 py-2 text-[11px] text-ds-text-secondary">
                  <p>Current stalls/timeouts: {currentStallCount}</p>
                  <p>Historical stalls/timeouts: {historicalStallCount}</p>
                  {pipeline.latest_historical_stall_at ? (
                    <p>Latest historical stall: {formatSourceTimestamp(String(pipeline.latest_historical_stall_at))}</p>
                  ) : null}
                </div>
              </PanelCard>
            ) : null}
            <RuntimeFailureAuditCard audit={runtime_failure_audit} />
            <RuntimeSkippedEngineAuditCard audit={runtime_skipped_engine_audit} />
            <AlertsCard alerts={alerts} alertGroups={alert_groups} acknowledged={acknowledged} onAck={onAckAlert} />
          </div>
        </section>
      </div>
    </div>
  );
}
