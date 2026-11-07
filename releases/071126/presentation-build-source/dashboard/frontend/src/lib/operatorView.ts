/**
 * Operator view model — maps existing snapshot fields to severity descriptors.
 * No new analytics; pure information architecture layer.
 */

import type { HealthLevel, LiveSnapshot, TimeframeState } from "../types";

export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";
export type Descriptor =
  | "HEALTHY"
  | "STABLE"
  | "DEGRADED"
  | "ESCALATING"
  | "DIVERGING"
  | "ALIGNED"
  | "FRAGILE"
  | "NORMAL"
  | "LOW"
  | "MODERATE"
  | "HIGH"
  | "CRITICAL"
  | "LIVE"
  | "STALE"
  | "OFFLINE"
  | "ACTIVE"
  | "WAITING"
  | "UNKNOWN";

export interface OperatorAlert {
  severity: AlertSeverity;
  message: string;
  source: string;
}

export interface RibbonChip {
  key: string;
  label: string;
  value: string;
  level: HealthLevel;
}

export interface BehavioralNarrative {
  regime: string;
  d1StructuralBias: string;
  activeOntology: string;
  auctionState: string;
  contradictions: Descriptor;
  reinforcement: Descriptor;
  transitionRisk: Descriptor;
  runtimeStability: Descriptor;
  entropyState: string;
  cognitionStability: Descriptor;
}

export interface MtfAlignmentView {
  hierarchy: TimeframeState[];
  d1: TimeframeState | null;
  tactical: TimeframeState[];
  agreement: Descriptor;
  propagation: Descriptor;
  divergence: Descriptor;
  alignmentStrength: Descriptor;
}

export interface OperatorView {
  ribbon: RibbonChip[];
  narrative: BehavioralNarrative;
  mtf: MtfAlignmentView;
  alerts: OperatorAlert[];
  feedAgeSeconds: number | null;
  pipelineLatencySeconds: number | null;
}

