# Research Basis for BTC Market Cognition Engine

Status: canonical research basis  
Scope: market cognition, context validation, lifecycle logic, QA gate, memory/retraining  
Execution status: non-execution / shadow-first

---

## 1. Purpose

This document fixes the research basis for the BTC Market Cognition Engine.

The system must not be developed as a set of arbitrary trading heuristics.  
Every major model change should be mapped to one of the following research areas:

1. Regime / phase detection
2. Structural break / changepoint detection
3. CatBoost / ordered boosting for tabular time-series features
4. Selective classification / reject option / decision gates
5. Explainability / black-box model audit
6. Continual learning / memory update policy
7. Reinforcement learning / off-policy evaluation, only for later execution research

Canonical operating principle:

- context first
- validation second
- execution later

---

## 2. Current System Mapping

Current architecture:

candle / volume
-> bar observation
-> auction episode
-> cognitive market state
-> raw market context
-> lifecycle context
-> final active_market_context
-> visualization

Research mapping:

- bar observation / auction episode -> structural break and regime evidence
- cognitive market state -> regime interpretation
- raw market context -> candidate regime direction
- market context lifecycle -> regime confirmation, persistence, invalidation
- OBSERVE / STAND_ASIDE / no-action -> selective classification / reject option
- Economic QA -> explanation, rejection, and validation gate
- memory / retraining -> continual learning without catastrophic forgetting
- execution later -> off-policy evaluation before any live RL or live trading

---

## 3. Regime / Phase Detection

### 3.1 Hamilton 1989 — Markov-switching / regime switching

Reference:

James D. Hamilton, 1989  
"A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle"  
Econometrica, Vol. 57, No. 2, pp. 357-384.

Links:

https://www.jstor.org/stable/1912559  
https://doi.org/10.2307/1912559

Use in this project:

- theoretical basis for market regime switching
- supports the idea that the market can move between hidden regimes
- useful as conceptual foundation for LONG_CONTEXT / SHORT_CONTEXT / OBSERVE regimes
- not used directly as a trading model

Project interpretation:

Market context should be treated as a latent regime, not as a direct signal.

---

### 3.2 PELT / changepoint detection

Reference:

Killick, R., Fearnhead, P., Eckley, I. A.  
"Optimal Detection of Changepoints With a Linear Computational Cost"

Link:

https://arxiv.org/abs/1101.1438

Use in this project:

- structural break detection
- offline labeling of regime transitions
- validation of context start/end boundaries
- future comparison against lifecycle episode boundaries

Project interpretation:

A context boundary should be checked against structural evidence, not only against one-bar events.

---

### 3.3 Bai-Perron structural breaks

Reference:

Jushan Bai, Pierre Perron  
"Estimating and Testing Linear Models with Multiple Structural Changes"

Link:

https://doi.org/10.2307/2998540

Use in this project:

- econometric validation of structural breaks
- comparison layer for regime boundaries
- possible benchmark for detecting persistent shifts

Project interpretation:

A regime transition should be persistent enough to qualify as structure, not just short-term noise.

---

## 4. CatBoost / Context Model

### 4.1 CatBoost original paper

Reference:

Prokhorenkova, L., Gusev, G., Vorobev, A., Dorogush, A. V., Gulin, A.  
"CatBoost: unbiased boosting with categorical features"

Link:

https://arxiv.org/abs/1706.09516

Use in this project:

- basis for using CatBoost on structured market features
- ordered boosting as protection against prediction shift / leakage
- tabular regime features, auction features, volume features

Project interpretation:

CatBoost should be used as a structured-context classifier, not as a raw price predictor.

---

### 4.2 CatBoost technical implementation paper

Reference:

Dorogush, A. V., Ershov, V., Gulin, A.  
"CatBoost: gradient boosting with categorical features support"

Link:

https://arxiv.org/abs/1810.11363

Use in this project:

- implementation reference
- practical training / inference basis
- feature handling and model deployment considerations

---

### 4.3 CatBoost ordered time handling

Reference:

CatBoost documentation — training parameters / has_time

Link:

https://catboost.ai/docs/en/references/training-parameters/common

Use in this project:

- time-order preservation
- avoiding random permutation where time order matters
- reducing leakage in time-series training

Project rule:

Time-series training must preserve chronology. Random train/test leakage is not acceptable.

---

### 4.4 CatBoost Quantile / MultiQuantile

Reference:

CatBoost documentation — regression loss functions

Link:

https://catboost.ai/docs/en/concepts/loss-functions-regression

Use in this project:

- modeling structural ranges
- potential future modeling of high/low boundaries
- uncertainty bands around context rather than one-point prediction

Project interpretation:

For market structure, boundaries can matter more than mean prediction.

---

## 5. Economic QA / Gate / Reject Option

### 5.1 Selective Classification

Reference:

Geifman, Y., El-Yaniv, R.  
"Selective Classification for Deep Neural Networks"

Link:

https://arxiv.org/abs/1705.08500

Use in this project:

