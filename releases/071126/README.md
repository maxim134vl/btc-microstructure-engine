# BTC-ML accepted installed snapshot — 071126

This directory preserves the actual installed 14-service composition, not an inferred checkout of the old root tree. R08 is a child of Paper. Role-specific sources are in `components/`; exact source SHA256 and Git blob IDs are in `SOURCE_FILES.json`. `runtime-overlays/` contains the real Legacy/profiling code mounts, and `presentation-build-source/` contains the accepted API/Dashboard/Chart build source and lock files.

`release_manifest.json` identifies original installed images and restore images. Current compiled images are the runnable artifacts retained privately on MaksTiger. Source folders may intentionally differ across owners; do not replace them with three latest files, merge them blindly, or use an old root Dockerfile as proof of this release.

Architecture, all14-service operations, module references, data lineage and recovery are in `docs/`. Engineering chronology preserves installed/research/superseded distinctions. A backup cut is not a new trading qualification. REAL remains disabled and all existing PAPER OPEN guards remain in force.

Private env/secrets, histories, WAL/books/positions, original captures, training payloads, image tar archives and full file-level data inventories are omitted from Git. The complete portable preservation package on owner storage is `BTCML_BACKUP_071126`; corpus/training originals remain under the documented MaksTiger logical roots. The config structure here is illustrative; use exact private restore config for restoration.

The parent branch's prior history is retained; obsolete root files were removed from current HEAD by the cleanup commit. This accepted snapshot is explicitly located under `releases/071126` so old root working-tree material is not silently presented as the running release.
