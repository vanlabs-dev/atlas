# Proposal

## Why

Subnet repositories are untrusted. Two gaps let a repository reach past
its own clone (audit B3, B8):

- The indexers, the economics scan and the signals seed open clone files
  without a link check. A committed symlink makes Atlas read whatever the
  link points at, and the index then hands that content to Hermes.
- The clone size cap runs only after checkout, and an update has no size
  cap and no disk check. One repository can fill the Pi's disk.

## What Changes

- One shared helper, `contained_file`, resolves a clone-relative path. It
  returns nothing when any part of the path is a symlink or the real path
  leaves the clone. Every reader of clone files uses it: the fleet index,
  the repotrack index, the rotation-metrics economics scan, the signals
  manifest seed, and both file-read MCP tools.
- The working-tree walk lists no symlinks. An indexer that meets a link
  path drops any old row for it.
- `setup_clone` sums the HEAD tree's file sizes before checkout and
  quarantines an oversized repository before its worktree is written. It
  checks free disk before checkout.
- `update_clone` sums the new head's tree after the fetch and before the
  advance. A breach leaves the clone at its last good head and marks the
  slot quarantined. It checks free disk before the advance.
- Reconcile checks free disk before every fleet fetch. Below the ceiling,
  updates are held as `disk-limited` and the clone keeps its last good
  state.
- The subtensor tracker checks free disk before its fetch and records
  `disk-limited` below a configured `min_free_bytes`.

## Capabilities

### New Capabilities

- `clone-file-containment`: how Atlas resolves and reads files inside
  untracked-trust clones (fleet and subtensor) without following links.

### Modified Capabilities

- `subnet-repo-fleet`: size cap measured on the tree before checkout and
  before every advance; disk ceiling applies to fetches, not only to new
  clones.
- `subtensor-repo-tracking`: update checks free disk before the fetch.
- `fleet-search`: the shared indexing helpers now skip links, so the
  indexer changes tracker behaviour in this one way; `fleet_file`
  refuses links.

## Impact

- Code: `repotrack/atlas_repo.py`, `repotrack/atlas_repo_server.py`,
  `fleet/atlas_fleet.py`, `fleet/atlas_fleet_index.py`,
  `fleet/atlas_fleet_metrics.py`, `fleet/atlas_fleet_signals.py`,
  `fleet/atlas_fleet_server.py`.
- Config: `repotrack/config.json` gains `min_free_bytes`.
- Size measure: `max_bytes` now bounds the sum of HEAD-tree file sizes,
  not git object size. The largest Pi clone measures 248 MB against a
  2 GiB cap.
- Store: no schema change, no indexer schema bump. Six existing fleet
  rows came from links; a targeted purge follows deploy with operator
  approval.
- Pi: `git pull` only. No unit change, no restart beyond the MCP servers
  loading the new read check (gateway `/restart`).
