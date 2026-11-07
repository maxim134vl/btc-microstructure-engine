import { create } from "zustand";
import { buildOpsFallbackSnapshot } from "../api/opsFallbackSnapshot";
import type { OpsSnapshot } from "../types/ops";

interface MonitorState {
  snapshot: OpsSnapshot | null;
  connected: boolean;
  debugMode: boolean;
  acknowledgedAlerts: Set<string>;
  expandedGroups: Set<string>;
  setSnapshot: (snapshot: OpsSnapshot) => void;
  setConnected: (connected: boolean) => void;
  setDebugMode: (debug: boolean) => void;
  acknowledgeAlert: (id: string) => void;
  toggleGroup: (id: string) => void;
}

export const useMonitorStore = create<MonitorState>((set, get) => ({
  // Seed full Operations UI immediately — live :8080 feed is optional.
  snapshot: buildOpsFallbackSnapshot(),
  connected: false,
  debugMode: window.location.hash === "#debug",
  acknowledgedAlerts: new Set(),
  expandedGroups: new Set(),
  setSnapshot: (snapshot) => set({ snapshot }),
  setConnected: (connected) => set({ connected }),
  setDebugMode: (debugMode) => set({ debugMode }),
  acknowledgeAlert: (id) => {
    const next = new Set(get().acknowledgedAlerts);
    next.add(id);
    set({ acknowledgedAlerts: next });
  },
  toggleGroup: (id) => {
    const next = new Set(get().expandedGroups);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    set({ expandedGroups: next });
  },
}));
