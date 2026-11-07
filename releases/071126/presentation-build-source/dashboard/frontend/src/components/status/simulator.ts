import { SYSTEM_STATUS } from "./vocabulary";
import type { ResolvedStatus, StatusTone } from "./types";

export const STATUS_SIMULATOR_STORAGE_KEY = "btc-ml.status-simulator";

export function applyStatusSimulator(status: ResolvedStatus, override: StatusTone | null): ResolvedStatus {
  if (!override) return status;

  const key =
    override === "operational"
      ? "operational"
      : override === "degraded"
        ? "degraded"
        : override === "critical"
          ? "critical"
          : "offline";

  return {
    domain: "system",
    key,
    label: SYSTEM_STATUS[key],
    tone: override,
  };
}

export function readSimulatorOverride(): StatusTone | null {
  if (!import.meta.env.DEV) return null;
  try {
    const raw = sessionStorage.getItem(STATUS_SIMULATOR_STORAGE_KEY);
    if (raw === "operational" || raw === "degraded" || raw === "critical" || raw === "offline") {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function writeSimulatorOverride(tone: StatusTone | null): void {
  if (!import.meta.env.DEV) return;
  try {
    if (tone) sessionStorage.setItem(STATUS_SIMULATOR_STORAGE_KEY, tone);
    else sessionStorage.removeItem(STATUS_SIMULATOR_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
