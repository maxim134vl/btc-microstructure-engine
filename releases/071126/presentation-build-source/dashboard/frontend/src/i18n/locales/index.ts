import type { SupportedLocale } from "../types";
import { en } from "./en";
import { ru } from "./ru";

export const dictionaries: Record<SupportedLocale, typeof en> = {
  en,
  ru,
};
