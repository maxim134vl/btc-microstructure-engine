# Release 071126 — preservation notes

This release records the installed 14-service BTC-ML composition, including the integrated Dashboard/Chart and R08 as a child of Paper. It preserves accepted TASK1–6 execution changes, T0 separation, release/provenance split, baseline300s/Q-Tspan, JournalV3/V2/V1 reading, state/copy/digest/serialization work, bounded receive worker/handoff/bar-close and stop-reason fixes, plus installed Publisher/Legacy/Visual optimizations. Current role-specific image/source hashes are the authority; historical accepted candidates are not silently installed.

The work adds a coherent offline preservation package, exact installed source/config, reconstructable missing Cognition artifact, restore tools and checks, data/lineage registries and engineering documentation. No trading formulas, entry guards, risk, SL/TP, ACK/fsync, VM limits, production data roots or REAL setting changed.

An emergency ENOSPC during the first backup was caused by the backup reader's binary stdout being duplicated into Docker json-file logging. That failed reader/log is gone; backup-only readers use logging disabled and no app healthcheck. The final archives passed complete content checks. Fourteen original containers were resumed with their original images/config/state. This does not qualify PAPER or assert a new S0/S1.

Storage cleanup removed superseded unreferenced execution tags and one separately archived/byte-compared inactive historical volume. APFS independent clones share verified redundant historical file contents without deleting unique research or owner editor history. Actual freed disk is measured separately from logical shared/virtual sizes.

Full second-stack runtime restore is NOT_TESTED; all required image roots, source/config and all volume contents are artifact-verified, with isolated state restoration checks. The original Cognition image ID was unavailable from the store; reconstructed348073… is explicitly identified rather than called byte-identical to093f… .

REAL_EXECUTION: DISABLED. PAPER admission and source freshness remain the application's real result. No fake permission, LIVE_QUALIFIED, S0/S1 or trade was made.
