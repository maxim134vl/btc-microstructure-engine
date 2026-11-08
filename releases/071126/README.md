# Accepted analytical owner snapshot — 071126

This branch contains the installed Canonical, Publisher, Cognition and native Legacy analytical subset. Exact bytes and source owners are in CANONICAL_SOURCE_FILES.json. Current code is per-role under components/, not the superseded root checkout.

[Architecture](docs/ARCHITECTURE_DIAGRAM_INDEX.md), [operations](docs/OPERATIONS/BTCML_DEPLOYMENT_AND_OPERATIONS_071126.md), [data lineage](docs/DATA_DICTIONARY/DATA_LINEAGE.md) and [restore](docs/RESTORE_GUIDE/RESTORE_071126.md) describe the complete system, including consumers whose execution/API/UI code is on the separate release branch. These descriptions do not copy that code into canonical scope or grant market permission.

Old root sources remain recoverable in parent Git ancestry. No force push or history rewrite. The sealed private backup preserves exact runnable images/config/state; documentation supplement is separate. REAL remains DISABLED; full runtime restore remains NOT_TESTED.
