import { MarketContextPanel } from "./components/ops/MarketContextPanel";
import { useEffect, useState } from "react";
import { startOpsLiveSession } from "./api/client";
import { buildOpsFallbackSnapshot } from "./api/opsFallbackSnapshot";
import { OpsUnifiedDashboard } from "./components/ops/OpsUnifiedDashboard";
import { StatusSimulatorProvider } from "./components/status";
import { AppHeader } from "./components/shell/AppHeader";
import { AppSidebar } from "./components/shell/AppSidebar";
import { MainContent } from "./components/shell/MainContent";
import { isFullBleedView, viewFromHash, type ViewMode } from "./components/shell/navConfig";
import { ChartsPanel } from "./components/trading-views/ChartsPanel";
import { DiaryPanel } from "./components/trading-views/DiaryPanel";
import { StatementPanel } from "./components/trading-views/StatementPanel";
import { useMonitorStore } from "./store/monitorStore";

function OpsMonitor({
  surface,
  fillWindow,
}: {
  surface: "operational" | "trading";
  fillWindow: boolean;
}) {
  const snapshot = useMonitorStore((s) => s.snapshot) ?? buildOpsFallbackSnapshot();
  const connected = useMonitorStore((s) => s.connected);
  const acknowledged = useMonitorStore((s) => s.acknowledgedAlerts);
  const acknowledgeAlert = useMonitorStore((s) => s.acknowledgeAlert);

  return (
    <div className="relative min-h-full">
      <OpsUnifiedDashboard
        snapshot={snapshot}
        liveConnected={connected}
        acknowledged={acknowledged}
        onAckAlert={acknowledgeAlert}
        surface={surface}
        fillWindow={fillWindow}
      />
    </div>
  );
}

function renderView(view: ViewMode, fillWindow: boolean) {
  switch (view) {
    case "market-context":
      return <MarketContextPanel />;
    case "trading":
      return <OpsMonitor surface="trading" fillWindow={fillWindow} />;
    case "statement":
      return <StatementPanel fillWindow={fillWindow} />;
    case "charts":
      return <ChartsPanel fillWindow={fillWindow} />;
    case "diary":
      return <DiaryPanel fillWindow={fillWindow} />;
    default:
      return <OpsMonitor surface="operational" fillWindow={fillWindow} />;
  }
}

export default function App() {
  const [view, setView] = useState<ViewMode>(viewFromHash);
  const [navOpen, setNavOpen] = useState(true);
  const setSnapshot = useMonitorStore((s) => s.setSnapshot);
  const setConnected = useMonitorStore((s) => s.setConnected);

  useEffect(() => {
    const session = startOpsLiveSession({
      onSnapshot: setSnapshot,
      onConnected: setConnected,
    });
    return () => session.stop();
  }, [setSnapshot, setConnected]);

  useEffect(() => {
    const sync = () => setView(viewFromHash());
    window.addEventListener("hashchange", sync);
    sync();
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const fillWindow = !navOpen;

  const content = (
    <div className="flex h-screen flex-col overflow-hidden bg-ds-background font-ds-text text-ds-text-primary">
      <div className="flex min-h-0 min-w-0 flex-1">
        <AppSidebar view={view} open={navOpen} />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <AppHeader view={view} navOpen={navOpen} onToggleNav={() => setNavOpen((open) => !open)} />
          <MainContent fullBleed={isFullBleedView(view)} nativeSurface>
            {renderView(view, fillWindow)}
          </MainContent>
        </div>
      </div>
    </div>
  );

  return import.meta.env.DEV ? <StatusSimulatorProvider>{content}</StatusSimulatorProvider> : content;
}
