# Parquet Storage Topology

**Phase:** 4B  
**Registry:** `storage/path_registry.py` — single source of truth

---

## Canonical Layout

```
data/
├── live/              # Market feeds, exchange flow
├── cognition/         # Structure, sequence, cognition memory
├── reinforcement/     # Auction synthesis, reinforcement, convergence
├── probabilistic/     # Probabilistic auction, state transitions
├── diagnostics/       # HTF guards, dependency state
├── replay/            # Replay-specific parquet (reserved)
└── artifacts/         # Research / training datasets
```

---

## Resolution Rules

| Operation | Behavior |
|-----------|----------|
| **Read** (`resolve_read`) | Canonical path if exists → legacy root → extra legacy (live feed mirror) → canonical (cold start) |
| **Write** (`resolve_write`) | Always canonical under `data/<category>/` |
| **Migration** | Auto-copy legacy root → canonical on first read (warns once) |

---

## Registered Runtime Parquets

### live/
- `live_market_feed.parquet`
- `multi_exchange_flow.parquet`

### cognition/
- `candle_structure_memory.parquet`
- `volume_classification_memory.parquet`
- `behavioral_sequence_memory.parquet`
- `microstructure_candle_memory.parquet`
- `volume_response_state.parquet`
- `runtime_cognition_memory.parquet`
- `multi_timeframe_synthesis.parquet`
- `climactic_behavior_memory.parquet`
- (+ geometry/localization/flow interaction memories)

### reinforcement/
- `auction_synthesis_memory.parquet`
- `auction_reinforcement_memory.parquet`
- `auction_convergence_memory.parquet`
- `auction_decay_memory.parquet`

### probabilistic/
- `probabilistic_auction_memory.parquet`
- `state_transition_memory.parquet`
- `state_transition_engine_state.parquet`

### diagnostics/
- `htf_structure_memory.parquet`
- `htf_ltf_context_memory.parquet`
- `runtime_dependency_state.parquet`

---

## Legacy Compatibility

| Legacy | Status |
|--------|--------|
| Root `*.parquet` | Read shim — migrated on access |
| `datasets/live/latest.parquet` | Live feed mirror (synced on write) |

**No silent duplication:** writes always target canonical `data/` paths.

---

## API

```python
from storage.path_registry import resolve_read, resolve_write, migrate_all_legacy

path = resolve_read("probabilistic_auction_memory.parquet")
out = resolve_write("candle_structure_memory.parquet")
```

`parquet_utils.safe_read_parquet` and `atomic_parquet_write` auto-resolve registered filenames.

---

## Environment

```bash
export BTC_ML_DATA_ROOT=/path/to/data   # optional override
```
