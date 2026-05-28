import { useState } from "react";
import type {
  AlertGroups,
  CollectorRow,
  CollectorSummary,
  ComponentClass,
  EngineRow,
  EngineStatus,
  FeedConfidence,
  HealthSummary,
  OpsAlert,
  OpsLevel,
  ParquetRow,
  ParquetSummary,
  PipelineSummary,
  StabilitySummary,
} from "../../types/ops";

const DOT: Record<string, string> = {
  GREEN: "🟢",
  YELLOW: "🟡",
  RED: "🔴",
  GREY: "⚪",
  HEALTHY: "🟢",
  DEFERRED: "🟡",
  FAILED: "🔴",
  TIMEOUT: "🔴",
  STALLED: "🔴",
};

const CLASS_BADGE: Record<ComponentClass, string> = {
  REQUIRED: "border-emerald-800/60 bg-emerald-950/40 text-emerald-400",
  OPTIONAL: "border-slate-700 bg-slate-900/60 text-slate-400",
  LEGACY: "border-slate-800 bg-slate-950/80 text-slate-600",
  RESEARCH: "border-violet-900/40 bg-violet-950/30 text-violet-400/80",
  DORMANT: "border-slate-800 bg-slate-950/80 text-slate-600",
};

export function dot(level: OpsLevel | EngineStatus | string): string {
  return DOT[level] ?? "⚪";
}

export function engineStatusClass(row: EngineRow): string {
  if (row.ignored_by_health) return "text-slate-500";
  return levelClass(row.status);
}

export function levelClass(level: OpsLevel | string): string {
  if (level === "GREEN" || level === "HEALTHY") return "text-emerald-400";
  if (level === "YELLOW" || level === "DEFERRED" || level === "DEGRADED") return "text-amber-400";
  if (level === "GREY") return "text-slate-500";
  return "text-red-400";
}

export function ClassBadge({ classification }: { classification?: ComponentClass }) {
  if (!classification) return null;
  return (
    <span className={`ml-2 rounded border px-1.5 py-0.5 text-[9px] font-semibold tracking-wide ${CLASS_BADGE[classification]}`}>
      {classification}
    </span>
  );
}

export function IgnoredHint({ ignored }: { ignored?: boolean }) {
  if (!ignored) return null;
  return <span className="ml-2 text-[9px] text-slate-600">ignored by health</span>;
}

