# BTC AUCTION COGNITION SYSTEM
## Full Architecture & Cognitive Validation Framework

**Document type:** Systems architecture / cognitive infrastructure specification  
**Status:** Living reference — reflects implemented platform as of Phase 4A  
**Audience:** Engineers, researchers, and operators working on behavioral market cognition  
**Scope:** BTC auction cognition pipeline, validation infrastructure, and longitudinal memory systems

---

# 1. INTRODUCTION

Most automated market systems are evaluated—and often designed—as black boxes. Inputs enter; outputs emerge; performance is summarized in a single scalar: profit and loss. When the system works, the mechanism is rarely examined. When it fails, the failure is attributed to “market conditions” rather than to a specific breakdown in perception, reasoning, or calibration.

This is insufficient for any system that claims to interpret market behavior rather than merely react to it.

PnL alone cannot answer fundamental questions:

- Did the system **see** the market correctly?
- Did its **reasoning** follow from what it saw?
- Was its **confidence** proportionate to observed follow-through?
- Did architectural assumptions **drift** over time?
- Did ontology updates **improve** or **degrade** cognition?

The BTC Auction Cognition System exists to address this gap. It is not primarily a prediction engine, a signal generator, or an execution platform. It is a **cognitive market interpretation and validation architecture** built around a specific thesis: markets are behavioral auction processes, and any system that interprets them must be able to observe, validate, and evolve its own cognition.

The distinction between **prediction** and **interpretation** is central. Prediction asks: *What will happen next?* Interpretation asks: *What behavioral structure is present, how confident should we be in that reading, and does subsequent market behavior confirm or refute it?* This platform is built for the second question—and for measuring how well the system answers it over time.

**Behavioral auction cognition** treats price action as the visible surface of a deeper process: initiative, absorption, exhaustion, rotation, continuation deterioration, and regime transition. The system's job is not to collapse this complexity into a trade signal, but to perceive it, reason about it, validate those reasonings against forward market behavior, and preserve the full history—including failures—for longitudinal refinement.

---

# 2. SYSTEM PHILOSOPHY

## 2.1 Market as Behavioral Auction Process

The platform models BTC not as a sequence of independent candles, but as a **multi-timeframe auction** in which participants reveal intent through price, volume, delta, and structural persistence. Behavioral events—climax, stopping, initiative shifts, rotational pressure—are first-class objects, not derived indicators.

## 2.2 Cognition vs Signal Generation

A **signal** is an output optimized for action. **Cognition** is an internal representation of market state with explicit uncertainty, provenance, and testable claims. This system produces cognition artifacts (parquet memory layers, synthesis states, probabilistic regimes) and validates them. It does not treat “BUY/SELL” as the primary output.

## 2.3 Perception vs Reasoning

The architecture enforces a strict separation:

| Layer | Question |
|-------|----------|
| **Stage 1 — Perception** | What behavioral structure does the market exhibit? |
| **Stage 2 — Reasoning** | Given that structure, what synthesis, regime, and confidence assignment is warranted? |

Perception can be correct while reasoning fails. Reasoning can compensate for bad perception (a dangerous artifact). Integrated validation exists precisely to detect these asymmetries.

## 2.4 Why Failed Cognition Is Valuable

Successful interpretations are necessary but not sufficient for system improvement. **Failures, contradictions, confidence inflation, and ontology drift** contain more information about architectural weakness than confirmed events. The longitudinal memory system explicitly preserves toxic and degraded cognition periods—not to train on them blindly, but to ensure future calibration and ML layers learn from **real** cognition history rather than an sanitized subset.

## 2.5 Ontology-Driven Interpretation

Market behavior is classified through a structured **ontology**: volume classes, climax states, effort/result relationships, auction regimes, synthesis states, and transition types. The ontology is not decorative—it governs what the system can perceive, how stages communicate, and what conformance backtests expect. Ontology drift is treated as a first-class failure mode.

## 2.6 Self-Validating Architecture

The platform is designed to **observe itself**:

- Benchmarks compare cognition claims against forward market behavior.
- Conformance backtests compare runtime outputs against architectural specifications.
- Longitudinal memory tracks evolution, regression, and trust classification over time.
- Visual cognition replay lets operators inspect *what the system saw*, not just what it concluded.

Validation is not a post-hoc report—it is infrastructure.

---

# 3. HIGH-LEVEL ARCHITECTURE

