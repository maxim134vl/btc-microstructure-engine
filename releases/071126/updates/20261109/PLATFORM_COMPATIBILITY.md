# Platform acceptance boundaries

## Verified scope

The existing071126 package and this12-file delta use Linux/ARM64 frozen native
artifacts. Application source hashes, changed-file compilation, owner/mode pins,
installed distribution versions and bounded regression results are recorded.
This is not a new full14-service market qualification or an AMD64 benchmark.

## Differences that may be expected on a new architecture

New OCI/config/layer IDs, architecture names, ELF machine type, native-library
binary hashes, loader details and build metadata can legitimately differ. They
must be recorded as new platform artifacts; they are never presented as the
old ARM64 images. A new process has its actual clock domain and receive times.
Historical source timestamps, RAW/ACK records and recorded clock domains remain
unchanged; independent clocks must not be made comparable by a synthetic offset.

No numeric tolerance or trading-result difference is approved here. Source code,
market values/timestamps, row order, schema/index/nullable semantics, transition
ordering, contributors, guards and financial results must pass the same saved
input comparisons. Byte-level equality is required for retained committed files.
Parquet/serialization changes are not automatically harmless: generation IDs and
source pins can depend on those bytes. Never recompute historical receipts or
rewrite committed data to make a new writer appear equivalent.

## Required Linux/AMD64 sequence

1. Select explicit native Linux/AMD64 base image digests. Match the recorded
   Python/native dependency versions and OS ABI requirements; resolve actual
   AMD64 wheel/package artifacts and record their SHA. Do not consume ARM64
   native binaries or install unconstrained newer versions as a fallback.
2. Reuse the exact071126 owner sources plus the12 accepted overrides. Compile
   the used entrypoints and helpers. Keep process users, readonly mounts,
   subpaths, single-writer state ownership, ACK/fsync and configured budgets.
3. Run the same saved-input Feed, Candle/FIFO/restart, Arrow/native cleanup,
   Publisher and publication/admission regressions on native AMD64. Compare
   owner outputs, IDs/source pins and restored committed state. Differences
   in trading data or persisted-generation semantics require investigation,
   not automatic approval.
4. Measure bounded native-target throughput and resource use. Emulation can
   be a smoke test only; it is not evidence of native production capacity.
5. Restore independently copied state in an isolated target, verify ordinary
   ownership/startup and current producer bindings, and only then schedule
   an authorized installation. Do not use the Nov7 backup as a silent rollback
   of current Nov9 books/WAL/cursors. No synthetic permission/S0/S1/OPEN.

Status: AMD64_NOT_VERIFIED. The supplied build wrapper fails explicitly for
AMD64 instead of selecting an unverified base or pretending ARM64 equivalence.
