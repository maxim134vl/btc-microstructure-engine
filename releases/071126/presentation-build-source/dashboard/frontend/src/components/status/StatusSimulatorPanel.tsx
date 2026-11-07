import { StatusBadge } from "./StatusBadge";
import { useStatusSimulator } from "./StatusSimulatorContext";
import type { ResolvedStatus, StatusTone } from "./types";
import { SYSTEM_STATUS } from "./vocabulary";

const PRESETS: StatusTone[] = ["operational", "degraded", "critical", "offline"];

function previewStatus(tone: StatusTone): ResolvedStatus {
  const key =
    tone === "operational"
      ? "operational"
      : tone === "degraded"
        ? "degraded"
        : tone === "critical"
          ? "critical"
          : "offline";
  return {
    domain: "system",
    key,
    label: SYSTEM_STATUS[key],
    tone,
  };
}

/** Development-only panel for forcing platform status tones. */
export function StatusSimulatorPanel({ className = "" }: { className?: string }) {
  const { enabled, override, setOverride } = useStatusSimulator();

  if (!enabled) return null;

  return (
    <section
      className={`rounded-ds-card border border-ds-border bg-ds-surface p-4 shadow-ds-sm ${className}`}
      aria-label="Status simulator"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[13px] font-semibold text-ds-text-primary">Status Simulator</h2>
          <p className="mt-0.5 text-[12px] text-ds-text-secondary">
            Force platform tones across all status primitives (development only).
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOverride(null)}
          className="rounded-ds-input px-2.5 py-1 text-[12px] font-medium text-ds-text-secondary hover:bg-ds-surface-secondary hover:text-ds-text-primary"
        >
          Reset
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((tone) => {
          const active = override === tone;
          return (
            <button
              key={tone}
              type="button"
              onClick={() => setOverride(active ? null : tone)}
              className={`rounded-ds-input border px-2 py-1 transition-colors duration-200 ${
                active
                  ? "border-ds-accent bg-ds-accent/10"
                  : "border-ds-border bg-ds-surface-secondary/60 hover:bg-ds-surface-secondary"
              }`}
            >
              <StatusBadge status={previewStatus(tone)} variant="pill" size="sm" />
            </button>
          );
        })}
      </div>

      {override ? (
        <p className="mt-3 text-[11px] text-ds-text-secondary">
          Active override: all status indicators render as{" "}
          <span className="font-medium text-ds-text-primary">{SYSTEM_STATUS[override === "operational" ? "operational" : override === "degraded" ? "degraded" : override === "critical" ? "critical" : "offline"]}</span>
        </p>
      ) : null}
    </section>
  );
}