const TF_ORDER = ["D1", "H4", "H1", "M30", "M15"];

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function str(value: unknown, fallback = "UNKNOWN"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function levelFromHealth(health?: HealthLevel): HealthLevel {
  return health ?? "YELLOW";
}

function scoreSeverity(value: number, warn: number, crit: number): HealthLevel {
  if (value >= crit) return "RED";
  if (value >= warn) return "YELLOW";
  return "GREEN";
}

function describeContradiction(unresolved: number, escalation: number): Descriptor {
  if (unresolved >= 0.75 || escalation >= 0.6) return "ESCALATING";
  if (unresolved >= 0.4 || escalation >= 0.3) return "MODERATE";
  return "LOW";
}

function describeDrift(drift: number, ontologyDrift: number): Descriptor {
  const combined = Math.max(drift, ontologyDrift);
  if (combined >= 0.35) return "DEGRADED";
  if (combined >= 0.15) return "MODERATE";
  return "NORMAL";
}

function describeReinforcement(stability: number): Descriptor {
  if (stability >= 0.85) return "STABLE";
  if (stability >= 0.6) return "ALIGNED";
  return "FRAGILE";
}

function describeTransitionRisk(
  waiting: boolean,
  transitionProb: number,
  transitionState?: string,
): Descriptor {
  if (waiting) return "MODERATE";
  if (transitionProb >= 0.5) return "HIGH";
  if (transitionState && transitionState !== "STABLE_STATE") return "MODERATE";
  return "LOW";
}

function describeRuntime(ops?: LiveSnapshot["runtime_operations"], health?: LiveSnapshot["runtime_health"]): Descriptor {
  if (ops?.failed_engines?.length) return "DEGRADED";
  if (health?.operational_health === "RED" || ops?.operational_health === "RED") return "DEGRADED";
  if (health?.operational_health === "YELLOW" || ops?.operational_health === "YELLOW") return "MODERATE";
  return "HEALTHY";
}

function describeCognition(stability: number, fragility: number): Descriptor {
  if (fragility >= 0.35 || stability < 0.7) return "FRAGILE";
  if (fragility >= 0.15 || stability < 0.85) return "MODERATE";
  return "STABLE";
}

function d1Bias(d1?: TimeframeState | null): string {
  if (!d1) return "UNKNOWN";
  const event = str(d1.latest_event_type, "NORMAL");
  const state = str(d1.auction_state, "NEUTRAL");
  if (event === "NORMAL" && state === "NEUTRAL") return "NEUTRAL STRUCTURE";
  const bias = state.includes("ABSORPTION") || event.includes("ABSORPTION") ? "ABSORPTION" : state.includes("DISTRIBUTION") ? "DISTRIBUTION" : state.replace(/_/g, " ");
  const direction = event.includes("BUYING") ? "BULLISH" : event.includes("SELLING") ? "BEARISH" : "STRUCTURAL";
  return `${direction} ${bias}`.trim();
}

function dominantOntology(snapshot: LiveSnapshot): string {
  const counts = snapshot.ontology?.event_counts_by_timeframe ?? {};
  let bestEvent = "NORMAL";
  let bestCount = 0;
  const alignedTfs: string[] = [];

  for (const tf of ["H4", "H1", "D1", "M30", "M15"]) {
    const tfCounts = counts[tf];
    if (!tfCounts) continue;
    for (const [event, count] of Object.entries(tfCounts)) {
      if (count > 0) alignedTfs.push(tf);
      if (count > bestCount) {
        bestCount = count;
        bestEvent = event;
      }
    }
  }

  if (bestCount === 0) {
    const climactic = str(snapshot.ontology?.climactic_behavior?.climactic_state, "NEUTRAL");
    return climactic === "NEUTRAL" || climactic.includes("NEUTRAL") ? "QUIET / NO DOMINANT EVENT" : climactic.replace(/_/g, " ");
  }

  const tfNote = alignedTfs.length ? ` (${[...new Set(alignedTfs)].slice(0, 3).join("/")} active)` : "";
  return `${bestEvent.replace(/_/g, " ")}${tfNote}`;
}

function computeMtfAlignment(mtf?: LiveSnapshot["mtf_cognition"]): MtfAlignmentView {
  const states = mtf?.timeframe_states ?? [];
  const byTf = Object.fromEntries(states.map((s) => [s.timeframe, s]));
  const hierarchy = TF_ORDER.map((tf) => byTf[tf]).filter(Boolean) as TimeframeState[];
  const d1 = byTf.D1 ?? mtf?.d1_macro_anchor ?? null;
  const tactical = hierarchy.filter((s) => s.timeframe !== "D1");

  const events = hierarchy.map((s) => str(s.latest_event_type, "NORMAL"));
  const uniqueEvents = new Set(events.filter((e) => e !== "NORMAL"));
  const d1Event = str(d1?.latest_event_type, "NORMAL");
  const h4Event = str(byTf.H4?.latest_event_type, "NORMAL");

  let agreement: Descriptor = "ALIGNED";
  let divergence: Descriptor = "LOW";
  if (uniqueEvents.size >= 3) {
    agreement = "DIVERGING";
    divergence = "HIGH";
  } else if (uniqueEvents.size === 2) {
    agreement = "MODERATE";
    divergence = "MODERATE";
  }

  if (d1Event !== "NORMAL" && h4Event !== "NORMAL" && d1Event !== h4Event) {
    divergence = "HIGH";
    agreement = "DIVERGING";
  }

  const propagation: Descriptor =
    d1Event !== "NORMAL" && events.slice(1).some((e) => e === d1Event) ? "ALIGNED" : d1Event === "NORMAL" ? "NORMAL" : "MODERATE";

  const alignmentStrength: Descriptor =
    agreement === "ALIGNED" ? "STABLE" : agreement === "DIVERGING" ? "FRAGILE" : "MODERATE";

  return { hierarchy, d1, tactical, agreement, propagation, divergence, alignmentStrength };
}

function buildAlerts(snapshot: LiveSnapshot, view: Partial<OperatorView>): OperatorAlert[] {
  const alerts: OperatorAlert[] = [];

  for (const item of snapshot.runtime_health?.alerts ?? []) {
    alerts.push({
      severity: item.severity === "RED" ? "CRITICAL" : "WARNING",
      message: `${item.type}${item.file ? `: ${item.file}` : ""}`,
      source: "runtime_health",
    });
  }

  if (snapshot.runtime_operations?.failed_engines?.length) {
    alerts.push({
      severity: "CRITICAL",
      message: `Failed engines: ${snapshot.runtime_operations.failed_engines.join(", ")}`,
      source: "pipeline",
    });
  }

  if (snapshot.runtime_operations?.state_transition_waiting) {
    alerts.push({
      severity: "WARNING",
      message: "State transition deferred — awaiting second synthesis snapshot",
      source: "state_transition",
    });
  }

  const unresolved = num(snapshot.reinforcement?.unresolved_contradiction_score);
  if (unresolved >= 0.75) {
    alerts.push({
      severity: "CRITICAL",
      message: "Contradiction escalation — unresolved score elevated",
      source: "contradiction",
    });
  } else if (unresolved >= 0.4) {
    alerts.push({
      severity: "WARNING",
      message: "Contradiction pressure building",
      source: "contradiction",
    });
  }

  const drift = num(snapshot.probabilistic_cognition?.latest?.calibration_drift_score);
  const ontologyDrift = num(snapshot.probabilistic_cognition?.latest?.ontology_drift_score);
  if (drift >= 0.35 || ontologyDrift >= 0.35) {
    alerts.push({
      severity: "WARNING",
      message: "Drift spike detected in calibration or ontology layer",
      source: "drift",
    });
  }

  const feedAge = view.feedAgeSeconds;
  if (feedAge !== null && feedAge !== undefined && feedAge > 120) {
    alerts.push({
      severity: feedAge > 300 ? "CRITICAL" : "WARNING",
      message: `Live feed stale (${Math.round(feedAge)}s)`,
      source: "feed",
    });
  }

  const pipelineLatency = view.pipelineLatencySeconds;
  if (pipelineLatency !== null && pipelineLatency !== undefined && pipelineLatency > 30) {
    alerts.push({
      severity: pipelineLatency > 60 ? "CRITICAL" : "WARNING",
      message: `Pipeline latency elevated (${pipelineLatency.toFixed(1)}s)`,
      source: "latency",
    });
  }

  if (view.mtf?.divergence === "HIGH") {
    alerts.push({
      severity: "WARNING",
      message: "D1/H4 or cross-TF severe divergence",
      source: "mtf",
    });
  }

  const severityOrder = { CRITICAL: 0, WARNING: 1, INFO: 2 };
  return alerts.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);
}

