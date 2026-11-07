function parseEnvFlag(value: string | undefined, defaultValue: boolean): boolean {
  if (value === undefined || value === "") return defaultValue;
  const normalized = value.trim().toLowerCase();
  if (normalized === "true" || normalized === "1" || normalized === "yes") return true;
  if (normalized === "false" || normalized === "0" || normalized === "no") return false;
  return defaultValue;
}

/** When false (default), experimental research modules are hidden from sidebar navigation. */
export const DASHBOARD_EXPERIMENTAL_MODULES = parseEnvFlag(
  import.meta.env.DASHBOARD_EXPERIMENTAL_MODULES,
  false,
);
