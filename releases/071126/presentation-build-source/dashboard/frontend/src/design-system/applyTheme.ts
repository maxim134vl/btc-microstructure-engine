import { themes, type ResolvedTheme } from "./themes";

export function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;

  const cssVars = themes[resolved].cssVars;
  for (const [name, value] of Object.entries(cssVars)) {
    root.style.setProperty(name, value);
  }
}

export function resolveTheme(mode: "light" | "dark" | "system"): ResolvedTheme {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return mode;
}
