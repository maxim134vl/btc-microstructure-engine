# Volume Localization Restoration — Phase 3 (Shadow Producer)

**Branch:** `memory/canonical-system`  
**Mode:** research-only shadow producer — no live wiring, no daemons, no process restarts

## Legacy contract (proven)

| Contract item | Legacy value | Candidate / shadow | Match |
|---|---|---|---|
| Input candle source | `candle_structure_memory.parquet` | same | yes |
| Timeframe | M15 (15m candle structure) | M15 only | yes |
| Timestamp semantics | bar open UTC | bar open + derived close=+15m | yes |
| Lookback / retention | append latest; max 5000 | shadow bounded/full read | n/a (shadow) |
| ELV formula | `volume * ratio` (0.5 body / 0.7 wick) | same `@8fbde36` | yes |
| Concentration | `elv / (volume + 1e-6)` | same | yes |
| Zone boundaries | wick/body geometry constants | same | yes |
| Null handling | skip bar if required fields NaN | same | yes |
| Output schema | ELV, concentration, behavior, zone_low/high/width, rejections | legacy names preserved + additive aliases | yes |
| Primary key | `timestamp` (dedup) | deterministic `shadow_row_id` | additive |
| Inventory transfer | **absent in v1 orphan schema** | research approximation only | documented |

Source of truth: `git show 8fbde36:src/btc_ml/cognition/volume_localization_engine_v1.py`  
Constants: `config/volume_localization.py` @ `8fbde36`.

## Outputs

```text
data/candidate/volume_localization_shadow/
  volume_localization_shadow.parquet
  volume_localization_shadow_status.json
  volume_localization_shadow_cycles.jsonl
  volume_localization_shadow_comparison.parquet
```

## Runner

```bash
PYTHONPATH=. python scripts/research/run_volume_localization_shadow.py --limit 256
PYTHONPATH=. python scripts/research/run_volume_localization_shadow.py \
  --limit 256 --watch-natural-bars 3 --timeout-s 1200 --poll-s 15
```

## Non-goals (this phase)

- No wiring into auction / reinforcement / probabilistic / runtime cognition
- No context refresher / manager / trader changes
- No persistent daemon
- No live cognition writes
