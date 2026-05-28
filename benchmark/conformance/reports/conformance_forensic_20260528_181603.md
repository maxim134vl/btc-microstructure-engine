# Cognition Conformance Backtest Report

Run ID: `20260528_181603`

## Architecture Conformance Summary

- Cognition health: **DEGRADED** 🔴
- Metrics evaluated: **26**
- Confirmed: **11**
- Failed / drift: **1** / **14**
- Cognition stability: **42.3%**
- Ontology integrity: **75.0%** (INTACT)
- Calibration health: **17.3%**
- Drift severity: **SEVERE**

### Health Scores

- Confidence realism: **0.0%**
- Transition stability: **0.0%**
- Contradiction pressure: **100.0%**
- Drift severity score: **100.0%**

### Drift Signals

- confidence inflation
- narrative degradation
- conformance regression
- transition instability
- ontology fragmentation
- perception drift
- synthesis drift

## Calibration Recommendations

- **[CALIBRATION_COLLAPSE]** Confidence weighting exceeds observed follow-through quality.
  - Evidence: Inverse metric overconfident_rate=100.0% exceeds max 30.0%.
- **[SEVERE_DRIFT]** Initiative detection thresholds likely too sensitive during low volatility.
  - Evidence: Observed 0.0% below minimum 35.0%.
- **[SEVERE_DRIFT]** Transition persistence assumptions diverge from runtime reality.
  - Evidence: Observed 0.0% below minimum 40.0%.
- **[SEVERE_DRIFT]** Synthesis state machine may be overreacting to local noise.
  - Evidence: Observed 0.0% below minimum 35.0%.
- **[SEVERE_DRIFT]** Reasoning bias mapping diverges from market behavior.
  - Evidence: Observed 0.0% below minimum 30.0%.
- **[SEVERE_DRIFT]** Confidence inflation detected — review conviction decomposition weights.
  - Evidence: Observed 100.0% exceeds maximum 35.0%.
- **[SEVERE_DRIFT]** Transition logic producing noisy state flips.
  - Evidence: Observed 0.0% below minimum 35.0%.
- **[SEVERE_DRIFT]** End-to-end cognition chain rarely confirms — review cross-stage wiring.
  - Evidence: Observed 0.0% below minimum 25.0%.
- **[SEVERE_DRIFT]** Perception-to-reasoning handoff diverging from architecture intent.
  - Evidence: Observed 0.0% below minimum 45.0%.
- **[SEVERE_DRIFT]** Integrated confidence exceeds market confirmation quality.
  - Evidence: Observed 0.0% below minimum 40.0%.
- **[SEVERE_DRIFT]** Rolling cognition drift exceeds architectural tolerance.
  - Evidence: Observed 100.0% exceeds maximum 35.0%.
- **[SEVERE_DRIFT]** Architecture assumptions about market confirmation diverge from runtime.
  - Evidence: Observed 0.0% below minimum 30.0%.
- **[SEVERE_DRIFT]** Perception layer failing within integrated validation.
  - Evidence: Observed 0.0% below minimum 30.0%.
- **[SEVERE_DRIFT]** Reasoning layer failing within integrated validation.
  - Evidence: Observed 0.0% below minimum 30.0%.
- **[ONTOLOGY_DEGRADATION]** Ontology fragmentation detected across cognition layers.
  - Evidence: Observed 0.0% below minimum 45.0%.

## Metric Conformance Forensics

--------------------------------------------------

METRIC: climax_density (stage1)

EXPECTED:
Climax events should be rare relative to total cognition events.

OBSERVED:
3.6%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Climax classification thresholds may be too sensitive.

--------------------------------------------------

METRIC: false_positive_rate (stage1)

EXPECTED:
Stage 1 false positives should remain low.

OBSERVED:
12.5%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Perception bias scoring may be miscalibrated for current regime.

--------------------------------------------------

METRIC: initiative_followthrough (stage1)

EXPECTED:
Initiative detection should show medium-high confirmation.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Initiative detection thresholds likely too sensitive during low volatility.

--------------------------------------------------

METRIC: transition_stability (stage1)

EXPECTED:
Auction transition interpretation should remain stable.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Transition persistence assumptions diverge from runtime reality.

--------------------------------------------------

METRIC: market_structure_coherence (stage1)

EXPECTED:
Market structure interpretation should stay coherent.

OBSERVED:
62.5%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Structure classification ontology may be fragmenting.

--------------------------------------------------

METRIC: confirmed_rate (stage1)

EXPECTED:
Overall Stage 1 perception confirmation should be moderate or better.

OBSERVED:
37.5%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Stage 1 perception layer requires calibration review.

--------------------------------------------------

