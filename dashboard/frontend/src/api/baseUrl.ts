/**
 * Dashboard API base URL resolution.
 *
 * Default: talk directly to the ops monitor on :8080 (CORS-enabled).
 * This avoids Vite proxy ECONNREFUSED spam when the API is offline.
 *
 * Override with VITE_DASHBOARD_API_BASE / VITE_DASHBOARD_WS_URL, or set
 * DASHBOARD_USE_VITE_PROXY=1 and use relative /api + /ws via vite.config.ts.
 */

function trimSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export function useViteProxy(): boolean {
  return import.meta.env.DASHBOARD_USE_VITE_PROXY === "1" || import.meta.env.DASHBOARD_ENABLE_API_PROXY === "1";
}

export function getApiBase(): string {
  const fromEnv = import.meta.env.VITE_DASHBOARD_API_BASE || import.meta.env.DASHBOARD_API_BASE;
  if (fromEnv) return trimSlash(String(fromEnv));
  if (useViteProxy()) return "/api/v1";
  return "http://127.0.0.1:8080/api/v1";
}

export function getWsUrl(): string {
  const fromEnv = import.meta.env.VITE_DASHBOARD_WS_URL || import.meta.env.DASHBOARD_WS_URL;
  if (fromEnv) return String(fromEnv);
  if (useViteProxy()) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}/ws/live`;
  }
  return "ws://127.0.0.1:8080/ws/live";
}