The end-to-end pipeline forms a closed loop from raw market ingestion through validated, evolvable cognition:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA ACQUISITION                                   │
│  Collectors → live market feed → parquet persistence                        │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RUNTIME ORCHESTRATION                                │
│  17-engine canonical loop · health monitoring · dependency guards           │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STAGE 1 — MARKET PERCEPTION                               │
│  Structure · volume · climax · stopping · effort/result · transitions       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   STAGE 2 — REASONING & SYNTHESIS                            │
│  MTF synthesis · regime · confidence · contradiction handling               │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  INTEGRATED COGNITION VALIDATION                             │
│  Perception → reasoning → outcome chains · root-cause attribution           │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CONFORMANCE BACKTESTING                                   │
│  Spec vs runtime · drift · calibration audit · cognition health             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 LONGITUDINAL COGNITION MEMORY                                │
│  History · trust classification · toxic separation · evolution tracking     │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    VISUAL COGNITION REPLAY                                   │
│  MTF auction map · cognition flow · behavioral propagation · timeline         │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Architectural hierarchy:**

1. **Runtime** produces cognition memory (parquet layers).
2. **Benchmarks** validate cognition quality against market outcomes.
3. **Conformance** validates runtime behavior against architectural specs.
4. **Memory** preserves all cycles for longitudinal comparison.
5. **Visual replay** renders cognition for human forensic review.

Each layer is independently runnable but designed to compose. The dashboard exposes ops health, validation state, evolution metrics, and visual replay as distinct views on the same underlying artifacts.

---

# 4. RUNTIME INFRASTRUCTURE

## 4.1 Collectors

Market data enters through collector processes that normalize feed input into durable parquet storage. Collectors are **required infrastructure**: without fresh candle and volume structure, no downstream engine can run. Collector health (latency, gaps, schema validity) is monitored independently of cognition quality.

## 4.2 Parquet Persistence

Cognition is persisted as append-oriented **memory parquets**, not ephemeral in-process state. Key layers include:

| Memory layer | Role |
|--------------|------|
| `candle_structure_memory.parquet` | Canonical M15 OHLCV + structural metrics |
| `volume_classification_memory.parquet` | Volume class assignments |
| `volume_response_state.parquet` | Effort/result, climax, participation |
| `auction_synthesis_memory.parquet` | Auction state synthesis |
| `multi_timeframe_synthesis.parquet` | MTF behavioral synthesis |
| `runtime_cognition_memory.parquet` | Stage 2 cognition export |
| `probabilistic_auction_memory.parquet` | Regime probabilities |
| `state_transition_memory.parquet` | Behavioral state transitions |

Parquet is the **contract** between engines, benchmarks, and replay systems. Lineage columns (`lineage_engine`, `lineage_source_parquet`, `lineage_event_timestamp`, `lineage_propagation_timestamp`, `lineage_dependency_chain`) provide end-to-end provenance for cognition propagation paths.

## 4.3 Runtime Orchestration

The canonical runtime executes a **17-step engine loop** via `src/btc_ml/runtime/pipeline.py` (and legacy entry `master_auction_runtime_v1.py`):

**Phase 1 — Structure:** candle structure, volume classification, schema validation, behavioral sequence, volume observer, microstructure candle, volume response.

**Phase 2 — Auction behavior:** climactic behavior, auction convergence, auction synthesis.

**Phase 3 — Stage 2 cognition:** `stage2_cognition_runtime_v1.py` (in-process: climax + MTF synthesis + cognition export), `runtime_cognition_engine_v1.py` (loads cognition into STATE).

**Phase 4 — Reinforcement & probability:** reinforcement, probabilistic auction, decay, state transition, adaptive meta-cognition.

Engines run on a fixed loop interval with dependency guards ensuring downstream steps wait for upstream memory updates.

## 4.4 Engine Supervision & Watchdogs

Runtime health is distinct from cognition health:

| Concern | Monitored by |
|---------|--------------|
| Engine execution | Pipeline step timing, subprocess exit codes |
| Parquet freshness | Staleness detection, missing file alerts |
| Schema integrity | Schema validation engine |
| Alignment integrity | Runtime cognition alignment audit |
| Timestamp drift | `runtime_integrity.compute_drift_metrics()` |

Watchdog semantics are **warning-first**: the system surfaces degradation before silent fallback corrupts cognition.

## 4.5 Operational Dashboard

The ops monitor (`#ops` view) provides NOC-style supervision:

