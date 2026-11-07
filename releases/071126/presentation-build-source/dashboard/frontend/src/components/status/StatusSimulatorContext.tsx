import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { applyStatusSimulator, readSimulatorOverride, writeSimulatorOverride } from "./simulator";
import type { ResolvedStatus, StatusTone } from "./types";

type StatusSimulatorContextValue = {
  enabled: boolean;
  override: StatusTone | null;
  setOverride: (tone: StatusTone | null) => void;
  simulate: (status: ResolvedStatus) => ResolvedStatus;
};

const StatusSimulatorContext = createContext<StatusSimulatorContextValue | null>(null);

export function StatusSimulatorProvider({ children }: { children: ReactNode }) {
  const [override, setOverrideState] = useState<StatusTone | null>(() =>
    import.meta.env.DEV ? readSimulatorOverride() : null,
  );

  const setOverride = (tone: StatusTone | null) => {
    setOverrideState(tone);
    writeSimulatorOverride(tone);
  };

  const value = useMemo<StatusSimulatorContextValue>(
    () => ({
      enabled: import.meta.env.DEV,
      override: import.meta.env.DEV ? override : null,
      setOverride,
      simulate: (status) => (import.meta.env.DEV ? applyStatusSimulator(status, override) : status),
    }),
    [override],
  );

  return <StatusSimulatorContext.Provider value={value}>{children}</StatusSimulatorContext.Provider>;
}

export function useStatusSimulator(): StatusSimulatorContextValue {
  const ctx = useContext(StatusSimulatorContext);
  if (ctx) return ctx;
  return {
    enabled: false,
    override: null,
    setOverride: () => {},
    simulate: (status) => status,
  };
}

export function useSimulatedStatus(status: ResolvedStatus): ResolvedStatus {
  return useStatusSimulator().simulate(status);
}
