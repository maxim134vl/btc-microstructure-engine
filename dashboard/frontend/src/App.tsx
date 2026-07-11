import { useEffect, useState } from "react";
import { connectOps, softFetchOpsSnapshot } from "./api/client";
import { buildOpsFallbackSnapshot } from "./api/opsFallbackSnapshot";
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
import { RuntimeActivityPanel } from "./components/runtime-activity/RuntimeActivityPanel";
import { OpsDashboard } from "./components/ops/OpsDashboard";
import { StatusSimulatorProvider } from "./components/status";
import { AppHeader } from "./components/shell/AppHeader";
import { AppSidebar } from "./components/shell/AppSidebar";
import { MainContent } from "./components/shell/MainContent";
import { isFullBleedView, viewFromHash, type ViewMode } from "./components/shell/navConfig";
import { ValidationPanel } from "./components/validation/ValidationPanel";
import { useMonitorStore } from "./store/monitorStore";
import type { ValidationSnapshot } from "./types/validation";
import { useTranslation } from "./i18n";

function OpsMonitor() {
  const snapshot = useMonitorStore((s) => s.snapshot) ?? buildOpsFallbackSnapshot();
  const connected = useMonitorStore((s) => s.connected);
  const acknowledged = useMonitorStore((s) => s.acknowledgedAlerts);
  const acknowledgeAlert = useMonitorStore((s) => s.acknowledgeAlert);
  const expandedGroups = useMonitorStore((s) => s.expandedGroups);
  const toggleGroup = useMonitorStore((s) => s.toggleGroup);

  return (
    <div className="relative min-h-full">
      {!connected ? (
        <div className="pointer-events-none absolute right-5 top-3 z-10 rounded-ds-pill border border-ds-border/70 bg-ds-surface/90 px-2.5 py-1 text-[10px] font-medium text-ds-text-secondary shadow-ds-sm backdrop-blur">
          Live feed optional / offline
        </div>
      ) : null}
      <OpsDashboard
        snapshot={snapshot}
        expandedStaleParquet={expandedGroups.has("stale_parquet")}
        onToggleStaleParquet={() => toggleGroup("stale_parquet")}
        acknowledged={acknowledged}
        onAckAlert={acknowledgeAlert}
      />
    </div>
  );
}

function RuntimeActivityView() {
  return <RuntimeActivityPanel />;
}

function ValidationView() {
  const [snapshot, setSnapshot] = useState<ValidationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const { t } = useTranslation();

  useEffect(() => {
    setLoading(true);
    fetchValidationSnapshot()
      .then(setSnapshot)
      .catch(() => setSnapshot(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="ops-surface flex h-64 items-center justify-center text-[15px] text-ds-text-secondary">
        {t("validation.loading")}
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="ops-surface flex h-64 items-center justify-center p-6 text-[15px] text-ds-text-secondary">
        {t("validation.loadFailed")}
      </div>
    );
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

function renderView(view: ViewMode) {
  switch (view) {
    case "validation":
      return <ValidationView />;
    case "debug":
      return <RuntimeActivityView />;
    default:
      return <OpsMonitor />;
  }
}

export default function App() {
  const [view, setView] = useState<ViewMode>(viewFromHash);
  const [shellNavExpanded, setShellNavExpanded] = useState(true);
  const setSnapshot = useMonitorStore((s) => s.setSnapshot);
  const setConnected = useMonitorStore((s) => s.setConnected);

  useEffect(() => {
    // Keep fallback UI immediately; upgrade to live when dashboard API is up.
    // Direct :8080 (CORS) — no Vite proxy, so offline does not spam ECONNREFUSED.
    let cancelled = false;
    let socket: ReturnType<typeof connectOps> | null = null;

    const attachLiveSocket = () => {
      if (cancelled || socket) return;
      socket = connectOps(
        (live) => {
          if (cancelled) return;
          setSnapshot(live);
        },
        (ok) => {
          if (cancelled) return;
          setConnected(ok);
        },
      );
    };

    const tryLive = () =>
      softFetchOpsSnapshot().then((live) => {
        if (cancelled || !live) return false;
        setSnapshot(live);
        setConnected(true);
        attachLiveSocket();
        return true;
      });

    void tryLive();

    const poll = window.setInterval(() => {
      if (cancelled || useMonitorStore.getState().connected) return;
      void tryLive();
    }, 8_000);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      socket?.close();
    };
  }, [setSnapshot, setConnected]);

  useEffect(() => {
    const sync = () => setView(viewFromHash());
    window.addEventListener("hashchange", sync);
    sync();
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const content = (
    <div className="flex h-screen flex-col overflow-hidden bg-ds-background font-ds-text text-ds-text-primary">
      <div className="flex min-h-0 flex-1">
        <AppSidebar
          view={view}
          expanded={shellNavExpanded}
          onToggleExpanded={() => setShellNavExpanded((open) => !open)}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <AppHeader view={view} />
          <MainContent
            fullBleed={isFullBleedView(view)}
            nativeSurface={
              view === "ops" ||
              view === "debug" ||
              view === "validation"
            }
          >
            {renderView(view)}
          </MainContent>
        </div>
      </div>
    </div>
  );

  return import.meta.env.DEV ? <StatusSimulatorProvider>{content}</StatusSimulatorProvider> : content;
}