- Engine table with last-run status
- Parquet freshness panel
- Collector health
- Pipeline stability metrics
- Alert grouping and acknowledgment

This dashboard answers: *Is the infrastructure running?* It does not answer: *Is the cognition correct?*

## 4.6 Required vs Optional Infrastructure

| Component | Classification |
|-----------|----------------|
| Collectors, candle structure, volume pipeline | **Required** |
| Stage 2 cognition runtime | **Required** (production direction) |
| Reinforcement, probabilistic, transition engines | **Required** (full loop) |
| Benchmark auto-run hooks | **Optional** (config-gated, 7-day default) |
| Evolution memory auto-run | **Optional** (config-gated) |
| Research dataset builder | **Optional** (offline/batch only) |
| Legacy autonomous runtimes | **Deprecated** |

---

# 5. STAGE 1 — MARKET PERCEPTION LAYER

Stage 1 is responsible for **seeing** the market. It does not assign narrative confidence or regime probabilities—that is Stage 2's domain. Stage 1 produces structured observations about behavioral auction structure.

## 5.1 Responsibilities

| Capability | Description |
|------------|-------------|
| **Market structure perception** | Candle geometry, spread/volume z-scores, structural ranking |
| **Initiative detection** | Delta-directional participation, buyer/seller dominance |
| **Climax detection** | Buying/selling exhaustion impulses via volume/spread percentiles |
| **Stopping activity** | Absorption at extremes, stopping volume events |
| **Effort/result analysis** | Effort-result divergence, absorption vs continuation response |
| **Auction state classification** | Convergence, synthesis, localized behavior |
| **Transition detection** | State machine transitions (excluding stable noise) |
| **Multi-timeframe synthesis input** | M15 native perception feeding MTF aggregation |

## 5.2 How Stage 1 "Sees" the Market

Stage 1 operates on **M15 candle structure memory** as its primary sensory input. Volume classification and volume response engines enrich each timestamp with behavioral labels:

- `volume_class`: climax, stopping, low_participation, etc.
- `volume_event`: STOPPING_VOLUME, ABSORPTION_VOLUME, EXHAUSTION_VOLUME, CONTINUATION_VOLUME
- `climax_state`: BUYING_CLIMAX, SELLING_CLIMAX, NO_CLIMAX
- `effort_result_state`: ABSORPTION_RESPONSE, EFFORT_WITHOUT_RESULT, etc.
- `localized_behavior`: rotation, distribution, accumulation patterns

The auction climax engine (`auction_climax_engine_v1.py`) processes behavioral datasets per timeframe, producing `auction_event_type`, `auction_state`, and cluster resolution semantics.

Stage 1 perception is **event-oriented**, not candle-oriented. The benchmark event extractor deliberately excludes backward-filled synthesis rows and STABLE_STATE transition noise—validation targets native behavioral emissions, not structural padding.

## 5.3 Stage 1 Outputs

Stage 1 writes to multiple memory layers consumed by Stage 2 and benchmarks:

- Enriched candle and volume parquets
- Volume response state
- Auction synthesis and convergence memory
- Inputs to `stage2_cognition_runtime_v1.py`

Stage 1 has no opinion about whether a climax "means reversal." It reports that the behavioral signature occurred.

---

# 6. STAGE 2 — REASONING & SYNTHESIS LAYER

Stage 2 interprets Stage 1 observations in context. Where Stage 1 asks *what happened*, Stage 2 asks *what does it mean within the broader auction structure*.

## 6.1 Responsibilities

| Capability | Description |
|------------|-------------|
| **Contextual interpretation** | Synthesis states (LOCAL_EXHAUSTION, CONTINUATION, etc.) |
| **Probabilistic reasoning** | Regime assignment, conviction decomposition |
| **Regime interpretation** | HIGH_CONVICTION_AUCTION, BALANCED_DISTRIBUTION, etc. |
| **Contradiction handling** | Cross-signal conflict detection and redistribution |
| **Confidence weighting** | Persistence scores, alignment scores, structural rank |
| **Synthesis narratives** | Trigger events linked to synthesis state |
| **Continuation vs reversal logic** | MTF alignment assessment, not binary signals |

## 6.2 How Stage 2 "Thinks"

The Stage 2 runtime (`stage2_cognition_runtime_v1.py`) executes in-process:

