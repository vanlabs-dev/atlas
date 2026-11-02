# Tasks

## 1. Containment helper

- [x] 1.1 Add `contained_file(root, rel)` to `repotrack/atlas_repo.py`: per-part link check from the clone's real path, real-path containment, rejects empty, `.`, `..` and leading `.git`. Verify: unit tests for a file link out, an in-clone link, a folder link, a dangling link, traversal and a plain file.
- [x] 1.2 `_walk_tree` drops symlinked files (folder links are already not descended). Verify: walk test over a tree with both link kinds.

## 2. Readers use the helper

- [x] 2.1 Repotrack `run_index` and fleet `index_slot`: a refused path is skipped and any old row for it removed. Verify: fixture remote with four committed links; full index has no link rows; incremental pass over a changed link path removes its row.
- [x] 2.2 `scan_clone_emissions` (metrics) and `seed_epoch` (signals) skip refused paths. Verify: tests with a linked econ file and a linked manifest pointing at a planted secret; nothing from the target is read.
- [x] 2.3 `fleet_file` and `repo_file` refuse refused paths with the existing `invalid` error. Verify: server tests for an in-clone link and an out-of-clone link.

## 3. Size and disk bounds

- [x] 3.1 `_head_tree_stats(clone_dir, rev)` returns file count and byte sum from one `ls-tree -r -l`, gitlinks as zero. Verify: unit test.
- [x] 3.2 `setup_clone` checks count and bytes before checkout, and free disk against `min_free_bytes` plus the tree bytes. Verify: oversized fixture quarantined with no worktree file written; low-disk fixture held.
- [x] 3.3 `update_clone` takes `caps`; after fetch it sizes the new head and checks disk before the advance; a size breach returns `quarantined` with the tree at the old head. `_persist_update` records `quarantined` without moving `local_sha`. Verify: fixture remote that grows past the cap.
- [x] 3.4 Reconcile checks disk before each update and records `disk-limited` with the slot left active. Verify: driver test with a low `disk_free`.
- [x] 3.5 Repotrack `update` checks `min_free_bytes` before fetch and records `disk-limited`, exit 1; `repotrack/config.json` gains `min_free_bytes`. Verify: update test with a patched disk probe.

## 4. Close

- [x] 4.1 Every Python suite and `npm --prefix web test` pass; `python3 tools/readme_sync.py`. Verify: command output.
- [ ] 4.2 After deploy: read-only query lists link rows in `fleet.db` and `repotrack.db`; propose the targeted purge to the operator.
