import type { ComponentType } from "react";
import { useTranslation } from "../../i18n";
import { StatusDot } from "./StatusDot";
import { useSimulatedStatus } from "./StatusSimulatorContext";
import type { ResolvedStatus, StatusTone } from "./types";
import { TONE_BADGE_CLASS } from "./visual";

type SymbolComponent = ComponentType<{ className?: string }>;

const FALLBACK_STATUS: ResolvedStatus = {
  domain: "system",
  key: "operational",
  label: "",
  tone: "operational",
};

export function StatusBadge({
  status,
  tone,
  label,
  icon: Icon,
  size = "sm",
  pulse = false,
  variant = "inline",
  className = "",
}: {
  status?: ResolvedStatus;
  tone?: StatusTone;
  label?: string;
  icon?: SymbolComponent;
  size?: "sm" | "md";
  pulse?: boolean;
  variant?: "inline" | "pill";
  className?: string;
}) {
  const { t } = useTranslation();
  const simulated = useSimulatedStatus(status ?? FALLBACK_STATUS);
  const resolvedTone = status ? simulated.tone : tone ?? "operational";
  const resolvedLabel = status
    ? t(`status.${simulated.domain}.${simulated.key}`)
    : label ?? "";
  const text = size === "md" ? "text-[14px] font-medium" : "text-[13px] font-medium";
  const iconBox = size === "md" ? "h-5 w-5" : "h-4 w-4";
  const dot = size === "md" ? "h-3 w-3" : "h-2.5 w-2.5";
  const pill = variant === "pill";

  return (
    <span
      className={`inline-flex items-center gap-2 text-ds-text-primary ${text} ${
        pill ? `rounded-ds-pill px-2.5 py-1 ${TONE_BADGE_CLASS[resolvedTone]}` : ""
      } ${className}`}
    >
      {Icon ? (
        <span className={`inline-flex shrink-0 items-center justify-center text-ds-text-secondary ${iconBox}`}>
          <Icon className="h-full w-full" />
        </span>
      ) : null}
      <StatusDot tone={resolvedTone} className={dot} pulse={pulse} />
      <span>{resolvedLabel}</span>
    </span>
  );
}
