import type { SupportedLocale } from "./types";
import { LOCALE_STORAGE_KEY } from "./types";

export function detectBrowserLocale(): SupportedLocale {
  if (typeof navigator === "undefined") return "en";
  const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const lang of languages) {
    const normalized = lang.toLowerCase();
    if (normalized.startsWith("ru")) return "ru";
    if (normalized.startsWith("en")) return "en";
  }
  return "en";
}

export function readStoredLocale(): SupportedLocale | null {
  try {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored === "en" || stored === "ru") return stored;
  } catch {
    /* ignore */
  }
  return null;
}

export function resolveInitialLocale(): SupportedLocale {
  return readStoredLocale() ?? detectBrowserLocale();
}
