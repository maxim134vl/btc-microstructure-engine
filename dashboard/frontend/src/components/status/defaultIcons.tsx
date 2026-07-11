import type { ComponentType } from "react";
import { SymbolEngine, SymbolHeart, SymbolLayers, SymbolWifi } from "../icons/Symbols";
import type { StatusDomain } from "./types";

export const DOMAIN_STATUS_ICON: Record<StatusDomain, ComponentType<{ className?: string }>> = {
  system: SymbolHeart,
  feed: SymbolWifi,
  engine: SymbolEngine,
  validation: SymbolLayers,
  research: SymbolLayers,
};
