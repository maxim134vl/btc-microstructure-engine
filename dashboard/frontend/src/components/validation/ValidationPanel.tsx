import { useState } from "react";
import type { EvolutionReport, IntermediateCognitionSnapshot, Stage2_5CalibrationSnapshot, Stage2_5Comparison, StageComparison, ValidationReport, ValidationSnapshot, ValidationStageSnapshot } from "../../types/validation";

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
    <div className="space-y-4">
      <section className="rounded border border-slate-800 bg-slate-950 p-4">
        <h2 className="text-sm font-semibold tracking-wide text-slate-200">COGNITION HEALTH</h2>
        <p className="mt-2 text-2xl font-mono">
          {snapshot.conformance.health_emoji ?? "⚪"} {snapshot.conformance.cognition_health ?? "UNKNOWN"}
        </p>
        <p className="mt-1 text-xs text-slate-500">{snapshot.conformance.purpose}</p>
        {snapshot.conformance.auto_run_due ? (
          <p className="mt-1 text-[10px] text-amber-400">Conformance audit due (7-day cycle)</p>
        ) : null}
      </section>

      {snapshot.intermediate_cognition ? (
        <IntermediateCognitionSection data={snapshot.intermediate_cognition} />
      ) : null}

      <StageSection
        title="Stage 1 — Perception Validation"
        accent="violet"
        stage={snapshot.stage1}
        running={running}
        runLabel="Run Stage 1 Benchmark"
        onRun={() => handleRun("stage1", onRunStage1)}
        onVisuals={() => handleRun("stage1-visuals", () => onGenerateVisuals("stage1"))}
        onExport={() => handleExport("stage1")}
        onReport={() => handleReport("stage1")}
        metrics={stage1Metrics(snapshot.stage1)}
      />

      <StageSection
        title="Stage 2.5 — Intermediate Cognition Benchmark"
        accent="cyan"
        stage={snapshot.stage2_5}
        running={running}
        runLabel="Run Stage 2.5 Benchmark"
        onRun={() => handleRun("stage2_5", onRunStage2_5)}
        onVisuals={() => handleRun("stage2_5-visuals", () => onGenerateVisuals("stage2_5"))}
        onExport={() => handleExport("stage2_5")}
        onReport={() => handleReport("stage2_5")}
        extraButtons={
          <>
            <ActionButton label="Open Intermediate Cognition Audit" onClick={() => handleReport("stage2_5")} />
            <ActionButton label="Compare Stage 2.5 vs Outcome" onClick={handleCompareStage2_5} />
          </>
        }
        metrics={stage2_5Metrics(snapshot.stage2_5)}
      />

      {snapshot.stage2_5_calibration ? (
        <Stage2_5CalibrationSection
          data={snapshot.stage2_5_calibration}
          running={running}
          onRun={() => handleRun("stage2_5-calibration", onRunStage2_5Calibration)}
        />
      ) : null}

      <StageSection
        title="Stage 2 — Reasoning Validation"
        accent="sky"
        stage={snapshot.stage2}
        running={running}
        runLabel="Run Stage 2 Benchmark"
        onRun={() => handleRun("stage2", onRunStage2)}
        onVisuals={() => handleRun("stage2-visuals", () => onGenerateVisuals("stage2"))}
        onExport={() => handleExport("stage2")}
        onReport={() => handleReport("stage2")}
        extraButtons={
          <>
            <ActionButton label="Open Reasoning Replay" onClick={() => handleReport("stage2")} />
            <ActionButton label="View Contradiction Analysis" onClick={() => handleReport("stage2")} />
            <ActionButton label="Confidence Calibration Audit" onClick={() => handleReport("stage2")} />
          </>
        }
        metrics={stage2Metrics(snapshot.stage2)}
      />

      <StageSection
        title="Integrated — Full Cognition Chain"
        accent="emerald"
        stage={snapshot.integrated}
        running={running}
        runLabel="Run Integrated Benchmark"
        onRun={() => handleRun("integrated", onRunIntegrated)}
        onVisuals={() => handleRun("integrated-visuals", () => onGenerateVisuals("integrated"))}
        onExport={() => handleExport("integrated")}
        onReport={() => handleReport("integrated")}
        extraButtons={
          <>
            <ActionButton label="Open Full Cognition Replay" onClick={() => handleReport("integrated")} />
            <ActionButton label="View Root Cause Analysis" onClick={() => handleReport("integrated")} />
            <ActionButton label="Open Contradiction Map" onClick={() => handleReport("integrated")} />
            <ActionButton label="Confidence Drift Analysis" onClick={() => handleReport("integrated")} />
          </>
        }
        metrics={integratedMetrics(snapshot.integrated)}
      />

      <StageSection
        title="Conformance — Architecture Backtest"
        accent="amber"
        stage={snapshot.conformance}
        running={running}
        runLabel="Run Conformance Backtest"
        onRun={() => handleRun("conformance", () => onRunConformance())}
        onVisuals={() => handleRun("conformance-visuals", () => onGenerateVisuals("conformance"))}
        onExport={() => handleExport("conformance")}
        onReport={() => handleReport("conformance")}
        extraButtons={
          <>
            <ActionButton label="Run Stage 1 Conformance" onClick={() => handleRun("conformance-s1", () => onRunConformance("stage1"))} />
            <ActionButton label="Run Stage 2 Conformance" onClick={() => handleRun("conformance-s2", () => onRunConformance("stage2"))} />
            <ActionButton label="Run Integrated Conformance" onClick={() => handleRun("conformance-int", () => onRunConformance("integrated"))} />
            <ActionButton label="Open Drift Report" onClick={() => handleReport("conformance")} />
            <ActionButton label="Open Calibration Audit" onClick={() => handleReport("conformance")} />
          </>
        }
        metrics={conformanceMetrics(snapshot.conformance)}
      />

      <EvolutionSection
        evolution={snapshot.evolution}
        running={running}
        onRun={() => handleRun("evolution", () => onRunEvolution(false))}
        onRunFull={() => handleRun("evolution-full", () => onRunEvolution(true))}
        onReport={handleEvolutionReport}
      />

      <section className="rounded border border-slate-800 bg-slate-950 p-4">
        <h3 className="text-xs font-semibold text-slate-300">Cross-Stage</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          <ActionButton label="Compare Stage 1 vs Stage 2 vs Outcome" onClick={handleCompare} />
        </div>
      </section>

      {error ? <p className="text-xs text-red-400">{error}</p> : null}

      {comparison ? (
        <section className="rounded border border-slate-800 bg-slate-950 p-4">
          <h3 className="text-xs font-semibold text-slate-300">Stage 1 vs Stage 2 vs Integrated</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-3 text-[10px] font-mono text-slate-400">
            <div>
              <div className="text-violet-400">Stage 1 ({comparison.stage1_run_id ?? "—"})</div>
              <div>Events: {comparison.stage1_summary?.event_count ?? 0}</div>
              <div>Confirmed: {pct(comparison.stage1_summary?.confirmed_rate)}</div>
              <div>Structure coherence: {pct(comparison.stage1_summary?.market_structure_coherence)}</div>
            </div>
            <div>
              <div className="text-sky-400">Stage 2 ({comparison.stage2_run_id ?? "—"})</div>
              <div>Events: {comparison.stage2_summary?.event_count ?? 0}</div>
              <div>Reasoning accuracy: {pct(comparison.stage2_summary?.reasoning_accuracy)}</div>
              <div>Narrative coherence: {pct(comparison.stage2_summary?.narrative_coherence)}</div>
            </div>
            <div>
              <div className="text-emerald-400">Integrated ({comparison.integrated_run_id ?? "—"})</div>
              <div>Chains: {comparison.integrated_summary?.event_count ?? 0}</div>
              <div>Fully confirmed: {pct(comparison.integrated_summary?.fully_confirmed_rate)}</div>
              <div>Drift health: {comparison.drift?.health ?? "—"}</div>
            </div>
          </div>
        </section>
      ) : null}

      {stage2_5Comparison?.comparisons && stage2_5Comparison.comparisons.length > 0 ? (
        <section className="rounded border border-slate-800 bg-slate-950 p-4">
          <h3 className="text-xs font-semibold text-cyan-300">Stage 2.5 vs Outcome</h3>
          <p className="mt-1 text-[10px] text-slate-500">
            Narrative confirmation: {pct(stage2_5Comparison.narrative_confirmation_rate)} · run {stage2_5Comparison.run_id ?? "—"}
          </p>
          <div className="mt-2 space-y-1 text-[10px] font-mono text-slate-400">
            {stage2_5Comparison.comparisons.slice(0, 12).map((row) => (
              <div key={`${row.timestamp}-${row.intermediate_state}`} className="rounded border border-slate-900 px-2 py-1">
                {String(row.timestamp ?? "—").slice(0, 19)} · {row.intermediate_state} · {row.verdict} · {row.observed_outcome}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {exportPaths.length > 0 ? (
        <section className="rounded border border-slate-800 bg-slate-950 p-4">
          <h3 className="text-xs font-semibold text-slate-300">Export Package</h3>
          <ul className="mt-2 space-y-1 text-[10px] text-slate-500">
            {exportPaths.map((path) => (
              <li key={path} className="font-mono">{path}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {report?.markdown ? (
        <section className="rounded border border-slate-800 bg-slate-950 p-4">
          <h3 className="mb-2 text-xs font-semibold text-slate-300">
            Forensic Report — {report.stage ?? "stage1"}
          </h3>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-[10px] text-slate-400">{report.markdown}</pre>
        </section>
      ) : null}

      {evolutionReport?.markdown ? (
        <section className="rounded border border-slate-800 bg-slate-950 p-4">
          <h3 className="mb-2 text-xs font-semibold text-slate-300">Cognition Evolution Report</h3>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-[10px] text-slate-400">{evolutionReport.markdown}</pre>
        </section>
      ) : null}
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
  const live = data.live_assessment ?? data.latest_run;
  const overall = live?.overall_status ?? data.latest_run?.overall_status ?? "—";
  const states = live?.states ?? data.latest_run?.states ?? {};
  const trends = live?.overall_trends ?? data.latest_run?.overall_trends ?? {};
  const isRunning = running === "stage2_5-calibration";

  return (
    <section className="rounded border border-slate-800 bg-slate-950 p-4">
      <h2 className="text-sm font-semibold tracking-wide text-teal-300">STAGE 2.5 CALIBRATION</h2>
      <p className="mt-1 text-xs text-slate-500">{data.purpose}</p>
      {data.auto_run_due ? (
        <p className="mt-1 text-[10px] text-amber-400">Weekly calibration cycle due</p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? "Running…" : "Run Weekly Calibration"} onClick={onRun} disabled={Boolean(running)} />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="Overall status" value={overall} />
        <Metric label="Precision trend" value={trends.precision?.trend ?? "—"} />
        <Metric label="Confirmation trend" value={trends.confirmation_rate?.trend ?? "—"} />
        <Metric label="False positive trend" value={trends.false_positive_rate?.trend ?? "—"} />
      </div>

      <div className="mt-4 overflow-auto">
        <table className="w-full text-left text-[10px] font-mono">
          <thead className="text-slate-500">
            <tr>
              <th className="pb-2 pr-2">State</th>
              <th className="pb-2 pr-2">Status</th>
              <th className="pb-2 pr-2">Precision</th>
              <th className="pb-2 pr-2">Confirmation</th>
              <th className="pb-2 pr-2">False pos.</th>
              <th className="pb-2">Early warn.</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(states).map(([state, block]) => (
              <tr key={state} className="border-t border-slate-900 text-slate-400">
                <td className="py-1.5 pr-2 text-slate-200">{state.replace("IC_", "")}</td>
                <td className="py-1.5 pr-2">{block.status ?? "—"}</td>
                <td className="py-1.5 pr-2">{pct(block.metrics?.precision)}</td>
                <td className="py-1.5 pr-2">{pct(block.metrics?.confirmation_rate)}</td>
                <td className="py-1.5 pr-2">{pct(block.metrics?.false_positive_rate)}</td>
                <td className="py-1.5">{pct(block.metrics?.early_warning_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.weekly_history && data.weekly_history.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-300">Weekly History</h3>
          <div className="mt-2 space-y-1 text-[10px] font-mono text-slate-500">
            {data.weekly_history.slice(-6).reverse().map((row) => (
              <div key={row.run_id} className="rounded border border-slate-900 px-2 py-1">
                {String(row.generated_at ?? "—").slice(0, 19)} · {row.overall_status} · precision {pct(row.overall_metrics?.precision)}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function IntermediateCognitionSection({ data }: { data: IntermediateCognitionSnapshot }) {
  const rows = data.timeline.slice(-20).reverse();

  return (
    <section className="rounded border border-slate-800 bg-slate-950 p-4">
      <h2 className="text-sm font-semibold tracking-wide text-cyan-300">INTERMEDIATE COGNITION</h2>
      <p className="mt-1 text-xs text-slate-500">{data.purpose}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="Events (window)" value={String(data.event_count)} />
        <Metric label="Latest state" value={data.latest?.intermediate_state ?? "—"} />
        <Metric label="Stage 2 anchor" value={data.linked_stage2_anchor ?? "—"} />
        <Metric label="Anchor time" value={String(data.anchor_timestamp ?? "—").slice(0, 16)} />
      </div>
      <div className="mt-3 overflow-auto">
        <table className="w-full text-left text-[10px] font-mono">
          <thead className="text-slate-500">
            <tr>
              <th className="pb-2 pr-2">Timestamp</th>
              <th className="pb-2 pr-2">State</th>
              <th className="pb-2 pr-2">Confidence</th>
              <th className="pb-2 pr-2">Severity</th>
              <th className="pb-2">Stage 2 anchor</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.timestamp}-${index}`} className="border-t border-slate-900 text-slate-400">
                <td className="py-1.5 pr-2">{String(row.timestamp ?? "—").slice(0, 19)}</td>
                <td className="py-1.5 pr-2 text-slate-200">{row.intermediate_state ?? "—"}</td>
                <td className="py-1.5 pr-2">{row.confidence != null ? row.confidence.toFixed(2) : "—"}</td>
                <td className="py-1.5 pr-2">{row.severity ?? "—"}</td>
                <td className="py-1.5">{row.anchor_stage2_state ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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
  const trust = evolution.trust;
  const latest = evolution.latest_run;
  const comparisons = evolution.comparison?.comparisons ?? [];
  const trends = evolution.evolution?.trends ?? {};
  const regression = evolution.regression;
  const datasetTotals = evolution.dataset_totals ?? {};
  const isRunning = running?.startsWith("evolution") ?? false;

  return (
    <section className="rounded border border-slate-800 bg-slate-950 p-4">
      <h2 className="text-sm font-semibold tracking-wide text-rose-300">COGNITION EVOLUTION</h2>
      <p className="mt-1 text-xs text-slate-500">{evolution.purpose}</p>
      {evolution.auto_run_due ? (
        <p className="mt-1 text-[10px] text-amber-400">Evolution memory cycle due (7-day interval)</p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? "Running…" : "Update Evolution Memory"} onClick={onRun} disabled={Boolean(running)} />
        <ActionButton label="Run Full Evolution Cycle" onClick={onRunFull} disabled={Boolean(running)} />
        <ActionButton label="Open Evolution Report" onClick={onReport} />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <Metric label="Trust level" value={trust?.current_trust_level ?? "—"} />
        <Metric label="Rolling stability" value={pct(trust?.stability_score)} />
        <Metric label="History cycles" value={String(evolution.history_length ?? 0)} />
        <Metric label="Regression verdict" value={regression?.verdict ?? "—"} />
        <Metric label="Trustworthy share" value={pct(trust?.trustworthy_share)} />
        <Metric label="Stable vs toxic ratio" value={trust?.stable_vs_toxic_ratio?.toFixed(2) ?? "—"} />
      </div>

      {comparisons.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-300">Longitudinal Comparison</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-2 text-[10px] font-mono text-slate-400">
            {comparisons.slice(0, 6).map((row) => (
              <div key={row.metric ?? row.key ?? row.label} className="rounded border border-slate-900 px-2 py-1">
                <div className="text-slate-300">{row.label}</div>
                <div>Current: {pct(row.current)} · Δ prev: {row.delta_vs_previous != null ? `${(row.delta_vs_previous * 100).toFixed(1)}%` : "—"}</div>
                <div>Trend: {row.trend ?? "—"}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500">No longitudinal history yet — run evolution memory to establish baseline.</p>
      )}

      {Object.keys(trends).length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-300">Evolution Trends</h3>
          <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-mono text-slate-400">
            {Object.entries(trends).map(([alias, trend]) => (
              <span key={alias} className="rounded border border-slate-900 px-2 py-1">
                {alias}: {trend}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {regression?.events && regression.events.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-300">Regression Events</h3>
          <ul className="mt-2 space-y-1 text-[10px] text-slate-500">
            {regression.events.map((event, index) => (
              <li key={`${event.type}-${index}`} className="font-mono">
                [{event.type}] {event.note ?? "—"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {Object.keys(datasetTotals).length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-300">ML Dataset Buckets</h3>
          <div className="mt-2 grid gap-2 md:grid-cols-4 text-[10px] font-mono text-slate-400">
            {Object.entries(datasetTotals).map(([bucket, count]) => (
              <div key={bucket}>
                <div className="text-slate-500">{bucket}</div>
                <div>{count} records</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {latest?.run_id ? (
        <p className="mt-2 text-[10px] text-slate-500">Latest evolution run: {latest.run_id}</p>
      ) : null}
    </section>
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
  extraButtons?: React.ReactNode;
}) {
  const accentClass =
    accent === "violet"
      ? "text-violet-300"
      : accent === "sky"
        ? "text-sky-300"
        : accent === "emerald"
          ? "text-emerald-300"
          : accent === "cyan"
            ? "text-cyan-300"
            : "text-amber-300";
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
    <section className="rounded border border-slate-800 bg-slate-950 p-4">
      <h2 className={`text-sm font-semibold tracking-wide ${accentClass}`}>{title}</h2>
      <p className="mt-1 text-xs text-slate-500">{stage.purpose}</p>
      {stage.auto_run_due ? (
        <p className="mt-1 text-[10px] text-amber-400">Auto benchmark cycle due (default: 7 days)</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton label={isRunning ? "Running…" : runLabel} onClick={onRun} disabled={Boolean(running)} />
        <ActionButton label="Generate Visual Replay" onClick={onVisuals} disabled={Boolean(running)} />
        <ActionButton label="Export Cognition Report" onClick={onExport} disabled={Boolean(running)} />
        <ActionButton label="Open Benchmark Report" onClick={onReport} />
        {extraButtons}
      </div>
      {metrics.length > 0 ? (
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {metrics.map((metric) => (
            <Metric key={metric.label} label={metric.label} value={metric.value} />
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500">No benchmark run yet.</p>
      )}
      {stage.latest_run?.visuals && stage.latest_run.visuals.length > 0 ? (
        <p className="mt-2 text-[10px] text-slate-500">{stage.latest_run.visuals.length} chart(s) in benchmark/visuals/</p>
      ) : null}
    </section>
  );
}

function stage1Metrics(stage: ValidationStageSnapshot) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: "Events", value: String(summary.event_count) },
    { label: "Confirmed", value: pct(summary.confirmed_rate) },
    { label: "False positives", value: pct(summary.false_positive_rate) },
    { label: "Climax confirmation", value: pct(summary.climax_confirmation_rate) },
    { label: "Stopping quality", value: pct(summary.stopping_quality_rate) },
    { label: "Structure coherence", value: pct(summary.market_structure_coherence) },
  ];
}

function stage2_5Metrics(stage: ValidationStageSnapshot) {
  const summary = stage.latest_run?.summary as Record<string, unknown> | undefined;
  if (!summary) return [];
  return [
    { label: "Events", value: String(summary.event_count ?? 0) },
    { label: "Precision", value: pct(summary.precision as number | undefined) },
    { label: "Confirmation", value: pct(summary.confirmation_rate as number | undefined) },
    { label: "False positives", value: pct(summary.false_positive_rate as number | undefined) },
    { label: "Early warnings", value: pct(summary.early_warning_rate as number | undefined) },
    { label: "Narrative confirm", value: pct(summary.narrative_confirmation_rate as number | undefined) },
  ];
}

function stage2Metrics(stage: ValidationStageSnapshot) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: "Events", value: String(summary.event_count) },
    { label: "Reasoning accuracy", value: pct(summary.reasoning_accuracy) },
    { label: "Calibration quality", value: pct(summary.probabilistic_calibration_quality) },
    { label: "Narrative coherence", value: pct(summary.narrative_coherence) },
    { label: "Contradiction rate", value: pct(summary.contradiction_frequency) },
    { label: "Overconfident rate", value: pct(summary.overconfident_rate) },
  ];
}

function integratedMetrics(stage: ValidationStageSnapshot) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: "Chains", value: String(summary.event_count) },
    { label: "Fully confirmed", value: pct(summary.fully_confirmed_rate) },
    { label: "Cross-stage alignment", value: pct(summary.cross_stage_alignment) },
    { label: "Confidence realism", value: pct(summary.confidence_realism) },
    { label: "Market confirmation", value: pct(summary.market_confirmation_rate) },
    { label: "Cognition drift", value: pct(summary.cognition_drift_frequency) },
  ];
}

function conformanceMetrics(stage: ValidationStageSnapshot) {
  const summary = stage.latest_run?.summary;
  if (!summary) return [];
  return [
    { label: "Metrics", value: String(summary.metric_count ?? summary.event_count ?? 0) },
    { label: "Stability", value: pct(summary.cognition_stability_score) },
    { label: "Ontology", value: pct(summary.ontology_integrity_score) },
    { label: "Calibration", value: pct(summary.calibration_health_score) },
    { label: "Drift severity", value: pct(summary.drift_severity_score) },
    { label: "Failed", value: String(summary.failed_count ?? 0) },
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
      className="rounded border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
    >
      {label}
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-900 px-3 py-2 text-xs font-mono">
      <div className="text-slate-500">{label}</div>
      <div className="text-slate-200">{value}</div>
    </div>
  );
}