1. Reads `candle_structure_memory.parquet`
2. Invokes climax detection per timeframe
3. Builds multi-timeframe synthesis via `multi_timeframe_synthesis_engine.py`
4. Exports `multi_timeframe_synthesis.parquet` and `runtime_cognition_memory.parquet`

Each cognition row carries:

- `synthesis_state` — integrated behavioral reading
- `trigger_event` — originating Stage 1 signal
- `persistence_score` / `alignment_score` — cross-TF coherence
- `structural_rank` — hierarchy weight (LOW → HIGH)
- `location_bias` — positional context (e.g., UPPER_DISTRIBUTION)

Downstream engines consume cognition through `STATE["runtime_cognition"]`:

- **Reinforcement engine** — asymmetry, contradiction redistribution
- **Probabilistic engine** — regime vectors, transition probability, fragility scores
- **Meta-cognition engine** — stability monitoring, ontology stress evaluation

Stage 2 reasoning is **probabilistic, not deterministic**. It assigns degrees of belief subject to calibration validation.

---

# 7. INTEGRATED COGNITION VALIDATION

Integrated validation (`benchmark/integrated/`) tests the **full chain**: Stage 1 perception → Stage 2 reasoning → forward market outcome. It is the primary instrument for detecting cross-stage failures that isolated stage benchmarks miss.

## 7.1 Validation Chain

For each cognition event, the integrated benchmark constructs a chain:

1. **Stage 1 verdict** — Did perception match forward price behavior?
2. **Stage 2 verdict** — Did reasoning match forward behavior and Stage 1 context?
3. **Cross-stage alignment** — Are perception and reasoning coherent?
4. **Confidence realism** — Was stated confidence proportionate to outcome?
5. **Integrated verdict** — End-to-end chain assessment

## 7.2 Failure Patterns A–E

The cross-stage validator (`cross_stage_validator.py`) classifies failures into five patterns:

| Pattern | Condition | Interpretation |
|---------|-----------|----------------|
| **A** | Stage 1 correct, Stage 2 wrong | Reasoning defect — perception was sound |
| **B** | Stage 1 wrong, Stage 2 correct | Compensation artifact — reasoning masked bad perception |
| **C** | Stage 1 weak/correct, Stage 2 overconfident | Confidence pathology / calibration inflation |
| **D** | Stage 1 correct, Stage 2 contradictory | Synthesis instability — signals conflict |
| **E** | Stage 1 wrong, Stage 2 wrong | Ontology/perception collapse — full chain failure |

Pattern **B** is particularly insidious: it can inflate Stage 2 accuracy metrics while hiding Stage 1 degradation. Integrated validation exposes this.

## 7.3 Root-Cause Attribution

Integrated forensic reports assign root causes:

- Perception failure
- Reasoning failure
- Confidence inflation
- Synthesis instability
- Ontology mismatch
- Contradiction cascade
- Context corruption
- Ontology/perception collapse

## 7.4 Key Integrated Metrics

- `fully_confirmed_rate` — End-to-end chain confirmation
- `cross_stage_alignment` — Perception-reasoning coherence
- `confidence_realism` — Confidence vs market follow-through
- `cognition_drift_frequency` — Rolling instability rate
- `ontology_coherence` — Cross-layer semantic consistency
- `contradiction_propagation` — Upstream conflict carried downstream

---

# 8. BENCHMARK SYSTEMS

Benchmarks validate **cognition quality**, not PnL. Each benchmark compares system beliefs against observed forward market behavior over a configurable horizon (default: 7–11 M15 candles).

## 8.1 Benchmark Philosophy

A benchmark event is a **testable claim**:

> "At time T, the system believed X. Over the next N candles, the market did Y. Was X validated?"

This is fundamentally different from a trading backtest, which asks whether a strategy made money. Benchmarks ask whether the system's **interpretation architecture** is honest.

## 8.2 Stage 1 Benchmark

**Location:** `benchmark/stage1/`  
**CLI:** `scripts/run_stage1_benchmark.py`

Validates **market perception** against forward price behavior:

| Target | Question |
|--------|----------|
| Market structure | Did structural readings match follow-through? |
| Initiative | Did delta-directional bias confirm? |
| Climax | Did exhaustion signatures precede expected behavior? |
| Stopping | Did stopping activity correspond to absorption? |
| Effort/result | Did effort-result divergence resolve as expected? |
| Transitions | Were state transitions stable vs noisy? |

**Verdict types:** CONFIRMED, PARTIAL, FAILED, FALSE POSITIVE, LATE DETECTION, EARLY DETECTION.

