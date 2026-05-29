# Stage 2.5 — Intermediate Cognition Layer
## Architecture Specification

**Status:** Design specification (no implementation)  
**Version:** 1.0  
**Date:** 2026-05-29  
**Evidence basis:** Behavioral Gap Analysis (2026-05-21 → 2026-05-28), Stage 2 Event Density Audit, Architectural Review

---

## 1. Purpose

Stage 2.5 fills the **cognitive continuity gap** between:

| Layer | Granularity | Role |
|-------|-------------|------|
| **Stage 1** | Per-candle / per-emission perception | What behavioral signals exist? |
| **Stage 2.5** *(new)* | Semi-continuous context evolution | How is the auction narrative changing between major events? |
| **Stage 2** | Event-triggered MTF synthesis | What does this major auction event mean across timeframes? |

### Evidence motivating Stage 2.5

From the Behavioral Gap Analysis (anchor: 2026-05-20 08:30):

- Stage 2 recorded **0 updates** while **47 candidate intermediate events** were observable in structure/probabilistic layers.
- On May 21 alone: **14** continuation-weakening signals, **14** initiative shifts, **10** rotational-pressure signals — none persisted as cognition.
- Probabilistic regime changed **4 times** (May 26–27) while Stage 2 remained frozen on `BUYING_CLIMAX` / `LOCAL_EXHAUSTION`.
- M30 `BUYING_CLIMAX` (2026-05-21 04:00) occurred without Stage 2 synthesis — **alignment degradation** invisible to cognition export.
- State transition engine recorded **100% STABLE_STATE** despite material behavioral change.

Stage 2.5 exists so the platform can **narrate evolution**, not only **annotate climax**.

---

## 2. Design Principles

1. **Event synthesis (Stage 2) remains authoritative for major inflection points.** Stage 2.5 never overrides Tier-1 synthesis at the same timestamp.
2. **Intermediate states are explicitly lower confidence** than Stage 2 event synthesis.
3. **Material change only** — emit when behavioral delta exceeds thresholds; target **12–20 rows/week**, not per-candle flooding.
4. **Provenance required** — every Stage 2.5 row cites Stage 1 inputs and trigger rule ID.
5. **Failures are first-class** — intermediate misreads are benchmarked and stored in evolution memory.
6. **Append with dedup** — unlike current Stage 2 full-replace, Stage 2.5 accumulates timeline history.

---

## 3. Intermediate Cognition States

Each state is a **testable claim** about behavioral evolution, not a verdict on market direction.

### 3.1 Primary states (Tier 2)

| State ID | Label | Meaning |
|----------|-------|---------|
| `IC_CONTINUATION_WEAKENING` | Continuation weakening | Directional effort and price follow-through diverging; trend quality decaying |
| `IC_INITIATIVE_DETERIORATION` | Initiative deterioration | Buyer/seller dominance eroding or flipping without new climax |
| `IC_INITIATIVE_RECOVERY` | Initiative recovery | Directional participation returning after deterioration block |
| `IC_ROTATIONAL_PRESSURE` | Rotational pressure | Two-sided participation; delta sign alternation; stopping/absorption character |
| `IC_ALIGNMENT_DEGRADATION` | Alignment degradation | Higher-TF signal present without Stage 2 synthesis; MTF coherence falling |
| `IC_PRE_EXHAUSTION` | Pre-exhaustion | Climax-class precursors (volume class, spread/volume percentile) without confirmed climax |
| `IC_CONTEXT_DRIFT` | Context drift | Active Stage 2 snapshot materially inconsistent with current Stage 1 context |
| `IC_REGIME_TRANSITION` | Regime transition | Probabilistic auction regime change with cognition linkage |
| `IC_ABSORPTION_DOMINANCE` | Absorption dominance | Effort/result and volume response indicate absorption over continuation |
| `IC_STRUCTURAL_STABILIZATION` | Structural stabilization | Volatility/compression after deterioration; rotation resolving |

### 3.2 Composite / escalation states

Emitted only when primary states persist or co-occur:

| State ID | Label | Escalation from |
|----------|-------|-----------------|
| `IC_CONTINUATION_COLLAPSE` | Continuation collapse | `IC_CONTINUATION_WEAKENING` × 2+ within 4h or effort/price divergence severity HIGH |
| `IC_ONTOLOGY_TENSION` | Ontology tension | Conflicting Stage 1 signals (e.g. buyer delta + stopping volume + seller synthesis context) |
| `IC_COGNITION_STALE` | Cognition stale | Stage 2 anchor age exceeds threshold while Stage 1 shows material change |

