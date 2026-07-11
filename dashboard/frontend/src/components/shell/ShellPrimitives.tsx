import type { ReactNode } from "react";
import { useTranslation } from "../../i18n";

/** Shared shell motion — 200ms, no flashy animation. */
export const shellMotion =
  "transition-[color,background-color,box-shadow,opacity,transform] duration-200 ease-ds";

export function ShellDivider({ className = "" }: { className?: string }) {
  return <span className={`block h-4 w-px shrink-0 bg-ds-border/80 ${className}`} aria-hidden />;
}

export function EnvironmentStatus() {
  const { t } = useTranslation();
  const isDev = import.meta.env.DEV;

  return (
    <span
      className={`env-badge inline-flex items-center gap-1.5 rounded-ds-pill px-2 py-0.5 text-[10px] font-medium ${shellMotion} ${
        isDev ? "env-badge--dev" : "env-badge--prod"
      }`}
      title={isDev ? t("shell.developmentEnv") : t("shell.productionEnv")}
    >
      <span
        className={`status-dot h-1.5 w-1.5 ${isDev ? "status-dot--degraded" : "status-dot--operational status-dot--calm"}`}
        aria-hidden
      />
      {isDev ? t("shell.development") : t("shell.production")}
    </span>
  );
}

export function IconChip({
  children,
  active = false,
  accent = false,
  className = "",
}: {
  children: ReactNode;
  active?: boolean;
  accent?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`icon-chip inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] ${shellMotion} ${
        active ? "icon-chip--active" : accent ? "icon-chip--accent" : ""
      } ${className}`}
    >
      {children}
    </span>
  );
}

export function TimestampBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="timestamp-badge inline-flex items-center gap-1.5 text-[12px]">
      <span className="font-medium">{label}</span>
      <span className="tabular-nums">{value}</span>
    </span>
  );
}
