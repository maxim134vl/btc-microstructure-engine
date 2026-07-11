/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly DASHBOARD_EXPERIMENTAL_MODULES?: string;
  readonly DASHBOARD_ENABLE_API_PROXY?: string;
  readonly DASHBOARD_USE_VITE_PROXY?: string;
  readonly DASHBOARD_API_BASE?: string;
  readonly DASHBOARD_WS_URL?: string;
  readonly VITE_DASHBOARD_API_BASE?: string;
  readonly VITE_DASHBOARD_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
