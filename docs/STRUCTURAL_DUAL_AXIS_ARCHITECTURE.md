# Structural Dual-Axis Architecture (Candidate Diagnostics)

## Axes

- **A** `local_auction_state` — unchanged production auction episode
- **B** `structural_direction` ∈ {BULLISH, BEARISH, NEUTRAL, CONFLICTED, UNKNOWN}
- **C** `accepted_price_migration` ∈ {MIGRATING_UP, MIGRATING_DOWN, STATIONARY, ROTATIONAL, UNCERTAIN}
- **D** `structural_relationship` + `economic_qa_code` (diagnostics only)

No single opaque `structural_migration_bias` field; decomposition is retained.

## Decision Matrix (sample)

| Local | Structural | Migration | Relationship | QA |
| --- | --- | --- | --- | --- |
| BALANCE | BULLISH | MIGRATING_UP | LOCALLY_NEUTRAL_STRUCTURALLY_DIRECTIONAL | LOCAL_BALANCE_WITH_BULLISH_STRUCTURE |
| BALANCE | BEARISH | MIGRATING_DOWN | LOCALLY_NEUTRAL_STRUCTURALLY_DIRECTIONAL | LOCAL_BALANCE_WITH_BEARISH_STRUCTURE |
| BALANCE | BULLISH | MIGRATING_DOWN | STRUCTURAL_CONFLICT | LOCAL_BALANCE_WITH_CONFLICTED_STRUCTURE |
| BALANCE | BEARISH | MIGRATING_UP | STRUCTURAL_CONFLICT | LOCAL_BALANCE_WITH_CONFLICTED_STRUCTURE |
| BALANCE | NEUTRAL | STATIONARY | NO_STRUCTURAL_EVIDENCE | LOCAL_BALANCE_STATIONARY |
| ACCEPTANCE_HIGHER | BULLISH | MIGRATING_UP | ALIGNED | LOCAL_STATE_ALIGNED_WITH_BULLISH_STRUCTURE |
| ACCEPTANCE_LOWER | BEARISH | MIGRATING_DOWN | ALIGNED | LOCAL_STATE_ALIGNED_WITH_BEARISH_STRUCTURE |
| LOWER_ABSORPTION | BULLISH | MIGRATING_UP | ALIGNED | LOCAL_STATE_ALIGNED_WITH_BULLISH_STRUCTURE |
| LOWER_ABSORPTION | BEARISH | MIGRATING_DOWN | LOCAL_COUNTERTREND | LOCAL_STATE_COUNTER_TO_BEARISH_STRUCTURE |
| UPPER_DISTRIBUTION | BULLISH | MIGRATING_UP | LOCAL_COUNTERTREND | LOCAL_STATE_COUNTER_TO_BULLISH_STRUCTURE |
| UPPER_DISTRIBUTION | BEARISH | MIGRATING_DOWN | ALIGNED | LOCAL_STATE_ALIGNED_WITH_BEARISH_STRUCTURE |
| UNKNOWN | UNKNOWN | UNCERTAIN | UNKNOWN | NO_STRUCTURAL_EVIDENCE |

## OLD vs CANDIDATE Trading Path

| Layer | Changed trading rows |
| --- | ---: |
| local auction state | 0 |
| cognitive primary state | 0 |
| final context | 0 |
| lifecycle | 0 |
| invalidation | 0 |
| action_allowed / eligibility | 0 |

## July 23 Coverage

