import { useEffect, useState } from "react";
import { connectOps, fetchDebugSnapshot, fetchOpsSnapshot } from "./api/client";
import {
  compareStage1Stage2,
  compareStage2_5VsOutcome,
  exportValidationPackage,
  fetchEvolutionReport,
  fetchValidationReport,
  fetchValidationSnapshot,
  generateVisualReplay,
  runEvolutionCycle,
  runIntegratedBenchmark,
  runConformanceBacktest,
  runStage2Benchmark,
  runStage2_5Benchmark,
  runStage2_5Calibration,
  runValidationBenchmark,
} from "./api/validationClient";
import {
  AlertsPanel,
  CollectorsPanel,
  EngineTable,
  FeedConfidencePanel,
  HealthPanel,
  OpsRibbon,
  ParquetPanel,
  PipelinePanel,
  StabilityPanel,
} from "./components/ops/MonitorPanels";
import { ValidationPanel } from "./components/validation/ValidationPanel";
import { VisualCognitionPanel } from "./components/visual-cognition/VisualCognitionPanel";
import { useMonitorStore } from "./store/monitorStore";
import type { ValidationSnapshot } from "./types/validation";

type ViewMode = "ops" | "debug" | "validation" | "visual-cognition";

function OpsMonitor() {
  const snapshot = useMonitorStore((s) => s.snapshot);
  const setSnapshot = useMonitorStore((s) => s.setSnapshot);
  const setConnected = useMonitorStore((s) => s.setConnected);
  const acknowledged = useMonitorStore((s) => s.acknowledgedAlerts);
  const acknowledgeAlert = useMonitorStore((s) => s.acknowledgeAlert);
  const expandedGroups = useMonitorStore((s) => s.expandedGroups);
  const toggleGroup = useMonitorStore((s) => s.toggleGroup);

  useEffect(() => {
    fetchOpsSnapshot().then(setSnapshot).catch(console.error);
    const socket = connectOps(setSnapshot, setConnected);
    return () => socket.close();
  }, [setSnapshot, setConnected]);

  if (!snapshot) {
    return <div className="flex h-64 items-center justify-center text-sm text-slate-500">Connecting to runtime monitor…</div>;
  }

  return (
    <div className="space-y-3">
      <OpsRibbon items={snapshot.ribbon} />
      <div className="grid gap-3 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <EngineTable engines={snapshot.engines} />
        </div>
        <div className="space-y-3 xl:col-span-5">
          <HealthPanel health={snapshot.health} />
          {snapshot.feed_confidence ? <FeedConfidencePanel feed={snapshot.feed_confidence} /> : null}
          <PipelinePanel pipeline={snapshot.pipeline} />
          {snapshot.stability ? <StabilityPanel stability={snapshot.stability} /> : null}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <ParquetPanel
          parquet={snapshot.parquet}
          expanded={expandedGroups.has("stale_parquet")}
          onToggle={() => toggleGroup("stale_parquet")}
        />
        <CollectorsPanel collectors={snapshot.collectors} />
        <AlertsPanel
          alerts={snapshot.alerts}
          alertGroups={snapshot.alert_groups}
          acknowledged={acknowledged}
          onAck={acknowledgeAlert}
        />
      </div>
    </div>
  );
}

function DebugView() {
  const [payload, setPayload] = useState<string>("Loading debug telemetry…");

  useEffect(() => {
    fetchDebugSnapshot()
      .then((data) => setPayload(JSON.stringify(data, null, 2)))
      .catch((error) => setPayload(String(error)));
  }, []);

  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <div className="mb-2 text-sm font-semibold text-amber-400">Debug Mode — cognition/ontology telemetry (not operational)</div>
      <pre className="panel-scroll max-h-[80vh] overflow-auto text-[10px] text-slate-400">{payload}</pre>
    </div>
  );
}

function ValidationView() {
  const [snapshot, setSnapshot] = useState<ValidationSnapshot | null>(null);

  useEffect(() => {
    fetchValidationSnapshot().then(setSnapshot).catch(console.error);
  }, []);

  if (!snapshot) {
    return <div className="text-sm text-slate-500">Loading validation framework…</div>;
  }

  return (
    <ValidationPanel
      snapshot={snapshot}
      onRunStage1={async () => {
        await runValidationBenchmark();
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunStage2={async () => {
        await runStage2Benchmark();
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunStage2_5={async () => {
        await runStage2_5Benchmark();
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunStage2_5Calibration={async () => {
        await runStage2_5Calibration(true);
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunIntegrated={async () => {
        await runIntegratedBenchmark();
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunConformance={async (layer) => {
        await runConformanceBacktest(7, layer);
        setSnapshot(await fetchValidationSnapshot());
      }}
      onRunEvolution={async (fullCycle) => {
        await runEvolutionCycle(Boolean(fullCycle));
        setSnapshot(await fetchValidationSnapshot());
      }}
      onLoadReport={(stage) => fetchValidationReport(stage)}
      onLoadEvolutionReport={fetchEvolutionReport}
      onGenerateVisuals={async (stage) => {
        await generateVisualReplay(stage);
        setSnapshot(await fetchValidationSnapshot());
      }}
      onExportPackage={(stage) => exportValidationPackage(stage)}
      onCompare={compareStage1Stage2}
      onCompareStage2_5={compareStage2_5VsOutcome}
    />
  );
}

function viewFromHash(): ViewMode {
  const hash = window.location.hash.replace("#", "");
  if (hash === "debug") return "debug";
  if (hash === "validation") return "validation";
  if (hash === "visual-cognition") return "visual-cognition";
  return "ops";
}

export default function App() {
  const [view, setView] = useState<ViewMode>(viewFromHash);

  useEffect(() => {
    const sync = () => setView(viewFromHash());
    window.addEventListener("hashchange", sync);
    sync();
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  return (
    <div className="min-h-screen bg-[#05080d] text-slate-200">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <h1 className="text-sm font-semibold tracking-[0.18em] text-slate-100">BTC-ML RUNTIME OPERATIONS MONITOR</h1>
          <p className="text-[11px] text-slate-500">
            {view === "validation"
              ? "Perception · reasoning · integrated cognition validation"
              : view === "visual-cognition"
                ? "Stage 1 MTF visual cognition replay"
                : "Infrastructure supervision · NOC view"}
          </p>
        </div>
        <nav className="flex gap-3 text-xs font-mono text-slate-500">
          <a href="#" className={view === "ops" ? "text-slate-200" : "hover:text-slate-300"}>ops</a>
          <a href="#validation" className={view === "validation" ? "text-violet-300" : "hover:text-slate-300"}>
            validation
          </a>
          <a href="#visual-cognition" className={view === "visual-cognition" ? "text-emerald-300" : "hover:text-slate-300"}>
            visual-cognition
          </a>
          <a href="#debug" className={view === "debug" ? "text-amber-300" : "hover:text-slate-300"}>debug</a>
        </nav>
      </header>
      <main className="p-3">
        {view === "validation" ? (
          <ValidationView />
        ) : view === "visual-cognition" ? (
          <VisualCognitionPanel />
        ) : view === "debug" ? (
          <DebugView />
        ) : (
          <OpsMonitor />
        )}
      </main>
    </div>
  );
}
