# Accepted071126 runtime delta — 2026-11-09

This is an additive update to the existing published071126 release, not a new
flattened version of BTC-ML. The original source, manifests, backup and receipts
remain unchanged. `RECONCILIATION.md` records the comparison before this delta.

The published release receipt is8f45e026…, canonical45efea61…; this branch starts
at the preserved release HEAD3e5c07fc…. Of8116 current source/service pairs,
8104 already match071126. Only12 application files are added here:9 replacements
and3 additions in Feed, Canonical and Publisher. `CURRENT_SOURCE_FILES.json`
resolves the complete original manifest plus those12 overrides. Per-role paths
remain separate. Do not flatten R08, Paper, Timeframe or analytical owners.

The other11 installed image IDs and all13 Python dependency sets match071126.
Existing execution, R08/V3, guards, Legacy/Visual and frontend071126 preservation
are reused. Existing Cognition restore image348073d3… is reused from the sealed
backup with its prior verification. It remains distinct from original093f…;
no repeated reconstruction or replacement is required.

## Build and configuration

Restore the exact071126 frozen bases and use `build_delta.py --output /external/path`.
Only3 owners are built. Base ID/platform and source hashes are checked; the
BuildKit reference contains the pinned digest. No dependency resolution, network
RUN, application startup or production volume is used. New tags are unique and
existing tags are never overwritten. Build results record the exact source commit.

`deployment/compose.json` specifies all14 current roles. It requires explicit
restored volume names and private binding paths, with no production-volume
defaults. Code bindings refer to the already saved071126 component sources.
RO boundaries, subpaths, process users, resource settings, network-none Legacy
roles and one-writer ownership are retained. REAL remains disabled. It must not
be launched against the current production project during candidate preparation.

All live data, WAL, books, private policies/approvals/credentials and saved market
fixtures stay outside Git. Dependencies record exact installed versions, while
the pinned native image artifacts provide the binary environment. The public
source/metadata is not permission to fabricate startup bindings or market results.

## Validation limits and migration prerequisites

Use the separate bounded saved-input bundle and recorded regression commands.
The changed source, ordering/FIFO/restart, Arrow cleanup and publication guards
are tested without production mounts or network. Unchanged071126 evidence is
reused after byte comparison, not requalified as a new market run.

Linux/ARM64 frozen-artifact reproduction and Linux/AMD64 are different targets.
The builder refuses AMD64. AMD64 requires explicit native base digests, platform
locks and the same output/native-cleanup regressions on that architecture; no
equivalence is inferred from emulation or ARM64 tests. Full14-service restore
and a current consistent state handoff remain separate controlled prerequisites.
The existing sealed backup cut is2026-11-07; it is not relabelled as Nov9 state.

Pre-existing malformed dormant source `initiative_memory_engine.py:78` and the
conditional Feed metadata-publication handling are preserved and reported as
existing debt. No formula, market condition, FIFO, ACK/fsync, accounting or
guard was changed to obtain a passing result.
