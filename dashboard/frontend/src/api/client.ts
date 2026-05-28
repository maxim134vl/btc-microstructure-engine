import type { OpsSnapshot } from "../types/ops";

const API = "/api/v1";

export async function fetchOpsSnapshot(): Promise<OpsSnapshot> {
  const response = await fetch(`${API}/ops/snapshot`);
  if (!response.ok) throw new Error(`ops snapshot ${response.status}`);
  return response.json();
}

export async function fetchDebugSnapshot(): Promise<unknown> {
  const response = await fetch(`${API}/debug/snapshot`);
  if (!response.ok) throw new Error(`debug snapshot ${response.status}`);
  return response.json();
}

export function connectOps(onSnapshot: (data: OpsSnapshot) => void, onStatus: (ok: boolean) => void) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/live`);

  socket.onopen = () => onStatus(true);
  socket.onclose = () => onStatus(false);
  socket.onerror = () => onStatus(false);
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "snapshot") onSnapshot(payload.data);
    } catch {
      /* ignore */
    }
  };

  return socket;
}