### 3.3 State metadata (every row)

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | datetime | Event time (M15 bar close or engine evaluation time) |
| `intermediate_state` | enum | One of above |
| `severity` | LOW / MEDIUM / HIGH | Materiality of change |
| `confidence_score` | float [0,1] | Stage 2.5 confidence (cap below Stage 2 event confidence) |
| `trigger_rule_id` | string | e.g. `T-INIT-01` |
| `stage1_inputs` | object | Snapshot of contributing Stage 1 fields |
| `stage2_anchor_id` | string | Reference to active Stage 2 synthesis row |
| `stage2_anchor_age_bars` | int | M15 bars since last Stage 2 event |
| `supersedes_row_id` | optional | Prior intermediate row this updates |
| `tier` | int | Always `2` (intermediate); Stage 2 events are `1` |
| `lineage_*` | columns | Standard propagation metadata |

---

## 4. Trigger Logic

Triggers evaluate on **M15 evaluation cadence** (each new candle_structure row) and on **cross-layer updates** (probabilistic regime change, volume_response snapshot).

### 4.1 `IC_CONTINUATION_WEAKENING`

**Rule T-CW-01 — Effort/price divergence**

```
IF rolling_delta_5 and rolling_price_change_5 have opposite sign
AND abs(rolling_delta_5) > CONTINUATION_DELTA_MIN (default: 200)
AND abs(rolling_price_change_5) > CONTINUATION_PRICE_MIN (default: 100)
THEN emit IC_CONTINUATION_WEAKENING, severity from magnitude ratio
```

**Rule T-CW-02 — Continuation quality decay**

```
IF volume_response.continuation_quality IN (WEAK, DETERIORATING)
AND prior continuation_quality IN (NEUTRAL, STRONG, HEALTHY)
THEN emit IC_CONTINUATION_WEAKENING
```

**Escalation T-CW-03 → `IC_CONTINUATION_COLLAPSE`**

```
IF IC_CONTINUATION_WEAKENING count >= 2 within 4 hours
OR effort/price divergence severity HIGH for 3 consecutive evaluations
THEN emit IC_CONTINUATION_COLLAPSE
```

*Gap evidence:* 14 divergences on 2026-05-21; anchor BUYING_CLIMAX followed by effort-up/price-down block 06:45–11:15.

---

### 4.2 `IC_INITIATIVE_DETERIORATION` / `IC_INITIATIVE_RECOVERY`

**Rule T-INIT-01 — Initiative MA flip**

```
IF sign(delta_ma_5) != sign(delta_ma_5_previous)
AND abs(delta_ma_5) > INITIATIVE_MA_MIN (default: 100)
AND abs(delta_ma_5_previous) > INITIATIVE_MA_MIN
THEN emit IC_INITIATIVE_DETERIORATION (flip) or IC_INITIATIVE_RECOVERY (recovery after >=3 bar opposite run)
```

**Rule T-INIT-02 — Sustained initiative run exhaustion**

```
IF current_initiative_run_length >= INITIATIVE_RUN_MIN (default: 5 bars)
AND run_delta_sum magnitude declining vs prior run
THEN emit IC_INITIATIVE_DETERIORATION
```

*Gap evidence:* Buyer→seller flip 2026-05-21 02:15; seller run 02:15–03:45 (Δ −4413); buyer recovery 06:45–08:00.

---

### 4.3 `IC_ROTATIONAL_PRESSURE`

**Rule T-ROT-01 — Delta sign alternation**

```
IF sign_flips_in_5_bars >= 3
THEN emit IC_ROTATIONAL_PRESSURE, severity MEDIUM
```

**Rule T-ROT-02 — Stopping / localized distribution**

```
IF volume_class == stopping
OR volume_response.localized_behavior CONTAINS rotation|distribution
OR volume_event IN (STOPPING_VOLUME, ABSORPTION_VOLUME)
THEN emit IC_ROTATIONAL_PRESSURE
```

*Gap evidence:* 10 rotational signals; stopping at 08:45; localized_distribution in volume_response.

---

### 4.4 `IC_ALIGNMENT_DEGRADATION`

**Rule T-ALIGN-01 — Higher-TF event without Stage 2**

```
IF non-NORMAL auction_event on M30 OR H1 OR H4
AND no Stage 2 synthesis row at same or merged timestamp
THEN emit IC_ALIGNMENT_DEGRADATION, severity HIGH
```

**Rule T-ALIGN-02 — Alignment score decay**

