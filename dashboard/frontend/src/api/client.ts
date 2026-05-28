import type { LiveSnapshot } from "../types";

const API = "/api/v1";

export async function fetchSnapshot(): Promise<LiveSnapshot> {
  const response = await fetch(`${API}/snapshot`);
  if (!response.ok) throw new Error(`snapshot ${response.status}`);
  return response.json();
}

export function connectLive(onSnapshot: (data: LiveSnapshot) => void, onStatus: (ok: boolean) => void) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  const socket = new WebSocket(`${protocol}://${host}/ws/live`);

  socket.onopen = () => onStatus(true);
  socket.onclose = () => onStatus(false);
  socket.onerror = () => onStatus(false);
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "snapshot") onSnapshot(payload.data);
    } catch {
      /* ignore malformed frames */
    }
  };

  return socket;
}
