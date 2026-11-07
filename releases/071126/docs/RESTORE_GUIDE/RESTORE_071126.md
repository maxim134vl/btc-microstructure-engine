# Restore release 071126 on another compatible computer

Use the single `BTCML_BACKUP_071126` directory, plus the retained training/corpus roots on MaksTiger. The runtime backup contains its own images, current sources, immutable config, every live volume and every required host binding. It does not depend on `${ORIGINAL_HOME}`, the old Mac Git checkout or a remote registry. Historical source paths inside receipts remain provenance only.

## What has actually been checked

All saved OCI content blobs/descriptors, source archives, host bindings and each volume member were hashed and decoded. All 12 unique restore image roots covering 14 roles were loaded and create-checked without starting applications. Reconstructed Cognition additionally passed the real UID/cwd import probe. Visual and critical Paper/WAL states were physically restored into isolated empty targets using the shipped helper; UID10001 write/rename/delete was checked. No second full trading stack was started. Full-stack runtime restore remains NOT_TESTED.

The current original 14 containers were resumed after the coherent cut; that is a continuity check, not a restoration from backup. No extra genuine capture, source permission, S0/S1 or OPEN was created.

## Requirements

A clean compatible Docker host supporting Linux/arm64, adequate persistent disk/RAM for the original services and restored copies, Docker Compose, host Python >=3.11. Source build is not needed. The saved image provides PyArrow 25.0.1 for zstd restoration. Do not use tmpfs for persistent restored data. Mac M1/8GB is constrained; do not run this alongside another full stack.

Keep the backup read-only in ordinary operation. Its private configuration and original evidence require owner-only access. Do not publish `*.private.*`, env files, WAL, books or positions. Copy mutable host bindings into a distinct runtime directory; do not let resumed services write into the backup.

## Plan and apply

Set `B` to the mounted backup directory, `T` to a new empty persistent runtime directory, and `SOCKET_GID` to the actual Docker socket group on the target host. Preserve UID10001 and inspect host bind access in the actual container domain; a different Mac numeric owner is not by itself an error.

```sh
python3 "$B/RESTORE/restore_release.py" --backup-root "$B" --runtime-root "$T" --volume-prefix btcml_071126 --socket-gid "$SOCKET_GID"
python3 "$B/RESTORE/restore_release.py" --backup-root "$B" --runtime-root "$T" --volume-prefix btcml_071126 --socket-gid "$SOCKET_GID" --apply
```

The first command is plan-only. Apply verifies saved regular-file checksums, refuses an existing production Compose project or nonempty target/volumes, loads the saved images and restores separate copies. It does not start applications unless `--start` is explicitly supplied. Do not point it at the original three volumes or historical inactive archive.

Once artifacts and current owner decisions are reviewed, add `--start` on this new target or use the exact private Compose with `BTCML_BACKUP_ROOT`, `BTCML_RUNTIME_ROOT`, `BTCML_VOLUME_PREFIX`, `DOCKER_SOCKET_GID`. Project label `btcml-vps-smoke` is retained because the accepted API's service identity depends on it. A different project label would require a separately validated configuration change, not a silent rename.

There is no automatic market backfill or new T0 reset in this helper. Original books, offsets, financial provenance and operating policy are retained. Real startup may correctly wait/block on current source freshness/admission. Let the actual producer publish its own descriptor; do not fabricate INIT/permission, source pins or approvals.

## Verify on the target

Check 14 actual services/images against `CONFIG/restore_release_manifest.json`, their startup commands/user/mounts and current timestamped outputs. Confirm original WAL/checkpoint relationships and no duplicate writer. Inspect Paper implementation/release provenance separately from historical financial anchor, child observer/descriptor, Manager command/ACK flow and Intrabar observations. Inspect each TF's own source publication. Health/RUNNING alone does not prove market freshness, PAPER entry eligibility or qualification.

Keep REAL disabled through the saved config and actual application guards. Do not force OPEN, clear queues, skip cursors, discard WAL tails or reuse old capture as current genuine input. Follow `OPERATIONS/BTCML_DEPLOYMENT_AND_OPERATIONS_071126.md` for cold/normal/partial restart and controlled stop.

## Archive representation

Volumes are standard `tar.zst` with a terminal gzip JSONL index. Exact duplicate file content may be stored as a tar content link, explicitly distinct from an original filesystem hardlink. The supplied `restore_component.py` materializes independently mutable copies for content-dedup aliases, preserves genuine hardlinks, restores symlink text and normalizes original saved ownership/metadata. Do not substitute a plain tar extraction that would incorrectly couple independent files. V1/V2/V3 journals themselves are unchanged.

The root `SHA256SUMS` covers regular saved files; link text hashes are in the corresponding indexes. Manifest and checksum-list digests are recorded outside their own hash cycle in the storage seal. A matching saved artifact is not proof of post-cut live state or a historical durable ACK that never existed.
