# Tasks

## 1. Listing and eligibility

- [x] 1.1 `fleet/atlas_fleet_orgrepos.py`: owner parse, `org_repos` table, budgeted daily listing with back-off and 7-day bound; verify unit tests with a stubbed HTTP opener (no network)
- [x] 1.2 Eligibility: organisation only, shared-owner detection from current slots, fork/archived/90-day filter, config exclusions, `max_repos`; verify tests for macrocosm-os style sharing, a User owner and an excluded repo

## 2. History-only fetch

- [x] 2.1 Bare `--filter=tree:0` clone and fetch, disk check before each, size cap after, push URL disabled; verify tests with a local file:// remote that no working tree or blob exists
- [x] 2.2 Fleet README and config comments for the new keys; verify `python3 tools/readme_sync.py` and `tools/tests`

## 3. Combined activity

- [x] 3.1 Union by commit id in `compute_activity`, new `metric_activity` columns and `metric_activity_repos`; verify tests for a sibling-repo commit, a mirrored commit and a bot commit
- [x] 3.2 Figure-set switch read by board, classifier, dashboard, signals and export; verify `shadow` output equals the pre-change output on the same store, and `on` changes c30 and cold
  - Signals read activity only through `report()`. Checked on a read-only Pi snapshot (2026-11-04): report, board JSON and board HTML are byte-identical to the pre-change code in `shadow`, unmigrated and `on`-without-combined.
- [x] 3.3 Report CLI listing both figure sets and counted repos per subnet; verify on a test store

## 4. Deploy (operator approvals)

- [x] 4.1 Every Python suite and `npm --prefix web test` pass; commit
- [ ] 4.2 Push, Pi pull with fleet timer stopped, one pass, report reviewed with the operator (each needs a yes)
- [ ] 4.3 Operator sets exclusions and `on` in a separate commit; decision entry in `docs/decisions.md`
