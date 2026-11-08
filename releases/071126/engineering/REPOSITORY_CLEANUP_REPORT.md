# Repository cleanup — 071126 / 8 November 2026

The installed per-role source manifest is the authority for release071126. This original development checkout also contains pre-release work; its unstaged source/config changes are preserved and were not silently made part of this cleanup commit. The public release uses separately frozen per-role source trees rather than flattening file versions.

## Exact cleanup

- Before:9339 tracked files. Removed from the current index:6513 generated `dashboard/frontend/node_modules` files and one generated `tsconfig.tsbuildinfo`.
- Kept Dashboard frontend/backend source, package.json/package-lock.json, build configuration, deployment files, tests and all active host bindings.
- Host-only `venv`, `.venv_presentation` and npm dependencies had no open native-process reference and no container mount. All74147 files/links were archived and every member byte-checked after decompression before removal. Archive SHA256:`e367ff7ec7fed1ec15b5ac6822565f47dc6c65556b82344560852ecdd7dfe35f`.
- The archive is on MaksTiger at `BTCML_ENGINEERING_JOURNAL/WORKING_TREES/20261108/inactive-host-development-environments.tar.zst`. It is optional Mac development data, not a runtime image dependency. Locks remain for clean builds.
- The generated directories occupied2399264768 allocated bytes; cross-time internal free-space delta was3536941056 bytes and also includes unrelated host/swap changes. Do not attribute that entire delta to these files.
- Added only scoped cache/development ignore rules; current source and configuration are not hidden.

## Historical preservation and exclusions

All original tracked bytes remain reachable at parent commit `4167c96cdb33e62be0be2739364c89595976d9f4`. Full private history is in the sealed backup `SOURCES/local-git-history.bundle`. WIP3176 members were separately byte-verified in the engineering journal (archive SHA256 `7a37ec0ec436cf9a3911788d440cdea448dab838c3f367b3af0036d9d4edc624`); active bind paths remain in place and in the original coherent backup cut.

`archive_removed` stays because existing legacy hardening checks explicitly reference its mirror archive. Old benchmark, research, fixtures, data and unresolved dynamic paths were not deleted merely for lacking a static import. The four historical syntax-invalid root alternatives are not repaired or selected as runtime entrypoints by this task. This is not a claim that every retained research file is production-active.

The complete private working-tree map and conservative runtime-reference closure are in `BTCML_STORAGE_MANIFEST/CLEANUP_20261108/`. Active mounts, CLI/entrypoints, literal/dynamic paths, Docker COPY exclusions, tests, docs and restore provenance were checked. The original tree's unresolved/nondeployed research remains explicitly retained pending semantic evidence; it is not automatically admitted production code.

## Validation boundary

This commit changes no application Python/TypeScript source, trading formula, R08 implementation, Docker config, permissions, WAL, books, cursor or service. It does not rebuild or restart services. Public release/canonical HEAD cleanup is recorded separately, with normal ancestry-preserving commits. Full runtime restore remains NOT_TESTED; REAL remains DISABLED.

## Root training matrices

Eight historical root NumPy arrays were removed from HEAD only and remain physically unchanged as local training originals. They are already excluded by Docker build contexts. Exact bytes remain in original Git commit4167c96cdb33e62be0be2739364c89595976d9f4 and the preserved private history bundle. Added only root-scoped `/*.npy` ignore; test fixture arrays are not hidden. No physical space is claimed for this index-only action. Tracked total after this final source hygiene step:2818.

## Public HEAD cleanup

This `release` branch contains the complete accepted execution/API/UI and analytical source package. SOURCE_FILES.json is its exact code manifest.

Old root files:9117. Recovery parent:`8f45e0260929ba87ccaca1d8fe6e08949cc1d94a`. All existing accepted per-role source blobs remain unchanged. See HEAD_CLEANUP_20261108.json.
