# Full Model Architecture Audit

**Repo:** `/Users/fontecrypto/btc-ml`
**Branch:** `memory/canonical-system`
**Mode:** read-only (no production writes, restarts, flag flips, commits)
**Snapshot:** 2026-07-24 ~10:36Z research generation + tip re-read

**Companion artifacts**

| Artifact | Path |
| --- | --- |
| Intent reconstruction | `docs/CANONICAL_MODEL_INTENT_RECONSTRUCTION.md` |
| Invariants | `docs/CANONICAL_MODEL_INVARIANTS.md` |
| Dependency graph (doc) | `docs/FULL_MODEL_DEPENDENCY_GRAPH.md` |
| Dependency graph (json) | `data/research/full_model_dependency_graph.json` |
| Intent×impl matrix | `data/research/full_model_intent_implementation_matrix.csv` |
| Component inventory | `data/research/full_model_component_inventory.json` |
| Dataset inventory | `data/research/full_model_dataset_inventory.csv` |
| State reachability | `data/research/full_model_state_reachability.csv` |
| Field lineage | `data/research/full_model_field_lineage.csv` |
| Collapse points | `data/research/full_model_collapse_points.csv` |
| Gaps | `data/research/full_model_gaps.json` |

**Source priority used:** working code/data > tests > git/docs > narrative.

---

## A. Executive Verdict

**ARCHITECTURE_FRAGMENTED**

The original cognition-first auction interpreter still exists as a working core (OHLCV/delta → volume response/climax → hierarchical MTF scores → probabilistic/reinforcement → shadow context → fail-closed decision → paper). But the system is split across **three write planes**, several intended auction states are **production-unreachable**, structural information **collapses** into OBSERVE via local BALANCE, MTF is **event-sparse** against dense bars, and paper trading **does not consume** the probabilistic plane. Dashboard ops still describes a **24-step** pipeline that is not the live **19-step** runtime.

This is stronger than “partial preservation of a single stack” and weaker than “intent lost.” Intent is recoverable; runtime topology is fragmented.

---

## B. What Is Solid

Do not casually rewrite:

1. **Sensory core:** live M15 feed → `candle_structure` (OHLCV + delta).
2. **Auction perception engines** in Plane A: volume_response, climactic_behavior, convergence, synthesis path.
3. **Hierarchical MTF idea** in stage2 (alignment / persistence / structural_rank / location_bias) — even if sparse.
4. **Probabilistic + reinforcement + decay + meta** pipeline chain as belief machinery.
5. **Shadow lifecycle contract:** episode id, origin, ACTIVE/CHALLENGED/INVALIDATED, invalidation types.
6. **Decision logger fail-closed:** `action_allowed=False` on all 213 logged rows.
7. **Paper controller = simulation only** (no exchange).
8. **Research dual-axis diagnostics** as additive, trading-neutral correction path.

---

## C. Critical Defects (proven S0 / S1)

### S0

No **execution-corruption / wrong-side / look-ahead** defect was newly proven in this pass with fill-level forensic evidence. Prior separate audits (continuation shadow write, paper economics) remain out-of-scope to re-litigate here.

**Reclassified from draft gaps:** dashboard phantom engines are **S1 ops false-confidence**, not S0 execution risk.

### S1 (architectural — proven)

| ID | Defect | Category | Evidence |
| --- | --- | --- | --- |
| S1-1 | CONTINUATION / BUYER_CONTROL / SELLER_CONTROL unreachable under production flags | EXISTS_BUT_UNREACHABLE / DISABLED | reachability count=0; `BTC_ML_CONTINUATION_PROGRESSION` default OFF |
| S1-2 | Local BALANCE → cognitive BALANCE → final OBSERVE collapses HTF/migration | SEMANTICALLY_COLLAPSED | final distribution OBSERVE ~75%; July 23 BALANCE audit |
| S1-3 | MTF / runtime_cognition event-sparse (165) vs ~6.7k bars | WRONG_GRANULARITY | tip 2026-07-23T16:00 while feed tip 10:15 next day |
| S1-4 | Shadow context chain not in CANONICAL_PIPELINE | EXISTS_BUT_NOT_WIRED | pipeline.py 19 vs shadow builders |
| S1-5 | Paper ignores reinforcement/probabilistic conviction | EXISTS_BUT_NOT_CONSUMED | controller consumes lifecycle/decision only |
| S1-6 | OI (and other collectors) disconnected from cognition | EXISTS_BUT_NOT_WIRED | not in Stage1/2 inputs |
| S1-7 | HTF structure / localization / trading-state engines unwired or phantom | EXISTS_BUT_NOT_WIRED / STALE | dashboard 24 vs runtime 19; missing files in ops list |
| S1-8 | Shadow tip lag vs feed/candle (~1h in snapshot) | EXISTS_BUT_STALE (plane sync) | episode/final/lifecycle tip 09:00 vs candle 10:15 |