```
IF computed_mtf_alignment_score < stage2_anchor.alignment_score - ALIGNMENT_DECAY_MIN (0.15)
AND stage2_anchor_age_bars > 4
THEN emit IC_ALIGNMENT_DEGRADATION
```

*Gap evidence:* M30 BUYING_CLIMAX 2026-05-21 04:00 with no Stage 2 update; anchor alignment already 0.25.

---

### 4.5 `IC_PRE_EXHAUSTION`

**Rule T-PRE-01 — Volume class climax without engine climax**

```
IF volume_class == climax
AND climax_state == NO_CLIMAX (or absent)
THEN emit IC_PRE_EXHAUSTION
```

**Rule T-PRE-02 — Percentile exhaustion proxy**

```
IF volume_percentile_50 >= 0.90 AND spread_percentile_50 >= 0.60
AND auction_event_type == NORMAL
AND range_position extreme (>0.80 buyer side or <0.20 seller side)
THEN emit IC_PRE_EXHAUSTION, severity LOW
```

*Gap evidence:* volume_class climax 2026-05-21 00:45 without Stage 2 synthesis.

---

### 4.6 `IC_CONTEXT_DRIFT`

**Rule T-CTX-01 — Stage 2 anchor vs market drift**

```
IF stage2_anchor_age_bars > STALE_ANCHOR_BARS (default: 12)
AND (price_change_since_anchor > CONTEXT_PRICE_MIN OR initiative_sign_flip_since_anchor)
THEN emit IC_CONTEXT_DRIFT
```

**Rule T-CTX-02 — Cross-layer semantic mismatch**

```
IF stage2.synthesis_state implies direction X
AND stage1_composite_initiative implies direction Y (opposite)
AND condition persists >= 2 evaluations
THEN emit IC_CONTEXT_DRIFT
```

**Rule T-CTX-03 — Structure memory stale**

```
IF candle_structure last_timestamp lag > STRUCTURE_STALE_MINUTES (default: 60)
AND probabilistic or other layers still updating
THEN emit IC_COGNITION_STALE (specialization of context drift)
```

*Gap evidence:* Anchor buyer climax vs seller-leaning May 21 session; candles stopped 2026-05-21 16:15 while prob continued to May 28.

---

### 4.7 `IC_REGIME_TRANSITION`

**Rule T-REG-01 — Probabilistic regime change**

```
IF probabilistic.auction_regime != previous_regime
AND regime persisted >= REGIME_CONFIRM_TICKS (default: 2)
THEN emit IC_REGIME_TRANSITION with previous → current mapping
```

**Rule T-REG-02 — Regime vs Stage 2 mismatch**

```
IF regime IN (UNCERTAIN, ABSORPTION_REGIME)
AND stage2_anchor.trigger_event IN (BUYING_CLIMAX, SELLING_CLIMAX)
AND stage2_anchor_age_bars > 8
THEN emit IC_REGIME_TRANSITION + IC_CONTEXT_DRIFT (co-emitted, linked)
```

*Gap evidence:* HIGH_CONVICTION → UNCERTAIN → ABSORPTION flips May 26–27 while Stage 2 frozen.

---

### 4.8 `IC_ABSORPTION_DOMINANCE`

**Rule T-ABS-01**

```
IF effort_result_state IN (ABSORPTION_RESPONSE, ABSORPTION)
AND continuation_quality IN (NEUTRAL, WEAK)
THEN emit IC_ABSORPTION_DOMINANCE
```

---

### 4.9 `IC_STRUCTURAL_STABILIZATION`

**Rule T-STAB-01**

```
IF prior intermediate state IN (IC_ROTATIONAL_PRESSURE, IC_CONTINUATION_WEAKENING)
AND spread_zscore declining for 5 bars
AND sign_flips_in_5_bars <= 1
THEN emit IC_STRUCTURAL_STABILIZATION (recovery narrative)
```

---

## 5. Persistence Rules

Stage 2.5 uses **append-with-state-change** semantics (similar to `should_persist_state` + `append_state_row`), not Stage 2's full-file replace.

### 5.1 When to persist

| Condition | Action |
|-----------|--------|
| New `intermediate_state` at timestamp | **Append** new row |
| Same state, same severity, within cooldown | **Do not persist** |
| Same state, severity increased | **Append** escalation row; link via `supersedes_row_id` |
| State transition A → B | **Append** B; optionally close A |
| Stage 2 Tier-1 event at same timestamp | **Append** Stage 2 only; Stage 2.5 defers or emits `IC_ALIGNMENT_DEGRADATION` if MTF conflict |

