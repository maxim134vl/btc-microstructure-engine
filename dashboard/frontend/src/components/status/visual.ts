import type { StatusTone } from "./types";

/** Theme-aware status dot — calm operational, stronger warning/critical */
export const TONE_DOT_CLASS: Record<StatusTone, string> = {
  operational: "status-dot status-dot--operational",
  degraded: "status-dot status-dot--degraded",
  critical: "status-dot status-dot--critical",
  offline: "status-dot status-dot--offline",
};

export const TONE_STROKE: Record<StatusTone, string> = {
  operational: "var(--ds-status-healthy)",
  degraded: "var(--ds-status-warning)",
  critical: "var(--ds-status-error)",
  offline: "var(--ds-status-idle)",
};

export const TONE_RING_TRACK: Record<StatusTone, string> = {
  operational: "var(--ds-status-healthy-ring-track)",
  degraded: "var(--ds-status-warning-ring-track)",
  critical: "var(--ds-status-error-ring-track)",
  offline: "var(--ds-status-idle-ring-track)",
};

/** Ring progress glow — only warnings and critical draw the eye */
export const TONE_RING_GLOW_CLASS: Record<StatusTone, string> = {
  operational: "",
  degraded: "ring-gauge-progress--degraded",
  critical: "ring-gauge-progress--critical",
  offline: "",
};

export const TONE_BADGE_CLASS: Record<StatusTone, string> = {
  operational: "bg-ds-status-healthy/8 text-ds-text-primary ring-1 ring-ds-status-healthy/22",
  degraded:
    "bg-ds-status-warning/12 text-ds-text-primary ring-1 ring-ds-status-warning/32 shadow-[var(--ds-status-warning-glow)]",
  critical:
    "bg-ds-status-error/14 text-ds-text-primary ring-1 ring-ds-status-error/40 shadow-[var(--ds-status-error-glow)]",
  offline: "bg-ds-surface-secondary text-ds-text-secondary ring-1 ring-ds-border",
};

/** Orb glow — operational stays calm; problems escalate */
export const TONE_GLOW: Record<StatusTone, string> = {
  operational: "",
  degraded: "status-dot-glow status-dot-glow--degraded",
  critical: "status-dot-glow status-dot-glow--critical",
  offline: "",
};

export const TONE_ACCENT_BAR: Record<StatusTone, string> = {
  operational: "from-ds-status-healthy/35 via-ds-status-healthy/15 to-transparent",
  degraded: "from-ds-status-warning/55 via-ds-status-warning/25 to-transparent",
  critical: "from-ds-status-error/70 via-ds-status-error/35 to-transparent",
  offline: "from-ds-status-idle/50 to-transparent",
};

export const TONE_KPI_WASH: Record<StatusTone, string> = {
  operational: "bg-gradient-to-br from-ds-status-healthy/8 via-transparent to-transparent",
  degraded: "bg-gradient-to-br from-ds-status-warning/14 via-transparent to-transparent",
  critical: "bg-gradient-to-br from-ds-status-error/18 via-transparent to-transparent",
  offline: "bg-gradient-to-br from-ds-status-idle/8 via-transparent to-transparent",
};

export const TONE_STRIPE: Record<StatusTone, string> = {
  operational: "bg-ds-status-healthy/70",
  degraded: "bg-ds-status-warning",
  critical: "bg-ds-status-error",
  offline: "bg-ds-status-idle",
};

export const TONE_ICON_CHIP: Record<StatusTone, string> = {
  operational: "!bg-ds-surface-secondary/90 !text-ds-text-secondary",
  degraded: "!bg-ds-status-warning/12 !text-ds-status-warning ring-1 !ring-ds-status-warning/28",
  critical: "!bg-ds-status-error/12 !text-ds-status-error ring-1 !ring-ds-status-error/35",
  offline: "!bg-ds-status-idle/12 !text-ds-status-idle ring-1 !ring-ds-status-idle/25",
};
