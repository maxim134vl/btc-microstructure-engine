# CANONICAL RUNTIME ARCHITECTURE

## PROJECT STATUS

Current architecture is based on a unified behavioral
market state machine.

Legacy cognition systems, mutation layers, and abandoned
predictive abstractions were isolated into archive/.

The active system now focuses on:

- market structure
- liquidity interaction
- behavioral interpretation
- temporal escalation
- feedback-driven context evolution

---

# CANONICAL PIPELINE

live market feed
    ↓
candle geometry
    ↓
volume localization
    ↓
liquidity test recognition
    ↓
defended liquidity detection
    ↓
perception/context integration
    ↓
temporal escalation memory
    ↓
contextual feedback state

---

# ACTIVE RUNTIME

## runtime/

- run_canonical_pipeline.py
- live_engine_runner.py
- realtime_streaming_engine_v1.py

---

# CORE ENGINES

## Structure

- candle_geometry_engine_v2.py
- volume_localization_engine_v2.py
- test_recognition_engine_v1.py
- defended_liquidity_engine_v1.py

## Context

- perception_context_integration_v1.py
- contextual_memory_loader_v2.py
- temporal_context_memory_v1.py

---

# ACTIVE MEMORY FILES

- live_market_feed.parquet
- candle_geometry_v2_memory.parquet
- volume_localization_v2_memory.parquet
- test_recognition_memory.parquet
- defended_liquidity_memory.parquet
- perception_context_integration.parquet
- contextual_memory_state.parquet
- temporal_context_memory.parquet

---

# ARCHIVE

Legacy systems moved into:

- archive/legacy_cognition/
- archive/mutation_legacy/
- archive/reinforcement_legacy/
- archive/predictive_legacy/

These systems are preserved for historical/reference purposes
but are not part of the canonical runtime.

---

# RESEARCH

## research/

Contains:

- replay systems
- backtests
- analysis tools

Research layer is separated from production runtime.

---

# TOOLING

## tools/

Contains:

- debug scripts
- patch utilities

These are not part of the active runtime.

---

# RUNTIME CONVENTIONS

- Runtime scripts are executed from project root.
- Relative parquet paths assume project root execution.
- Canonical architecture is state-machine driven.
- Avoid introducing parallel cognition systems.
- Expand the existing temporal/context architecture
  instead of creating disconnected engines.

---

# CURRENT DEVELOPMENT FOCUS

Current priorities:

1. schema normalization
2. temporal decay/exhaustion logic
3. transition detection
4. behavioral calibration
5. runtime stability