export function buildOperatorView(snapshot: LiveSnapshot | null, wsConnected: boolean): OperatorView | null {
  if (!snapshot) return null;

  const ops = snapshot.runtime_operations;
  const health = snapshot.runtime_health;
  const cognition = snapshot.probabilistic_cognition?.latest ?? {};
  const regime = snapshot.regime;
  const reinforcement = snapshot.reinforcement;
  const transitions = snapshot.state_transitions;
  const mtf = computeMtfAlignment(snapshot.mtf_cognition);

  const feedWrite = ops?.last_parquet_writes?.find((w) => w.file.includes("live_market_feed"));
  const feedAgeSeconds = feedWrite?.age_seconds ?? null;
  const feedLevel: HealthLevel =
    feedAgeSeconds === null ? "YELLOW" : feedAgeSeconds > 300 ? "RED" : feedAgeSeconds > 120 ? "YELLOW" : "GREEN";

  const durations = (ops?.engine_execution_order ?? [])
    .map((e) => num(e.duration_s))
    .filter((d) => d > 0);
  const pipelineLatencySeconds = durations.length ? Math.max(...durations) : null;
  const latencyLevel: HealthLevel =
    pipelineLatencySeconds === null
      ? "YELLOW"
      : pipelineLatencySeconds > 60
        ? "RED"
        : pipelineLatencySeconds > 30
          ? "YELLOW"
          : "GREEN";

  const unresolved = num(reinforcement?.unresolved_contradiction_score);
  const escalation = num(reinforcement?.contradiction_escalation_score);
  const drift = num(cognition.calibration_drift_score);
  const ontologyDrift = num(cognition.ontology_drift_score);
  const stability = num(cognition.calibration_stability_score, 1);
  const fragility = num(cognition.semantic_fragility_score);
  const reinfStability = num(reinforcement?.reinforcement_stability_score, 1);

  const contradictionDesc = describeContradiction(unresolved, escalation);
  const driftDesc = describeDrift(drift, ontologyDrift);
  const runtimeDesc = describeRuntime(ops, health);
  const cognitionDesc = describeCognition(stability, fragility);

  const narrative: BehavioralNarrative = {
    regime: str(regime?.regime_state ?? regime?.current_regime, "UNKNOWN"),
    d1StructuralBias: d1Bias(mtf.d1),
    activeOntology: dominantOntology(snapshot),
    auctionState: str(transitions?.current_auction_state, "UNKNOWN"),
    contradictions: contradictionDesc,
    reinforcement: describeReinforcement(reinfStability),
    transitionRisk: describeTransitionRisk(
      !!transitions?.waiting_for_second_state,
      num(regime?.regime_transition_probability),
      str(transitions?.latest_transition?.transition_state, "STABLE_STATE"),
    ),
    runtimeStability: runtimeDesc,
    entropyState: str(cognition.entropy_transition_type ?? snapshot.probabilistic_cognition?.entropy_state?.entropy_transition_type, "UNKNOWN"),
    cognitionStability: cognitionDesc,
  };

  const ontologyActive = narrative.activeOntology.includes("QUIET") ? "QUIET" : "ACTIVE";
  const ontologyLevel: HealthLevel = ontologyActive === "ACTIVE" ? "GREEN" : "YELLOW";

  const contradictionLevel = scoreSeverity(unresolved, 0.4, 0.75);
  const driftLevel: HealthLevel = driftDesc === "DEGRADED" ? "RED" : driftDesc === "MODERATE" ? "YELLOW" : "GREEN";

  const ribbon: RibbonChip[] = [
    {
      key: "runtime",
      label: "RUNTIME",
      value: runtimeDesc,
      level: levelFromHealth(ops?.operational_health),
    },
    {
      key: "feed",
      label: "FEED",
      value: feedAgeSeconds === null ? "UNKNOWN" : feedAgeSeconds > 120 ? "STALE" : "LIVE",
      level: feedLevel,
    },
    {
      key: "regime",
      label: "REGIME",
      value: narrative.regime.replace(/_/g, " "),
      level: "GREEN",
    },
    {
      key: "d1",
      label: "D1",
      value: narrative.d1StructuralBias,
      level: mtf.divergence === "HIGH" ? "YELLOW" : "GREEN",
    },
    {
      key: "ontology",
      label: "ONTOLOGY",
      value: ontologyActive,
      level: ontologyLevel,
    },
    {
      key: "contradictions",
      label: "CONTRADICTIONS",
      value: contradictionDesc,
      level: contradictionLevel,
    },
    {
      key: "drift",
      label: "DRIFT",
      value: driftDesc,
      level: driftLevel,
    },
    {
      key: "latency",
      label: "LATENCY",
      value: pipelineLatencySeconds === null ? "—" : `${pipelineLatencySeconds.toFixed(1)}s`,
      level: latencyLevel,
    },
    {
      key: "health",
      label: "HEALTH",
      value: str(health?.operational_health, "UNKNOWN"),
      level: levelFromHealth(health?.operational_health),
    },
    {
      key: "ws",
      label: "WS",
      value: wsConnected ? "LIVE" : "DOWN",
      level: wsConnected ? "GREEN" : "RED",
    },
    {
      key: "pipeline",
      label: "PIPELINE",
      value: ops?.failed_engines?.length ? "DEGRADED" : "CYCLING",
      level: ops?.failed_engines?.length ? "RED" : "GREEN",
    },
  ];

  const partial: Partial<OperatorView> = { feedAgeSeconds, pipelineLatencySeconds, mtf };
  const alerts = buildAlerts(snapshot, partial);

  return { ribbon, narrative, mtf, alerts, feedAgeSeconds, pipelineLatencySeconds };
}

export function descriptorColor(desc: Descriptor): HealthLevel {
  if (["HEALTHY", "STABLE", "ALIGNED", "LOW", "NORMAL", "LIVE", "ACTIVE"].includes(desc)) return "GREEN";
  if (["MODERATE", "WAITING", "FRAGILE", "DEGRADED"].includes(desc)) return "YELLOW";
  if (["HIGH", "CRITICAL", "ESCALATING", "DIVERGING", "STALE", "OFFLINE"].includes(desc)) return "RED";
  return "YELLOW";
}
