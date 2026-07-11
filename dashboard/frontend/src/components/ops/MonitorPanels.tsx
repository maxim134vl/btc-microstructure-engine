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
  REQUIRED: "border-emerald-800/60 bg-emerald-950/40 text-ds-status-healthy",
  OPTIONAL: "border-slate-700 bg-slate-900/60 text-ds-text-secondary",
  LEGACY: "border-slate-800 bg-slate-950/80 text-ds-text-tertiary",
  RESEARCH: "border-violet-900/40 bg-violet-950/30 text-ds-text-secondary/80",
  DORMANT: "border-slate-800 bg-slate-950/80 text-ds-text-tertiary",
};

export function dot(level: OpsLevel | EngineStatus | string): string {
  return DOT[level] ?? "⚪";
}

export function engineStatusClass(row: EngineRow): string {
  if (row.ignored_by_health) return "text-ds-text-tertiary";
  return levelClass(row.status);
}

export function levelClass(level: OpsLevel | string): string {
  if (level === "GREEN" || level === "HEALTHY") return "text-ds-status-healthy";
  if (level === "YELLOW" || level === "DEFERRED" || level === "DEGRADED") return "text-ds-status-warning";
  if (level === "GREY") return "text-ds-text-tertiary";
  return "text-ds-status-error";
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
  return <span className="ml-2 text-[9px] text-ds-text-tertiary">ignored by health</span>;
}

export function OpsRibbon({ items }: { items: { key: string; label: string; level: OpsLevel; value?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-2 border-b border-slate-800 bg-[#060a10] px-4 py-3">
      {items.map((item) => (
        <div key={item.key} className="flex items-center gap-1.5 rounded border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs font-mono">
          <span>{dot(item.level)}</span>
          <span className="text-ds-text-secondary">{item.label}</span>
          {item.value ? <span className="text-ds-text-primary">{item.value}</span> : null}
        </div>
      ))}
    </div>
  );
}

export function EngineTable({ engines }: { engines: EngineRow[] }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">Engine Status</header>
      <div className="overflow-auto">
        <table className="w-full text-left text-xs font-mono">
          <thead className="text-ds-text-tertiary">
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
                <td className="px-3 py-2 text-ds-text-primary">
                  {row.short_name}
                  <ClassBadge classification={row.classification} />
                </td>
                <td className={`px-3 py-2 ${engineStatusClass(row)}`}>
                  {dot(row.status)} {row.status}
                  {row.note ? <div className="text-[10px] text-ds-text-tertiary">{row.note}</div> : null}
                  <IgnoredHint ignored={row.ignored_by_health} />
                </td>
                <td className="px-3 py-2 text-ds-text-secondary">
                  {row.last_run_ago && /^-/.test(row.last_run_ago.trim()) ? "just now" : row.last_run_ago ?? "—"}
                </td>
                <td className="px-3 py-2 text-ds-text-secondary">{row.duration_s != null ? `${row.duration_s}s` : "—"}</td>
                <td className="px-3 py-2 text-ds-text-tertiary">{row.mode}</td>
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
    <div className={`rounded border px-2 py-1 ${muted ? "border-slate-900/80 text-ds-text-tertiary" : "border-slate-900 text-ds-text-secondary"}`}>
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
        <div className="flex items-center justify-between text-sm font-semibold text-ds-text-primary">
          <span>
            Required Parquet {dot(parquet.summary_level)}
            <ClassBadge classification="REQUIRED" />
          </span>
          <span className="text-xs font-normal text-ds-text-tertiary">
            {parquet.live_count} live · {parquet.stale_count} stale · {parquet.missing_count} missing
          </span>
        </div>
      </header>
      <div className="space-y-2 p-3 text-xs font-mono">
        {parquet.stale_count > 0 ? (
          <button type="button" onClick={onToggle} className="w-full rounded border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-left text-ds-status-warning">
            REQUIRED STALE ({parquet.stale_count}) {expanded ? "▲" : "▼"}
          </button>
        ) : (
          <div className="text-ds-status-healthy">All required parquets live</div>
        )}
        {expanded && parquet.stale_files.map((p) => <ParquetRowItem key={p.file} row={p} />)}
        {parquet.missing_count > 0 ? (
          <div className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-ds-status-error">
            REQUIRED MISSING ({parquet.missing_count})
          </div>
        ) : null}

        {optional.length > 0 ? (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowOptional(!showOptional)}
              className="w-full rounded border border-slate-800 px-3 py-2 text-left text-ds-text-tertiary"
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
              className="w-full rounded border border-slate-900 px-3 py-2 text-left text-ds-text-tertiary"
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
      <span className="text-ds-text-primary">
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
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">
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
            className="w-full px-4 py-2 text-left text-xs text-ds-text-tertiary"
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
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">
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
      <div className="text-ds-text-tertiary">{label}</div>
      <div className="text-ds-text-primary">{value}</div>
    </div>
  );
}

export function FeedConfidencePanel({ feed }: { feed: FeedConfidence }) {
  const signals = [feed.ws, feed.write, feed.consume];
  return (
    <section className="rounded border border-slate-800 bg-slate-950">
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">
        Feed Confidence {dot(feed.overall)}
      </header>
      <div className="space-y-2 p-3 text-xs font-mono">
        {signals.map((signal) => (
          <div key={signal.label} className="rounded border border-slate-900 px-3 py-2">
            <div className={`${levelClass(signal.level)}`}>
              {signal.label} {dot(signal.level)}
            </div>
            <div className="mt-1 text-ds-text-tertiary">{signal.reason}</div>
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
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">Stability History</header>
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
        <div className="mt-1 text-sm text-ds-text-primary">{health.primary_reason}</div>
        <div className="text-[10px] text-ds-text-tertiary">Manifest-scored · REQUIRED components only</div>
      </header>
      <div className="space-y-2 p-4 text-sm">
        <div className="text-ds-text-secondary">Reason:</div>
        <ul className="list-inside list-disc space-y-1 text-ds-text-primary">
          {health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono text-ds-text-tertiary">
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
      <header className="border-b border-slate-800 px-4 py-2 text-sm font-semibold text-ds-text-primary">
        Actionable Alerts ({actionable.length})
      </header>
      <div className="max-h-72 space-y-2 overflow-auto p-3">
        {actionable.length === 0 ? (
          <div className="text-xs text-ds-status-healthy">No actionable alerts</div>
        ) : (
          actionable.map((alert) => (
            <div key={alert.id} className="rounded border border-slate-900 px-3 py-2 text-xs">
              <div className="flex items-center justify-between">
                <span className={alert.severity === "CRITICAL" ? "text-ds-status-error" : "text-ds-status-warning"}>{alert.severity}</span>
                <button type="button" onClick={() => onAck(alert.id)} className="text-ds-text-tertiary hover:text-ds-text-primary">
                  ack
                </button>
              </div>
              <div className="mt-1 text-ds-text-primary">{alert.message}</div>
            </div>
          ))
        )}
        {informational.length > 0 ? (
          <div className="pt-2">
            <button type="button" onClick={() => setShowInfo(!showInfo)} className="w-full text-left text-[10px] text-ds-text-tertiary">
              Informational ({informational.length}) {showInfo ? "▲" : "▼"}
            </button>
            {showInfo
              ? informational.map((alert) => (
                  <div key={alert.id} className="mt-1 rounded border border-slate-900/60 px-2 py-1 text-[10px] text-ds-text-tertiary">
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