Native event extraction ensures benchmarks test real emissions, not synthetic row counts.

## 8.3 Stage 2 Benchmark

**Location:** `benchmark/stage2/`  
**CLI:** `scripts/run_stage2_benchmark.py`

Validates **reasoning and synthesis** from `runtime_cognition_memory.parquet`:

| Target | Question |
|--------|----------|
| Reasoning quality | Did synthesis match outcome? |
| Probabilistic validity | Were regime assignments calibrated? |
| Narrative coherence | Did trigger → synthesis chain hold? |
| Contradiction handling | Were contradictions resolved or propagated? |
| Confidence calibration | Was confidence proportionate? |

**Verdict types:** CONFIRMED, PARTIAL, FAILED, OVERCONFIDENT, UNDERCONFIDENT, CONTRADICTORY, NOISY_REASONING, CONTEXT_FAILURE, FALSE_NARRATIVE.

## 8.4 Integrated Benchmark

**Location:** `benchmark/integrated/`  
**CLI:** `scripts/run_integrated_benchmark.py`

Chains Stage 1 and Stage 2 events into unified cognition chains with cross-stage validation, drift analysis, and forensic root-cause reports.

**Verdict types:** FULLY_CONFIRMED, PARTIAL_CONFIRMATION, PERCEPTION_FAILURE, REASONING_FAILURE, CONFIDENCE_FAILURE, CONTRADICTION_FAILURE, FALSE_NARRATIVE, SYNTHESIS_COLLAPSE, CONTEXT_BREAKDOWN, ONTOLOGY_DRIFT.

## 8.5 Auto-Execution

Benchmark auto-run is config-gated (`benchmark/config.yaml`) with a default 7-day interval. The runtime pipeline includes hooks: `_maybe_run_stage1_benchmark()`, `_maybe_run_stage2_benchmark()`, `_maybe_run_integrated_benchmark()`.

---

# 9. CONFORMANCE BACKTESTING

Conformance backtesting (`benchmark/conformance/`) answers a different question than benchmarks:

> **Does the running system behave the way the architecture specification says it should?**

## 9.1 Spec vs Runtime

Expected behavior is defined in YAML specs (`benchmark/specs/`):

- `stage1_expected_behavior.yaml`
- Stage 2 and integrated spec files

Conformance compares **live benchmark outputs** against these specifications metric-by-metric.

## 9.2 Cognition Health States

| State | Meaning |
|-------|--------|
| **STABLE** | Runtime outputs within spec tolerances |
| **DRIFTING** | Metric deviation detected, not yet critical |
| **DEGRADED** | Multiple metrics failed — architectural stress |

## 9.3 Conformance Capabilities

| Capability | Description |
|------------|-------------|
| **Drift detection** | Observed vs expected metric divergence |
| **Calibration auditing** | Confidence realism, overconfidence rates |
| **Ontology integrity** | Cross-layer semantic consistency |
| **Regression analysis** | Post-change improvement vs degradation |
| **Architecture conformance** | Spec pass/fail with calibration recommendations |

## 9.4 Trading Backtest vs Cognition Conformance

| Dimension | Trading backtest | Cognition conformance |
|-----------|------------------|----------------------|
| Primary metric | PnL, Sharpe, drawdown | Cognition stability, calibration health |
| Question | Did we make money? | Does the system behave as designed? |
| Failure mode | Loss | Drift, inflation, ontology degradation |
| Output | Equity curve | Calibration recommendations, drift reports |

Conformance does not optimize execution. It audits whether the cognition architecture remains trustworthy.

---

# 10. LONGITUDINAL COGNITION MEMORY

Benchmark snapshots are insufficient alone. The platform maintains **persistent cognition history** (`benchmark/memory/`) so that every validation cycle becomes a data point in a longitudinal record.

## 10.1 Architecture

| Module | Role |
|--------|------|
| `cognition_history_store.py` | Ingests and persists all layer snapshots |
| `longitudinal_comparator.py` | Current vs previous, rolling average, baseline |
| `regression_detector.py` | IMPROVEMENT / REGRESSION / MIXED after changes |
| `trust_classifier.py` | VERIFIED → TOXIC / ONTOLOGY_COLLAPSE / CALIBRATION_COLLAPSE |
| `toxic_data_separator.py` | Routes events into ML-ready dataset buckets |
| `evolution_tracker.py` | Metric timelines over cycles |
| `calibration_evolution.py` | Calibration change impact memory |
| `ontology_evolution.py` | Ontology integrity timeline |
| `runner.py` | Full evolution cycle orchestration |

