import type { HealthLevel } from "../types";

const COLORS: Record<HealthLevel, string> = {
  GREEN: "text-ds-status-healthy border-command-green/40 bg-command-green/10",
  YELLOW: "text-ds-status-warning border-command-yellow/40 bg-command-yellow/10",
  RED: "text-ds-status-error border-command-red/40 bg-command-red/10",
};

export function HealthBadge({ level, label }: { level: HealthLevel | string; label?: string }) {
  const normalized = (level === "SUCCESS" ? "GREEN" : level === "FAILED" ? "RED" : level) as HealthLevel;
  const style = COLORS[normalized] ?? COLORS.YELLOW;
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-mono uppercase ${style}`}>
      {label ?? level}
    </span>
  );
}

export function MetricCell({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-command-border bg-command-bg/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-ds-text-tertiary">{label}</div>
      <div className="mt-1 font-mono text-sm text-ds-text-primary truncate">{formatValue(value)}</div>
    </div>
  );
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? value.toFixed(4).replace(/\.?0+$/, "") : "—";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 80);
  return String(value);
}

export function PanelShell({
  title,
  subtitle,
  children,
  onFullscreen,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  onFullscreen?: () => void;
  className?: string;
}) {
  return (
    <section className={`flex h-full min-h-0 flex-col rounded border border-command-border bg-command-panel ${className}`}>
      <header className="flex items-center justify-between border-b border-command-border px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-ds-text-primary">{title}</h2>
          {subtitle ? <p className="text-[11px] text-ds-text-tertiary">{subtitle}</p> : null}
        </div>
        {onFullscreen ? (
          <button
            type="button"
            onClick={onFullscreen}
            className="rounded border border-command-border px-2 py-1 text-[10px] uppercase text-ds-text-tertiary hover:text-ds-text-primary"
          >
            Expand
          </button>
        ) : null}
      </header>
      <div className="panel-scroll min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </section>
  );
}
