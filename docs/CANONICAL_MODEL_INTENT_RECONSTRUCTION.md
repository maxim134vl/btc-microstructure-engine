# Canonical Model Intent Reconstruction

Read-only reconstruction of the BTC Auction / Behavioral Cognition Model intent from architecture docs, runtime code, shadow builders, and production evidence.
**Priority:** working code/data > tests > git/docs narrative.

External canon cited by the repo: Stage1/Stage2 architecture notes under Downloads (see `docs/ARCHITECTURE_REFERENCE.md`). In-repo anchors: `docs/BTC_AUCTION_COGNITION_ARCHITECTURE.md`, `docs/CANONICAL_RUNTIME_MAP.md`, `docs/MARKET_CONTEXT_SHADOW_CHAIN.md`.

---

## Thesis (original)

Markets are a **behavioral auction**. Stage 1 perceives effort/result and local auction phenomena; Stage 2 reasons with multi-timeframe hierarchy and probabilistic belief. **Execution is later.** The system is a cognition OS, not a PnL bot.

---

## 3.1 Market data

| Source | Intended | Implemented | Live | Used by cognition | Stored | Status |
| --- | --- | --- | --- | --- | --- | --- |
| OHLCV M15 | Yes | Yes | Yes (`live_market_feed`) | Yes | Yes | IMPLEMENTED_AND_ACTIVE |
| Delta (taker) | Yes | Yes (buy−sell) | Yes | Yes | Yes | IMPLEMENTED_AND_ACTIVE |
| Open interest | Yes (supporting) | Collector exists | Partial | **No** (not in Stage1/2) | Partial | EXISTS_BUT_NOT_WIRED |
| Funding | Later / cashflow | Download scripts | No in cognition | No | Historical pulls | EXISTS_RESEARCH_ONLY / S4 |
| Basis | Not original sensory | Edge/lookup docs | No | Diagnostics only | Research | EXISTS_RESEARCH_ONLY |
| Intrabar | Ops/timing, not ontology | Yes | Yes | Paper/decision clock | Yes | EXISTS_BUT_NOT_CONSUMED (cognition) |
| Volume location | Yes | Engines/memories exist | Stale/partial | Often via deprecated paths | Yes | EXISTS_BUT_STALE / PARTIAL |
| Orderbook / liquidations | Collectors in topology | Collectors present | Supporting | Not Stage1/2 core | Partial | EXISTS_BUT_NOT_WIRED |

---

## 3.2 Auction behavior

| Phenomenon | Producer | Memory | Consumer | Downstream | Reachability |
| --- | --- | --- | --- | --- | --- |
| Effort/result | volume_response / episode builder | VR + episode | synthesis, shadow | cognitive/final | Active |
| Acceptance | shadow `ACCEPTANCE_*` | auction_episode | cognitive→final | LONG/SHORT | Active (shadow) |
| Rejection | rejected price / failed breakout | episode | cognitive | OBSERVE / distribution | Active |
| Continuation | episode CONTINUATION | auction_episode | BUYER/SELLER_CONTROL | LONG/SHORT | **UNREACHABLE** (flag OFF, count=0) |
| Absorption | climax + LOWER_ABSORPTION | VR/MTF/episode | final LONG | Active |
| Distribution | UPPER_DISTRIBUTION | same | final SHORT | Active |
| Exhaustion / climax | climactic + climax engines | climax memories | MTF location | Active |
| Unfinished auction | legacy/research | various | mostly unwired | EXISTS_BUT_NOT_WIRED |
| Trapped participation | narrative in docs | sparse | limited | PARTIAL |
| Inventory transfer | MID_AUCTION_TRANSFER language | MTF location | limited | PARTIAL |
| Directional efficiency | research dual-axis / structure flags | research parquet | diagnostics | EXISTS_RESEARCH_ONLY |
| Balance | episode BALANCE | auction_episode | NEUTRAL→OBSERVE | Active but **semantically collapsed** |
| Auction migration | dual-axis research | research | not trading | EXISTS_RESEARCH_ONLY |

---

## 3.3 Memory types (do not mix)

| Intended family | Reality | Semantics |
| --- | --- | --- |
| Raw market memory | `live_market_feed`, candle_structure | per-bar event/state |
| Behavioral memory | volume_response, climactic, behavioral_sequence | per-bar / sequence |
| Probabilistic memory | probabilistic_auction_memory | rolling heuristic scores |
| Transition memory | state_transition_memory | transition events |
| Meta-cognition | adaptive_meta_cognition_state | latest/meta state |
| Context episode memory | lifecycle_memory + episodes | episode (shadow) |
| Decision memory | context_decision_log | append-only log |
| Learning / toxic cases | `benchmark/memory/` | research longitudinal |
| Reinforcement / decay | reinforcement/* | pipeline memories |

**Shadow vs pipeline:** auction_episode → cognitive → final → lifecycle is a **second plane**, not steps inside `CANONICAL_PIPELINE`.

---

## 3.4 Multi-timeframe model

**Intended:** hierarchical alignment (M15 noise vs H1/H4 structure), structural rank, persistence — **not** independent TF bots.

**Evidence of hierarchy:** `multi_timeframe_synthesis_engine.py`, Stage2 runtime, docs alignment 0.25→1.0.

**Not intended as current stage (S4):** manager agent → trader agents → virtual subaccounts → simultaneous opposite TF portfolios. Mentioned as Stage 7 roadmap in Architecture Note — **MISSING by design for now**, not a regression of a finished feature.

**Granularity defect:** MTF synthesis is **event-sparse** (~165 rows) while bar memories are ~6.7k — continuous asof-join makes sparse events look persistent.

---

## 3.5 Probabilistic layer

| Name | Meaning in docs | Reality | Downstream |
| --- | --- | --- | --- |
| absorption/distribution probability | window counts | heuristic frequencies | regimes / diagnostics |
| conviction_probability | belief degree | counts × cognition multipliers | state_transition / meta |
| persistence / alignment / structural_rank | MTF hierarchy | scores on events | reinforcement |
| entropy / overconfidence | meta | adaptive_meta | limited trading use |
| Calibration / discipline | Phase 1 envelope | flag-gated, default raw | PARTIAL |

These are **not** well-calibrated probabilities. Paper trading does **not** consume them directly.

---

## 3.6 Context and trading chain

**Intended chain (restored mid-2026):**

```text
behavioral state → auction episode → cognitive state → final context
→ lifecycle episode (origin, invalidation) → decision log → paper position
```

**Granularity intended:** single global active context for the restored shadow MVP (not per-TF). Per-TF contexts/positions are future (S4), not proven as abandoned completed work.

**Execution intent:** `action_allowed=False` in decision logger; paper before live; exchange forbidden in bounded controller.

---

## Intent confidence

| Area | Confidence |
| --- | --- |
| Cognition-first auction interpreter | High |
| Hierarchical MTF (not independent TF traders) | High |
| Shadow context stack as restored MVP | High |
| Multi-agent portfolio / subaccounts | High that it is **future**, not missing current bug |
| CONTINUATION as live production state | Medium — docs expect it; production path disabled |
| Dual-axis structural diagnostics | High as research correction of BALANCE collapse |
