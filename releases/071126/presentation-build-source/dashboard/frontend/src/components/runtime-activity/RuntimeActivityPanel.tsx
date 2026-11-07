import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchDebugSnapshot } from "../../api/client";
import { useTranslation } from "../../i18n";
import { StatusSimulatorPanel } from "../status";
import { ActivityKpiRow, ActivityTimeline, EventDetailPanel, RawTelemetryInspector } from "./RuntimeActivityViews";
import { parseRuntimeActivity } from "./parseActivity";

type DebugSnapshotEnvelope = {
  ok?: boolean;
  status?: string;
  error?: string | null;
  snapshot?: unknown;
  warnings?: Array<string | { section?: string; reason?: string }>;
};

function isDebugSnapshotEnvelope(value: unknown): value is DebugSnapshotEnvelope {
  return Boolean(value && typeof value === "object" && "snapshot" in value && "status" in value);
}

function warningText(warning: string | { section?: string; reason?: string }): string {
  if (typeof warning === "string") return warning;
  return [warning.section, warning.reason].filter(Boolean).join(": ") || "Runtime debug data is partially unavailable.";
}

export function RuntimeActivityPanel() {
  const { t } = useTranslation();
  const [raw, setRaw] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rawExpanded, setRawExpanded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDebugSnapshot();
      setRaw(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const envelope = useMemo(() => (isDebugSnapshotEnvelope(raw) ? raw : null), [raw]);
  const snapshotPayload = envelope ? (envelope.snapshot ?? {}) : raw;
  const parsed = useMemo(() => (snapshotPayload ? parseRuntimeActivity(snapshotPayload) : null), [snapshotPayload]);
  const degradedReason = useMemo(() => {
    if (error) return error;
    if (!envelope || envelope.status === "ok") return null;
    return envelope.error || envelope.warnings?.map(warningText).join("; ") || "Debug snapshot returned partial runtime data.";
  }, [envelope, error]);

  useEffect(() => {
    if (!parsed?.events.length) return;
    if (!selectedId || !parsed.events.some((e) => e.id === selectedId)) {
      setSelectedId(parsed.events[0].id);
    }
  }, [parsed, selectedId]);

  const selected = parsed?.events.find((e) => e.id === selectedId) ?? null;

  if (loading && !parsed) {
    return (
      <div className="ops-surface flex h-64 items-center justify-center text-[15px] text-ds-text-secondary">
        {t("runtimeActivity.loading")}
      </div>
    );
  }

  if (error && !parsed) {
    return (
      <div className="ops-surface rounded-ds-card border border-ds-status-warning/35 bg-ds-status-warning/10 p-4 text-[13px] text-ds-text-primary">
        <h2 className="text-[14px] font-semibold text-ds-status-warning">Runtime Activity degraded</h2>
        <p className="mt-1 font-medium">Debug snapshot unavailable.</p>
        <p className="mt-1 text-ds-text-secondary">Reason: {error}</p>
      </div>
    );
  }

  if (!parsed) return null;

  return (
    <div className="ops-surface flex min-h-0 flex-1 flex-col gap-4 p-4">
      {import.meta.env.DEV ? <StatusSimulatorPanel /> : null}

      {degradedReason ? (
        <div className="rounded-ds-card border border-ds-status-warning/35 bg-ds-status-warning/10 p-3 text-[12px] text-ds-text-primary">
          <div className="font-semibold text-ds-status-warning">Runtime Activity degraded</div>
          <div className="mt-1">Debug snapshot unavailable or partial.</div>
          <div className="mt-1 text-ds-text-secondary">Reason: {degradedReason}</div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] text-ds-text-secondary">
            {t("runtimeActivity.description")}
          </p>
          {parsed.generatedAt ? (
            <p className="mt-0.5 text-[11px] text-ds-text-tertiary">
              {t("runtimeActivity.snapshot", { time: new Date(parsed.generatedAt).toLocaleString() })}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="rounded-ds-button border border-ds-border bg-ds-surface px-3 py-1.5 text-[12px] font-medium text-ds-text-primary shadow-ds-sm hover:bg-ds-surface-secondary disabled:opacity-50"
        >
          {loading ? t("common.refreshing") : t("common.refresh")}
        </button>
      </div>

      <ActivityKpiRow kpis={parsed.kpis} />

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]">
        <section className="ops-card flex min-h-[280px] min-w-0 flex-col lg:min-h-[360px]">
          <header className="border-b border-ds-border px-4 py-3">
            <h2 className="text-[14px] font-semibold text-ds-text-primary">{t("runtimeActivity.timelineTitle")}</h2>
            <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{t("runtimeActivity.timelineSubtitle")}</p>
          </header>
          <div className="min-h-0 flex-1 p-2">
            <ActivityTimeline events={parsed.events} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </section>

        <section className="ops-card flex min-h-[280px] flex-col lg:min-h-[360px]">
          <header className="border-b border-ds-border px-4 py-3">
            <h2 className="text-[14px] font-semibold text-ds-text-primary">{t("runtimeActivity.detailsTitle")}</h2>
            <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{t("runtimeActivity.detailsSubtitle")}</p>
          </header>
          <div className="min-h-0 flex-1">
            <EventDetailPanel event={selected} />
          </div>
        </section>
      </div>

      <RawTelemetryInspector raw={parsed.raw} expanded={rawExpanded} onToggle={() => setRawExpanded((v) => !v)} />
    </div>
  );
}
