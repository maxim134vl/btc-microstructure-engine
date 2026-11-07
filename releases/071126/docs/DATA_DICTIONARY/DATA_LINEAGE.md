# Data lineage — release 071126

The preservation boundary is 2026-11-07 14:14:36.770608 UTC for mutable runtime state. Later document generation, source inspection and resumption of the original services do not advance this backup cut. New events after the cut remain in the unchanged live volumes. The backup is not a continuously mirrored journal.

## Native market evidence

Market source messages retain their original source/market/symbol, exchange timestamps, local receive timestamps, sequence IDs and receipts where those fields actually exist. BTCUSDT alone does not establish Spot versus Futures. Exchange timestamps and Mac UTC/monotonic belong to different clock domains. Storage mtime, archive creation time and a reconstructed bar key are not proofs of local feature availability.

Spot RAW → durable Recorder publication → original delivery receipt/ACK → sequential adapter → R08/provider is preserved inside the Paper source, original frozen R08 host binding and main volume. A file count, JSONL line count, capture inventory or downloaded event is not a processed/ACKed cursor. The backup retains unacknowledged/pending records without upgrading their status. Historical public archives remain exchange-time research data, not genuine local S0/S1 evidence.

Futures market WAL/checkpoint and event-disposition generations are copied unchanged. The saved physical WAL tail can exceed a cache or processed checkpoint; the native WAL implementation resolves its own persisted state. No tail truncation, synthetic ACK or cursor advance was performed. See `RESTORE_VERIFICATION/SAVED_STATE_CONSISTENCY.json`.

## Analytical generations

Native Legacy source snapshots → Canonical Stage1/Stage2 → Cognition and causal Publisher → own-TF Final/Lifecycle/Context Phase → execution readers. Canonical and Publisher are independent owners, not one serial thread. Preserve generation/source IDs and their owner publication timestamps. Four TFs remain independent; an M15 row does not stand in for H4. Derived bar delta/body-share estimates are not literal unsigned Spot q.

R08 reference rate remains Q/(last contributor T − first contributor T), BTC/s, selected from the approved preceding 300-second prefix. Q/300, EWMA, message count, turnover and signed delta are not substituted. Frozen baseline, actual predecessor, source/context/policy and INIT causal order remain original. No new baseline/predecessor/S0/S1/permission was made in this preservation task.

## Execution and outcomes

Timeframe commands → CommandBus → Paper validation/ACK → financial generations/position books → Intrabar supervision. Retain command/idempotency, source descriptor, approval/release provenance, receipts, positions, prices, costs and reason codes as stored. A historical financial approval is not rewritten to attest to different application bytes. REAL remains disabled; missing qualifications are not replaced by owner intent to PAPER-trade.

Decision/candidate/outcome relations must use existing run/world/candidate/observation/source identifiers and original linkage contracts. Never infer a join from approximate time/price equality. NO_ACTION, rejection, shadow intervention and synthetic/counterfactual outcome are distinct observations; none is relabelled as a real executed trade.

## Training reconstruction

The original canonical reconstruction tree, all available training/calibration versions, manifests and field dictionaries remain on MaksTiger. The organized Master Book is an independent APFS clone of the original 17,409-row candidate table, verified by SHA. Its `BASELINE_DECISION` and `CAUSAL_COUNTERFACTUAL` worlds must remain separated. The 39,035-row multi-world outcome table is not a one-to-one trade ledger. Bar/state tables have 165,474 physical rows each; overlapping versions are not added as unique market observations.

The group registry is a locator, not a newly certified training set. Per-file SHA and stored schema/statistics are in the compressed index. A physical row count is not semantic sample identity. No training, joins, labels, synthetic market events, model inference or trading replay were run.
