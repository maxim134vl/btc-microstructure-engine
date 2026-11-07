import { useReleaseManifest } from "../../releaseVersion";
import type { OpsSnapshot } from "../../types/ops";
const text = (v: unknown) => v === null || v === undefined || v === "" ? "UNKNOWN" : String(v);
const seconds = (v: number | null | undefined) => v == null ? "UNKNOWN" : `${v.toFixed(1)} s`;
export function OwnerSource({snapshot, section}: {snapshot: OpsSnapshot; section: string}) {
  const runtime = snapshot.runtime_observation;
  const map: Record<string,string[]> = {"Live Operations Summary":["runtime_observation"],"Runtime Processes":["runtime_observation"],"Trading Operations":["trading.execution","trading.financial","trading.manager","trading.risk"],"Market Context":["context_chain","multi_timeframe"],"Pipeline Detail":["runtime_observation"],"Research / Validation":["research_pipeline.pipeline"],"Financial Performance":["trading.financial"],"Timeframe Traders":["trading.manager"],"Collectors":["operations.ingress_control"]};
  const keys = map[section] || [section.toLowerCase().replaceAll(" ","_")];
  return <p className="text-[11px] text-ds-text-tertiary">{keys.map(k => {
    if(k === "runtime_observation") return `Docker/native owner status · ${runtime?.observed_at || "DATA UNAVAILABLE"}`;
    const m=snapshot.transport?.sections[k];
    return `${m?.owner || k} · ${m?.status || "DATA UNAVAILABLE"} · ${m?.published_at || "timestamp unavailable"}`;
  }).join(" | ")}</p>;
}
export function ProcessTimingMonitor({snapshot}: {snapshot: OpsSnapshot}) {
 const r=snapshot.runtime_observation;const release=useReleaseManifest();
 return <section className="space-y-3" data-section="process-timing-monitor">
  <h2 className="text-[12px] font-semibold uppercase tracking-wide text-ds-text-tertiary">Process Timing Monitor</h2>
  <div className="overflow-x-auto rounded-xl border border-ds-border bg-ds-surface p-4">
   <table className="w-full text-left text-[11px] tabular-nums"><thead><tr><th>Process / schedule</th><th>Configured period</th><th>Last cycle</th><th>Current cycle</th><th>Overrun</th><th>Last success / market tip UTC</th><th>Status</th></tr></thead>
    <tbody>{r?.timing.map(t=><tr key={t.service} className="border-t border-ds-border"><td className="py-2">{t.label}<div className="text-ds-text-tertiary">{t.schedule_kind}</div></td><td>{seconds(t.configured_period_s)}</td><td>{seconds(t.last_cycle_duration_s)}</td><td>{seconds(t.current_duration_s)}</td><td>{seconds(t.overrun_s)}</td><td>{text(t.last_success_at)}<br/>{text(t.last_market_tip)}</td><td title={t.reason}>{t.status}</td></tr>)}</tbody>
   </table>
   {!r && <p>DATA UNAVAILABLE: runtime observer has not published a sample.</p>}
   <p className="mt-3 text-[11px] text-ds-text-tertiary">Source: {r?.source || "unavailable"} · {r?.observed_at || "timestamp unavailable"}. Canonical and Timeframe use post-cycle delays; those delays are not full-cycle deadlines. Missing cycle durations remain UNKNOWN.</p>
  </div>
  <div className="rounded-xl border border-ds-border bg-ds-surface p-4"><h3 className="text-sm font-semibold">Collector owner heartbeats</h3><p className="text-[11px] text-ds-text-tertiary">Literal owner status at its timestamp; ALIVE is not a substitute for a verified WebSocket healthcheck.</p>{r?.collector_heartbeats?.map(h=><p key={h.collector} className="mt-2 text-[11px]">{h.collector} · {h.status || "UNKNOWN"} · {h.timestamp || "timestamp unavailable"} · {h.event} · messages {h.message_count ?? "UNKNOWN"}{h.last_error ? ` · ${h.last_error}` : ""}<span className="block text-ds-text-tertiary">{h.source}</span></p>)}{!r?.collector_heartbeats?.length && <p className="text-xs">DATA UNAVAILABLE: owner heartbeats were not found.</p>}</div>
  <details className="rounded-xl border border-ds-border bg-ds-surface p-4"><summary className="cursor-pointer text-sm">System / About · Release {release?.version || "DATA UNAVAILABLE"}</summary><p className="mt-2 text-xs">{release?.app} · {release?.channel} · REAL {release?.real_execution || "UNKNOWN"}</p><a className="text-xs underline" href="/release.json" target="_blank" rel="noreferrer">Authoritative release manifest</a><p className="mt-2 text-[11px] text-ds-text-tertiary">{r?.resources.disks.map(d=>`${d.label}: ${d.free_bytes == null ? "UNKNOWN" : (d.free_bytes/1073741824).toFixed(2)+" GiB free"}`).join(" · ")}</p><p className="mt-2 text-[11px] text-ds-text-tertiary">Resources are Docker runtime observations, separate from trading model health. {r?.resources.scope}</p></details>
 </section>;
}