### 5.2 Cooldown windows (defaults)

| State category | Cooldown (M15 bars) |
|----------------|---------------------|
| ROTATIONAL_PRESSURE | 2 |
| CONTINUATION_WEAKENING | 3 |
| INITIATIVE_DETERIORATION | 4 |
| CONTEXT_DRIFT | 6 |
| REGIME_TRANSITION | 8 (regime must be stable) |
| PRE_EXHAUSTION | 6 |
| ALIGNMENT_DEGRADATION | 4 |

Cooldown prevents the 47 raw gap signals from becoming 47 persisted rows; target density achieved via cooldown + dedup.

### 5.3 History retention

| Parameter | Default |
|-----------|---------|
| `MAX_INTERMEDIATE_ROWS` | 520 (~5 weeks at 15–20/week) |
| Retention policy | Rolling tail; archive to `benchmark/memory/datasets/intermediate_cognition/` |
| Immutability | Rows never deleted; superseded rows marked via `supersedes_row_id` |

### 5.4 Stage 2 anchor binding

Every Stage 2.5 row records:

- `stage2_anchor_timestamp` — latest Tier-1 synthesis event ≤ evaluation time
- `stage2_anchor_age_bars` — distance from anchor

When new Stage 2 event occurs, open intermediate chains **close**; new chain begins referencing new anchor.

---

## 6. Deduplication Rules

### 6.1 Primary dedup key

```
dedup_key = (date_hour_bucket, intermediate_state, stage2_anchor_id)
```

Where `date_hour_bucket` = timestamp floored to 1-hour window (configurable).

### 6.2 Suppression rules

| Rule | Behavior |
|------|----------|
| **D-01 Same state within cooldown** | Suppress |
| **D-02 Lower severity replaces higher within bucket** | Keep higher severity only |
| **D-03 Tier-1 Stage 2 at timestamp** | Suppress redundant `IC_PRE_EXHAUSTION` if climax confirmed in Stage 2 |
| **D-04 Co-emitted CONTEXT_DRIFT + REGIME_TRANSITION** | Persist both but link `linked_row_id`; count as 1 toward weekly density target |
| **D-05 STABLE_STATE noise** | Never emit from state_transition alone unless paired with Stage 1 material change |

### 6.3 Cluster merge (hourly)

Within each 1-hour window, if ≥3 intermediate rows of same category:

```
Merge → single row with severity = max(severity)
       confidence = weighted_avg(confidence)
       trigger_rule_id = compound
```

*Expected effect on gap analysis data:* 47 raw → **~12–18** persisted rows/week (matches target).

---

## 7. Confidence Scoring

Stage 2.5 confidence is **explicitly capped below Tier-1 Stage 2 synthesis.**

### 7.1 Base confidence by state

| State | Base confidence |
|-------|-----------------|
| IC_REGIME_TRANSITION | 0.65 |
| IC_ALIGNMENT_DEGRADATION | 0.60 |
| IC_CONTINUATION_COLLAPSE | 0.58 |
| IC_CONTINUATION_WEAKENING | 0.55 |
| IC_INITIATIVE_DETERIORATION | 0.52 |
| IC_PRE_EXHAUSTION | 0.50 |
| IC_ROTATIONAL_PRESSURE | 0.48 |
| IC_CONTEXT_DRIFT | 0.45 |
| IC_ABSORPTION_DOMINANCE | 0.50 |
| IC_STRUCTURAL_STABILIZATION | 0.42 |
| IC_COGNITION_STALE | 0.70 (data integrity; high certainty of staleness) |

**Hard cap:** `confidence_score <= 0.75` for all Tier-2 rows.

**Stage 2 Tier-1 reference:** persistence_score 0.25–0.75 — intermediate rows must not imply equal or greater structural rank.

### 7.2 Adjustments

| Factor | Adjustment |
|--------|--------------|
| Multiple Stage 1 layers agree | +0.08 |
| Single-layer signal only | −0.10 |
| `stage2_anchor_age_bars` > 24 | −0.05 |
| `stage2_anchor_age_bars` > 48 | −0.10 |
| Conflicting Stage 1 signals | −0.15; consider `IC_ONTOLOGY_TENSION` |
| Confirmed by forward benchmark (retrospective) | +0.05 (calibration feedback only) |

### 7.3 Confidence bands (export)

