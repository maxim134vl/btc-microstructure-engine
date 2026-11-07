# Training/corpus inventory — 071126

The sequential metadata/index pass records **4,585,211 file/link entries**, **514 dataset collections**, **13,888 schema descriptions** and **486,607,738,645 logical file bytes**. This includes historical versions, archive members and frozen bindings: overlapping material is intentionally retained and must not be summed as unique market history or physical storage. 3,629,754 direct files were freshly fully hashed; 1,211 direct hashes reused completed same-file verification with unchanged metadata. Saved archive-member hashes and frozen binding indexes reuse completed full byte checks, without replay.

Exact per-file SHA, format/schema, paths, stored time/ID statistics and limitations: `BTCML_CORPUS/INDEX/DATA_FILES.jsonl.gz` (SHA256 `adce40a2671718c557915f3f4796b3747fe1e2043e86dc8c48d20ff13aed5828`). Group locator: `BTCML_STORAGE_MANIFEST/DATASET_REGISTRY.csv`. Schema descriptions: `BTCML_CORPUS/INDEX/DATASET_SCHEMAS/`. Read/metadata limits: `DATASET_METADATA_LIMITS.json`; unavailable original link targets: `MISSING_OR_EXTERNAL_LINKS.json` (30 entries). A metadata limitation is not silently replaced with zero. The catalog's path-based category is a locator, not market/source qualification.

## Sources retained

- All three coherent runtime-volume archives in the single backup, plus all nine frozen host binding roots. Complete RAW/ACK, WAL, books, source/publication, context/decision/financial artifacts remain private.
- Separately verified inactive `btc_ml_data_vps` archive in `BTCML_CORPUS/SOURCE_EVIDENCE/HISTORICAL_DOCKER_VOLUMES`; its153211 original files were compared again to the actual read-only source before exact volume deletion. It is historical data, not current continuation.
- Existing immutable source/research/training and old backup trees on MaksTiger remain on their original paths, indexed with hashes; no second physical copy of the400+GB corpus.
- Host-only data/datasets/output/research/models/artifacts copied and checked under `SOURCE_EVIDENCE/HOST_PROJECT_071126`:1593 files/1,165,333,835B, including model/tokenizer blobs and resolved original relative cache links. No owner venv was removed.
- Master Book: original canonical reconstruction candidate master,17409 rows/30 columns, SHA256 `88279f5b9c5c90daa3ae633aead7de6dab8d50af362e1a1e1b6afb98deb39c72`, independent APFS clone under `BTCML_TRAINING_DATA/MASTER_BOOK`. Original remains unchanged.

## Semantics and usable linkage

The original canonical masters include BAR_EVENT/STATE165474 rows each; CANDIDATE17409; CAUSAL_X17409; OUTCOME39035. The latter spans multiple worlds. BASELINE_DECISION, CAUSAL_COUNTERFACTUAL, SHADOW and any genuine execution records keep their original namespaces. IDs/run/source URIs and original field/label/split manifests are retained; no time/price coincidence joins or new labels were generated.

Parquet row counts are physical counts; Arrow stored time precision/timezone is exact. CSV semantic numeric units remain source-defined. JSONL line counts are physical lines, not ACK/processed events. Bounded JSON samples are not global time ranges. Opaque model binaries were preserved without unpickle/inference. Unknown units, absent typed time/ID stats, incomplete genuine capture, pending ACK and local historical availability remain explicit limitations. Never apply future features to an earlier decision.

RAW market identities remain Spot/Futures/source-specific. A symbol string is insufficient to infer market. Official archives prove exchange-time history, not local availability or S0/S1. No synthetic data, replay/backfill, model fit or new qualifications were created.

## Category sizes

Each index entry below is counted in one path-based locator category. Historical versions/archive members can still contain overlapping payloads. These are not APFS allocated/unique bytes or unique market events.

| Category | File/member entries | Logical bytes |
| --- | ---: | ---: |
| 1_MARKET_SOURCE | 365901 | 140512232891 |
| 2_STAGE1 | 629471 | 79724310610 |
| 3_CONTEXT_STAGE2 | 1735549 | 159326475998 |
| 4_DECISION_EXECUTION | 974699 | 72919864070 |
| 5_LEARNING_CALIBRATION | 326441 | 15923387830 |
| 6_SYSTEM_EVIDENCE | 553150 | 18201467246 |
