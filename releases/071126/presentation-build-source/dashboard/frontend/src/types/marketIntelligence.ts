export type MarketStateCategory =
  | "Accumulation"
  | "Distribution"
  | "Continuation"
  | "Exhaustion"
  | "Transition"
  | "Neutral";

export type CognitiveSignal = {
  id: string;
  label: string;
  state: string;
  confidence: number | null;
  detail?: string;
};

export type IntelligenceTimelineEntry = {
  id: string;
  timestamp: string;
  title: string;
  subtitle: string;
  kind: "transition" | "signal" | "event";
  active: boolean;
  eventIndex?: number;
  timelineIndex?: number;
};

export type MarketContextSlice = {
  id: string;
  label: string;
  value: string;
  detail?: string;
};

export type MarketIntelligenceModel = {
  marketState: MarketStateCategory;
  headline: string;
  narrative: string;
  cursorTimestamp: string | null;
  signals: CognitiveSignal[];
  timeline: IntelligenceTimelineEntry[];
  context: MarketContextSlice[];
  propagationSummary: string | null;
};