| Band | Range | Label |
|------|-------|-------|
| HIGH | ≥ 0.60 | `INTERMEDIATE_HIGH` |
| MEDIUM | 0.45–0.59 | `INTERMEDIATE_MEDIUM` |
| LOW | < 0.45 | `INTERMEDIATE_LOW` |

Integrated benchmark treats LOW band as **non-decisive** for chain confirmation.

---

## 8. Layer Interactions

### 8.1 Stage 1 → Stage 2.5

**Inputs (read-only):**

| Source parquet | Fields used |
|----------------|-------------|
| `candle_structure_memory` | OHLCV, delta, spread/volume z-scores |
| `volume_classification_memory` | volume_class |
| `volume_response_state` | volume_event, continuation_quality, effort_result_state, localized_behavior, climax_state |
| `auction_synthesis_memory` | auction_state (cross-check) |
| `probabilistic_auction_memory` | auction_regime, conviction_probability, regime_drift_score |
| `state_transition_memory` | transition_state (only non-STABLE with Stage 1 corroboration) |

**Stage 2.5 does not write to Stage 1 layers.**

Evaluation trigger: new M15 candle row **or** probabilistic regime change **or** volume_response update.

---

### 8.2 Stage 2.5 → Stage 2

| Direction | Rule |
|-----------|------|
| Stage 2.5 → Stage 2 | **No write path.** Stage 2 remains event-gated on M15 non-NORMAL climax. |
| Stage 2 → Stage 2.5 | New Tier-1 row **resets anchor**; closes open intermediate chains. |
| Coexistence | Both exported; `runtime_cognition_memory` becomes **timeline**; `STATE["runtime_cognition"]` carries **composite view** (see below). |

**Composite runtime view (recommended):**

```text
STATE["runtime_cognition"] = {
  tier1: latest Stage 2 synthesis row,
  tier2: latest Stage 2.5 intermediate row,
  effective_narrative: tier1 if age < 4 bars else tier2,
  anchor_age_bars: ...
}
```

Downstream probabilistic engine uses `effective_narrative` with explicit tier weighting.

---

### 8.3 Stage 2.5 → Integrated Benchmark

Integrated validation extends chains:

```text
Stage 1 perception → Stage 2.5 intermediate (optional) → Stage 2 synthesis → outcome
```

**New verdict modifiers:**

| Condition | Integrated impact |
|-----------|-------------------|
| Tier-2 only, no Tier-1 | `PARTIAL_CONFIRMATION` ceiling; root cause "intermediate inference" |
| Tier-2 contradicts Tier-1 | Pattern **D** extension: "intermediate-context contradiction" |
| Tier-2 predicted weakening, Tier-1 climax follows within 8 bars | `EARLY_DETECTION` credit |
| Tier-2 false continuation call | Pattern **C** extension: "intermediate confidence inflation" |

**New failure pattern (optional Pattern F):**

> Stage 1 correct, Stage 2.5 detected drift, Stage 2 absent or stale — **intermediate cognition failure to escalate**.

Benchmark stores `intermediate_state` in chain export JSON.

---

### 8.4 Stage 2.5 → Conformance Backtest

Add spec file: `benchmark/specs/stage2_5_expected_behavior.yaml`

| Metric | Expected range (initial) |
|--------|--------------------------|
| `intermediate_events_per_week` | 12–20 |
| `intermediate_to_stage2_ratio` | 3:1 – 7:1 |
| `context_drift_detection_latency_bars` | ≤ 12 after material change |
| `stale_cognition_detection` | 100% when structure lag > 60 min |
| `intermediate_confidence_mean` | 0.45–0.62 |
| `tier2_overconfidence_rate` | ≤ 25% |

Conformance health incorporates:

- **INTERMEDIATE_DENSE** — > 25/week (noise)
- **INTERMEDIATE_SPARSE** — < 8/week (blind)
- **INTERMEDIATE_STALE** — no rows while Stage 1 shows material change

---

### 8.5 Stage 2.5 → Cognition Evolution Memory

**New dataset bucket:** `benchmark/memory/datasets/intermediate_cognition/`

Each evolution cycle ingests:

- Intermediate row counts by state
- Confidence calibration (intermediate vs forward outcome)
- Anchor age at emission
- Tier-2 / Tier-1 coherence ratio

**Trust classification extension:**

| Trust level | Condition |
|-------------|-----------|
| `INTERMEDIATE_RELIABLE` | Tier-2 benchmark confirmation ≥ 55% |
| `INTERMEDIATE_NOISY` | High emission, low confirmation |
| `INTERMEDIATE_BLIND` | Material Stage 1 change, zero Tier-2 detection for > 24h |

