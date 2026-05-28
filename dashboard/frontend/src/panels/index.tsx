import { HealthBadge, MetricCell, PanelShell, formatValue } from "../components/ui";
import type { LiveSnapshot } from "../types";

export function RuntimeOperationsPanel({ data }: { data?: LiveSnapshot["runtime_operations"] }) {
  if (!data) return <PanelShell title="Runtime Operations">Loading…</PanelShell>;

  return (
    <PanelShell title="Runtime Operations" subtitle="Pipeline supervision & orchestration integrity">
      <div className="mb-3 flex flex-wrap gap-2">
        <HealthBadge level={data.operational_health} label={`OPS ${data.operational_health}`} />
        <HealthBadge level={data.runtime_continuity.status} label="CONTINUITY" />
        {data.state_transition_waiting ? <HealthBadge level="YELLOW" label="ST TRANS WAIT" /> : null}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
        <MetricCell label="Cycle" value={data.pipeline_cycle_counter} />
        <MetricCell label="Synthesis rows" value={data.synthesis_row_count} />
        <MetricCell label="CPU %" value={data.system.cpu_percent} />
        <MetricCell label="Memory %" value={data.system.memory_percent} />
        <MetricCell label="Disk %" value={data.system.disk_percent} />
        <MetricCell label="Uptime s" value={data.system.uptime_seconds} />
      </div>

      <h3 className="mb-2 text-xs uppercase tracking-wide text-command-muted">Engine heartbeat map</h3>
      <div className="overflow-auto">
        <table className="w-full text-left text-xs font-mono">
          <thead className="text-command-muted">
            <tr>
              <th className="pb-2 pr-2">#</th>
              <th className="pb-2 pr-2">Engine</th>
              <th className="pb-2 pr-2">Status</th>
              <th className="pb-2 pr-2">Duration</th>
              <th className="pb-2">Mode</th>
            </tr>
          </thead>
          <tbody>
            {data.engine_execution_order.map((row, index) => (
              <tr key={row.engine} className="border-t border-command-border/60">
                <td className="py-1.5 pr-2 text-command-muted">{index + 1}</td>
                <td className="py-1.5 pr-2">{row.engine.replace("_engine_v1.py", "")}</td>
                <td className="py-1.5 pr-2">
                  <HealthBadge level={row.status === "SUCCESS" ? "GREEN" : row.status === "FAILED" ? "RED" : "YELLOW"} label={row.status} />
                </td>
                <td className="py-1.5 pr-2">{formatValue(row.duration_s)}</td>
                <td className="py-1.5">{row.mode}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mb-2 mt-4 text-xs uppercase tracking-wide text-command-muted">Last parquet writes</h3>
      <div className="grid gap-2 md:grid-cols-2">
        {data.last_parquet_writes.map((item) => (
          <div key={item.file} className="rounded border border-command-border p-2 text-xs font-mono">
            <div className="text-slate-200">{item.file}</div>
            <div className="text-command-muted">rows {item.row_count} · age {item.age_seconds}s</div>
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

export function OntologyPanelView({ data }: { data?: LiveSnapshot["ontology"] }) {
  if (!data) return <PanelShell title="Behavioral Ontology">Loading…</PanelShell>;

  return (
    <PanelShell title="Behavioral Ontology" subtitle="Live auction interpretation observability">
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        {Object.entries(data.ontology_density).map(([key, value]) => (
          <MetricCell key={key} label={key} value={value} />
        ))}
      </div>

      <h3 className="mb-2 text-xs uppercase text-command-muted">Event counts by timeframe</h3>
      <div className="grid gap-2 md:grid-cols-5">
        {Object.entries(data.event_counts_by_timeframe).map(([tf, counts]) => (
          <div key={tf} className="rounded border border-command-border p-2 text-xs">
            <div className="mb-1 font-semibold text-command-accent">{tf}</div>
            {Object.entries(counts).map(([event, count]) => (
              <div key={event} className="flex justify-between font-mono text-command-muted">
                <span>{event}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <h3 className="mb-2 mt-4 text-xs uppercase text-command-muted">M15 event feed</h3>
      <div className="space-y-1 text-xs font-mono">
        {data.ontology_event_feed.slice(-12).reverse().map((event, index) => (
          <div key={index} className="rounded border border-command-border/70 px-2 py-1">
            {String(event.timestamp ?? "—")} · {String(event.auction_event_type ?? event.cluster_behavior_resolution ?? "EVENT")}
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

export function CognitionPanelView({ data }: { data?: LiveSnapshot["probabilistic_cognition"] }) {
  if (!data) return <PanelShell title="Probabilistic Cognition">Loading…</PanelShell>;

  const metrics = [
    "raw_conviction",
    "disciplined_conviction",
    "calibrated_conviction",
    "saturation_score",
    "calibration_drift_score",
    "resilience_score",
    "calibration_stability_score",
    "semantic_fragility_score",
  ];

  return (
    <PanelShell title="Probabilistic Cognition" subtitle="Cognition evolution & conviction decomposition">
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        {metrics.map((key) => (
          <MetricCell key={key} label={key} value={data.latest[key]} />
        ))}
      </div>

      <h3 className="mb-2 text-xs uppercase text-command-muted">Conviction decomposition</h3>
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4">
        {Object.entries(data.decomposition).map(([key, value]) => (
          <MetricCell key={key} label={key} value={value} />
        ))}
      </div>

      <h3 className="mb-2 text-xs uppercase text-command-muted">Contradiction dynamics</h3>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {Object.entries(data.contradiction).map(([key, value]) => (
          <MetricCell key={key} label={key} value={value} />
        ))}
      </div>
    </PanelShell>
  );
}

export function StateTransitionsPanelView({ data }: { data?: LiveSnapshot["state_transitions"] }) {
  if (!data) return <PanelShell title="State Transitions">Loading…</PanelShell>;

  return (
    <PanelShell title="State Transitions" subtitle="Auction-state evolution & transition chronology">
      <div className="mb-3 flex flex-wrap gap-2">
        {data.waiting_for_second_state ? <HealthBadge level="YELLOW" label="WAITING SECOND STATE" /> : <HealthBadge level="GREEN" label="ACTIVE" />}
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3">
        <MetricCell label="Previous auction state" value={data.previous_auction_state} />
        <MetricCell label="Current auction state" value={data.current_auction_state} />
        <MetricCell label="Latest transition" value={data.latest_transition?.transition_state} />
      </div>
      <div className="space-y-1 text-xs font-mono">
        {data.chronology.slice(-15).reverse().map((row, index) => (
          <div key={index} className="rounded border border-command-border px-2 py-1">
            {String(row.timestamp)} · {String(row.previous_state)} → {String(row.current_state)} · {String(row.transition_state)}
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

export function MtfPanelView({ data }: { data?: LiveSnapshot["mtf_cognition"] }) {
  if (!data) return <PanelShell title="Multi-Timeframe Cognition">Loading…</PanelShell>;

  return (
    <PanelShell title="Multi-Timeframe Cognition" subtitle="M15 · M30 · H1 · H4 · D1 hierarchy">
      <div className="grid gap-2 md:grid-cols-5">
        {data.timeframe_states.map((tf) => (
          <div key={tf.timeframe} className="rounded border border-command-border p-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-command-accent">{tf.timeframe}</span>
              <HealthBadge level={tf.status === "LIVE" ? "GREEN" : "YELLOW"} label={tf.in_live_pipeline ? "PIPELINE" : "OBS"} />
            </div>
            <div className="mt-2 space-y-1 text-xs font-mono text-command-muted">
              <div>{tf.latest_event_type ?? "NORMAL"}</div>
              <div>{tf.auction_state ?? "—"}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <MetricCell label="Stage2 synthesis" value={data.stage2_synthesis?.synthesis_state} />
        <MetricCell label="Runtime cognition" value={data.runtime_cognition?.synthesis_state} />
        <MetricCell label="D1 macro anchor" value={data.d1_macro_anchor?.auction_state} />
        <MetricCell label="D1 event" value={data.d1_macro_anchor?.latest_event_type} />
      </div>
    </PanelShell>
  );
}

export function ReinforcementPanelView({ data }: { data?: LiveSnapshot["reinforcement"] }) {
  if (!data) return <PanelShell title="Reinforcement & Contradictions">Loading…</PanelShell>;

  return (
    <PanelShell title="Reinforcement & Contradictions" subtitle="Propagation, asymmetry, contradiction escalation">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MetricCell label="reinforcement_stability" value={data.reinforcement_stability_score} />
        <MetricCell label="contradiction_escalation" value={data.contradiction_escalation_score} />
        <MetricCell label="unresolved_contradiction" value={data.unresolved_contradiction_score} />
        <MetricCell label="belief_state" value={data.reinforcement_latest?.belief_state} />
      </div>
    </PanelShell>
  );
}

export function RegimePanelView({ data }: { data?: LiveSnapshot["regime"] }) {
  if (!data) return <PanelShell title="Regime Monitoring">Loading…</PanelShell>;

  return (
    <PanelShell title="Regime Monitoring" subtitle="Live regime probabilities & drift">
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <MetricCell label="auction_regime" value={data.current_regime} />
        <MetricCell label="regime_state" value={data.regime_state} />
        <MetricCell label="confidence" value={data.regime_confidence} />
        <MetricCell label="transition_p" value={data.regime_transition_probability} />
      </div>
      <div className="grid gap-1 text-xs font-mono md:grid-cols-2">
        {Object.entries(data.regime_probabilities).map(([regime, prob]) => (
          <div key={regime} className="flex items-center gap-2 rounded border border-command-border px-2 py-1">
            <span className="w-40 truncate text-command-muted">{regime}</span>
            <div className="h-2 flex-1 rounded bg-command-bg">
              <div className="h-2 rounded bg-command-accent/70" style={{ width: `${Math.min(100, prob * 100)}%` }} />
            </div>
            <span>{prob.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

export function HealthPanelView({ data }: { data?: LiveSnapshot["runtime_health"] }) {
  if (!data) return <PanelShell title="Runtime Health">Loading…</PanelShell>;

  return (
    <PanelShell title="Runtime Health" subtitle="Parquet integrity, stale detection, alerts">
      <div className="mb-3">
        <HealthBadge level={data.operational_health} label={`HEALTH ${data.operational_health}`} />
      </div>
      <h3 className="mb-2 text-xs uppercase text-command-muted">Alerts</h3>
      <div className="mb-4 space-y-1 text-xs font-mono">
        {data.alerts.length === 0 ? <div className="text-command-muted">No active alerts</div> : null}
        {data.alerts.slice(0, 20).map((alert, index) => (
          <div key={index} className="rounded border border-command-border px-2 py-1">
            [{alert.severity}] {alert.type} {alert.file ?? ""}
          </div>
        ))}
      </div>
      <h3 className="mb-2 text-xs uppercase text-command-muted">Stale parquet ({data.stale_parquet.length})</h3>
      <div className="space-y-1 text-xs font-mono">
        {data.stale_parquet.slice(0, 12).map((item) => (
          <div key={item.file}>{item.file} · age {item.age_seconds}s</div>
        ))}
      </div>
    </PanelShell>
  );
}

export function ReplayPanelView({ data }: { data?: LiveSnapshot["replay_audit"] }) {
  if (!data) return <PanelShell title="Replay & Audit">Loading…</PanelShell>;

  return (
    <PanelShell title="Replay & Audit" subtitle="Forensic exports & replay controls">
      <h3 className="mb-2 text-xs uppercase text-command-muted">Replay controls</h3>
      <div className="mb-4 space-y-1 text-xs font-mono">
        {Object.entries(data.replay_controls).map(([key, value]) => (
          <div key={key} className="rounded border border-command-border px-2 py-1">
            {key}: {value}
          </div>
        ))}
      </div>
      <h3 className="mb-2 text-xs uppercase text-command-muted">Exports</h3>
      <div className="space-y-1 text-xs font-mono">
        {data.replay_exports.map((item) => (
          <div key={item.path} className="rounded border border-command-border px-2 py-1">
            {item.name} · {item.mtime}
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

export function TopologyPanelView({ data }: { data?: LiveSnapshot["topology"] }) {
  if (!data) return <PanelShell title="System Topology">Loading…</PanelShell>;

  return (
    <PanelShell title="System Topology" subtitle="Pipeline graph & dependency integrity">
      <div className="mb-3">
        <HealthBadge level={data.orchestration_integrity} label={`TOPOLOGY ${data.orchestration_integrity}`} />
        {data.dead_nodes.length ? <span className="ml-2 text-xs text-command-red">dead: {data.dead_nodes.join(", ")}</span> : null}
      </div>
      <div className="space-y-1 text-xs font-mono">
        {data.pipeline_nodes.map((node) => (
          <div key={node.id} className="flex items-center gap-2 rounded border border-command-border px-2 py-1">
            <span className="w-6 text-command-muted">{node.order}</span>
            <HealthBadge level={node.status === "SUCCESS" ? "GREEN" : node.status === "FAILED" ? "RED" : "YELLOW"} label={node.status} />
            <span className="truncate">{node.id}</span>
          </div>
        ))}
      </div>
    </PanelShell>
  );
}
