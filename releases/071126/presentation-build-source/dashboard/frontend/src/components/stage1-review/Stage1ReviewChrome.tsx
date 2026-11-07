import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import type { Stage1AuditEvent, Stage1EventClass, WindowOverlayEvent } from "../../types/eventReview";
import { EVENT_CLASS_COLORS } from "../../types/eventReview";
import { formatTime } from "../visual-cognition/chartUtils";

export function WorkflowSection({
  title,
  subtitle,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <div className="mb-2 px-0.5">
        <h3 className="font-ds-display text-[12px] font-semibold text-ds-text-primary">{title}</h3>
        {subtitle ? <p className="mt-0.5 text-[10px] leading-snug text-ds-text-tertiary">{subtitle}</p> : null}
      </div>
      <div className="ops-card space-y-2 p-3">{children}</div>
    </section>
  );
}

export function InspectorSection({
  title,
  meta,
  children,
  className = "",
}: {
  title: string;
  meta?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <div className="mb-2 flex items-baseline justify-between gap-2 px-0.5">
        <h3 className="font-ds-display text-[12px] font-semibold text-ds-text-primary">{title}</h3>
        {meta ? <span className="text-[10px] tabular-nums text-ds-text-tertiary">{meta}</span> : null}
      </div>
      <div className="ops-card p-3">{children}</div>
    </section>
  );
}

type ActionVariant = "default" | "warning" | "violet" | "emerald" | "sky";

const ACTION_VARIANT: Record<ActionVariant, { base: string; active: string }> = {
  default: {
    base: "border-ds-border text-ds-text-primary hover:bg-ds-surface-secondary",
    active: "border-ds-border bg-ds-surface-secondary ring-1 ring-ds-border text-ds-text-primary",
  },
  warning: {
    base: "border-amber-500/35 text-ds-status-warning hover:bg-amber-500/10",
    active: "border-amber-500/60 bg-amber-500/15 text-ds-status-warning ring-1 ring-amber-500/25",
  },
  violet: {
    base: "border-violet-500/35 text-ds-text-primary hover:bg-violet-500/10",
    active: "border-violet-500/60 bg-violet-500/15 text-ds-text-primary ring-1 ring-violet-500/25",
  },
  emerald: {
    base: "border-emerald-500/35 text-ds-text-primary hover:bg-emerald-500/10",
    active: "border-emerald-500/60 bg-emerald-500/15 text-ds-status-healthy ring-1 ring-emerald-500/25",
  },
  sky: {
    base: "border-sky-500/35 text-ds-text-primary hover:bg-sky-500/10",
    active: "border-sky-500/60 bg-sky-500/15 text-ds-text-primary ring-1 ring-sky-500/25",
  },
};

