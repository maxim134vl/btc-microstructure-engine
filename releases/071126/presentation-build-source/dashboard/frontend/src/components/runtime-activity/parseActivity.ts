import type { LiveSnapshot } from "../../types";
import type {
  ActivityCategory,
  ActivityEvent,
  ActivityKpis,
  ActivityOutcome,
  ParsedRuntimeActivity,
} from "../../types/runtimeActivity";

function parseTimestamp(value: unknown): { iso: string | null; ms: number } {
  if (value == null || value === "") return { iso: null, ms: 0 };
  const text = String(value);
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) return { iso: text, ms: 0 };
  return { iso: new Date(ms).toISOString(), ms };
}

function outcomeFromStatus(status: unknown): ActivityOutcome {
  const s = String(status ?? "").toUpperCase();
  if (["SUCCESS", "GREEN", "RUNNING", "ALIVE", "LIVE", "OK"].includes(s)) return "success";
  if (["FAILED", "RED", "ERROR", "CRITICAL"].includes(s)) return "failed";
  if (["YELLOW", "WARN", "WARNING", "SKIPPED", "DEFERRED", "WAITING"].includes(s)) return "warning";
  return "info";
}

function durationMs(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (Number.isNaN(n)) return null;
  return n < 1000 ? Math.round(n * 1000) : Math.round(n);
}

function shortEngine(name: string): string {
  return name.replace(/_engine_v1\.py$/, "").replace(/\.py$/, "").replace(/_/g, " ");
}

function pushEvent(
  bucket: ActivityEvent[],
  partial: Omit<ActivityEvent, "id" | "timestampMs"> & { timestampMs?: number },
  index: number,
) {
  const ts = partial.timestampMs ?? (partial.timestamp ? Date.parse(partial.timestamp) : 0);
  bucket.push({
    ...partial,
    id: `${partial.category}-${partial.source}-${ts}-${index}`,
    timestampMs: Number.isNaN(ts) ? 0 : ts,
  });
}

function parseEngineEvents(snapshot: LiveSnapshot, out: ActivityEvent[]) {
  const rows = snapshot.runtime_operations?.recent_events ?? [];
  rows.forEach((row, index) => {
    const { iso, ms } = parseTimestamp(row.timestamp);
    const engine = String(row.engine ?? "engine");
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: shortEngine(engine),
        subtitle: `Engine run · ${row.status ?? "unknown"}`,
        category: "engine",
        outcome: outcomeFromStatus(row.status),
        durationMs: durationMs(row.duration ?? (row as { duration_s?: number }).duration_s),
        source: engine,
        raw: row as unknown as Record<string, unknown>,
      },
      index,
    );
  });

  const order = snapshot.runtime_operations?.engine_execution_order ?? [];
  order.forEach((row, index) => {
    if (!row.timestamp) return;
    const { iso, ms } = parseTimestamp(row.timestamp);
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: shortEngine(String(row.engine)),
        subtitle: `Pipeline slot · ${row.status}`,
        category: "engine",
        outcome: outcomeFromStatus(row.status),
        durationMs: durationMs(row.duration_s),
        source: String(row.engine),
        raw: row as unknown as Record<string, unknown>,
      },
      1000 + index,
    );
  });
}

function parseTransitionEvents(snapshot: LiveSnapshot, out: ActivityEvent[]) {
  const rows = snapshot.state_transitions?.chronology ?? [];
  rows.forEach((row, index) => {
    const { iso, ms } = parseTimestamp(row.timestamp ?? row.transition_timestamp);
    const fromState = row.from_state ?? row.previous_state;
    const toState = row.to_state ?? row.transition_state ?? row.auction_state;
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: toState ? String(toState).replace(/_/g, " ") : "State transition",
        subtitle: fromState ? `${fromState} → ${toState ?? "?"}` : "Auction state change",
        category: "transition",
        outcome: outcomeFromStatus(row.transition_state ?? row.status ?? "info"),
        durationMs: null,
        source: "state_transition",
        raw: row,
      },
      index,
    );
  });

  const latest = snapshot.state_transitions?.latest_transition;
  if (latest && typeof latest === "object") {
    const { iso, ms } = parseTimestamp(latest.timestamp ?? latest.transition_timestamp);
    if (iso) {
      pushEvent(
        out,
        {
          timestamp: iso,
          timestampMs: ms,
          title: "Latest transition",
          subtitle: String(latest.transition_state ?? latest.to_state ?? "state change"),
          category: "transition",
          outcome: outcomeFromStatus(latest.transition_state),
          durationMs: null,
          source: "latest_transition",
          raw: latest,
        },
        9999,
      );
    }
  }
}

