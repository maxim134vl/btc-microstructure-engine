export type SupportedLocale = "en" | "ru";

export type TranslationParams = Record<string, string | number>;

export type TranslationDictionary = Record<string, unknown>;

export const LOCALE_STORAGE_KEY = "btc-ml-locale";

export const SUPPORTED_LOCALES: SupportedLocale[] = ["en", "ru"];
