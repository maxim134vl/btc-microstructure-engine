import type { OpsSnapshot } from "../types/ops";
import { getApiBase, getWsUrl } from "./baseUrl";

export async function fetchOpsSnapshot(): Promise<OpsSnapshot> {
  const response = await fetch(`${getApiBase()}/ops/snapshot`);
  if (!response.ok) throw new Error(`ops snapshot ${response.status}`);
  return response.json();
}

/** Soft live fetch — never throws; returns null when API is unavailable. */
export async function softFetchOpsSnapshot(timeoutMs = 1500): Promise<OpsSnapshot | null> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${getApiBase()}/ops/snapshot`, {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as OpsSnapshot;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function fetchDebugSnapshot(): Promise<unknown> {
  const response = await fetch(`${getApiBase()}/debug/snapshot`);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const reason =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error?: unknown }).error)
        : `HTTP ${response.status}`;
    return {
      ok: false,
      status: "degraded",
      error: `Debug snapshot unavailable: ${reason}`,
      snapshot: {},
      warnings: [{ section: "debug_snapshot", reason }],
    };
  }
  return payload;
}

export type OpsSocketHandle = {
  close: () => void;
};

/**
 * Soft WebSocket to live ops hub.
 * Reconnects with backoff while open; never throws; safe when API is down.
 */
export function connectOps(
  onSnapshot: (data: OpsSnapshot) => void,
  onStatus: (ok: boolean) => void,
): OpsSocketHandle {
  let closed = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let attempt = 0;

  const clearReconnect = () => {
    if (reconnectTimer != null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (closed) return;
    clearReconnect();
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5));
    attempt += 1;
    reconnectTimer = window.setTimeout(open, delay);
  };

  const open = () => {
    if (closed) return;
    clearReconnect();
    try {
      socket = new WebSocket(getWsUrl());
    } catch {
      onStatus(false);
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      attempt = 0;
      onStatus(true);
    };
    socket.onclose = () => {
      onStatus(false);
      socket = null;
      scheduleReconnect();
    };
    socket.onerror = () => {
      onStatus(false);
      try {
        socket?.close();
      } catch {
        /* ignore */
      }
    };
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "snapshot" && payload.data) onSnapshot(payload.data);
      } catch {
        /* ignore malformed frames */
      }
    };
  };

  open();

  return {
    close: () => {
      closed = true;
      clearReconnect();
      onStatus(false);
      try {
        socket?.close();
      } catch {
        /* ignore */
      }
      socket = null;
    },
  };
}
