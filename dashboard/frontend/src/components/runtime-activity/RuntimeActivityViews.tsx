import type { ActivityEvent, ActivityKpis } from "../../types/runtimeActivity";
import { formatDuration, formatEventTime, formatRelativeTime, outcomeTone } from "./parseActivity";
import { StatusDot } from "../status";

function KpiCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <article className="ops-card min-w-0 flex-1 p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-ds-text-tertiary">{label}</p>
      <p className="mt-1 font-ds-display text-[28px] font-semibold tabular-nums tracking-tight text-ds-text-primary">
        {value}
      </p>
      {hint ? <p className="mt-1 text-[11px] text-ds-text-secondary">{hint}</p> : null}
    </article>
  );
}

export function ActivityKpiRow({ kpis }: { kpis: ActivityKpis }) {
  const successLabel = kpis.successRate != null ? `${kpis.successRate}%` : "—";
  const avgLabel = formatDuration(kpis.avgDurationMs);
  const lastLabel = kpis.lastEventAt ? formatRelativeTime(kpis.lastEventAt) : "No events";
  const lastHint = kpis.lastEventAt ? formatEventTime(kpis.lastEventAt) : undefined;

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard label="Activity events" value={String(kpis.totalEvents)} hint={`Cycle ${kpis.currentCycle}`} />
      <KpiCard
        label="Success rate"
        value={successLabel}
        hint={`${kpis.successCount} ok · ${kpis.failedCount} failed · ${kpis.warningCount} attention`}
      />
      <KpiCard label="Avg duration" value={avgLabel} hint="Engine runs with timing" />
      <KpiCard label="Last activity" value={lastLabel} hint={lastHint} />
    </div>
  );
}

export function ActivityTimeline({
  events,
  selectedId,
  onSelect,
}: {
  events: ActivityEvent[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (events.length === 0) {
    return (
      <div className="flex h-full min-h-[200px] items-center justify-center text-[13px] text-ds-text-secondary">
        No activity events in the current telemetry snapshot.
      </div>
    );
  }

  return (
    <ul className="panel-scroll space-y-1 overflow-y-auto pr-1">
      {events.map((event) => {
        const active = event.id === selectedId;
        const tone = outcomeTone(event.outcome);
        return (
          <li key={event.id}>
            <button
              type="button"
              onClick={() => onSelect(event.id)}
              className={`flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors duration-ds ${
                active ? "bg-ds-surface-secondary shadow-ds-sm" : "hover:bg-ds-surface-secondary/60"
              }`}
            >
              <span className="mt-1.5 w-[52px] shrink-0 text-[10px] tabular-nums text-ds-text-tertiary">
                {event.timestamp ? formatEventTime(event.timestamp).split(", ").pop() : "—"}
              </span>
              <StatusDot tone={tone} className="mt-1.5 h-2 w-2 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-ds-text-primary">{event.title}</span>
                <span className="mt-0.5 block truncate text-[11px] text-ds-text-secondary">{event.subtitle}</span>
              </span>
              {event.durationMs != null ? (
                <span className="shrink-0 rounded-ds-pill bg-ds-surface-secondary px-2 py-0.5 text-[10px] tabular-nums text-ds-text-tertiary">
                  {formatDuration(event.durationMs)}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function EventDetailPanel({ event }: { event: ActivityEvent | null }) {
  if (!event) {
    return (
      <div className="flex h-full min-h-[200px] items-center justify-center px-4 text-center text-[13px] text-ds-text-secondary">
        Select an event to inspect what happened, when, and whether it succeeded.
      </div>
    );
  }

  const tone = outcomeTone(event.outcome);
  const outcomeLabel =
    event.outcome === "success"
      ? "Succeeded"
      : event.outcome === "failed"
        ? "Failed"
        : event.outcome === "warning"
          ? "Attention"
          : "Informational";

  const detailRows: Array<{ label: string; value: string }> = [
    { label: "When", value: formatEventTime(event.timestamp) },
    { label: "Duration", value: formatDuration(event.durationMs) },
    { label: "Category", value: event.category },
    { label: "Source", value: event.source },
    { label: "Outcome", value: outcomeLabel },
  ];

  const extraKeys = Object.keys(event.raw).filter(
    (k) => !["timestamp", "engine", "status", "duration", "duration_s"].includes(k),
  );

  return (
    <div className="panel-scroll flex h-full flex-col overflow-y-auto p-4">
      <div className="flex items-start gap-2">
        <StatusDot tone={tone} className="mt-1 h-2.5 w-2.5 shrink-0" />
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-ds-text-primary">{event.title}</h3>
          <p className="mt-0.5 text-[12px] text-ds-text-secondary">{event.subtitle}</p>
        </div>
      </div>

      <dl className="mt-4 space-y-2.5">
        {detailRows.map((row) => (
          <div key={row.label} className="grid grid-cols-[88px_1fr] gap-2 text-[12px]">
            <dt className="text-ds-text-tertiary">{row.label}</dt>
            <dd className="font-medium text-ds-text-primary">{row.value}</dd>
          </div>
        ))}
      </dl>

      {extraKeys.length > 0 ? (
        <div className="mt-5 border-t border-ds-border pt-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-ds-text-tertiary">
            Event fields
          </p>
          <dl className="space-y-2">
            {extraKeys.slice(0, 12).map((key) => (
              <div key={key} className="grid grid-cols-[88px_1fr] gap-2 text-[11px]">
                <dt className="truncate text-ds-text-tertiary">{key}</dt>
                <dd className="break-all font-ds-mono text-ds-text-secondary">
                  {formatRawValue(event.raw[key])}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </div>
  );
}

function formatRawValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function RawTelemetryInspector({ raw, expanded, onToggle }: { raw: unknown; expanded: boolean; onToggle: () => void }) {
  const text = JSON.stringify(raw, null, 2);

  return (
    <section className="ops-card overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-ds-surface-secondary/40"
      >
        <div>
          <h3 className="text-[13px] font-semibold text-ds-text-primary">Raw telemetry inspector</h3>
          <p className="mt-0.5 text-[11px] text-ds-text-secondary">Full debug snapshot JSON — secondary view</p>
        </div>
        <span className="text-[12px] text-ds-text-tertiary">{expanded ? "Hide" : "Show"}</span>
      </button>
      {expanded ? (
        <pre className="panel-scroll max-h-[320px] overflow-auto border-t border-ds-border bg-ds-surface-secondary/30 px-4 py-3 font-ds-mono text-[10px] leading-relaxed text-ds-text-secondary">
          {text}
        </pre>
      ) : null}
    </section>
  );
}