## 10.2 What Is Stored

Every benchmark cycle permanently records:

- Stage 1, Stage 2, integrated, and conformance outputs
- Drift analysis and calibration reports
- Contradiction analysis
- Confidence realism history
- Trust classification and regression events

## 10.3 Rolling Evolution

Historical comparison operates across cycles:

- **Previous cycle** — Immediate delta
- **Rolling average** — Smoothed baseline
- **Historical baseline** — Long-run reference
- **Best/worst stability periods** — Context for current state

Example interpretation:

> Week 1: confidence inflation HIGH  
> Week 2: confidence inflation HIGH  
> Week 3: confidence inflation LOWER after calibration update  
> → Calibration improvement CONFIRMED

> Week 4: contradiction frequency explodes  
> → Ontology degradation detected

## 10.4 Trust Classification

| Level | Meaning |
|-------|---------|
| VERIFIED | High stability, STABLE health |
| STABLE | Acceptable cognition quality |
| NOISY | Elevated noise, not yet degraded |
| LOW_TRUST | Drifting with calibration concerns |
| DEGRADED | Significant architectural stress |
| TOXIC | Severe drift + overconfidence |
| ONTOLOGY_COLLAPSE | Ontology degradation detected |
| CALIBRATION_COLLAPSE | Confidence system failure |

## 10.5 Toxic Data Separation

Future ML/LLM systems must not train on all cognition equally. Explicit dataset buckets:

- `validated_cognition/` — High-trust events
- `failed_cognition/` — Degraded readings
- `contradiction_events/` — Conflict-heavy periods
- `drift_epochs/` — Instability windows
- `toxic_periods/` — Severe degradation
- `calibration_history/` — Calibration collapse records
- `regression_history/` — Post-change regressions
- `ontology_health_history/` — Ontology degradation epochs

## 10.6 Auto-Execution

Memory evolution runs on a 7-day interval (config-gated) via `_maybe_run_evolution_memory()` in the runtime pipeline. Full cycle: benchmarks → integrated → conformance → longitudinal update → dataset separation → evolution report.

---

# 11. VISUAL COGNITION SYSTEM

Visual cognition (`visual_cognition/`) renders **market through the system's perception**—not raw candles with indicator overlays.

## 11.1 Scope

Initial timeframe scope: **M15, H1, H4, D1**. Explicitly excluded: M1, M5, tick microstructure, orderflow heatmaps, execution tools.

## 11.2 Components

| Module | Role |
|--------|------|
| `mtf_auction_map.py` | Synchronized four-TF chart data |
| `cognition_replay_builder.py` | Merges cognition memory layers |
| `behavioral_overlay_engine.py` | Initiative zones, climax, stopping, deterioration |
| `propagation_tracker.py` | D1 → H4 → H1 → M15 inheritance chain |
| `stage1_flow_renderer.py` | Step-by-step cognition reasoning chain |
| `cognition_timeline.py` | Replayable event timeline |
| `ontology_transition_renderer.py` | State transition markers |
| `replay_controller.py` | Cursor and event selection |

## 11.3 MTF Auction Map

Four synchronized charts share:

- Common timeline
- Shared replay cursor
- Event synchronization across timeframes

Overlays derive from cognition memory—not directly from raw OHLC.

## 11.4 Behavioral Propagation

The propagation tracker visualizes **behavioral inheritance**:

```
D1: bullish continuation weakening
  → H4: rotational pressure increases
    → H1: initiative deteriorates
      → M15: continuation collapses
```

Each link carries a signal classification: reflected, intensified, collapsed, stable.

## 11.5 Cognition Color Semantics

| Color | Semantics |
|-------|-----------|
| Green | Buyer initiative |
| Red | Seller initiative |
| Yellow | Instability / deterioration |
| Cyan | Absorption / compression |
| Orange | Climax / exhaustion |
| Purple | Contradiction / conflict |
| White | Neutral rotation |
| Grey | Dormant / low confidence |

## 11.6 Data Sources

Visual replay reads from:

- Cognition memory parquets (merged via `merge_asof`)
- Stage 1 benchmark exports
- Longitudinal memory datasets
- Native cognition events (same extraction logic as benchmarks)

