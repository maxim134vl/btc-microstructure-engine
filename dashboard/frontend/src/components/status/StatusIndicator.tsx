import type { ComponentType } from "react";
import { useTranslation } from "../../i18n";
import { pickStatusLabel } from "../ops/unifiedDisplay";
import { DOMAIN_STATUS_ICON } from "./defaultIcons";
import { StatusDot } from "./StatusDot";
import { useSimulatedStatus } from "./StatusSimulatorContext";
import type { ResolvedStatus } from "./types";

type SymbolComponent = ComponentType<{ className?: string }>;

export function StatusIndicator({
  status,
  icon,
  size = "sm",
  pulse = false,
  className = "",
}: {
  status: ResolvedStatus;
  icon?: SymbolComponent;
  size?: "sm" | "md";
  pulse?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const resolved = useSimulatedStatus(status);
  const Icon = icon ?? DOMAIN_STATUS_ICON[resolved.domain];
  const textClass = size === "md" ? "text-[14px] font-medium" : "text-[13px] font-medium";
  const iconBox = size === "md" ? "h-5 w-5" : "h-4 w-4";
  const dot = size === "md" ? "h-3 w-3" : "h-2.5 w-2.5";
  const i18nKey = `status.${resolved.domain}.${resolved.key}`;
  const label = pickStatusLabel({
    resolvedLabel: resolved.label,
    i18nValue: t(i18nKey),
    i18nKey,
  });

  return (
    <span className={`inline-flex items-center gap-2 text-ds-text-primary ${textClass} ${className}`}>
      <span className={`inline-flex shrink-0 items-center justify-center text-ds-text-secondary ${iconBox}`}>
        <Icon className="h-full w-full" />
      </span>
      <StatusDot tone={resolved.tone} className={dot} pulse={pulse} />
      <span>{label}</span>
    </span>
  );
}
