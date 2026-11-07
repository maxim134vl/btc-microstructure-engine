# Key accepted changes —071126

Dates refer to source reports, not an invented installation time. Original journals, exact current image/source identity and adoption status remain separate.

## Execution TASK1–6 / LONG-SHORT / 5A-5B-5C

**DATE**: 2026-11-02 historical report day; not inferred install timestamp

**PROBLEM**: Принятые исправления исполнения и независимость TF

**ROOT_CAUSE**: Original consolidated qualification report locator not available at its known locations. Original recovered journals/source/image provenance are retained; no missing qualification count is reconstructed.

**CHANGE**: Accepted consolidated implementation carried into actual Paper/Timeframe/Intrabar images; no rollback to old tags

**BEFORE**: Original measured workload/result is in the linked preserved report; not remeasured or rescaled here

**AFTER**: Exact current image/source/mount identity in backup coverage + component provenance; live eligibility is separate

**TEST_RESULTS**: {"status": "REPORT_LOCATOR_NOT_RESOLVED; installed byte/source manifests retained; no test tally invented"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Baseline provider 300s/Q-T-span

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Отсутствовала подготовка причинно доступного prefix

**ROOT_CAUSE**: The LIVE path consumed baseline/predecessor config but did not prepare the preceding observed Spot contributor inputs for ResearchSystem.

**CHANGE**: Completed previous observed 300 seconds; literal q/T-span and real predecessor; frozen before eligible initiative

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_LIVE_CONNECTION_20261103/REPORT.md", "saved": "SOURCE_REPORTS/02_R08_LIVE_CONNECTION_20261103_REPORT.md", "sha256": "cb06eb3d6143ec87755e6ac3e2f9c04ee4cfcaccd0a8300512ffc862c25de804"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## R08 memory / incremental journal read

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Росли RAM и повторное чтение полных старых commits

**ROOT_CAUSE**: Per-event full config/baseline/state copies and retained previous commit snapshots amplified RAM and repeated journal reads.

**CHANGE**: Incremental record read, shared immutable baseline/config and no full past snapshots retained

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_LIVE_MEMORY_FIX_20261103/REPORT.md", "saved": "SOURCE_REPORTS/03_R08_LIVE_MEMORY_FIX_20261103_REPORT.md", "sha256": "c9c5d4d4a94651e862ed02055ef88ad3ab83897ba57054ae5dcd88bba1c11a75"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## R08 compact records V2/V3

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Повторные полные states превышали record cap

**ROOT_CAUSE**: Journal records repeatedly serialized immutable baseline/config and growing logical state, reaching the8MiB record cap despite preserving four TF states.

**CHANGE**: Delta/reference record and backward readers; restored market states remain native

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_COMPACT_JOURNAL_S0_20261103/REPORT.md", "saved": "SOURCE_REPORTS/04_R08_COMPACT_JOURNAL_S0_20261103_REPORT.md", "sha256": "9c520bc672785700c61602cd62251a5ab0ab3313ac1c27e18cbfc39e34a02945"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## R08 state-copy optimization

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Полное копирование логического state на каждом событии

**ROOT_CAUSE**: ResearchSystem deep-copied full logical state; append rebuilt committed snapshots and canonical full-state preparation even for small compact changes.

**CHANGE**: Copy mutable branches only; unchanged baseline/config shared; failed append keeps committed state

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_STATE_COPY_FIX_20261103/REPORT.md", "saved": "SOURCE_REPORTS/05_R08_STATE_COPY_FIX_20261103_REPORT.md", "sha256": "3a18dd0b0aed54fc0c1ca01e58f68dc5d7456b0c4ed0f5de760fff4bb5347fb4"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## R08 full-state digest removal

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Полный digest рос вместе с историей

**ROOT_CAUSE**: Per-event mandatory digest of accumulated full logical state grew to305MB; compact delta storage alone did not remove this work.

**CHANGE**: V3 record identity is explicit and never labelled a full-state SHA; V1/V2 read preserved

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_FULL_M15_PROCESSING_20261103/REPORT.md", "saved": "SOURCE_REPORTS/06_R08_FULL_M15_PROCESSING_20261103_REPORT.md", "sha256": "9ac9f3acf9f024a81f6eba99d5da6876e5ded92af16627dc158e5147ece114d2"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Four-TF Spot bar close / watermark

**DATE**: 2026-11-03 historical report day; not inferred install timestamp

**PROBLEM**: Не формировался seal закрываемого Spot бара

**ROOT_CAUSE**: Recorder delivery coverage did not produce the expected closed-bar seal; watermark existed as a consumer without the required Spot kline-close input.

**CHANGE**: Native correct-TF kline x=true plus actual local coverage; incomplete first bar not falsely sealed

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_SPOT_BAR_CLOSE_INPUT_20261103/REPORT.md", "saved": "SOURCE_REPORTS/07_R08_SPOT_BAR_CLOSE_INPUT_20261103_REPORT.md", "sha256": "8ac721f9e51e5c516051316d857139bef7915062fcf575eb6b68a033321e8e9a"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Nonblocking receive / Recorder ACK

**DATE**: 2026-11-04 historical report day; not inferred install timestamp

**PROBLEM**: Synchronous receive waited for heavy ingest

**ROOT_CAUSE**: WebSocket receive callback synchronously waited for Recorder/adapter/R08/commit instead of returning after bounded enqueue with original receive marks.

**CHANGE**: One bounded receive queue/worker; original receive marks; durable commit before ACK, no parallel writers

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_NONBLOCKING_PIPELINE_20261104/REPORT.md", "saved": "SOURCE_REPORTS/08_R08_NONBLOCKING_PIPELINE_20261104_REPORT.md", "sha256": "5634f55895a8fe7507e31de517652ae5ac4643543d1166af350db04924120a85"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Independent clocks / INIT handoff

**DATE**: 2026-11-04 historical report day; not inferred install timestamp

**PROBLEM**: Queued event received before actual INIT readiness

**ROOT_CAUSE**: Worker dequeued messages received before actual baseline/Context/policy/INIT readiness and incorrectly tried to start an initiative under a later-fixed baseline.

**CHANGE**: Preserve raw and sequence, account preactivation input; first eligible event selected by original receive order

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_INIT_HANDOFF_FIX_20261104/REPORT.md", "saved": "SOURCE_REPORTS/09_R08_INIT_HANDOFF_FIX_20261104_REPORT.md", "sha256": "2c63dd562e5d20e1ba6e32f627ab8603e16ce0e475b0f839d501db174aa2e64b"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## FULL_M15_PROCESSED stop reason

**DATE**: 2026-11-04 historical report day; not inferred install timestamp

**PROBLEM**: Normal stop became duration failure/exit1

**ROOT_CAUSE**: Normal FULL_M15_PROCESSED cancellation was overwritten by generic duration termination and false exitcode1.

**CHANGE**: Accepted normal stop mapping; no one-off canary M15 stop imposed as a permanent-service policy

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/R08_STOP_REASON_FIX_20261104/REPORT.md", "saved": "SOURCE_REPORTS/10_R08_STOP_REASON_FIX_20261104_REPORT.md", "sha256": "10a42bded11372aeadc1db9bde48b79a3a6b9193584d6714cd2d37ad59735785"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Release / historical provenance separation

**DATE**: 2026-11-04 historical report day; not inferred install timestamp

**PROBLEM**: Historical financial snapshot code pins blocked accepted release

**ROOT_CAUSE**: working_admission used implementation pins from the immutable historical financial snapshot, coupling state provenance to current application bytes.

**CHANGE**: Current implementation manifest separated from unchanged historical snapshot/approval/anchor

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_RUNTIME_WIRING_20261104/provenance-fix-20261104/REPORT.md", "saved": "SOURCE_REPORTS/11_provenance-fix-20261104_REPORT.md", "sha256": "598c8de0c3d3ad11578604c4a18aa6b7d39ddeb38c5ec920c0e7db610f1b75f0"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## T0 current market domain

**DATE**: 2026-11-04 historical report day; not inferred install timestamp

**PROBLEM**: Owner rejected pre-T0 historical catch-up

**ROOT_CAUSE**: Historical pre-T0 catch-up and moving overflow fence prevented an owner-approved fresh current domain; old histories had to be retained rather than replayed as new.

**CHANGE**: Preserve old histories; use approved current domain, no manual pre-T0 recovery in preservation

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_T0_START_20261104/REPORT.md", "saved": "SOURCE_REPORTS/12_BTCML_T0_START_20261104_REPORT.md", "sha256": "e37363a9c70a61d80fa1e5342ea17015c67afdf04da6619295d50a894c66ad91"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Publisher native pass reuse / timers

**DATE**: 2026-11-05 historical report day; not inferred install timestamp

**PROBLEM**: Repeated unchanged native processing in one pass

**ROOT_CAUSE**: freeze_sources/snapshot/M15 preparation repeated decoding, normalization and copies of the same immutable native Parquet within one pass.

**CHANGE**: Accepted current image 8f5985… retained with instrumentation; old/small timings are not current full-cycle measurements

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_PUBLISHER_NATIVE_PASS_REUSE_20261105/REPORT.md", "saved": "SOURCE_REPORTS/13_BTCML_PUBLISHER_NATIVE_PASS_REUSE_20261105_REPORT.md", "sha256": "57ae51907f8772bd5409794e2c2cf76bec50a8ccd2eafd877d513c86d9bb9de9"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Legacy snapshot read reuse

**DATE**: 2026-11-05 historical report day; not inferred install timestamp

**PROBLEM**: Repeated reads of unchanged snapshot

**ROOT_CAUSE**: Clusters/Inventory read the same multi_exchange_flow snapshot repeatedly; pass-local reuse preserves native algorithms and invalidates on a changed source signature.

**CHANGE**: Exact active io_runtime.py/legacy_pair_runtime.py overlay saved in bind-08; changes invalidate native signature

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_TARGETED_RESOURCE_OPT_20261105/REPORT.md", "saved": "SOURCE_REPORTS/14_BTCML_TARGETED_RESOURCE_OPT_20261105_REPORT.md", "sha256": "cbad7a5123ef83d0c9da5a097bad925c36cc0a6cebea600c0043bb2d7314316a"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Visual skip unchanged inputs

**DATE**: 2026-11-05 historical report day; not inferred install timestamp

**PROBLEM**: Full projection rebuild with unchanged inputs

**ROOT_CAUSE**: Visual renderer repeated full projection work when the actual versioned inputs had not changed.

**CHANGE**: Accepted Visual image preserved; new-input update cadence/formulas unchanged

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_TARGETED_RESOURCE_OPT_20261105/REPORT.md", "saved": "SOURCE_REPORTS/15_BTCML_TARGETED_RESOURCE_OPT_20261105_REPORT.md", "sha256": "cbad7a5123ef83d0c9da5a097bad925c36cc0a6cebea600c0043bb2d7314316a"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Qualified R08 algorithms vs deployment I/O

**DATE**: 2026-11-06 historical report day; not inferred install timestamp

**PROBLEM**: Durable publication slow in Desktop environment

**ROOT_CAUSE**: Qualified algorithm/Journal optimizations were present; deployment publication latency was observed in durable filesystem calls on Docker Desktop. These measurements do not establish native Linux performance.

**CHANGE**: Qualified algorithms/Journal/Recorder semantics retained; local filesystem timing not generalized to Linux

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_R08_QUALIFIED_PERFORMANCE_RESTORE_20261106/REPORT.md", "saved": "SOURCE_REPORTS/16_BTCML_R08_QUALIFIED_PERFORMANCE_RESTORE_20261106_REPORT.md", "sha256": "54208ef1b296642625388784a941b365ac16945c5bdfb9b6d8ddfed6bc0dc959"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Dashboard integration / release 071126

**DATE**: 2026-11-07 historical report day; not inferred install timestamp

**PROBLEM**: Single 14-role view with chart and actual provenance

**ROOT_CAUSE**: Dashboard/Chart/OPS metadata and owner currentness were fragmented; transport availability was not a reliable substitute for process/owner/source status.

**CHANGE**: Accepted API/UI and previous 19 targeted checks preserved; no algorithm requalification

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/BTCML_RELEASE_071126/REPORT.md", "saved": "SOURCE_REPORTS/17_BTCML_RELEASE_071126_REPORT.md", "sha256": "a3c3491dd32eaf9441f5705c7a1b7c02893472e28f3107f49d724eb8c95f3856"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.

## Cognition portable recovery image

**DATE**: 2026-11-07 historical report day; not inferred install timestamp

**PROBLEM**: Original image metadata unavailable

**ROOT_CAUSE**: Original Cognition image metadata was absent from Docker store while the actual container filesystem and startup metadata remained available.

**CHANGE**: Actual read-only rootfs reconstructed as distinct artifact; original live container not replaced

**BEFORE**: Original comparable before measurement and boundary: see ORIGINAL_MEASURED_EXCERPTS and exact saved report. If absent there, NOT_RECORDED; no new measurement invented.

**AFTER**: Original accepted after measurement with its own workload/result scope: see same exact report. Current installed identity is separate in CURRENT_ADOPTION_071126.json.

**TEST_RESULTS**: {"original": "${MAKS_ROOT}/BTCML_BACKUP_071126/BACKUP_RESTORE_VERIFICATION.md", "saved": "SOURCE_REPORTS/18_BTCML_BACKUP_071126_REPORT.md", "sha256": "5a9a980a0cc2b02b74f6165e18c641c18c0b3890f5d491dc775f65c44bfbc90e"}

**COMMIT_OR_SOURCE_REVISION**: INVENTORY/containers.private.json + SOURCES/INSTALLED/*.source-index.jsonl.gz + CONFIG/HOST_MOUNTS/bind-00/bind-08; some accepted late patches have image/source SHA rather than a published Git commit

**DEPLOYMENT_STATUS**: ACCEPTED_NOT_INSTALLED

**PRESERVED_GUARANTEES**: Trading formulas/guards, native timestamps, original RAW/receipts/ACK, baseline, per-TF state and REAL off unchanged

**KNOWN_LIMITATIONS**: Historical PASS/benchmarks do not confer current LIVE_QUALIFIED, S0/S1, OPEN or runtime throughput. Some report locators may be missing; original journals and actual image bytes remain authoritative.


