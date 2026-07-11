import { useCallback, useEffect, useState } from "react";
import { fetchStage1EventMap } from "../../api/visualCognitionClient";
import type { Stage1EventMapSnapshot } from "../../types/visualCognition";
import { Stage1EventMapChart } from "./Stage1EventMapChart";

function SummaryCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded border border-neutral-800 bg-black px-3 py-2">
      <div className="text-[9px] uppercase tracking-wide text-ds-text-tertiary">{label}</div>
      <div className="mt-1 font-mono text-lg text-ds-text-primary" style={accent ? { color: accent } : undefined}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}

export function Stage1EventMapPanel({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<Stage1EventMapSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchStage1EventMap());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return <div className="text-sm text-ds-text-tertiary">Loading full Stage 1 event map…</div>;
  }

  if (error && !data) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-ds-status-error">{error}</p>
        <button type="button" onClick={load} className="text-xs text-ds-text-secondary underline">
          Retry
        </button>
      </div>
    );
  }

  if (!data || data.status === "NO_DATA") {
    return <div className="text-sm text-ds-text-tertiary">{data?.message ?? "No Stage 1 history available."}</div>;
  }

  const summary = data.summary;
  const markerOk = summary.total_markers > 0;

  const inner = (
    <>
      {!embedded ? (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-ds-text-primary">STAGE 1 EVENT MAP — FULL HISTORY AUDIT</h2>
            <p className="mt-1 max-w-3xl text-xs text-ds-text-tertiary">
              Entire <code className="text-ds-text-secondary">candle_structure_memory</code> +{" "}
              <code className="text-ds-text-secondary">volume_classification_memory</code>. All climax, stopping, and high_average markers on price — no replay window limit.
            </p>
            {data.start && data.end ? (
              <p className="mt-1 font-mono text-[10px] text-ds-text-tertiary">
                {data.start.replace("T", " ").slice(0, 19)} → {data.end.replace("T", " ").slice(0, 19)} · {summary.total_bars.toLocaleString()} bars
              </p>
            ) : null}
          </div>
          <button type="button" onClick={load} disabled={loading} className="rounded border border-neutral-700 px-2 py-1 text-[10px] font-mono text-ds-text-secondary hover:text-ds-text-primary">
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      ) : (
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-[10px] text-ds-text-tertiary">
            {summary.total_bars.toLocaleString()} bars · {summary.total_markers.toLocaleString()} markers
          </p>
          <button type="button" onClick={load} disabled={loading} className="rounded border border-neutral-700 px-2 py-0.5 text-[10px] font-mono text-ds-text-secondary hover:text-ds-text-primary">
            {loading ? "…" : "Refresh"}
          </button>
        </div>
      )}

      {!embedded ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
          <SummaryCard label="climax" value={summary.climax} accent="#22c55e" />
          <SummaryCard label="stopping" value={summary.stopping} accent="#eab308" />
          <SummaryCard label="high_average" value={summary.high_average} accent="#06b6d4" />
          <SummaryCard label="total markers" value={summary.total_markers} accent={markerOk ? "#22c55e" : "#ef4444"} />
          <SummaryCard label="climax buying" value={summary.climax_buying ?? 0} />
          <SummaryCard label="climax selling" value={summary.climax_selling ?? 0} />
        </div>
      ) : null}

      {!markerOk ? (
        <p className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-ds-status-error">
          Zero markers rendered — Stage 1 event visualization is broken or classification memory is missing.
        </p>
      ) : embedded ? null : (
        <p className="text-[10px] font-mono text-ds-text-tertiary">
          {summary.total_markers.toLocaleString()} point markers at concentration price · hollow candles = price context only
        </p>
      )}

      <Stage1EventMapChart bars={data.bars} events={data.events} />

      {error ? <p className="text-xs text-ds-status-error">{error}</p> : null}
    </>
  );

  if (embedded) {
    return <div className="space-y-2">{inner}</div>;
  }

  return (
    <section className="space-y-3 rounded border border-neutral-800 bg-black p-3">
      {inner}
    </section>
  );
}
