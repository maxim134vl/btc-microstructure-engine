import type {
  CognitiveSignal,
  IntelligenceTimelineEntry,
  MarketContextSlice,
  MarketIntelligenceModel,
  MarketStateCategory,
} from "../../types/marketIntelligence";
import type {
  CognitionBar,
  CognitionFlowStep,
  PropagationState,
  TimelineEvent,
  VisualCognitionSnapshot,
} from "../../types/visualCognition";

function humanize(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .map((word) => {
      const upper = word.toUpperCase();
      if (upper.length <= 3 && upper === word) return upper;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

function collectCorpus(snapshot: VisualCognitionSnapshot, m15: PropagationState | undefined): string {
  const parts: string[] = [];
  if (snapshot.interpretation) parts.push(snapshot.interpretation);
  if (m15?.synthesis_state) parts.push(String(m15.synthesis_state));
  if (m15?.climax_state) parts.push(String(m15.climax_state));
  if (m15?.trigger_event) parts.push(String(m15.trigger_event));
  m15?.behaviors?.forEach((b) => parts.push(b));
  snapshot.cognition_flow?.forEach((step) => {
    parts.push(step.label, step.detail, step.behavior ?? "");
  });
  return parts.join(" ").toUpperCase();
}

function classifyMarketState(corpus: string, m15: PropagationState | undefined): MarketStateCategory {
  if (/TRANSITION|STATE TRANSITION|TRANSITION_DETERIORATION/.test(corpus)) return "Transition";
  if (/EXHAUSTION|CLIMAX|BUYING CLIMAX|SELLING CLIMAX|STOPPING/.test(corpus)) return "Exhaustion";
  if (/ACCUMULATION|ACCUMUL/.test(corpus)) return "Accumulation";
  if (/DISTRIBUTION|DISTRIBUT/.test(corpus)) return "Distribution";
  if (/CONTINUATION|FOLLOW.?THROUGH|INITIATIVE (BUY|SELL)/.test(corpus) && !/WEAK|COLLAPSE|DETERIORAT/.test(corpus)) {
    return "Continuation";
  }
  const health = m15?.continuation_health;
  if (health != null && health >= 0.65) return "Continuation";
  if (health != null && health < 0.35) return "Transition";
  return "Neutral";
}

function flowStep(snapshot: VisualCognitionSnapshot, match: RegExp): CognitionFlowStep | undefined {
  return snapshot.cognition_flow?.find((step) => match.test(step.label));
}

function participationState(m15: PropagationState | undefined, snapshot: VisualCognitionSnapshot): CognitiveSignal {
  const initiative = m15?.initiative ?? "dormant";
  const rotation = flowStep(snapshot, /ROTATION|NEUTRAL PARTICIPATION/i);
  const buyer = flowStep(snapshot, /BUYER INITIATIVE/i);
  const seller = flowStep(snapshot, /SELLER INITIATIVE/i);

  let state = "Balanced";
  let detail = "Two-sided participation without clear dominance.";
  if (buyer) {
    state = "Buyer-led";
    detail = buyer.detail;
  } else if (seller) {
    state = "Seller-led";
    detail = seller.detail;
  } else if (rotation) {
    state = "Rotational";
    detail = rotation.detail;
  } else if (initiative === "buyer") {
    state = "Buyer-led";
    detail = "Delta alignment favors buyers at this timeframe.";
  } else if (initiative === "seller") {
    state = "Seller-led";
    detail = "Delta alignment favors sellers at this timeframe.";
  } else if (initiative === "neutral") {
    state = "Rotational";
    detail = "Participation is balanced across both sides.";
  } else {
    state = "Quiet";
    detail = "Low directional participation observed.";
  }

  const confidence =
    initiative === "dormant" ? 42 : initiative === "neutral" ? 58 : m15?.continuation_health != null ? Math.round(m15.continuation_health * 100) : 65;

  return { id: "participation", label: "Participation", state, confidence, detail };
}

function persistenceSignal(snapshot: VisualCognitionSnapshot, m15: PropagationState | undefined): CognitiveSignal {
  const synthesis = flowStep(snapshot, /^SYNTHESIS$/i);
  const stable = snapshot.propagation?.inheritance?.every((row) => row.signal === "stable");
  const collapsed = snapshot.propagation?.inheritance?.some((row) => row.signal === "collapsed");

  let state = "Developing";
  let detail = synthesis?.detail?.replace(/^Multi-signal synthesis state:\s*/i, "") ?? "Structure is still forming across timeframes.";
  if (collapsed) {
    state = "Fragile";
    detail = "Lower timeframe structure failed to hold parent context.";
  } else if (stable && (m15?.continuation_health ?? 0) >= 0.55) {
    state = "Established";
    detail = "Behavioral pattern holds consistently across the hierarchy.";
  } else if ((m15?.continuation_health ?? 0.5) < 0.4) {
    state = "Eroding";
    detail = "Prior structure is losing coherence.";
  }

  const confidence = m15?.continuation_health != null ? Math.round(m15.continuation_health * 100) : synthesis ? 62 : 48;

  return { id: "persistence", label: "Persistence", state, confidence, detail: humanize(detail) };
}

function effortResultSignal(snapshot: VisualCognitionSnapshot): CognitiveSignal {
  const step = flowStep(snapshot, /EFFORT/i);
  const detail = step?.detail ?? "Effort and price response remain aligned.";
  const divergent = /DIVERG|WITHOUT RESULT|IMBALANCE/i.test(detail);

  return {
    id: "effort_result",
    label: "Effort vs Result",
    state: divergent ? "Divergent" : step ? humanize(detail.replace(/^Effort-result divergence:\s*/i, "").split(".")[0]) : "Balanced",
    confidence: divergent ? 78 : step ? 68 : 52,
    detail: humanize(detail),
  };
}

function auctionRegimeSignal(snapshot: VisualCognitionSnapshot): CognitiveSignal {
  const step = flowStep(snapshot, /AUCTION REGIME/i);
  const match = snapshot.interpretation?.match(/Regime:\s*([^.]+)/i);
  const raw = match?.[1] ?? step?.detail?.replace(/^Probabilistic regime context:\s*/i, "").split(".")[0];
  const state = raw ? humanize(raw) : "Unclassified";

  return {
    id: "auction_regime",
    label: "Auction Regime",
    state,
    confidence: raw ? 72 : 45,
    detail: step?.detail ? humanize(step.detail) : "Regime context inferred from probabilistic auction memory.",
  };
}

function trendContinuationSignal(m15: PropagationState | undefined, snapshot: VisualCognitionSnapshot): CognitiveSignal {
  const health = m15?.continuation_health ?? 0.5;
  const weak = flowStep(snapshot, /CONTINUATION WEAK|CONTINUATION COLLAP/i);

  let state = "Healthy";
  if (weak?.label.includes("COLLAPSE") || health < 0.25) state = "Broken";
  else if (weak || health < 0.45) state = "Weakening";
  else if (health < 0.65) state = "Moderate";

  return {
    id: "trend_continuation",
    label: "Trend Continuation",
    state,
    confidence: Math.round(health * 100),
    detail: weak?.detail ?? "Follow-through quality relative to current initiative.",
  };
}

function buildSignals(snapshot: VisualCognitionSnapshot, m15: PropagationState | undefined): CognitiveSignal[] {
  return [
    participationState(m15, snapshot),
    persistenceSignal(snapshot, m15),
    effortResultSignal(snapshot),
    auctionRegimeSignal(snapshot),
    trendContinuationSignal(m15, snapshot),
  ];
}

function timelineKind(event: TimelineEvent): IntelligenceTimelineEntry["kind"] {
  const type = (event.type ?? "").toUpperCase();
  const label = (event.label ?? "").toUpperCase();
  if (/TRANSITION|STATE CHANGE/.test(type + label)) return "transition";
  if (/CLIMAX|VOLUME|EFFORT|REGIME|SYNTHESIS|TRIGGER/.test(type + label)) return "signal";
  return "event";
}

function timelineTitle(event: TimelineEvent): string {
  if (event.label) {
    const first = event.label.split(".")[0]?.trim();
    if (first && first.length <= 72) return humanize(first.replace(/^(Trigger event|Volume event|Climax state|Synthesis|Regime|Effort\/result):\s*/i, ""));
  }
  if (event.type) return humanize(event.type);
  if (event.verdict) return humanize(event.verdict);
  return "Market shift";
}

function timelineSubtitle(event: TimelineEvent): string {
  if (event.behaviors?.length) return event.behaviors.map(humanize).join(" · ");
  if (event.verdict) return humanize(event.verdict);
  if (event.severity) return humanize(event.severity);
  return "Cognition update";
}

function buildTimeline(snapshot: VisualCognitionSnapshot): IntelligenceTimelineEntry[] {
  const events = snapshot.timeline ?? [];
  const visible = events.slice(-24);
  const activeTs = snapshot.cursor_timestamp;

  return visible.map((event, index) => ({
    id: `${event.timeline_index ?? index}-${event.timestamp}`,
    timestamp: event.timestamp,
    title: timelineTitle(event),
    subtitle: timelineSubtitle(event),
    kind: timelineKind(event),
    active: event.timestamp === activeTs,
    eventIndex: event.event_index,
    timelineIndex: event.timeline_index,
  }));
}

function cursorBar(section: { bars?: CognitionBar[]; cursor_index?: number | null } | undefined): CognitionBar | undefined {
  if (!section?.bars?.length) return undefined;
  const idx = section.cursor_index;
  if (idx != null && idx >= 0 && idx < section.bars.length) return section.bars[idx];
  return section.bars[section.bars.length - 1];
}

function buildContext(
  snapshot: VisualCognitionSnapshot,
  activeTf: string,
  m15: PropagationState | undefined,
): MarketContextSlice[] {
  const section = snapshot.mtf_map[activeTf];
  const bar = cursorBar(section);
  const volumeLabel = bar?.volume_class_label ? humanize(bar.volume_class_label) : "Normal flow";
  const volumeEvents = bar?.volume_events?.map(humanize).join(", ") || "No notable volume events";

  const chain = snapshot.propagation?.chain ?? [];
  const structure =
    chain.length > 0
      ? chain.map((line) => line.replace(/^[A-Z0-9]+:\s*/, "")).join(" → ")
      : snapshot.propagation?.summary ?? "Structure unavailable";

  const behavior =
    snapshot.interpretation?.split(".").slice(0, 2).join(". ").trim() ||
    snapshot.cognition_flow?.[0]?.detail ||
    "Observing market behavior at the cursor.";

  const health = m15?.continuation_health;
  const probability =
    health != null
      ? `${Math.round(health * 100)}% continuation confidence`
      : auctionRegimeSignal(snapshot).state !== "Unclassified"
        ? auctionRegimeSignal(snapshot).state
        : "Insufficient conviction data";

  return [
    { id: "volume", label: "Volume", value: volumeLabel, detail: volumeEvents },
    { id: "structure", label: "Structure", value: humanize(m15?.synthesis_state ? String(m15.synthesis_state) : "Multi-timeframe"), detail: structure },
    { id: "behavior", label: "Behavior", value: humanize(behavior.split(".")[0] ?? behavior), detail: behavior },
    { id: "probability", label: "Probability", value: probability, detail: "Derived from continuation health and regime context at cursor." },
  ];
}

function buildHeadline(category: MarketStateCategory, m15: PropagationState | undefined): string {
  if (category !== "Neutral") return category;
  const initiative = m15?.initiative;
  if (initiative === "buyer") return "Buyer Initiative";
  if (initiative === "seller") return "Seller Initiative";
  if (initiative === "neutral") return "Rotational Balance";
  return "Quiet Market";
}

function buildNarrative(snapshot: VisualCognitionSnapshot, category: MarketStateCategory): string {
  if (snapshot.interpretation) {
    return snapshot.interpretation.replace(/\b(Trigger event|Volume event|Climax state|Synthesis|Regime|Effort\/result):/gi, "").replace(/\s+/g, " ").trim();
  }
  const lead = snapshot.cognition_flow?.find((s) => s.detail)?.detail;
  if (lead) return lead;
  const summaries: Record<MarketStateCategory, string> = {
    Accumulation: "Participation is building without aggressive distribution.",
    Distribution: "Supply or demand is being released into the auction.",
    Continuation: "Directional structure remains intact across timeframes.",
    Exhaustion: "Impulse energy is fading after climactic participation.",
    Transition: "Market character is shifting between behavioral regimes.",
    Neutral: "No dominant behavioral narrative at the cursor.",
  };
  return summaries[category];
}

export function parseMarketIntelligence(snapshot: VisualCognitionSnapshot, activeTf = "M15"): MarketIntelligenceModel {
  const m15 = snapshot.propagation?.states?.find((s) => s.timeframe === "M15") ?? snapshot.propagation?.states?.slice(-1)[0];
  const corpus = collectCorpus(snapshot, m15);
  const marketState = classifyMarketState(corpus, m15);

  return {
    marketState,
    headline: buildHeadline(marketState, m15),
    narrative: buildNarrative(snapshot, marketState),
    cursorTimestamp: snapshot.cursor_timestamp ?? null,
    signals: buildSignals(snapshot, m15),
    timeline: buildTimeline(snapshot),
    context: buildContext(snapshot, activeTf, m15),
    propagationSummary: snapshot.propagation?.summary ?? null,
  };
}