METRIC: climax_confirmation_rate (stage1)

EXPECTED:
Climax events that occur should confirm at reasonable rate.

OBSERVED:
40.0%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Climax threshold or follow-through horizon may need adjustment.

--------------------------------------------------

METRIC: contradiction_frequency (stage1)

EXPECTED:
Contradictions in Stage 1 layer should remain low.

OBSERVED:
12.5%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Perception ontology producing conflicting signals.

--------------------------------------------------

METRIC: confidence_realism (stage2)

EXPECTED:
Confidence should remain moderate and match follow-through.

OBSERVED:
0.0%

RESULT:
CALIBRATION_COLLAPSE

DRIFT:
CALIBRATION_COLLAPSE

CALIBRATION IMPLICATION:
Confidence weighting exceeds observed follow-through quality.

--------------------------------------------------

METRIC: narrative_coherence (stage2)

EXPECTED:
Stage 2 narratives should remain coherent.

OBSERVED:
71.7%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Synthesis narrative construction degrading — review MTF alignment rules.

--------------------------------------------------

METRIC: contradiction_frequency (stage2)

EXPECTED:
Internal reasoning contradictions should remain low.

OBSERVED:
0.0%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Reasoning layer producing contradictory synthesis states.

--------------------------------------------------

METRIC: synthesis_stability (stage2)

EXPECTED:
Synthesis conclusions should remain stable when confirmed.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Synthesis state machine may be overreacting to local noise.

--------------------------------------------------

METRIC: reasoning_accuracy (stage2)

EXPECTED:
Stage 2 reasoning should confirm at moderate rate.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Reasoning bias mapping diverges from market behavior.

--------------------------------------------------

METRIC: confidence_drift (stage2)

EXPECTED:
Confidence drift should remain low.

OBSERVED:
100.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Confidence inflation detected — review conviction decomposition weights.

--------------------------------------------------

METRIC: transition_logic_quality (stage2)

EXPECTED:
Regime transition logic should remain stable.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Transition logic producing noisy state flips.

--------------------------------------------------

METRIC: context_failure_rate (stage2)

EXPECTED:
Context integrity failures should remain rare.

OBSERVED:
0.0%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Stage 2 losing contextual linkage to Stage 1 inputs.

--------------------------------------------------

METRIC: fully_confirmed_rate (integrated)

EXPECTED:
Full cognition chains should confirm end-to-end at meaningful rate.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
End-to-end cognition chain rarely confirms — review cross-stage wiring.

--------------------------------------------------

METRIC: cross_stage_alignment (integrated)

EXPECTED:
Stage 1 perception and Stage 2 reasoning should align.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Perception-to-reasoning handoff diverging from architecture intent.

--------------------------------------------------

METRIC: confidence_realism (integrated)

EXPECTED:
Integrated confidence should remain realistic.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Integrated confidence exceeds market confirmation quality.

--------------------------------------------------

METRIC: ontology_coherence (integrated)

EXPECTED:
Ontology should remain coherent across the cognition chain.

OBSERVED:
0.0%

RESULT:
ONTOLOGY_DEGRADATION

DRIFT:
ONTOLOGY_DEGRADATION

CALIBRATION IMPLICATION:
Ontology fragmentation detected across cognition layers.

--------------------------------------------------

METRIC: cognition_drift_frequency (integrated)

EXPECTED:
Cognition drift signals should remain low.

OBSERVED:
100.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Rolling cognition drift exceeds architectural tolerance.

--------------------------------------------------

METRIC: contradiction_propagation (integrated)

EXPECTED:
Contradictions should not propagate through the chain.

OBSERVED:
0.0%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Contradiction cascade detected — review propagation guards.

--------------------------------------------------

METRIC: narrative_stability (integrated)

EXPECTED:
Integrated narratives should remain stable.

OBSERVED:
71.7%

RESULT:
CONFIRMED

DRIFT:
CONFIRMED

CALIBRATION IMPLICATION:
Narrative degradation across integrated cognition chain.

--------------------------------------------------

METRIC: market_confirmation_rate (integrated)

EXPECTED:
Combined cognition narrative should confirm against market.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Architecture assumptions about market confirmation diverge from runtime.

--------------------------------------------------

METRIC: perception_accuracy (integrated)

EXPECTED:
Stage 1 perception within integrated chains should hold.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Perception layer failing within integrated validation.

--------------------------------------------------

METRIC: reasoning_accuracy (integrated)

EXPECTED:
Stage 2 reasoning within integrated chains should hold.

OBSERVED:
0.0%

RESULT:
SEVERE_DRIFT

DRIFT:
SEVERE

CALIBRATION IMPLICATION:
Reasoning layer failing within integrated validation.