The replay answers: *Why did the system believe continuation was weakening?*—not merely *"SELLING_CLIMAX detected."*

---

# 12. DASHBOARD ARCHITECTURE

The dashboard (`dashboard/`) provides four distinct views on the same platform:

## 12.1 Views

| View | Hash | Purpose |
|------|------|---------|
| **Ops Monitor** | `#ops` | Runtime infrastructure health |
| **Validation** | `#validation` | Benchmark and conformance framework |
| **Visual Cognition** | `#visual-cognition` | Stage 1 MTF replay |
| **Debug** | `#debug` | Raw cognition/ontology telemetry |

## 12.2 Ops Monitor

- Engine execution table
- Parquet freshness and staleness
- Collector status
- Pipeline stability
- Alert management

**Question answered:** Is the machine running?

## 12.3 Validation Panel

Sections:

- **Cognition Health** — Conformance-derived STABLE / DRIFTING / DEGRADED banner
- **Stage 1** — Perception validation
- **Stage 2** — Reasoning validation
- **Integrated** — Full cognition chain
- **Conformance** — Architecture backtest
- **Cognition Evolution** — Longitudinal memory metrics

API routes under `/api/v1/validation/*`.

## 12.4 Visual Cognition Tab

Layout:

- **Top:** MTF Auction Map (D1 / H4 / H1 / M15)
- **Right:** Stage 1 Cognition Flow (reasoning chain)
- **Bottom:** Cognition Timeline (event scrubber)

API routes under `/api/v1/visual-cognition/*`.

## 12.5 Runtime Health vs Cognition Health

| Concern | Indicator | View |
|---------|-----------|------|
| Engine crashed | Engine table RED | Ops |
| Parquet stale | Staleness alert | Ops |
| Collector gap | Feed confidence | Ops |
| Overconfidence | Stage 2 benchmark | Validation |
| Ontology drift | Integrated benchmark | Validation |
| Architecture drift | Conformance health | Validation |
| Long-term regression | Evolution memory | Validation |
| Behavioral misreading | Visual replay | Visual Cognition |

A system can be **operationally healthy** and **cognitively degraded** simultaneously. The dashboard separates these concerns deliberately.

---

# 13. DATASETS & ML READINESS

The platform produces structured datasets designed for future ML/LLM-assisted analysis—not autonomous trading.

## 13.1 Dataset Buckets

| Bucket | Contents |
|--------|----------|
| `validated_cognition/` | High-trust confirmed cognition |
| `failed_cognition/` | Degraded or failed readings |
| `contradiction_events/` | Contradiction-heavy events |
| `drift_epochs/` | Instability periods |
| `toxic_periods/` | Severe degradation windows |
| `calibration_history/` | Calibration change records |
| `regression_history/` | Post-change regression events |
| `ontology_health_history/` | Ontology degradation epochs |

## 13.2 ML Readiness Philosophy

Future ML layers should learn from:

- **Failures** — not just successes
- **Drift periods** — when the architecture was wrong
- **Contradictions** — where signals conflicted
- **Toxic cognition** — explicitly separated, not mixed with validated data
- **Calibration evolution** — what changed and whether it helped

Training on confirmed events alone produces overconfident models that inherit the system's blind spots.

## 13.3 Export Artifacts

Each validation layer produces:

- JSON exports (`benchmark/exports/`)
- CSV forensic tables
- Markdown reports (`benchmark/reports/`)
- Visual replays (`benchmark/visuals/`)
- Evolution exports (`benchmark/memory/exports/`)

All artifacts carry run IDs, timestamps, and summary statistics for reproducible research.

---

# 14. CURRENT LIMITATIONS

Intellectual honesty requires acknowledging where the system is early-stage:

## 14.1 Limited Runtime History

The platform has accumulated limited live runtime history. Longitudinal memory infrastructure exists, but statistical confidence in evolution trends requires more cycles than currently recorded.

## 14.2 Immature Ontology

The behavioral ontology is under active refinement. Overlap between states, ambiguous transition boundaries, and cluster resolution edge cases remain open research problems (documented in `docs/ONTOLOGY_*` references).

## 14.3 Calibration Instability

Conformance audits have detected **confidence inflation**—Stage 2 overconfidence rates exceeding architectural tolerance. Calibration is not yet stable across regimes.

## 14.4 Confidence Inflation

Integrated validation Pattern C (confidence pathology) appears with non-trivial frequency. Confidence decomposition weights may not yet reflect observed follow-through quality.