---

## D. Missing Components

### Missing as current-stage gaps (should exist for declared MVP)

- Production-reachable CONTINUATION progression (currently flag-gated research).
- Explicit wiring contract between Plane A belief and Plane B/C trading (or documented intentional isolation).
- Ops metadata aligned to the real 19-engine pipeline.
- OI (if still “supporting sensory”) either wired or formally deprecated from Stage1 claims.

### Missing as future layers (S4 — not current bugs)

- Manager agent / trader agents / virtual subaccounts.
- Independent per-TF portfolios and simultaneous opposite TF positions.
- Live exchange execution and funding cashflow in paper→live.
- Calibrated probability layer with OOS discipline as trading gate.

---

## E. Disconnected Components

| Component | Status | Notes |
| --- | --- | --- |
| OI collector | EXISTS_BUT_NOT_WIRED | data may exist; cognition unused |
| Intrabar feed | EXISTS_BUT_NOT_CONSUMED | timing/ops, not ontology |
| HTF structure memories | EXISTS_BUT_NOT_WIRED / STALE | referenced in some dependency maps |
| volume_localization | EXISTS_BUT_NOT_WIRED | dashboard still lists |
| market/trading/shadow/economic validation engines | EXISTS_BUT_UNREACHABLE (ops) | in 24-list; not in runtime 19 |
| Dual-axis structural diagnostics | EXISTS_RESEARCH_ONLY | trading deltas 0 |
| Reinforcement → paper | EXISTS_BUT_NOT_CONSUMED | belief unused for fills |
| CONTINUATION progression | EXISTS_BUT_DISABLED | candidate validated KEEP_FEATURE_OFF |

---

## F. Unreachable States

From `full_model_state_reachability.csv`:

| State | Layer | Count | Reachable |
| --- | --- | --- | --- |
| CONTINUATION | auction_episode | 0 | False |
| BUYER_CONTROL | cognitive | 0 | False |
| SELLER_CONTROL | cognitive | 0 | False |

Mechanism: effort FT=YES → ACCEPTED; episode classifier historically required CONTINUED∧FT after ACCEPTANCE; production progression flag OFF → dead path. Candidate restoration produces counts only under flag ON.

Other enumerated states (BALANCE, ACCEPTANCE_*, ABSORPTION/DISTRIBUTION, lifecycle ACTIVE/CHALLENGED/INVALIDATED, final LONG/SHORT/OBSERVE) are reachable with non-zero counts.

---

## G. Semantic Drift

1. **BALANCE:** intended local auction balance → used as global “no direction” → OBSERVE, neutralizing days with clear HTF migration (July 23).
2. **Probability names:** `conviction_probability` etc. are heuristic scores, not calibrated probs.
3. **“Pipeline” in ops:** docs/dashboard lag (17/24) vs code (19).
4. **Context stack restored as shadow MVP** while belief stack lives in Plane A — two “sources of market truth.”
5. **MTF hierarchy** intended continuous structural context; implemented as sparse climax-triggered events held by asof.

---

## H. Data and Freshness

| Layer | Tip (UTC) | Cadence character | Issue |
| --- | --- | --- | --- |
| live feed / candle | 2026-07-24T10:15 | dense M15 | solid |
| shadow episode/final/lifecycle | 2026-07-24T09:00 | dense but **lagging** | plane sync |
| decision log | 2026-07-24T08:45 | sparse events | expected |
| MTF / runtime_cognition | 2026-07-23T16:00 | event-sparse | stale tip vs dense bars; mtime can look fresh |
| probabilistic | 2026-07-24T10:30 | high-freq | can mask upstream staleness |

Defaults of concern: missing/failed directional → BALANCE/UNKNOWN → OBSERVE (fail-open to inaction, fail-closed to edge). Engine SKIPPED freezes tips without trading halt.

Dataset inventory: `data/research/full_model_dataset_inventory.csv` (79 datasets).

---

## I. Multi-Timeframe Architecture

| Question | Finding |
| --- | --- |
| Independent analysis M15/M30/H1/H4/D1? | Partial in-process in stage2; not persisted as full per-TF series |
| Informational hierarchy? | Yes — alignment/persistence/structural_rank |
| Inter-TF reinforcement? | Yes in Plane A multipliers |
| Independent TF trading? | **No** (and not current-stage intent) |
| Opposite simultaneous TF positions? | **No** (S4) |
| Manager / trader agents / subaccounts? | **Absent** (Stage7 roadmap) |
| Collapse point? | C1: multi-TF → one synthesis_state (+ scores) |

