import type { TimelineEvent } from "../../types/visualCognition";

export function CognitionTimeline({
  events,
  activeTimestamp,
  onSelect,
}: {
  events: TimelineEvent[];
  activeTimestamp?: string;
  onSelect: (event: TimelineEvent) => void;
}) {
  if (!events.length) {
    return <p className="text-xs text-slate-500">No cognition events in lookback window.</p>;
  }

  const visible = events.slice(-40);

  return (
    <section className="rounded border border-slate-800 bg-slate-950 p-3">
      <h2 className="text-xs font-semibold tracking-wide text-slate-300">COGNITION TIMELINE</h2>
      <p className="mt-1 text-[10px] text-slate-500">Select timestamp or benchmark event to replay Stage 1 perception</p>
      <div className="mt-3 flex gap-2 overflow-x-auto pb-2">
        {visible.map((event) => {
          const active = event.timestamp === activeTimestamp;
          return (
            <button
              key={`${event.timeline_index}-${event.timestamp}`}
              type="button"
              onClick={() => onSelect(event)}
              className={`min-w-[140px] rounded border px-2 py-2 text-left text-[10px] ${
                active ? "border-sky-500 bg-sky-950/30" : "border-slate-800 bg-slate-900/40 hover:border-slate-600"
              }`}
            >
              <div className="font-mono text-slate-400">{event.timestamp.replace("T", " ").slice(0, 16)}</div>
              <div className="mt-1 font-semibold text-slate-200">{event.type ?? "EVENT"}</div>
              <div className="mt-1 line-clamp-2 text-slate-500">{event.label ?? "—"}</div>
              {event.verdict ? <div className="mt-1 text-[9px] text-violet-400">{event.verdict}</div> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