function parseCognitionEvents(snapshot: LiveSnapshot, out: ActivityEvent[]) {
  const rows = snapshot.intermediate_cognition?.timeline ?? [];
  rows.forEach((row, index) => {
    const { iso, ms } = parseTimestamp(row.timestamp ?? row.anchor_timestamp);
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: String(row.intermediate_state ?? "Cognition update"),
        subtitle: "Intermediate cognition",
        category: "cognition",
        outcome: "info",
        durationMs: null,
        source: "intermediate_cognition",
        raw: row,
      },
      index,
    );
  });

  const feed = snapshot.ontology?.ontology_event_feed ?? [];
  feed.forEach((row, index) => {
    const { iso, ms } = parseTimestamp(row.timestamp);
    const eventType = String(row.auction_event_type ?? row.event_type ?? "Ontology event");
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: eventType.replace(/_/g, " "),
        subtitle: `M15 ontology · ${row.auction_state ?? row.timeframe ?? "feed"}`,
        category: "ontology",
        outcome: eventType === "NORMAL" ? "info" : "success",
        durationMs: null,
        source: "ontology_feed",
        raw: row,
      },
      index,
    );
  });
}

function parseHealthEvents(snapshot: LiveSnapshot, out: ActivityEvent[]) {
  const alerts = snapshot.runtime_health?.alerts ?? [];
  alerts.forEach((row, index) => {
    pushEvent(
      out,
      {
        timestamp: snapshot.generated_at ?? null,
        title: String(row.type ?? "Health alert").replace(/_/g, " "),
        subtitle: row.file ? String(row.file) : "Runtime health",
        category: "health",
        outcome: outcomeFromStatus(row.severity),
        durationMs: null,
        source: "runtime_health",
        raw: row as unknown as Record<string, unknown>,
      },
      index,
    );
  });

  const exports = snapshot.replay_audit?.replay_exports ?? [];
  exports.slice(0, 8).forEach((row, index) => {
    const { iso, ms } = parseTimestamp(row.mtime);
    pushEvent(
      out,
      {
        timestamp: iso,
        timestampMs: ms,
        title: row.name,
        subtitle: "Replay export",
        category: "export",
        outcome: "info",
        durationMs: null,
        source: "replay_audit",
        raw: row as unknown as Record<string, unknown>,
      },
      index,
    );
  });
}

function dedupeEvents(events: ActivityEvent[]): ActivityEvent[] {
  const seen = new Set<string>();
  const unique: ActivityEvent[] = [];
  for (const event of events) {
    const key = `${event.category}|${event.source}|${event.timestamp}|${event.title}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(event);
  }
  return unique;
}

function computeKpis(events: ActivityEvent[], snapshot: LiveSnapshot): ActivityKpis {
  const withOutcome = events.filter((e) => e.category === "engine" || e.category === "health");
  const successCount = withOutcome.filter((e) => e.outcome === "success").length;
  const failedCount = withOutcome.filter((e) => e.outcome === "failed").length;
  const warningCount = withOutcome.filter((e) => e.outcome === "warning").length;
  const denom = successCount + failedCount + warningCount;
  const durations = events.map((e) => e.durationMs).filter((d): d is number => d != null && d > 0);
  const avgDurationMs =
    durations.length > 0 ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : null;

  const sorted = [...events].sort((a, b) => b.timestampMs - a.timestampMs);
  const last = sorted.find((e) => e.timestampMs > 0);

  return {
    totalEvents: events.length,
    successCount,
    failedCount,
    warningCount,
    successRate: denom > 0 ? Math.round((successCount / denom) * 100) : null,
    avgDurationMs,
    currentCycle: snapshot.runtime_operations?.current_cycle ?? 0,
    pipelineHealth: snapshot.runtime_operations?.operational_health ?? "UNKNOWN",
    lastEventAt: last?.timestamp ?? null,
  };
}

export function parseRuntimeActivity(raw: unknown): ParsedRuntimeActivity {
  const snapshot = (raw ?? {}) as LiveSnapshot;
  const events: ActivityEvent[] = [];

  parseEngineEvents(snapshot, events);
  parseTransitionEvents(snapshot, events);
  parseCognitionEvents(snapshot, events);
  parseHealthEvents(snapshot, events);

  const deduped = dedupeEvents(events).sort((a, b) => b.timestampMs - a.timestampMs);

  return {
    events: deduped,
    kpis: computeKpis(deduped, snapshot),
    generatedAt: snapshot.generated_at ?? null,
    raw,
  };
}

export function outcomeTone(outcome: ActivityOutcome): "operational" | "degraded" | "critical" | "offline" {
  if (outcome === "success") return "operational";
  if (outcome === "failed") return "critical";
  if (outcome === "warning") return "degraded";
  return "offline";
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export function formatEventTime(iso: string | null): string {
  if (!iso) return "Unknown time";
  try {
    return new Date(iso).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const delta = Date.now() - ms;
  if (delta < 60_000) return "Just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
  return formatEventTime(iso);
}

export function categoryLabel(category: ActivityCategory): string {
  const labels: Record<ActivityCategory, string> = {
    engine: "Engine",
    transition: "Transition",
    cognition: "Cognition",
    ontology: "Ontology",
    health: "Health",
    export: "Export",
  };
  return labels[category];
}
