# Reconciliation before the accepted source delta

Authority: existing release071126, published GitHub receipt 2026-11-07, and the sealed BTCML_BACKUP_071126. The earlier local Gitea source audit did not account for this separate complete publication. Its Git/source-loss and Cognition-not-restorable conclusions must not be applied to the published071126 package. No historical report or backup is rewritten.

- Published release: `8f45e0260929ba87ccaca1d8fe6e08949cc1d94a`; canonical: `45efea614eaf74934ff419f752103beea6e12b16`. Historical receipt records successful normal push and verified remote heads. This is not a new live remote query.
- Existing release checkout is clean at `3e5c07fcd8099bb3ec87b8c65ab9486146a69a45`, retaining the accepted071126 tree with later documentation/cleanup.
- 8116 current service/source pairs: 8104 unchanged, 9 modified, 3 new. 8113 existing source blob IDs checked against the published commit; 8102 non-UI entries checked against backup indexes. All13 source archive SHA verified (30,165,409 bytes); no data/corpus rescan.
- Only3 installed images changed: collector-watchdog, canonical-runtime, context-refresh-daemon. Other11 installed image IDs match071126.
- Existing Cognition rootfs recovery image348073d3… already saved, load/create/import tested with846source hashes. Current810source hashes match preserved source. Original093f… OCI identity remains distinct; use the existing recovery artifact. No new reconstruction is needed.

The provisional Gitea worktree0972c6cd and its newly built packaging images were made before this reconciliation. They are retained as provisional evidence, not the accepted release base and not for deployment. The source-delta candidate continues the existing071126 Git history, preserving all previous work. No existing branch, backup, production image/container or persistent state was modified.

## Exact application delta

- collector-watchdog `/app/feed_gap_recovery.py`: ADDED; accepted SHA `fde3a91c2934624c4ef4a287103e10bf0c17fa209c9c4849f57807b599d8f492`.
- collector-watchdog `/app/live_binance_feed_v2.py`: MODIFIED; accepted SHA `1fedd0de643fc48f41f40fff60d95d32c283fc87d91b7ef571bc315ec583d289`.
- canonical-runtime `/app/auction_parquet_io.py`: ADDED; accepted SHA `bd7dc0e76544cf4ecc8d0852af6d99a04f7e120bf1381f25a8deddff76d09398`.
- canonical-runtime `/app/auction_synthesis_engine_v1.py`: MODIFIED; accepted SHA `1e6b3a18db0db14f94b55cc062beb810f1df6a3fa1c1c76f3fc08fce0336fbde`.
- canonical-runtime `/app/engine_worker.py`: MODIFIED; accepted SHA `830c0f93a2c259e90f93e50e1e5132cba36325cbaba3493462a7dbd9608ef033`.
- canonical-runtime `/app/live_feed_paths.py`: MODIFIED; accepted SHA `fde9403ca048191a9bfd7176d6a938d48bfcf606cc483b613afe582b58206130`.
- canonical-runtime `/app/runtime_engine_guard.py`: MODIFIED; accepted SHA `21b6860040b697f11916086e0b5d4b9aa334990ddeb02a52621a2f1515c568d1`.
- canonical-runtime `/app/src/btc_ml/runtime/canonical_candle_lane.py`: ADDED; accepted SHA `8b97400e46cf15a801d6dd811fe4af453d69177b565e6e5eefbe4bd0177192ae`.
- canonical-runtime `/app/src/btc_ml/runtime/pipeline.py`: MODIFIED; accepted SHA `72661eda10890e53d73e69aa8f6eb51fbfb42d26bfafa39338d322beb4fca33d`.
- canonical-runtime `/app/state_manager_v1.py`: MODIFIED; accepted SHA `505c8db51166a5a65940c19133da29e78c09e166fa8da123c86f60a636895785`.
- canonical-runtime `/app/storage/path_registry.py`: MODIFIED; accepted SHA `70204d4bcfaf69fc867bec0e38fdab6eca142f16be41dc717c8c7dc2ec9ebe7a`.
- context-refresh-daemon `/app/src/btc_ml/external_traders/context_stage2_evidence.py`: MODIFIED; accepted SHA `1c81b8b590aab23262467c94bb6c43b4aa9d53cf43e24e19c7d1d95eab160544`.
