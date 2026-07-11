import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Optional same-origin proxy. Default frontend talks to :8080 directly (CORS)
// so offline API does not spam Vite with ECONNREFUSED.
const apiProxyTarget = process.env.DASHBOARD_API_PROXY_TARGET ?? "http://127.0.0.1:8080";
const wsProxyTarget = process.env.DASHBOARD_WS_PROXY_TARGET ?? "ws://127.0.0.1:8080";
const enableApiProxy =
  process.env.DASHBOARD_USE_VITE_PROXY === "1" || process.env.DASHBOARD_ENABLE_API_PROXY === "1";

export default defineConfig({
  envPrefix: ["VITE_", "DASHBOARD_"],
  plugins: [react()],
  server: {
    port: 5173,
    proxy: enableApiProxy
      ? {
          "/api": apiProxyTarget,
          "/ws": { target: wsProxyTarget, ws: true },
          "/health": apiProxyTarget,
        }
      : undefined,
  },
});
