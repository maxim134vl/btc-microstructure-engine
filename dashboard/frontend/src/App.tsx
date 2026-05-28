import { useEffect, useMemo } from "react";
import { connectLive, fetchSnapshot } from "./api/client";
import {
  AlertsPanel,
  CollapsibleSection,
  CompactOntologyPanel,
  D1DominancePanel,
  MtfHierarchyPanel,
  NarrativePanel,
  RibbonChipView,
  StateBlock,
} from "./components/cockpit";
import { buildOperatorView } from "./lib/operatorView";
import {
  CognitionPanelView,
  HealthPanelView,
  ReplayPanelView,
  RuntimeOperationsPanel,
  TopologyPanelView,
} from "./panels";
import { useDashboardStore } from "./store/dashboardStore";

function OperatorRibbon() {
  const snapshot = useDashboardStore((s) => s.snapshot);
  const connected = useDashboardStore((s) => s.connected);
  const view = useMemo(() => buildOperatorView(snapshot, connected), [snapshot, connected]);

  return (
    <header className="sticky top-0 z-30 border-b border-command-border bg-[#04070d]/98 backdrop-blur">
      <div className="border-b border-command-border/60 px-4 py-2">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs font-semibold tracking-[0.22em] text-slate-100">BTC-ML OPERATOR COCKPIT</div>
            <div className="text-[10px] text-command-muted">Behavioral control center · primary supervision surface</div>
          </div>
          <div className="text-[10px] font-mono text-command-muted">
            {view?.alerts.filter((a) => a.severity === "CRITICAL").length ?? 0} critical ·{" "}
            {view?.alerts.filter((a) => a.severity === "WARNING").length ?? 0} warning
          </div>
        </div>
      </div>
      <div className="panel-scroll flex gap-2 overflow-x-auto px-4 py-3">
        {view?.ribbon.map((chip) => <RibbonChipView key={chip.key} chip={chip} />)}
      </div>
    </header>
  );
}

function PrimaryCockpit() {
  const snapshot = useDashboardStore((s) => s.snapshot);
  const connected = useDashboardStore((s) => s.connected);
  const view = useMemo(() => buildOperatorView(snapshot, connected), [snapshot, connected]);

  if (!view || !snapshot) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-command-muted">
        Awaiting live runtime snapshot…
      </div>
    );
  }

  return (
    <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-12">
      {/* LEFT — narrative + D1 + regime */}
      <div className="flex min-h-0 flex-col gap-3 xl:col-span-3">
        <NarrativePanel narrative={view.narrative} />
        <D1DominancePanel mtf={view.mtf} />
        <section className="rounded border border-command-border bg-command-panel p-4">
          <div className="text-[10px] uppercase tracking-wider text-command-muted">Active Regime</div>
          <div className="mt-2 font-mono text-lg font-semibold text-slate-100">{view.narrative.regime.replace(/_/g, " ")}</div>
          <div className="mt-3 text-xs text-command-muted">
            Confidence {String(snapshot.regime?.regime_confidence ?? "—")}
          </div>
        </section>
      </div>

      {/* CENTER — ontology, auction, MTF */}
      <div className="flex min-h-0 flex-col gap-3 xl:col-span-5">
        <section className="rounded border border-command-border bg-command-panel p-4">
          <div className="text-[10px] uppercase tracking-wider text-command-muted">Current Auction State</div>
          <div className="mt-2 font-mono text-2xl font-semibold text-slate-100">
            {view.narrative.auctionState.replace(/_/g, " ")}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <StateBlock label="Transition" value={String(snapshot.state_transitions?.latest_transition?.transition_state ?? "STABLE")} />
            <StateBlock label="MTF Alignment" value={view.mtf.agreement} descriptor={view.mtf.alignmentStrength} />
          </div>
        </section>
        <CompactOntologyPanel events={snapshot.ontology?.ontology_event_feed ?? []} />
        <MtfHierarchyPanel mtf={view.mtf} />
      </div>

      {/* RIGHT — health, contradictions, alerts */}
      <div className="flex min-h-0 flex-col gap-3 xl:col-span-4">
        <section className="rounded border border-command-border bg-command-panel p-4">
          <div className="text-[10px] uppercase tracking-wider text-command-muted">Runtime Health</div>
          <div className="mt-2 font-mono text-xl font-semibold text-slate-100">{view.narrative.runtimeStability}</div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded border border-command-border px-2 py-1.5">
              <div className="text-command-muted">Cycle</div>
              <div className="font-mono">{snapshot.runtime_operations?.pipeline_cycle_counter ?? "—"}</div>
            </div>
            <div className="rounded border border-command-border px-2 py-1.5">
              <div className="text-command-muted">Latency</div>
              <div className="font-mono">{view.pipelineLatencySeconds?.toFixed(1) ?? "—"}s</div>
            </div>
          </div>
        </section>
        <section className="rounded border border-command-border bg-command-panel p-4">
          <div className="text-[10px] uppercase tracking-wider text-command-muted">Contradiction State</div>
          <div className="mt-2 font-mono text-xl font-semibold text-slate-100">{view.narrative.contradictions}</div>
          <div className="mt-2 text-xs text-command-muted">
            Reinforcement {view.narrative.reinforcement} · Cognition {view.narrative.cognitionStability}
          </div>
        </section>
        <AlertsPanel alerts={view.alerts} />
      </div>
    </div>
  );
}

function AdvancedDiagnostics() {
  const snapshot = useDashboardStore((s) => s.snapshot);
  const advancedOpen = useDashboardStore((s) => s.advancedOpen);
  const toggleAdvanced = useDashboardStore((s) => s.toggleAdvanced);

  return (
    <div className="mt-3 space-y-2 border-t border-command-border pt-3">
      <CollapsibleSection
        title="Advanced Diagnostics"
        subtitle="Probabilistic decomposition · entropy internals · engine telemetry"
        open={advancedOpen.diagnostics}
        onToggle={() => toggleAdvanced("diagnostics")}
      >
        <div className="grid gap-3 xl:grid-cols-2">
          <RuntimeOperationsPanel data={snapshot?.runtime_operations} />
          <CognitionPanelView data={snapshot?.probabilistic_cognition} />
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Forensic / Audit"
        subtitle="Replay exports · audit artifacts"
        open={advancedOpen.forensic}
        onToggle={() => toggleAdvanced("forensic")}
      >
        <ReplayPanelView data={snapshot?.replay_audit} />
      </CollapsibleSection>

      <CollapsibleSection
        title="Debug / Topology"
        subtitle="Pipeline graph · dependency propagation · topology internals"
        open={advancedOpen.debug}
        onToggle={() => toggleAdvanced("debug")}
      >
        <div className="grid gap-3 xl:grid-cols-2">
          <TopologyPanelView data={snapshot?.topology} />
          <HealthPanelView data={snapshot?.runtime_health} />
        </div>
      </CollapsibleSection>
    </div>
  );
}

export default function App() {
  const setSnapshot = useDashboardStore((s) => s.setSnapshot);
  const setConnected = useDashboardStore((s) => s.setConnected);

  useEffect(() => {
    fetchSnapshot().then(setSnapshot).catch(console.error);
    const socket = connectLive(setSnapshot, setConnected);
    return () => socket.close();
  }, [setSnapshot, setConnected]);

  return (
    <div className="flex min-h-screen flex-col bg-command-bg">
      <OperatorRibbon />
      <main className="panel-scroll flex min-h-0 flex-1 flex-col overflow-auto p-3">
        <PrimaryCockpit />
        <AdvancedDiagnostics />
      </main>
    </div>
  );
}