export function OpsRibbon({ items }: { items: { key: string; label: string; level: OpsLevel; value?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-2 border-b border-slate-800 bg-[#060a10] px-4 py-3">
      {items.map((item) => (
        <div key={item.key} className="flex items-center gap-1.5 rounded border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs font-mono">
          <span>{dot(item.level)}</span>
          <span className="text-slate-400">{item.label}</span>
          {item.value ? <span className="text-slate-200">{item.value}</span> : null}
        </div>
      ))}
    </div>
  );
}

export function EngineTable({ engines }: { engines: EngineRow[] }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">Engine Status</header>
      <div className="overflow-auto">
        <table className="w-full text-left text-xs font-mono">
          <thead className="text-slate-500">
            <tr>
              <th className="px-3 py-2">Engine</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last Run</th>
              <th className="px-3 py-2">Duration</th>
              <th className="px-3 py-2">Mode</th>
            </tr>
          </thead>
          <tbody>
            {engines.map((row) => (
              <tr key={row.engine} className={`border-t border-slate-900 ${row.ignored_by_health ? "opacity-70" : ""}`}>
                <td className="px-3 py-2 text-slate-300">
                  {row.short_name}
                  <ClassBadge classification={row.classification} />
                </td>
                <td className={`px-3 py-2 ${engineStatusClass(row)}`}>
                  {dot(row.status)} {row.status}
                  {row.note ? <div className="text-[10px] text-slate-500">{row.note}</div> : null}
                  <IgnoredHint ignored={row.ignored_by_health} />
                </td>
                <td className="px-3 py-2 text-slate-400">{row.last_run_ago ?? "—"}</td>
                <td className="px-3 py-2 text-slate-400">{row.duration_s != null ? `${row.duration_s}s` : "—"}</td>
                <td className="px-3 py-2 text-slate-500">{row.mode}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ParquetRowItem({ row }: { row: ParquetRow }) {
  const muted = row.ignored_by_health;
  return (
    <div className={`rounded border px-2 py-1 ${muted ? "border-slate-900/80 text-slate-600" : "border-slate-900 text-slate-400"}`}>
      <div className="flex flex-wrap items-center gap-1">
        <span>{row.file}</span>
        <ClassBadge classification={row.classification} />
        <IgnoredHint ignored={row.ignored_by_health} />
      </div>
      <div className="text-[10px]">
        {row.freshness} · {row.age_seconds != null ? `${Math.round(row.age_seconds)}s` : "—"}
      </div>
    </div>
  );
}

export function ParquetPanel({
  parquet,
  expanded,
  onToggle,
}: {
  parquet: ParquetSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [showOptional, setShowOptional] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const optional = parquet.optional ?? parquet.all.filter((p) => p.classification === "OPTIONAL");
  const archived = parquet.archived ?? parquet.all.filter((p) => p.ignored_by_health && p.classification !== "OPTIONAL");

  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2">
        <div className="flex items-center justify-between text-sm font-semibold text-slate-200">
          <span>
            Required Parquet {dot(parquet.summary_level)}
            <ClassBadge classification="REQUIRED" />
          </span>
          <span className="text-xs font-normal text-slate-500">
            {parquet.live_count} live · {parquet.stale_count} stale · {parquet.missing_count} missing
          </span>
        </div>
      </header>
      <div className="space-y-2 p-3 text-xs font-mono">
        {parquet.stale_count > 0 ? (
          <button type="button" onClick={onToggle} className="w-full rounded border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-left text-amber-300">
            REQUIRED STALE ({parquet.stale_count}) {expanded ? "▲" : "▼"}
          </button>
        ) : (
          <div className="text-emerald-400">All required parquets live</div>
        )}
        {expanded && parquet.stale_files.map((p) => <ParquetRowItem key={p.file} row={p} />)}
        {parquet.missing_count > 0 ? (
          <div className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-red-300">
            REQUIRED MISSING ({parquet.missing_count})
          </div>
        ) : null}

        {optional.length > 0 ? (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowOptional(!showOptional)}
              className="w-full rounded border border-slate-800 px-3 py-2 text-left text-slate-500"
            >
              Optional parquets ({optional.length}) {showOptional ? "▲" : "▼"}
            </button>
            {showOptional ? (
              <div className="mt-2 space-y-1">
                {optional.map((p) => (
                  <ParquetRowItem key={p.file} row={p} />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {archived.length > 0 ? (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowArchived(!showArchived)}
              className="w-full rounded border border-slate-900 px-3 py-2 text-left text-slate-600"
            >
              Legacy / research / dormant ({archived.length}) — ignored by health {showArchived ? "▲" : "▼"}
            </button>
            {showArchived ? (
              <div className="mt-2 space-y-1 opacity-60">
                {archived.map((p) => (
                  <ParquetRowItem key={p.file} row={p} />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function CollectorRowItem({ row }: { row: CollectorRow }) {
  const muted = row.ignored_by_health;
  return (
    <div className={`flex items-center justify-between px-4 py-2 text-xs font-mono ${muted ? "opacity-60" : ""}`}>
      <span className="text-slate-300">
        {row.name}
        <ClassBadge classification={row.classification} />
      </span>
      <span className={levelClass(row.level)}>
        {dot(row.level)} {row.status}
        {row.latency_note ? ` · ${row.latency_note}` : ""}
        <IgnoredHint ignored={row.ignored_by_health} />
      </span>
    </div>
  );
}

export function CollectorsPanel({ collectors }: { collectors: CollectorSummary }) {
  const [showOptional, setShowOptional] = useState(false);
  const required = collectors.required ?? collectors.collectors.filter((c) => c.classification === "REQUIRED");
  const optional = collectors.optional ?? collectors.collectors.filter((c) => c.classification === "OPTIONAL");
  const legacy = collectors.legacy ?? collectors.collectors.filter((c) => c.classification === "LEGACY");

  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">
        Collectors {dot(collectors.level)}
        <ClassBadge classification="REQUIRED" />
      </header>
      <div className="divide-y divide-slate-900">
        {required.map((c) => (
          <CollectorRowItem key={c.name} row={c} />
        ))}
      </div>

      {optional.length > 0 ? (
        <div className="border-t border-slate-900">
          <button
            type="button"
            onClick={() => setShowOptional(!showOptional)}
            className="w-full px-4 py-2 text-left text-xs text-slate-500"
          >
            Optional collectors ({optional.length}) {showOptional ? "▲" : "▼"}
          </button>
          {showOptional ? (
            <div className="divide-y divide-slate-900 opacity-80">
              {optional.map((c) => (
                <CollectorRowItem key={c.name} row={c} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {legacy.length > 0 ? (
        <div className="border-t border-slate-900 opacity-50">
          {legacy.map((c) => (
            <CollectorRowItem key={c.name} row={c} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function PipelinePanel({ pipeline }: { pipeline: PipelineSummary }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">
        Pipeline Status {dot(pipeline.heartbeat_level)}
      </header>
      <div className="grid grid-cols-2 gap-2 p-3 text-xs font-mono md:grid-cols-3">
        <Metric label="Cycle" value={String(pipeline.current_cycle)} />
        <Metric label="Avg duration" value={pipeline.average_cycle_duration_s != null ? `${pipeline.average_cycle_duration_s}s` : "—"} />
        <Metric label="State" value={pipeline.active_state} />
        <Metric label="Failed" value={String(pipeline.failed_engine_count)} />
        <Metric label="Timeouts" value={String(pipeline.timeout_count)} />
        <Metric label="Stalled" value={String(pipeline.stalled_engine_count)} />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-900 px-2 py-1.5">
      <div className="text-slate-500">{label}</div>
      <div className="text-slate-200">{value}</div>
    </div>
  );
}

export function FeedConfidencePanel({ feed }: { feed: FeedConfidence }) {
  const signals = [feed.ws, feed.write, feed.consume];
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">
        Feed Confidence {dot(feed.overall)}
      </header>
      <div className="space-y-2 p-3 text-xs font-mono">
        {signals.map((signal) => (
          <div key={signal.label} className="rounded border border-slate-900 px-3 py-2">
            <div className={`${levelClass(signal.level)}`}>
              {signal.label} {dot(signal.level)}
            </div>
            <div className="mt-1 text-slate-500">{signal.reason}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function StabilityPanel({ stability }: { stability: StabilitySummary }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">Stability History</header>
      <div className="grid grid-cols-2 gap-2 p-3 text-xs font-mono">
        <Metric label="Runtime uptime" value={formatUptime(stability.runtime_uptime_s)} />
        <Metric label="Collector uptime" value={formatUptime(stability.collector_uptime_s)} />
        <Metric label="WS uptime" value={formatUptime(stability.websocket_uptime_s)} />
        <Metric label="Restarts" value={String(stability.restart_count)} />
        <Metric label="Last disconnect" value={stability.last_disconnect ? new Date(stability.last_disconnect).toLocaleString() : "—"} />
        <Metric label="Last timeout" value={stability.last_timeout ? new Date(stability.last_timeout).toLocaleString() : "—"} />
      </div>
    </section>
  );
}

export function HealthPanel({ health }: { health: HealthSummary }) {
  const level = health.level === "HEALTHY" ? "GREEN" : health.level === "DEGRADED" ? "YELLOW" : "RED";
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2">
        <div className={`text-lg font-semibold ${levelClass(level)}`}>
          RUNTIME HEALTH: {health.level} {dot(level)}
        </div>
        <div className="mt-1 text-sm text-slate-300">{health.primary_reason}</div>
        <div className="text-[10px] text-slate-600">Manifest-scored · REQUIRED components only</div>
      </header>
      <div className="space-y-2 p-4 text-sm">
        <div className="text-slate-400">Reason:</div>
        <ul className="list-inside list-disc space-y-1 text-slate-300">
          {health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono text-slate-500">
          <span>CPU {health.cpu_percent.toFixed(0)}%</span>
          <span>MEM {health.memory_percent.toFixed(0)}%</span>
          <span>DISK {health.disk_percent.toFixed(0)}%</span>
          {health.deferred_engine_count != null ? <span>Deferred {health.deferred_engine_count}</span> : null}
          {health.optional_offline_count != null ? <span>Optional offline {health.optional_offline_count}</span> : null}
        </div>
      </div>
    </section>
  );
}

export function AlertsPanel({
  alerts,
  alertGroups,
  acknowledged,
  onAck,
}: {
  alerts: OpsAlert[];
  alertGroups?: AlertGroups;
  acknowledged: Set<string>;
  onAck: (id: string) => void;
}) {
  const actionable = (alertGroups?.actionable ?? alerts.filter((a) => a.actionable !== false && !a.ignored_by_health)).filter(
    (a) => !acknowledged.has(a.id),
  );
  const informational = (alertGroups?.informational ?? alerts.filter((a) => a.ignored_by_health || a.actionable === false)).filter(
    (a) => !acknowledged.has(a.id),
  );
  const [showInfo, setShowInfo] = useState(false);

  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-slate-200">
        Actionable Alerts ({actionable.length})
      </header>
      <div className="max-h-72 space-y-2 overflow-auto p-3">
        {actionable.length === 0 ? (
          <div className="text-xs text-emerald-400">No actionable alerts</div>
        ) : (
          actionable.map((alert) => (
            <div key={alert.id} className="rounded border border-slate-900 px-3 py-2 text-xs">
              <div className="flex items-center justify-between">
                <span className={alert.severity === "CRITICAL" ? "text-red-400" : "text-amber-400"}>{alert.severity}</span>
                <button type="button" onClick={() => onAck(alert.id)} className="text-slate-500 hover:text-slate-300">
                  ack
                </button>
              </div>
              <div className="mt-1 text-slate-300">{alert.message}</div>
            </div>
          ))
        )}
        {informational.length > 0 ? (
          <div className="pt-2">
            <button type="button" onClick={() => setShowInfo(!showInfo)} className="w-full text-left text-[10px] text-slate-600">
              Informational ({informational.length}) {showInfo ? "▲" : "▼"}
            </button>
            {showInfo
              ? informational.map((alert) => (
                  <div key={alert.id} className="mt-1 rounded border border-slate-900/60 px-2 py-1 text-[10px] text-slate-600">
                    {alert.message}
                  </div>
                ))
              : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