`{'bars': 96, 'balance': 66, 'structural_direction': {'BEARISH': 42, 'CONFLICTED': 32, 'BULLISH': 22}, 'migration': {'MIGRATING_DOWN': 43, 'STATIONARY': 33, 'MIGRATING_UP': 20}, 'relationship': {'LOCALLY_NEUTRAL_STRUCTURALLY_DIRECTIONAL': 41, 'STRUCTURAL_CONFLICT': 32, 'LOCAL_COUNTERTREND': 14, 'ALIGNED': 9}, 'qa_codes': {'LOCAL_BALANCE_WITH_CONFLICTED_STRUCTURE': 25, 'LOCAL_BALANCE_WITH_BEARISH_STRUCTURE': 25, 'LOCAL_BALANCE_WITH_BULLISH_STRUCTURE': 16, 'LOCAL_STATE_COUNTER_TO_BEARISH_STRUCTURE': 12, 'LOCAL_STATE_ALIGNED_WITH_BEARISH_STRUCTURE': 5, 'LOCAL_STATE_ALIGNED_WITH_BULLISH_STRUCTURE': 4, 'NO_STRUCTURAL_EVIDENCE': 4, 'BEARISH_MIGRATION_WITHOUT_HTF_CONFIRMATION': 2, 'LOCAL_STATE_COUNTER_TO_BULLISH_STRUCTURE': 2, 'BULLISH_MIGRATION_WITHOUT_HTF_CONFIRMATION': 1}, 'veto_bear_observe': 25, 'trading_unchanged': True}`

## Full-History Symmetry

`{'bullish_days': 10, 'bearish_days': 20, 'bull_mean_struct_bull_share': 0.5187567117850407, 'bear_mean_struct_bear_share': 0.49075383190043836, 'bull_mean_veto': 29.1, 'bear_mean_veto': 23.6}`

Days table: `structural_dual_axis_days.parquet` (30 days with |ret|≥1% & BALANCE≥50%).

## Continuous Segments (no UTC reset)

`[{'hours': 4, 'mean_bear_share': 0.29509988193877984, 'mean_bull_share': 0.33639309980904014, 'symmetry_abs_diff': 0.0412932178702603}, {'hours': 8, 'mean_bear_share': 0.2952401216203303, 'mean_bull_share': 0.3355971360091295, 'symmetry_abs_diff': 0.040357014388799184}, {'hours': 12, 'mean_bear_share': 0.29533839127501915, 'mean_bull_share': 0.3351545796718198, 'symmetry_abs_diff': 0.03981618839680062}, {'hours': 24, 'mean_bear_share': 0.2949435087377605, 'mean_bull_share': 0.3351781450898071, 'symmetry_abs_diff': 0.040234636352046604}]`

## Scientific Benchmarks

- Hamilton filtered: `{'ok': True, 'aic': -66257.53209704341, 'bic': -66216.6123316357, 'means': [-2.1977976014513757e-05, -3.5108596484566557e-05], 'corr_struct_bear_vs_filt': 0.04707403754845344, 'corr_struct_bull_vs_one_minus_filt': 0.05906480046175814, 'note': 'Filtered only for PIT comparison; smoothed not used as feature.'}`
- PELT retrospective: `{'pens': [8.0, 15.0, 30.0], 'n_breaks': {'8.0': 2, '15.0': 2, '30.0': 2}, 'retrospective_only': True}`
- CatBoost challenger: `{'run': True, 'n': 6739, 'walkforward_base_auc_mean': 0.5139518721867266, 'walkforward_full_auc_mean': 0.9502005249865526, 'delta_mean': 0.43624865279982605, 'bootstrap_auc_ci95_last_fold': (0.9499346762118686, 0.9740545301784621), 'symmetry': {'note': 'subset sizes recorded', 'test_mig_down': 227, 'test_mig_up': 180}, 'note': 'Challenger only; labels are PIT-future migration persistence, not trading actions.'}`

## Recommendation

**ACTIVATE_DUAL_AXIS_DIAGNOSTICS_ONLY**

Advisory only. Do not wire into trading eligibility.
Production CONTINUATION=0 and PRICE_GATE=OFF remain.

CatBoost walk-forward delta is large but treated as a **challenger diagnostic only** (features and target share migration family); it is not a license for trading activation. Hamilton filtered correlation with structural labels is weak — axes remain explanatory, not regime substitutes.

## Safety

- CONTINUATION flag OFF; PRICE_GATE OFF
- no production parquet writes; no runtime restart; no ledger/execution; no commit/push

## Tests

```bash
venv/bin/python3 -m pytest tests/test_structural_dual_axis.py -q
```

**17 passed**.
