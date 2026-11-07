import { create } from "zustand";
import type { LiveSnapshot } from "../types";

interface DashboardState {
  snapshot: LiveSnapshot | null;
  connected: boolean;
  lastUpdate: string | null;
  advancedOpen: {
    diagnostics: boolean;
    forensic: boolean;
    debug: boolean;
  };
  setSnapshot: (snapshot: LiveSnapshot) => void;
  setConnected: (connected: boolean) => void;
  toggleAdvanced: (key: keyof DashboardState["advancedOpen"]) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  snapshot: null,
  connected: false,
  lastUpdate: null,
  advancedOpen: {
    diagnostics: false,
    forensic: false,
    debug: false,
  },
  setSnapshot: (snapshot) =>
    set({ snapshot, lastUpdate: snapshot.generated_at ?? new Date().toISOString() }),
  setConnected: (connected) => set({ connected }),
  toggleAdvanced: (key) =>
    set((state) => ({
      advancedOpen: { ...state.advancedOpen, [key]: !state.advancedOpen[key] },
    })),
}));