- theoretical basis for OBSERVE / STAND_ASIDE
- rejection of low-confidence decisions
- risk-coverage trade-off

Project interpretation:

The model is allowed to refuse a decision. No-context is a valid output, not a failure.

---

### 5.2 SelectiveNet

Reference:

Geifman, Y., El-Yaniv, R.  
"SelectiveNet: A Deep Neural Network with an Integrated Reject Option"

Link:

https://arxiv.org/abs/1901.09192

Use in this project:

- integrated reject-option logic
- future architecture for confidence-aware decision layers
- useful reference for Economic QA / Gate

Project interpretation:

A high-quality gate should optimize both decision quality and rejection quality.

---

### 5.3 Explainability / Black-box audit

Reference:

Guidotti, R., Monreale, A., Ruggieri, S., Turini, F., Pedreschi, D., Giannotti, F.  
"A Survey of Methods for Explaining Black Box Models"

Link:

https://arxiv.org/abs/1802.01933

Use in this project:

- model audit
- reason codes for rejected contexts
- explanation of why a context was accepted, challenged, invalidated, or rejected
- future Economic QA report design

Project interpretation:

Every context decision should eventually have an explanation trace.

---

## 6. Memory / Continual Learning / Retraining

### 6.1 Continual Lifelong Learning

Reference:

Parisi, G. I., Kemker, R., Part, J. L., Kanan, C., Wermter, S.  
"Continual Lifelong Learning with Neural Networks: A Review"

Link:

https://arxiv.org/abs/1802.07569

Use in this project:

- memory update policy
- protection from catastrophic forgetting
- retraining discipline
- replay / historical validation

Project interpretation:

New live observations should improve the model without destroying old regime knowledge.

---

### 6.2 Continual Learning Survey

Reference:

De Lange, M., Aljundi, R., Masana, M., Parisot, S., Jia, X., Leonardis, A., Slabaugh, G., Tuytelaars, T.  
"A continual learning survey: Defying forgetting in classification tasks"

Link:

https://arxiv.org/abs/1909.08383

Use in this project:

- stability-plasticity trade-off
- evaluation of memory update methods
- model retraining guardrails

Project interpretation:

Retraining must be measured against both recent adaptation and old-regime retention.

---

## 7. Reinforcement Learning / Execution Later

### 7.1 Sutton & Barto — Reinforcement Learning

Reference:

Sutton, R. S., Barto, A. G.  
"Reinforcement Learning: An Introduction", 2nd edition, 2018

Link:

http://incompleteideas.net/book/the-book-2nd.html

Use in this project:

- delayed reward framework
- off-policy evaluation
- reward design
- later-stage execution research only

Project restriction:

RL is not a current execution engine. RL can only be considered after context validation and off-policy testing.

---

## 8. Sources Not Accepted Yet

The following sources must not be used as authoritative project references until originals are confirmed:

- Dunis et al. 2021 — "Regime Switching Models with Machine Learning for Financial Forecasting"
- DeepGates — "Efficient Inference of Deep Neural Networks with Gating Networks"

Reason:

Exact original publications were not confirmed. Do not cite them in project docs, research notes, or investor-facing materials.

---

## 9. Development Rules Derived From Research Basis

### 9.1 Context is not a trade

Market context is not a trading signal.

A context can support a future setup, but it must not directly imply execution.

### 9.2 OBSERVE is a valid state

Rejecting action is part of the model.

OBSERVE / STAND_ASIDE must be treated as a valid selective-classification outcome.

### 9.3 No one-bar regime death

A confirmed market context should not be killed by one weak neutral bar.

Lifecycle invalidation should require:

- persistent evidence
- or confirmed opposite context
- or real thesis invalidation

### 9.4 Structural evidence matters

Context boundaries should be compared against:

- auction evidence
- volume evidence
- structural break evidence
- follow-through evidence

### 9.5 Retraining must be controlled

Any retraining protocol must check:

- recent improvement
- old-regime retention
- catastrophic forgetting risk
- context quality
- false confirmation rate
- false invalidation rate

### 9.6 QA gate before execution

Before any live execution, the system needs:

- context quality audit
- setup quality audit
- reject-option gate
- risk gate
- off-policy validation
- execution simulator

---

## 10. Immediate Application To Current Project

Current safe operating mode:

- observe only
- shadow_only = true
- action_allowed = false
- execution later

Next research-aligned development stages:

1. Live context quality audit
2. Formation-to-confirmation delay audit
3. Context persistence / invalidation quality audit
4. Structural break benchmark against lifecycle episodes
5. Selective QA gate for accepted/rejected contexts
6. Memory update / retraining policy
7. Off-policy execution simulation
8. Only then execution research

---

## 11. Canonical Short Form

Hamilton / PELT / Bai-Perron -> regime and structure

CatBoost / ordered boosting / has_time -> context model

Selective Classification / SelectiveNet -> OBSERVE and reject option

Guidotti explainability -> Economic QA and decision trace

Parisi / continual learning -> memory and retraining

Sutton & Barto -> later off-policy execution research
