# BTC-ML — accepted release 071126

The current source authority is the exact installed per-role snapshot under [releases/071126](releases/071126/README.md). Fourteen Docker services are preserved; R08 belongs inside Paper. REAL remains disabled. No new trading qualification or market permission is conferred by this repository cleanup.

Start with the [architecture diagrams](releases/071126/docs/ARCHITECTURE_DIAGRAM_INDEX.md), [system architecture](releases/071126/docs/SYSTEM_ARCHITECTURE/BTCML_SYSTEM_ARCHITECTURE_071126.md), [operations manual](releases/071126/docs/OPERATIONS/BTCML_DEPLOYMENT_AND_OPERATIONS_071126.md) and [restore guide](releases/071126/docs/RESTORE_GUIDE/RESTORE_071126.md).

The obsolete pre-release root checkout was removed from this branch HEAD by a normal commit. Every old file remains recoverable in parent Git history; there was no history rewrite, reset or force push. Exact per-role versions are intentionally retained and must not be flattened into one guessed latest source tree. Public configuration is illustrative: deploy from the exact private saved images/config/state according to the restore guide.

This `memory/canonical-system` branch contains the accepted analytical Canonical/Publisher/Cognition/Legacy subset. CANONICAL_SOURCE_FILES.json is its exact code manifest. Execution/API/UI sources remain in the `release` branch; architecture documentation may describe those external-to-this-branch consumers without copying their code here.