## 14.5 Limited Regime Diversity

Observed runtime data spans a narrow slice of market regimes. Benchmark and conformance metrics may not generalize until broader regime coverage is accumulated.

## 14.6 Early-Stage Cognition Drift

Conformance reports have returned DEGRADED cognition health with elevated drift severity. The system detects this—detection is working—but remediation is not automated.

## 14.7 Longitudinal Evidence Gap

Evolution memory is operational but young. Regression detection, trust classification, and calibration improvement confirmation require sustained 7-day cycles over months to become statistically meaningful.

These limitations are not failures of intent—they define the current research frontier the platform is built to address.

---

# 15. FUTURE ROADMAP

## 15.1 Ontology Refinement

Continued consolidation of overlapping behavioral states, clearer transition boundaries, and reduced semantic entropy across layers.

## 15.2 Calibration Stabilization

Evidence-based adjustment of confidence decomposition weights, validated through longitudinal memory—not ad hoc threshold tuning.

## 15.3 Contradiction Reduction

Improved cross-signal reconciliation in Stage 2 synthesis, with integrated benchmark tracking of contradiction propagation rates over time.

## 15.4 Cognition Evolution

Deepening longitudinal memory: multi-month baselines, seasonality-aware drift detection, architecture change attribution.

## 15.5 Adaptive Calibration

Calibration updates triggered by conformance recommendations, validated by regression detection in evolution memory before acceptance.

## 15.6 ML-Assisted Cognition Analysis

Using separated dataset buckets to train analysis layers that assist—not replace—human forensic review. No autonomous trading pathway.

## 15.7 Deeper Replay Systems

Extended visual cognition: event-to-event animation, cross-benchmark replay, integrated chain visualization.

**Explicit non-goals:** AGI claims, autonomous execution, retail signal packaging, PnL optimization framing.

---

# 16. CONCLUSION

The BTC Auction Cognition System is a **self-validating behavioral cognition research platform**. It treats market interpretation as an engineering problem with measurable quality—not a marketing narrative about predictive AI.

The system's core loop:

1. **Perceive** market behavior through a structured ontology (Stage 1).
2. **Reason** about that behavior probabilistically (Stage 2).
3. **Validate** perception and reasoning against forward market behavior (benchmarks).
4. **Audit** runtime behavior against architectural specifications (conformance).
5. **Remember** all outcomes—including failures—longitudinally (evolution memory).
6. **Visualize** cognition for human forensic review (visual replay).

The platform does not primarily ask whether it would have made money. It asks whether its beliefs about market behavior were honest, calibrated, and architecturally sound—and whether those beliefs are improving or degrading over time.

That question is harder than PnL optimization. It is also the prerequisite for any cognition system that claims to interpret markets rather than merely trade them.

---

## Appendix A: Key Repository Locations

| Path | Contents |
|------|----------|
| `src/btc_ml/runtime/pipeline.py` | Canonical 17-engine loop |
| `benchmark/stage1/` | Stage 1 perception benchmark |
| `benchmark/stage2/` | Stage 2 reasoning benchmark |
| `benchmark/integrated/` | Integrated cognition validation |
| `benchmark/conformance/` | Architecture conformance backtest |
| `benchmark/memory/` | Longitudinal cognition memory |
| `visual_cognition/` | Visual cognition replay engine |
| `dashboard/` | Ops, validation, visual cognition UI |
| `docs/CANONICAL_RUNTIME_MAP.md` | Runtime engine map |
| `docs/RUNTIME_LINEAGE_MAP.md` | Parquet lineage specification |
| `benchmark/config.yaml` | Benchmark and memory configuration |

## Appendix B: Verification Commands

```bash
# Runtime wiring
venv/bin/python3 scripts/verify_phase0a_wiring.py
venv/bin/python3 scripts/verify_phase0b_integrity.py

# Benchmarks
venv/bin/python3 scripts/run_stage1_benchmark.py
venv/bin/python3 scripts/run_stage2_benchmark.py
venv/bin/python3 scripts/run_integrated_benchmark.py
venv/bin/python3 scripts/run_conformance_backtest.py

# Evolution memory
venv/bin/python3 scripts/run_cognition_evolution.py --full-cycle

# Visual cognition
venv/bin/python3 scripts/run_visual_cognition_replay.py
```

---

*Document maintained as part of the BTC-ML research platform. Update when architectural phases change.*
