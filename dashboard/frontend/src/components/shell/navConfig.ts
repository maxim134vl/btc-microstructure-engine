import type { ThemeMode } from "../../design-system";
import type { NavSymbolId } from "../icons/Symbols";

export type ViewMode =
  | "ops"
  | "debug"
  | "validation";

export type NavSection = "platform" | "research";

export type NavItem = {
  id: ViewMode;
  label: string;
  href: string;
  description: string;
  icon: NavSymbolId;
  section: NavSection;
  fullBleed?: boolean;
};

/** Flat product navigation — one icon per destination. */
export const NAV_ITEMS: NavItem[] = [
  {
    id: "ops",
    label: "Operations",
    href: "#",
    description: "Runtime health, pipeline, and system activity",
    icon: "operations",
    section: "platform",
  },
  {
    id: "debug",
    label: "Runtime Activity",
    href: "#debug",
    description: "Pipeline activity timeline with raw telemetry inspector",
    icon: "pulse",
    section: "platform",
  },
  {
    id: "validation",
    label: "Validation",
    href: "#validation",
    description: "Cognition validation — quality overview and domain benchmarks",
    icon: "check-shield",
    section: "research",
  },
];

export function getVisibleNavItems(): NavItem[] {
  return NAV_ITEMS;
}

/** @deprecated Use getVisibleNavItems() — kept for callers that iterate sections. */
export const NAV_SECTIONS: Array<{ title: string; items: NavItem[] }> = [
  { title: "Platform", items: NAV_ITEMS.filter((item) => item.section === "platform") },
  { title: "Research", items: NAV_ITEMS.filter((item) => item.section === "research") },
];

export const VIEW_TITLES: Record<ViewMode, string> = {
  ops: "Operations",
  debug: "Runtime Activity",
  validation: "Validation",
};

export const THEME_OPTIONS: Array<{ value: ThemeMode; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

export function viewFromHash(): ViewMode {
  const hash = window.location.hash.replace("#", "");
  if (hash === "debug") return "debug";
  if (hash === "validation") return "validation";
  return "ops";
}

export function isFullBleedView(view: ViewMode): boolean {
  return NAV_ITEMS.some((item) => item.id === view && item.fullBleed);
}
