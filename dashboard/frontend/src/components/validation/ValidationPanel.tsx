import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "../../i18n";
import type { TranslationParams } from "../../i18n";

type TFunction = (key: string, params?: TranslationParams) => string;
import type { EvolutionReport, IntermediateCognitionSnapshot, Stage2_5CalibrationSnapshot, Stage2_5Comparison, StageComparison, ValidationReport, ValidationSnapshot, ValidationStageSnapshot } from "../../types/validation";
import { ValidationDomainNav } from "./ValidationDomainNav";
import { ValidationExecutiveOverview } from "./ValidationExecutiveOverview";
import { buildExecutiveKpis, type ValidationDomain } from "./validationOverview";

export function ValidationPanel({
  snapshot,
  onRunStage1,
  onRunStage2,
  onRunStage2_5,
  onRunStage2_5Calibration,
  onRunIntegrated,
  onRunConformance,
  onRunEvolution,
  onLoadReport,
  onLoadEvolutionReport,
  onGenerateVisuals,
  onExportPackage,
  onCompare,
  onCompareStage2_5,
}: {
  snapshot: ValidationSnapshot;
  onRunStage1: () => Promise<void>;
  onRunStage2: () => Promise<void>;
  onRunStage2_5: () => Promise<void>;
  onRunStage2_5Calibration: () => Promise<void>;
  onRunIntegrated: () => Promise<void>;
  onRunConformance: (layer?: string) => Promise<void>;
  onRunEvolution: (fullCycle?: boolean) => Promise<void>;
  onLoadReport: (stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance") => Promise<ValidationReport>;
  onLoadEvolutionReport: () => Promise<EvolutionReport>;
  onGenerateVisuals: (stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance") => Promise<void>;
  onExportPackage: (stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance") => Promise<{ exports: { type: string; path: string }[] }>;
  onCompare: () => Promise<StageComparison>;
  onCompareStage2_5: () => Promise<Stage2_5Comparison>;
}) {
  const [running, setRunning] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [evolutionReport, setEvolutionReport] = useState<EvolutionReport | null>(null);
  const [comparison, setComparison] = useState<StageComparison | null>(null);
  const [stage2_5Comparison, setStage2_5Comparison] = useState<Stage2_5Comparison | null>(null);
  const [exportPaths, setExportPaths] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeDomain, setActiveDomain] = useState<ValidationDomain>("perception");
  const { t } = useTranslation();

  const executiveKpis = useMemo(() => buildExecutiveKpis(snapshot, t), [snapshot, t]);

  async function handleRun(label: string, action: () => Promise<void>) {
    setRunning(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(null);
    }
  }

  async function handleReport(stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance") {
    setError(null);
    try {
      const data = await onLoadReport(stage);
      setReport(data);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleExport(stage: "stage1" | "stage2" | "stage2_5" | "integrated" | "conformance") {
    setError(null);
    try {
      const data = await onExportPackage(stage);
      setExportPaths(data.exports.map((item) => item.path));
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleCompareStage2_5() {
    setError(null);
    try {
      setStage2_5Comparison(await onCompareStage2_5());
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleCompare() {
    setError(null);
    try {
      setComparison(await onCompare());
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleEvolutionReport() {
    setError(null);
    try {
      setEvolutionReport(await onLoadEvolutionReport());
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="ops-surface flex min-h-0 flex-1 flex-col gap-5 p-4 sm:p-5">
      {snapshot.status === "UNAVAILABLE" ? (
        <section className="ops-card p-4">
          <p className="text-sm font-medium text-ds-text-primary">{t("validation.unavailable")}</p>
          <p className="mt-1 text-xs text-ds-text-secondary">
            {snapshot.message ?? t("validation.notGenerated")}
          </p>
          <p className="mt-2 text-[11px] text-ds-text-tertiary">
            {t("validation.domainsAvailable")}
          </p>
        </section>
      ) : null}

      <header>
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ds-text-tertiary">{t("validation.eyebrow")}</p>
        <h1 className="font-ds-display text-[22px] font-semibold tracking-tight text-ds-text-primary sm:text-[26px]">
          {t("validation.title")}
        </h1>
      </header>

      <ValidationExecutiveOverview kpis={executiveKpis} />

      <ValidationDomainNav active={activeDomain} onChange={setActiveDomain} />

      <div className="ops-card min-h-0 flex-1 p-4 sm:p-5">
        <div className="space-y-4">
          {activeDomain === "perception" ? (
            <StageSection
              title={t("validation.stages.stage1.title")}
              accent="violet"
              stage={snapshot.stage1}
              running={running}
              runLabel={t("validation.stages.stage1.run")}
              onRun={() => handleRun("stage1", onRunStage1)}
              onVisuals={() => handleRun("stage1-visuals", () => onGenerateVisuals("stage1"))}
              onExport={() => handleExport("stage1")}
              onReport={() => handleReport("stage1")}
              metrics={stage1Metrics(snapshot.stage1, t)}
            />
          ) : null}

          {activeDomain === "reasoning" ? (
            <>
              <StageSection
                title={t("validation.stages.stage2.title")}
                accent="sky"
                stage={snapshot.stage2}
                running={running}
                runLabel={t("validation.stages.stage2.run")}
                onRun={() => handleRun("stage2", onRunStage2)}
                onVisuals={() => handleRun("stage2-visuals", () => onGenerateVisuals("stage2"))}
                onExport={() => handleExport("stage2")}
                onReport={() => handleReport("stage2")}
                extraButtons={
                  <>
                    <ActionButton label={t("validation.actions.reasoningReplay")} onClick={() => handleReport("stage2")} />
                    <ActionButton label={t("validation.actions.contradictionAnalysis")} onClick={() => handleReport("stage2")} />
                    <ActionButton label={t("validation.actions.calibrationAudit")} onClick={() => handleReport("stage2")} />
                  </>
                }
                metrics={stage2Metrics(snapshot.stage2, t)}
              />
              <StageSection
                title={t("validation.stages.integrated.title")}
                accent="emerald"
                stage={snapshot.integrated}
                running={running}
                runLabel={t("validation.stages.integrated.run")}
                onRun={() => handleRun("integrated", onRunIntegrated)}
                onVisuals={() => handleRun("integrated-visuals", () => onGenerateVisuals("integrated"))}
                onExport={() => handleExport("integrated")}
                onReport={() => handleReport("integrated")}
                extraButtons={
                  <>
                    <ActionButton label={t("validation.actions.fullReplay")} onClick={() => handleReport("integrated")} />
                    <ActionButton label={t("validation.actions.rootCause")} onClick={() => handleReport("integrated")} />
                    <ActionButton label={t("validation.actions.contradictionMap")} onClick={() => handleReport("integrated")} />
                    <ActionButton label={t("validation.actions.confidenceDrift")} onClick={() => handleReport("integrated")} />
                  </>
                }
                metrics={integratedMetrics(snapshot.integrated, t)}
              />
              <DomainSubsection title={t("validation.crossStageComparison")}>
                <div className="flex flex-wrap gap-2">
                  <ActionButton label={t("validation.compareStage1Stage2")} onClick={handleCompare} />
                </div>
                {comparison ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                    <ComparisonCard
                      title={t("validation.comparison.stage1", { runId: comparison.stage1_run_id ?? "—" })}
                      lines={[
                        `${t("validation.metrics.events")}: ${comparison.stage1_summary?.event_count ?? 0}`,
                        `${t("validation.metrics.confirmed")}: ${pct(comparison.stage1_summary?.confirmed_rate)}`,
                        `${t("validation.metrics.structureCoherence")}: ${pct(comparison.stage1_summary?.market_structure_coherence)}`,
                      ]}
                    />
                    <ComparisonCard
                      title={t("validation.comparison.stage2", { runId: comparison.stage2_run_id ?? "—" })}
                      lines={[
                        `${t("validation.metrics.events")}: ${comparison.stage2_summary?.event_count ?? 0}`,
                        `${t("validation.metrics.reasoningAccuracy")}: ${pct(comparison.stage2_summary?.reasoning_accuracy)}`,
                        `${t("validation.metrics.narrativeCoherence")}: ${pct(comparison.stage2_summary?.narrative_coherence)}`,
                      ]}
                    />
                    <ComparisonCard
                      title={t("validation.comparison.integrated", { runId: comparison.integrated_run_id ?? "—" })}
                      lines={[
                        `${t("validation.metrics.chains")}: ${comparison.integrated_summary?.event_count ?? 0}`,
                        `${t("validation.metrics.fullyConfirmed")}: ${pct(comparison.integrated_summary?.fully_confirmed_rate)}`,
                        `${t("validation.comparison.driftHealth", { value: comparison.drift?.health ?? "—" })}`,
                      ]}
                    />
                  </div>
                ) : null}
              </DomainSubsection>
            </>
          ) : null}

          {activeDomain === "intermediate" ? (
            <>
              {snapshot.intermediate_cognition ? (
                <IntermediateCognitionSection data={snapshot.intermediate_cognition} />
              ) : (
                <EmptyDomainNote message={t("validation.icNotPresent")} />
              )}
              <StageSection
                title={t("validation.stages.stage2_5.title")}
                accent="cyan"
                stage={snapshot.stage2_5}
                running={running}
                runLabel={t("validation.stages.stage2_5.run")}
                onRun={() => handleRun("stage2_5", onRunStage2_5)}
                onVisuals={() => handleRun("stage2_5-visuals", () => onGenerateVisuals("stage2_5"))}
                onExport={() => handleExport("stage2_5")}
                onReport={() => handleReport("stage2_5")}
                extraButtons={
                  <>
                    <ActionButton label={t("validation.actions.intermediateAudit")} onClick={() => handleReport("stage2_5")} />
                    <ActionButton label={t("validation.actions.compareStage2_5")} onClick={handleCompareStage2_5} />
                  </>
                }
                metrics={stage2_5Metrics(snapshot.stage2_5, t)}
              />
              {stage2_5Comparison?.comparisons && stage2_5Comparison.comparisons.length > 0 ? (
                <DomainSubsection title={t("validation.stage2_5VsOutcome")}>
                  <p className="text-[11px] text-ds-text-secondary">
                    {t("validation.narrativeConfirmation", { value: pct(stage2_5Comparison.narrative_confirmation_rate) })} ·{" "}
                    {t("validation.comparison.runId", { id: stage2_5Comparison.run_id ?? "—" })}
                  </p>
                  <div className="mt-3 max-h-[320px] space-y-1 overflow-y-auto pr-1">
                    {stage2_5Comparison.comparisons.map((row) => (
                      <div
                        key={`${row.timestamp}-${row.intermediate_state}`}
                        className="rounded-xl bg-ds-surface-secondary/80 px-3 py-2 text-[11px] text-ds-text-secondary"
                      >
                        {String(row.timestamp ?? "—").slice(0, 19)} · {row.intermediate_state} · {row.verdict} ·{" "}
                        {row.observed_outcome}
                      </div>
                    ))}
                  </div>
                </DomainSubsection>
              ) : null}
            </>
          ) : null}

          {activeDomain === "calibration" ? (
            snapshot.stage2_5_calibration ? (
              <Stage2_5CalibrationSection
                data={snapshot.stage2_5_calibration}
                running={running}
                onRun={() => handleRun("stage2_5-calibration", onRunStage2_5Calibration)}
              />
            ) : (
              <EmptyDomainNote message={t("validation.calibrationNotPresent")} />
            )
          ) : null}

          {activeDomain === "evolution" ? (
            <EvolutionSection
              evolution={snapshot.evolution}
              running={running}
              onRun={() => handleRun("evolution", () => onRunEvolution(false))}
              onRunFull={() => handleRun("evolution-full", () => onRunEvolution(true))}
              onReport={handleEvolutionReport}
            />
          ) : null}

          {activeDomain === "architecture" ? (
            <StageSection
              title={t("validation.stages.conformance.title")}
              accent="amber"
              stage={snapshot.conformance}
              running={running}
              runLabel={t("validation.stages.conformance.run")}
              onRun={() => handleRun("conformance", () => onRunConformance())}
              onVisuals={() => handleRun("conformance-visuals", () => onGenerateVisuals("conformance"))}
              onExport={() => handleExport("conformance")}
              onReport={() => handleReport("conformance")}
              extraButtons={
                <>
                  <ActionButton label={t("validation.actions.conformanceS1")} onClick={() => handleRun("conformance-s1", () => onRunConformance("stage1"))} />
                  <ActionButton label={t("validation.actions.conformanceS2")} onClick={() => handleRun("conformance-s2", () => onRunConformance("stage2"))} />
                  <ActionButton label={t("validation.actions.conformanceIntegrated")} onClick={() => handleRun("conformance-int", () => onRunConformance("integrated"))} />
                  <ActionButton label={t("validation.actions.driftReport")} onClick={() => handleReport("conformance")} />
                  <ActionButton label={t("validation.actions.calibrationAuditShort")} onClick={() => handleReport("conformance")} />
                </>
              }
              metrics={conformanceMetrics(snapshot.conformance, t)}
            />
          ) : null}

          {error ? <p className="text-xs text-ds-status-error">{error}</p> : null}

          {exportPaths.length > 0 ? (
            <DomainSubsection title={t("validation.exportPackage")}>
              <ul className="space-y-1 text-[11px] text-ds-text-tertiary">
                {exportPaths.map((path) => (
                  <li key={path} className="font-mono break-all">
                    {path}
                  </li>
                ))}
              </ul>
            </DomainSubsection>
          ) : null}

          {report?.markdown ? (
            <DomainSubsection title={t("validation.forensicReport", { stage: report.stage ?? "stage1" })}>
              <pre className="panel-scroll max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-xl bg-ds-surface-secondary/60 p-3 text-[11px] leading-relaxed text-ds-text-secondary">
                {report.markdown}
              </pre>
            </DomainSubsection>
          ) : null}

          {evolutionReport?.markdown ? (
            <DomainSubsection title={t("validation.evolutionReport")}>
              <pre className="panel-scroll max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-xl bg-ds-surface-secondary/60 p-3 text-[11px] leading-relaxed text-ds-text-secondary">
                {evolutionReport.markdown}
              </pre>
            </DomainSubsection>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Stage2_5CalibrationSection({
  data,
  running,
  onRun,
}: {
  data: Stage2_5CalibrationSnapshot;
  running: string | null;
  onRun: () => void;
}) {
  const { t } = useTranslation();
  const live = data.live_assessment ?? data.latest_run;
  const overall = live?.overall_status ?? data.latest_run?.overall_status ?? "—";
  const states = live?.states ?? data.latest_run?.states ?? {};
  const trends = live?.overall_trends ?? data.latest_run?.overall_trends ?? {};
  const isRunning = running === "stage2_5-calibration";

  return (
    <DomainSubsection title={t("validation.sections.calibration")}>
      <p className="text-[12px] text-ds-text-secondary">{data.purpose}</p>
      {data.auto_run_due ? (
        <p className="mt-1 text-[11px] text-ds-status-warning">{t("validation.sections.weeklyDue")}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? t("validation.running") : t("validation.actions.runWeeklyCalibration")} onClick={onRun} disabled={Boolean(running)} />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label={t("validation.metrics.overallStatus")} value={overall} />
        <Metric label={t("validation.metrics.precisionTrend")} value={trends.precision?.trend ?? "—"} />
        <Metric label={t("validation.metrics.confirmationTrend")} value={trends.confirmation_rate?.trend ?? "—"} />
        <Metric label={t("validation.metrics.falsePositiveTrend")} value={trends.false_positive_rate?.trend ?? "—"} />
      </div>

      <div className="mt-4 panel-scroll max-h-[280px] overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-ds-surface text-ds-text-tertiary">
            <tr>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.state")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.overallStatus")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.precision")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.confirmation")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.falsePos")}</th>
              <th className="pb-2 font-medium">{t("validation.metrics.earlyWarn")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(states).map(([state, block]) => (
              <tr key={state} className="border-t border-ds-border/60 text-ds-text-secondary">
                <td className="py-2 pr-2 text-ds-text-primary">{state.replace("IC_", "")}</td>
                <td className="py-2 pr-2">{block.status ?? "—"}</td>
                <td className="py-2 pr-2">{pct(block.metrics?.precision)}</td>
                <td className="py-2 pr-2">{pct(block.metrics?.confirmation_rate)}</td>
                <td className="py-2 pr-2">{pct(block.metrics?.false_positive_rate)}</td>
                <td className="py-2">{pct(block.metrics?.early_warning_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.weekly_history && data.weekly_history.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ds-text-primary">{t("validation.metrics.weeklyHistory")}</h3>
          <div className="mt-2 space-y-1">
            {data.weekly_history.slice(-6).reverse().map((row) => (
              <div key={row.run_id} className="rounded-xl bg-ds-surface-secondary/80 px-3 py-2 text-[11px] text-ds-text-secondary">
                {String(row.generated_at ?? "—").slice(0, 19)} · {row.overall_status} · precision {pct(row.overall_metrics?.precision)}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </DomainSubsection>
  );
}

function IntermediateCognitionSection({ data }: { data: IntermediateCognitionSnapshot }) {
  const { t } = useTranslation();
  const rows = data.timeline.slice(-20).reverse();

  return (
    <DomainSubsection title={t("validation.sections.intermediateCognition")}>
      <p className="text-[12px] text-ds-text-secondary">{data.purpose}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label={t("validation.metrics.eventsWindow")} value={String(data.event_count)} />
        <Metric label={t("validation.metrics.latestState")} value={data.latest?.intermediate_state ?? "—"} />
        <Metric label={t("validation.metrics.stage2Anchor")} value={data.linked_stage2_anchor ?? "—"} />
        <Metric label={t("validation.metrics.anchorTime")} value={String(data.anchor_timestamp ?? "—").slice(0, 16)} />
      </div>
      <div className="mt-4 panel-scroll max-h-[320px] overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-ds-surface text-ds-text-tertiary">
            <tr>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.timestamp")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.state")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.confidence")}</th>
              <th className="pb-2 pr-2 font-medium">{t("validation.metrics.severity")}</th>
              <th className="pb-2 font-medium">{t("validation.metrics.stage2Anchor")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.timestamp}-${index}`} className="border-t border-ds-border/60 text-ds-text-secondary">
                <td className="py-2 pr-2">{String(row.timestamp ?? "—").slice(0, 19)}</td>
                <td className="py-2 pr-2 text-ds-text-primary">{row.intermediate_state ?? "—"}</td>
                <td className="py-2 pr-2">{row.confidence != null ? row.confidence.toFixed(2) : "—"}</td>
                <td className="py-2 pr-2">{row.severity ?? "—"}</td>
                <td className="py-2">{row.anchor_stage2_state ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DomainSubsection>
  );
}

function EvolutionSection({
  evolution,
  running,
  onRun,
  onRunFull,
  onReport,
}: {
  evolution: ValidationSnapshot["evolution"];
  running: string | null;
  onRun: () => void;
  onRunFull: () => void;
  onReport: () => void;
}) {
  const { t } = useTranslation();
  const trust = evolution.trust;
  const latest = evolution.latest_run;
  const comparisons = evolution.comparison?.comparisons ?? [];
  const trends = evolution.evolution?.trends ?? {};
  const regression = evolution.regression;
  const datasetTotals = evolution.dataset_totals ?? {};
  const isRunning = running?.startsWith("evolution") ?? false;

  return (
    <DomainSubsection title={t("validation.sections.evolution")}>
      <p className="text-[12px] text-ds-text-secondary">{evolution.purpose}</p>
      {evolution.auto_run_due ? (
        <p className="mt-1 text-[11px] text-ds-status-warning">{t("validation.sections.evolutionDue")}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? t("validation.running") : t("validation.actions.updateEvolution")} onClick={onRun} disabled={Boolean(running)} />
        <ActionButton label={t("validation.actions.runFullEvolution")} onClick={onRunFull} disabled={Boolean(running)} />
        <ActionButton label={t("validation.actions.openEvolutionReport")} onClick={onReport} />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <Metric label={t("validation.metrics.trustLevel")} value={trust?.current_trust_level ?? "—"} />
        <Metric label={t("validation.metrics.rollingStability")} value={pct(trust?.stability_score)} />
        <Metric label={t("validation.metrics.historyCycles")} value={String(evolution.history_length ?? 0)} />
        <Metric label={t("validation.metrics.regressionVerdict")} value={regression?.verdict ?? "—"} />
        <Metric label={t("validation.metrics.trustworthyShare")} value={pct(trust?.trustworthy_share)} />
        <Metric label={t("validation.metrics.stableVsToxic")} value={trust?.stable_vs_toxic_ratio?.toFixed(2) ?? "—"} />
      </div>

      {comparisons.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ds-text-primary">{t("validation.sections.longitudinal")}</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            {comparisons.map((row) => (
              <div key={row.metric ?? row.key ?? row.label} className="rounded-xl bg-ds-surface-secondary/80 px-3 py-2 text-[11px] text-ds-text-secondary">
                <div className="font-medium text-ds-text-primary">{row.label}</div>
                <div>{t("validation.metrics.currentDelta", { current: pct(row.current), delta: row.delta_vs_previous != null ? `${(row.delta_vs_previous * 100).toFixed(1)}%` : "—" })}</div>
                <div>{t("validation.metrics.trend", { value: row.trend ?? "—" })}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-2 text-[12px] text-ds-text-tertiary">{t("validation.noEvolutionHistory")}</p>
      )}

      {Object.keys(trends).length > 0 ? (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ds-text-primary">{t("validation.sections.trends")}</h3>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-ds-text-secondary">
            {Object.entries(trends).map(([alias, trend]) => (
              <span key={alias} className="rounded-ds-pill bg-ds-surface-secondary px-2.5 py-1">
                {alias}: {trend}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {regression?.events && regression.events.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ds-text-primary">{t("validation.sections.regressionEvents")}</h3>
          <ul className="mt-2 space-y-1 text-[11px] text-ds-text-secondary">
            {regression.events.map((event, index) => (
              <li key={`${event.type}-${index}`}>
                [{event.type}] {event.note ?? "—"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {Object.keys(datasetTotals).length > 0 ? (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ds-text-primary">{t("validation.sections.mlBuckets")}</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-4 text-[11px] text-ds-text-secondary">
            {Object.entries(datasetTotals).map(([bucket, count]) => (
              <div key={bucket} className="rounded-xl bg-ds-surface-secondary/60 px-3 py-2">
                <div className="text-ds-text-tertiary">{bucket}</div>
                <div className="font-medium text-ds-text-primary">{t("validation.sections.records", { count })}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {latest?.run_id ? <p className="mt-2 text-[11px] text-ds-text-tertiary">{t("validation.sections.latestEvolutionRun", { id: latest.run_id })}</p> : null}
    </DomainSubsection>
  );
}

function StageSection({
  title,
  accent,
  stage,
  running,
  runLabel,
  onRun,
  onVisuals,
  onExport,
  onReport,
  metrics,
  extraButtons,
}: {
  title: string;
  accent: "violet" | "sky" | "emerald" | "amber" | "cyan";
  stage: ValidationStageSnapshot;
  running: string | null;
  runLabel: string;
  onRun: () => void;
  onVisuals: () => void;
  onExport: () => void;
  onReport: () => void;
  metrics: { label: string; value: string }[];
  extraButtons?: ReactNode;
}) {
  const { t } = useTranslation();
  const runPrefix =
    accent === "violet"
      ? "stage1"
      : accent === "sky"
        ? "stage2"
        : accent === "cyan"
          ? "stage2_5"
          : accent === "emerald"
            ? "integrated"
            : "conformance";
  const isRunning = running?.startsWith(runPrefix) ?? false;

  return (
    <DomainSubsection title={title}>
      <p className="text-[12px] text-ds-text-secondary">{stage.purpose}</p>
      {stage.auto_run_due ? (
        <p className="mt-1 text-[11px] text-ds-status-warning">{t("validation.autoBenchmarkDue")}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? t("validation.running") : runLabel} onClick={onRun} disabled={Boolean(running)} />
        <ActionButton label={t("validation.generateVisualReplay")} onClick={onVisuals} disabled={Boolean(running)} />
        <ActionButton label={t("validation.exportReport")} onClick={onExport} disabled={Boolean(running)} />
        <ActionButton label={t("validation.openReport")} onClick={onReport} />
        {extraButtons}
      </div>
      {metrics.length > 0 ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.map((metric) => (
            <Metric key={metric.label} label={metric.label} value={metric.value} />
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[12px] text-ds-text-tertiary">{t("validation.noBenchmarkYet")}</p>
      )}
      {stage.latest_run?.visuals && stage.latest_run.visuals.length > 0 ? (
        <p className="mt-2 text-[11px] text-ds-text-tertiary">{t("validation.chartsInBenchmark", { count: stage.latest_run.visuals.length })}</p>
      ) : null}
    </DomainSubsection>
  );
}

function stage1Metrics(stage: ValidationStageSnapshot, t: TFunction) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: t("validation.metrics.events"), value: String(summary.event_count) },
    { label: t("validation.metrics.confirmed"), value: pct(summary.confirmed_rate) },
    { label: t("validation.metrics.falsePositives"), value: pct(summary.false_positive_rate) },
    { label: t("validation.metrics.climaxConfirmation"), value: pct(summary.climax_confirmation_rate) },
    { label: t("validation.metrics.stoppingQuality"), value: pct(summary.stopping_quality_rate) },
    { label: t("validation.metrics.structureCoherence"), value: pct(summary.market_structure_coherence) },
  ];
}

function stage2_5Metrics(stage: ValidationStageSnapshot, t: TFunction) {
  const summary = stage.latest_run?.summary as Record<string, unknown> | undefined;
  if (!summary) return [];
  return [
    { label: t("validation.metrics.events"), value: String(summary.event_count ?? 0) },
    { label: t("validation.metrics.precision"), value: pct(summary.precision as number | undefined) },
    { label: t("validation.metrics.confirmation"), value: pct(summary.confirmation_rate as number | undefined) },
    { label: t("validation.metrics.falsePositives"), value: pct(summary.false_positive_rate as number | undefined) },
    { label: t("validation.metrics.earlyWarnings"), value: pct(summary.early_warning_rate as number | undefined) },
    { label: t("validation.metrics.narrativeConfirm"), value: pct(summary.narrative_confirmation_rate as number | undefined) },
  ];
}

function stage2Metrics(stage: ValidationStageSnapshot, t: TFunction) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: t("validation.metrics.events"), value: String(summary.event_count) },
    { label: t("validation.metrics.reasoningAccuracy"), value: pct(summary.reasoning_accuracy) },
    { label: t("validation.metrics.calibrationQuality"), value: pct(summary.probabilistic_calibration_quality) },
    { label: t("validation.metrics.narrativeCoherence"), value: pct(summary.narrative_coherence) },
    { label: t("validation.metrics.contradictionRate"), value: pct(summary.contradiction_frequency) },
    { label: t("validation.metrics.overconfidentRate"), value: pct(summary.overconfident_rate) },
  ];
}

function integratedMetrics(stage: ValidationStageSnapshot, t: TFunction) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: t("validation.metrics.chains"), value: String(summary.event_count) },
    { label: t("validation.metrics.fullyConfirmed"), value: pct(summary.fully_confirmed_rate) },
    { label: t("validation.metrics.crossStageAlignment"), value: pct(summary.cross_stage_alignment) },
    { label: t("validation.metrics.confidenceRealism"), value: pct(summary.confidence_realism) },
    { label: t("validation.metrics.marketConfirmation"), value: pct(summary.market_confirmation_rate) },
    { label: t("validation.metrics.cognitionDrift"), value: pct(summary.cognition_drift_frequency) },
  ];
}

function conformanceMetrics(stage: ValidationStageSnapshot, t: TFunction) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: t("validation.metrics.metrics"), value: String(summary.metric_count ?? summary.event_count ?? 0) },
    { label: t("validation.metrics.stability"), value: pct(summary.cognition_stability_score) },
    { label: t("validation.metrics.ontology"), value: pct(summary.ontology_integrity_score) },
    { label: t("validation.metrics.calibration"), value: pct(summary.calibration_health_score) },
    { label: t("validation.metrics.driftSeverity"), value: pct(summary.drift_severity_score) },
    { label: t("validation.metrics.failed"), value: String(summary.failed_count ?? 0) },
  ];
}

function pct(value?: number | null) {
  if (value === undefined || value === null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function ActionButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-ds-button border border-ds-border bg-ds-surface-secondary px-3 py-1.5 text-[12px] font-medium text-ds-text-primary transition-colors hover:bg-ds-surface disabled:opacity-50"
    >
      {label}
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-ds-surface-secondary/70 px-3 py-2.5">
      <div className="text-[11px] text-ds-text-tertiary">{label}</div>
      <div className="mt-0.5 font-ds-display text-[15px] font-semibold tabular-nums text-ds-text-primary">{value}</div>
    </div>
  );
}

function DomainSubsection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-ds-border/50 bg-ds-surface-secondary/30 p-4">
      <h2 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ComparisonCard({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="rounded-xl bg-ds-surface-secondary/80 px-3 py-2.5 text-[11px] text-ds-text-secondary">
      <div className="font-medium text-ds-text-primary">{title}</div>
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

function EmptyDomainNote({ message }: { message: string }) {
  return <p className="rounded-xl bg-ds-surface-secondary/50 px-4 py-6 text-[13px] text-ds-text-secondary">{message}</p>;
}