Longitudinal comparator adds series:

- `intermediate_emission_rate`
- `context_drift_detection_latency`
- `stale_cognition_incidents`

Regression detector fires if ontology/threshold change alters intermediate density by > ±40% week-over-week.

---

## 9. Export & Storage

### 9.1 Proposed artifacts

| Artifact | Description |
|----------|-------------|
| `intermediate_cognition_memory.parquet` | Primary Tier-2 timeline |
| `intermediate_cognition_index.json` | Anchor chains, weekly counts |
| `runtime_cognition_composite.parquet` | Tier-1 + Tier-2 joined view for dashboard |

### 9.2 Module placement (future)

```text
stage2_5_intermediate_cognition/
  state_definitions.py      # enums, thresholds
  trigger_engine.py         # rule evaluation
  persistence_controller.py # append, cooldown, dedup
  confidence_scorer.py
  runner.py                 # orchestration hook in pipeline
```

Pipeline position: **after Stage 1 memory refresh, before or after Stage 2** (recommended: **after Stage 2** so anchor is current).

---

## 10. Expected Event Density

### 10.1 Target

**12–20 intermediate cognition events per week** (M15 cadence, BTC spot).

### 10.2 Derivation from gap analysis

| Raw signal class | Gap period count | After cooldown + hourly merge (est.) |
|------------------|------------------|-------------------------------------|
| CONTINUATION_WEAKENING | 14 | 4–5 |
| INITIATIVE_DETERIORATION | 14 | 4–5 |
| ROTATIONAL_PRESSURE | 10 | 2–3 |
| REGIME_TRANSITION | 4 | 2–3 |
| CONTEXT_DRIFT | 3 | 1–2 |
| PRE_EXHAUSTION | 1 | 1 |
| ALIGNMENT_DEGRADATION | 1 | 1 |
| **Total** | **47** | **15–20** |

May 21–28 is **atypical**: full structure data for ~1 day, then prob-only for 6 days. A normal week with continuous candles would likely land **14–18** events.

### 10.3 Density guardrails

| Condition | Action |
|-----------|--------|
| < 8 events/week | WARN `INTERMEDIATE_SPARSE`; review thresholds |
| 12–20 events/week | NORMAL |
| > 25 events/week | WARN `INTERMEDIATE_DENSE`; tighten cooldowns |
| > 35 events/week | DEGRADED; disable lowest-severity rotational triggers |

### 10.4 Comparison to current architecture

| Layer | Current density (7-day window) | Post Stage 2.5 |
|-------|-------------------------------|----------------|
| Stage 1 candles | 350 | 350 |
| Stage 1 benchmark events | ~16 | ~16 |
| Stage 2 synthesis | **3** | **3** (unchanged) |
| Intermediate cognition | **0** | **12–20** (target) |

Stage 2.5 adds **~4–6×** cognition timeline density vs Stage 2 alone, without diluting Tier-1 event significance.

---

## 11. Validation Strategy (spec-only)

| Test | Method |
|------|--------|
| Detection latency | Time from material Stage 1 change to first matching Tier-2 row |
| False intermediate rate | Forward price behavior contradicts Tier-2 claim |
| Anchor coherence | Tier-2 rows correctly reference Stage 2 anchor |
| Density stability | Weekly count within 12–20 band across 8+ weeks |
| Escalation accuracy | `IC_CONTINUATION_COLLAPSE` precedes climax within N bars |

---

## 12. Non-Goals

Stage 2.5 does **not**:

- Generate trade signals or execution intent
- Replace Stage 2 event synthesis
- Emit per-candle rows (350/week)
- Modify Stage 1 perception thresholds
- Auto-calibrate thresholds without conformance/evidence cycle

---

## 13. Summary

Stage 2.5 is the **narrative continuity layer** the platform currently lacks. It converts Stage 1's continuous perception into **material, bounded, testable claims** about how auction behavior evolves between major events — exactly the 47-signal gap observed while Stage 2 remained frozen on a May 20 buyer climax.

**Tier-1 (Stage 2):** "What does this climax mean?"  
**Tier-2 (Stage 2.5):** "How is the story changing while we wait for the next climax?"

Together they support integrated validation, conformance, evolution memory, and visual cognition replay without collapsing the distinction between **high-confidence event synthesis** and **intermediate contextual inference**.

---

*Specification only. Implementation requires pipeline hook, parquet schema, benchmark spec, and dashboard integration in separate phases.*
