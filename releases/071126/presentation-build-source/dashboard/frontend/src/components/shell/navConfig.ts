import type { ThemeMode } from "../../design-system";
import type { NavSymbolId } from "../icons/Symbols";

export type ViewMode = "ops" | "trading" | "statement" | "charts" | "diary" | "market-context";

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
  {id:"market-context",label:"Market Context",href:"#market-context",description:"Native M15 / M30 / H1 / H4 owner chart",icon:"chart",section:"platform",fullBleed:true},
  {
    id: "ops",
    label: "Operational",
    href: "#",
    description: "Runtime health, pipeline, and operational control",
    icon: "operations",
    section: "platform",
  },
  {
    id: "trading",
    label: "Trading State",
    href: "#trading",
    description: "Trading operations and market context",
    icon: "trading",
    section: "platform",
  },
  {
    id: "statement",
    label: "Statement",
    href: "#statement",
    description: "Closed trades in an exchange statement layout",
    icon: "list-doc",
    section: "platform",
  },
  {
    id: "charts",
    label: "Charts",
    href: "#charts",
    description: "Return, equity, and performance charts",
    icon: "chart",
    section: "platform",
  },
  {
    id: "diary",
    label: "Diary",
    href: "#diary",
    description: "Daily results calendar — win rate and return",
    icon: "calendar",
    section: "platform",
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
  "market-context":"Market Context",
  ops: "Operational",
  trading: "Trading State",
  statement: "Statement",
  charts: "Charts",
  diary: "Diary",
};

export const THEME_OPTIONS: Array<{ value: ThemeMode; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

const HASH_VIEWS: Record<string, ViewMode> = {
  "market-context":"market-context",
  trading: "trading",
  statement: "statement",
  charts: "charts",
  diary: "diary",
};

export function viewFromHash(): ViewMode {
  const hash = window.location.hash.replace("#", "");
  return HASH_VIEWS[hash] ?? "ops";
}

export function isFullBleedView(view: ViewMode): boolean {
  return NAV_ITEMS.some((item) => item.id === view && item.fullBleed);
}
