# Offline historical cleanup-path restoration

These helpers restore archived duplicate paths only. They never start applications, replay events, create ACK, change qualification or publish permissions. Default is plan-only; --write requires an explicit destination root and refuses existing files. SHA/size are checked before exclusive publication. Original mode, mtime and saved xattrs are restored; original UID/GID remain in the index and are not silently forced. Inode/ctime are not historical receive-time evidence.

Use the private maps in BTCML_STORAGE_MANIFEST/CLEANUP_20261108: SAFE_BACKUP_DATA_RESTORE_MAP.private.jsonl.gz and INACTIVE_BACKUP_PAYLOAD_RESTORE_MAP.private.jsonl.gz. Those maps and original payloads are not published in Git.

For one path, btcml_restore_cleanup_path.py can read a direct keeper or an explicitly regular archive member. It is not a general tar-content-link resolver. The new archive-backed table subset was checked against exact regular payload entries of the already fully verified sealed main/legacy file index.

For a large batch, restore each required main/legacy component ONCE into a new empty offline target using the unchanged sealed BTCML_BACKUP_071126/RESTORE/restore_component.py and the prerequisites in the main restore guide. This existing component restorer handles its original content-link/hardlink representation. Arrange the outputs as MATERIALIZED/main and MATERIALIZED/legacy, then pass --materialized-components MATERIALIZED to btcml_restore_cleanup_batch.py. It reads exact bytes there and materializes independent destination files according to original aliases. Do not rescan a multi-GB archive for every path.

This revision checked one actual archive payload, one direct-keeper payload and one-path batch plumbing, including overwrite refusal. It did not restore the whole historical tree or run a second trading stack. A source-bound retained capture needs its complete original inventory/root and all original conditions before its original reader can be used. Copying files never grants earlier availability or a new LIVE S0.
