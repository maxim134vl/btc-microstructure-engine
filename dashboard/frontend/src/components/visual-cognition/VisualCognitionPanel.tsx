import { useCallback, useEffect, useState } from "react";
import { fetchVisualCognitionSnapshot } from "../../api/visualCognitionClient";
import { COGNITION_COLOR_LEGEND, type TimelineEvent, type VisualCognitionSnapshot } from "../../types/visualCognition";
import { CognitionFlowPanel } from "./CognitionFlowPanel";
import { CognitionTimeline } from "./CognitionTimeline";
import { MtfChart } from "./MtfChart";

export function VisualCognitionPanel() {
  const [snapshot, setSnapshot] = useState<VisualCognitionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (params?: { timestamp?: string; eventIndex?: number }) => {
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await fetchVisualCognitionSnapshot(params));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function handleSelectEvent(event: TimelineEvent) {
    load({ timestamp: event.timestamp, eventIndex: event.event_index ?? event.timeline_index });
  }

  if (!snapshot && loading) {
    return <div className="text-sm text-slate-500">Loading visual cognition replay…</div>;
  }

  if (!snapshot || snapshot.status === "NO_DATA") {
    return <div className="text-sm text-slate-500">{snapshot?.message ?? "No cognition memory available."}</div>;
  }

  const timeframes = snapshot.timeframes ?? ["D1", "H4", "H1", "M15"];

  return (
    <div className="space-y-3">
      <section className="rounded border border-slate-800 bg-slate-950 p-3">
        <h1 className="text-sm font-semibold tracking-wide text-emerald-300">VISUAL COGNITION</h1>
        <p className="mt-1 text-xs text-slate-500">
          Stage 1 market perception replay — M15 → D1 auction hierarchy (cognition memory, not raw candles)
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] font-mono text-slate-400">
          <span>Cursor: {snapshot.cursor_timestamp?.replace("T", " ").slice(0, 19) ?? "—"}</span>
          {snapshot.propagation?.summary ? <span className="text-slate-300">Propagation: {snapshot.propagation.summary}</span> : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {COGNITION_COLOR_LEGEND.map((item) => (
            <span key={item.key} className="inline-flex items-center gap-1 text-[9px] text-slate-500">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </section>

      <div className="grid gap-3 xl:grid-cols-12">
        <div className="space-y-2 xl:col-span-8">
          <h2 className="text-xs font-semibold text-slate-300">MTF AUCTION MAP</h2>
          {timeframes.map((tf) => {
            const section = snapshot.mtf_map[tf];
            return (
              <MtfChart
                key={tf}
                timeframe={tf}
                bars={section?.bars ?? []}
                cursorIndex={section?.cursor_index ?? snapshot.cursor_indices?.[tf]}
              />
            );
          })}

          {snapshot.propagation?.inheritance && snapshot.propagation.inheritance.length > 0 ? (
            <section className="rounded border border-slate-900 bg-slate-950/50 p-3">
              <h3 className="text-[10px] font-semibold text-slate-400">BEHAVIORAL INHERITANCE</h3>
              <ul className="mt-2 space-y-1 text-[10px] font-mono text-slate-500">
                {snapshot.propagation.inheritance.map((row) => (
                  <li key={`${row.from}-${row.to}`}>
                    {row.from} → {row.to}: <span className="text-slate-300">{row.signal}</span> (parent {Math.round(row.parent_health * 100)}% · child {Math.round(row.child_health * 100)}%)
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <div className="xl:col-span-4">
          <CognitionFlowPanel steps={snapshot.cognition_flow ?? []} interpretation={snapshot.interpretation} />
        </div>
      </div>

      <CognitionTimeline
        events={snapshot.timeline ?? []}
        activeTimestamp={snapshot.cursor_timestamp}
        onSelect={handleSelectEvent}
      />

      {error ? <p className="text-xs text-red-400">{error}</p> : null}
      {loading ? <p className="text-[10px] text-slate-500">Updating replay…</p> : null}
    </div>
  );
}