export function WorkflowActionButton({
  active = false,
  variant = "default",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; variant?: ActionVariant }) {
  const styles = ACTION_VARIANT[variant];
  return (
    <button
      type="button"
      className={`w-full rounded-xl border px-2.5 py-2 text-left text-[11px] font-medium transition-colors duration-ds disabled:opacity-40 ${active ? styles.active : styles.base} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function WorkspaceToolbarButton({
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`rounded-ds-button border border-ds-border bg-ds-surface px-2.5 py-1 text-[11px] font-medium text-ds-text-secondary transition-colors hover:bg-ds-surface-secondary hover:text-ds-text-primary disabled:opacity-40 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

/** Narrow vertical control for the collapsed left workflow rail (~48px). */
export function WorkspaceRailButton({
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-ds-border bg-ds-surface text-[11px] font-medium text-ds-text-secondary transition-colors hover:bg-ds-surface-secondary hover:text-ds-text-primary disabled:opacity-40 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function WorkspaceSidebarRail({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex h-full w-12 shrink-0 flex-col items-center gap-1.5 border-r border-ds-border/60 bg-ds-surface/40 py-2 ${className}`}
    >
      {children}
    </div>
  );
}

export function ReviewCheckbox({
  label,
  checked,
  onChange,
  swatch,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: () => void;
  swatch?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-[11px] text-ds-text-primary">
      <input type="checkbox" checked={checked} onChange={onChange} className="rounded border-ds-border" />
      {swatch ? <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: swatch }} /> : null}
      {label}
    </label>
  );
}

export function ModeHint({
  variant = "warning",
  children,
}: {
  variant?: "warning" | "sky";
  children: ReactNode;
}) {
  const styles =
    variant === "sky"
      ? "border-sky-500/30 bg-sky-500/10 text-ds-text-primary"
      : "border-amber-500/30 bg-amber-500/10 text-ds-status-warning";
  return (
    <div className={`rounded-xl border px-2.5 py-2 text-[10px] leading-relaxed ${styles}`}>{children}</div>
  );
}

export function InspectorHint({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-ds-border bg-ds-surface-secondary/60 px-2.5 py-2 text-[10px] text-ds-text-secondary">
      {children}
    </div>
  );
}

export function InspectorListItem({
  active = false,
  highlight = "active",
  interactive = false,
  children,
  onClick,
  onKeyDown,
}: {
  active?: boolean;
  highlight?: "active" | "source" | "target";
  interactive?: boolean;
  children: ReactNode;
  onClick?: () => void;
  onKeyDown?: (event: React.KeyboardEvent) => void;
}) {
  const toneClass =
    highlight === "source"
      ? "border-sky-500/50 bg-sky-500/10"
      : highlight === "target"
        ? "border-sky-500/30 bg-sky-500/5"
        : active
          ? "border-ds-border bg-ds-surface-secondary ring-1 ring-ds-border"
          : interactive
            ? "cursor-pointer border-ds-border hover:border-ds-border hover:bg-ds-surface-secondary/80"
            : "border-ds-border/80 bg-ds-surface-secondary/30";
  return (
    <li
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={`rounded-xl border px-2.5 py-2 text-[10px] transition-colors ${toneClass}`}
    >
      {children}
    </li>
  );
}

export function InspectorMicroButton({
  tone = "neutral",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "neutral" | "danger" | "success" | "sky" }) {
  const toneClass =
    tone === "danger"
      ? "border-red-500/30 text-ds-status-error hover:bg-red-500/10"
      : tone === "success"
        ? "border-emerald-500/30 text-ds-status-healthy hover:bg-emerald-500/10"
        : tone === "sky"
          ? "border-sky-500/30 text-ds-text-primary hover:bg-sky-500/10"
          : "border-ds-border text-ds-text-primary hover:bg-ds-surface-secondary";
  return (
    <button
      type="button"
      className={`rounded-lg border px-1.5 py-0.5 text-[9px] font-medium transition-colors disabled:opacity-40 ${toneClass}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function ReviewField({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <label className="block">
      {label ? <span className="mb-1 block text-[10px] font-medium text-ds-text-tertiary">{label}</span> : null}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="w-full rounded-xl border border-ds-border bg-ds-surface-secondary/50 px-2.5 py-2 text-[11px] text-ds-text-primary placeholder:text-ds-text-tertiary"
      />
    </label>
  );
}

export function ReviewSelect({
  value,
  onChange,
  children,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full rounded-xl border border-ds-border bg-ds-surface-secondary/50 px-2.5 py-1.5 text-[11px] text-ds-text-primary ${className}`}
    >
      {children}
    </select>
  );
}

export function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-2 border-b border-ds-border/60 py-1.5 text-[11px] last:border-b-0">
      <div className="text-ds-text-tertiary">{label}</div>
      <div className="break-all text-ds-text-primary">{value}</div>
    </div>
  );
}

export function EventTimeline({
  events,
  currentEvent,
  onSelect,
}: {
  events: WindowOverlayEvent[];
  currentEvent: Stage1AuditEvent | null;
  onSelect: (event: WindowOverlayEvent) => void;
}) {
  if (events.length === 0) {
    return <p className="text-[11px] text-ds-text-tertiary">Нет событий в текущем окне.</p>;
  }
  return (
    <ul className="panel-scroll max-h-48 space-y-1.5 overflow-y-auto">
      {events.map((event) => {
        const isCurrent =
          currentEvent != null &&
          event.timestamp === currentEvent.timestamp &&
          event.event_class === currentEvent.event_class;
        const color = EVENT_CLASS_COLORS[event.event_class as Stage1EventClass];
        return (
          <li key={`${event.timestamp}|${event.event_class}`}>
            <button
              type="button"
              onClick={() => onSelect(event)}
              className={`w-full rounded-xl border px-2.5 py-2 text-left text-[11px] transition-colors ${
                isCurrent
                  ? "border-ds-border bg-ds-surface-secondary ring-1 ring-ds-border text-ds-text-primary"
                  : "border-ds-border/70 text-ds-text-secondary hover:border-ds-border hover:bg-ds-surface-secondary/60 hover:text-ds-text-primary"
              }`}
            >
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ backgroundColor: color }} />
              <span className="text-ds-text-tertiary">{formatTime(event.timestamp)}</span>{" "}
              <span style={{ color }}>{event.event_class}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function ChartFormSurface({ children }: { children: ReactNode }) {
  return (
    <div className="mt-2 space-y-2 border-t border-ds-border/60 pt-2">{children}</div>
  );
}

export function ChartInlineForm({
  tone = "neutral",
  title,
  children,
}: {
  tone?: "neutral" | "warning" | "violet" | "sky";
  title?: ReactNode;
  children: ReactNode;
}) {
  const toneClass =
    tone === "warning"
      ? "border-amber-500/30 bg-amber-500/8"
      : tone === "violet"
        ? "border-violet-500/30 bg-violet-500/8"
        : tone === "sky"
          ? "border-sky-500/30 bg-sky-500/8"
          : "border-ds-border bg-ds-surface-secondary/40";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      {title ? <div className="mb-2 text-[11px] font-medium text-ds-text-primary">{title}</div> : null}
      {children}
    </div>
  );
}

export function ReviewStatusButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-xl border px-3 py-1.5 text-[11px] font-medium transition-colors disabled:opacity-40 ${
        active
          ? "border-ds-border bg-ds-surface-secondary text-ds-text-primary ring-1 ring-ds-border"
          : "border-ds-border/70 text-ds-text-secondary hover:bg-ds-surface-secondary/60"
      }`}
    >
      {children}
    </button>
  );
}

export function ReviewCheckboxInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" className="rounded border-ds-border" {...props} />;
}
