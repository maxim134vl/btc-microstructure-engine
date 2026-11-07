import type { TranslationDictionary, TranslationParams } from "./types";

export function getNestedValue(dict: TranslationDictionary, key: string): string | undefined {
  const parts = key.split(".");
  let current: unknown = dict;
  for (const part of parts) {
    if (current == null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "string" ? current : undefined;
}

export function interpolate(template: string, params?: TranslationParams): string {
  if (!params) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => {
    const value = params[name];
    return value == null ? "" : String(value);
  });
}

export function createTranslator(dict: TranslationDictionary) {
  return (key: string, params?: TranslationParams): string => {
    const value = getNestedValue(dict, key);
    if (value == null) return key;
    return interpolate(value, params);
  };
}
