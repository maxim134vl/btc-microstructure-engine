import type {
  DirectionalContextEpisode,
  MarketStateRegime,
  MarketStateTransition,
  TimelineEvent,
} from "../../types/marketState";

export type MarketStateSelectionType =
  | "market_state_regime"
  | "market_state_transition"
  | "directional_context_episode"
  | "timeline_event";

export type MarketStateSelection =
  | { type: "market_state_regime"; id: string; payload: MarketStateRegime }
  | { type: "market_state_transition"; id: string; payload: MarketStateTransition }
  | { type: "directional_context_episode"; id: string; payload: DirectionalContextEpisode }
  | { type: "timeline_event"; id: string; payload: TimelineEvent };

export function timelineEventKey(event: TimelineEvent, index: number): string {
  return `${event.time}-${event.event_type}-${index}`;
}

export function isMarketStateSelection(
  selection: MarketStateSelection | null,
  type: MarketStateSelectionType,
  id: string,
): boolean {
  return selection?.type === type && selection.id === id;
}

export function selectableSurfaceClass(selected: boolean): string {
  return [
    "cursor-pointer transition",
    selected
      ? "border-ds-accent/45 bg-ds-accent/10 ring-1 ring-inset ring-ds-accent/35"
      : "border-ds-border/45 bg-ds-surface-secondary/40 hover:border-ds-border-strong hover:bg-ds-surface-secondary/70",
  ].join(" ");
}

export function selectableRowClass(selected: boolean): string {
  return [
    "cursor-pointer border-t border-ds-border/35 transition",
    selected ? "bg-ds-accent/10 ring-1 ring-inset ring-ds-accent/35" : "hover:bg-ds-surface-secondary/50",
  ].join(" ");
}

export type ChartViewAction = "fit" | "latest" | "reset";

export interface ChartViewCommand {
  token: number;
  action: ChartViewAction;
}