**Do not** treat “one dominant TF bot” or “fully independent TF bots” as the current implemented model without evidence — hierarchy is the documented intent; sparse synthesis is the implementation defect.

---

## J. Trading Architecture

What paper actually does:

- Reads **lifecycle / final / decision** (Plane B/C).
- Applies policy gates; simulates orders/fills/positions under `data/research/paper_simulator/`.
- Real execution disabled; decision log `action_allowed=False`.

What it does **not** do:

- Consume reinforcement/probabilistic conviction as primary edge.
- Per-TF or per-agent books.
- Funding-aware perpetual cashflow (deferred).
- Exchange routing.

True trading logic today ≈ **context lifecycle + decision gates + paper simulation**. Probabilistic OS is belief infrastructure, not the fill path.

---

## K. Scientific Validity

| Claim | Status |
| --- | --- |
| Auction effort/result ontology | Operational heuristics with production memory — not a published OOS scientific result |
| CONTINUATION progression | Candidate in-sample effect; validation recommended **KEEP_FEATURE_OFF** pending OOS |
| Dual-axis structural diagnostics | Research-only; trading-neutral |
| Probabilistic “probabilities” | Uncalibrated; saturation risk; discipline flags default off |
| Hamilton/PELT/CatBoost challengers | Research/benchmark tooling — presence ≠ validated edge |
| Economic QA / selective prediction | Framework docs/tools — not proven live gate |

Narrative architecture ≫ validated economic edge for the full stack.

---

## L. Preservation Plan (freeze as working core)

1. Plane A sensory + climax/VR + stage2 score schema.
2. Plane B lifecycle episode identity + origin immutability + invalidation enum.
3. Decision fail-closed contract.
4. Paper no-exchange invariant.
5. Feature-flag OFF baseline (`CONTINUATION_PROGRESSION=0`, PRICE_GATE OFF).
6. Research-only write sinks under `data/research/`.

See `docs/CANONICAL_MODEL_INVARIANTS.md`.

---

## M. Repair Order

```text
S0 data/execution forensics (only if re-proven: fills, look-ahead, ledger)
→ S1 architecture
    1) align ops metadata to 19-step reality
    2) declare or wire Plane A↔B sync cadence
    3) resolve BALANCE/OBSERVE collapse (diagnostics first — dual-axis)
    4) MTF granularity contract (event vs bar)
    5) CONTINUATION only after OOS (keep flag OFF until then)
    6) OI/HTF: wire or deprecate
→ S2 semantics (naming, local vs structural)
→ S3 calibration (conviction scales, discipline)
→ S4 future (agents, subaccounts, live execution)
```

Prefer **reuse** of shadow builders, stage2 scores, and lifecycle over greenfield rewrite.

---

## N. Safety

This audit task performed **only**:

- read of code, docs, git history (via prior agents), production/research parquets;
- write of research artifacts under `docs/` and `data/research/full_model_*`;

and did **not**:

- modify production engines or production memories;
- activate feature flags;
- restart collector/feed/master/visual/paper;
- create trades/orders;
- commit or push.

---

## Intent vs implementation (summary)

See full matrix CSV. Headline statuses:

| Subsystem | Status |
| --- | --- |
| OHLCV + delta | MATCHES_INTENT |
| OI / funding | DISCONNECTED / MISSING(S4) |
| Climax absorption/distribution | MATCHES_INTENT |
| CONTINUATION | UNREACHABLE |
| MTF hierarchy | PARTIAL (WRONG_GRANULARITY) |
| Independent TF trading | MISSING (S4) |
| Probabilistic conviction | PARTIAL (CALIBRATION) |
| Context lifecycle | PARTIAL (shadow plane) |
| BALANCE→OBSERVE | SEMANTIC_DRIFT |
| Decision fail-closed | MATCHES_INTENT |
| Paper before live | PARTIAL (by design) |
| Dashboard pipeline list | DATA_DEFECT |
| Reinforcement→paper | DISCONNECTED |
| Manager/trader agents | MISSING (S4) |

---

## Field lineage / collapse / precedence (pointers)

- Lineage table: `data/research/full_model_field_lineage.csv`
- Collapse: `data/research/full_model_collapse_points.csv` (C1–C7)
- Precedence defect (CONTINUATION shadowed by ACCEPTANCE/FT order): documented in `docs/CONTINUATION_PATH_RESTORATION_AUDIT.md` — not fixed in this task.
- BALANCE migration: `docs/BALANCE_MIGRATION_AUDIT.md`

---

## Inventory scope note

`full_model_component_inventory.json` inventories **runtime-critical planes and major engines**, not every Python file in the monorepo. Dataset inventory covers production/research parquet families observed under `data/` and `benchmark/`. Exhaustive path-by-path listing of all scripts remains open as a follow-on research pass without changing the verdict.
