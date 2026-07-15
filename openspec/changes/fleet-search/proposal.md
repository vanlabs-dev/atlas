## Why

The `subnet-repo-fleet` change maintains ~104 blobless subnet code clones on
the Pi (`var/fleet/clones/<netuid>/`), self-healing and change-tracked — but
its own proposal deferred every downstream use of those clones. Hermes can
full-text search the single subtensor clone (`atlas-repo`'s `repo_search`) yet
is blind to all the subnet source it now has on-device. This change gives
Hermes the same code-search evidence over the whole fleet, so it can answer
"how does subnet N implement X" from the tracked source instead of guessing.

## What Changes

- Add a **shared FTS5 index** over the fleet clones, scoped by `(netuid, epoch)`
  in `var/fleet/fleet.db`, generalizing repotrack's proven `files` / `files_fts`
  pattern. `UNIQUE(netuid, path)` lets every subnet keep its own paths; epoch
  scoping keeps a recycled netuid's two projects from ever mixing in results.
  A per-slot `index_state` row tracks indexed SHA / schema / file count.
- Add `fleet/atlas_fleet_index.py` (new module): `index_slot`, `purge_slot`,
  `search`, `index_freshness`. Reuses repotrack's pure `_indexable` /
  `_walk_tree` / `local_sha` helpers via a lazy import — no `run_index` fork.
- **Index inline on reconcile**: `atlas_fleet.py` calls the indexer at its
  existing clone / update / repoint / discard hook points (feeding an update's
  changed paths straight in for incremental indexing; full walk on clone /
  repoint; purge on repoint's old epoch and on discard). Indexing is **per-slot
  fail-closed** — an unreadable repo is recorded and skipped, never failing the
  reconcile pass. This adds calls only; the reconcile logic is not forked.
- Add a standalone `python3 fleet/atlas_fleet.py index [--netuid N] [--rebuild]`
  command to **backfill the 104 already-cloned slots** (they will not re-clone,
  so they need this) and to repair / rebuild on demand.
- Broaden the index file filter to polyglot subnet code (config-driven in
  `fleet/config.json`), reusing repotrack's extension-allowlist + `max_file_bytes`
  + binary-sniff `_indexable`.
- Add `fleet/atlas_fleet_server.py` (new module): a read-only MCP server
  `atlas-fleet` with three tools — `fleet_search(query, netuid?, max_results?)`,
  `fleet_file(netuid, path, start_line?, end_line?)`, `fleet_status(netuid?)` —
  structurally a clone of `atlas_repo_server.py`. Hermes registration is an
  operator action.

## Capabilities

### New Capabilities
- `fleet-search`: A read-only, provenance-cited full-text search surface over
  the maintained subnet-repo fleet — a shared `(netuid, epoch)`-scoped FTS index
  kept in step with reconcile, plus the `atlas-fleet` MCP tools that query it.

### Modified Capabilities
<!-- None. The reconcile-indexing hook is a requirement OF fleet-search, not a
     change to subnet-repo-fleet's requirements; the fleet's clone/update/
     epoch behavior is unchanged. -->

## Impact

- **New code**: `fleet/atlas_fleet_index.py`, `fleet/atlas_fleet_server.py`,
  `fleet/tests/` additions.
- **Minimal edits**: `fleet/atlas_fleet.py` (indexer hook calls at existing
  reconcile actions; new `index` subcommand), `fleet/config.json` (an `index`
  block with the polyglot extension allowlist + `max_file_bytes`).
- **Store**: additive index tables in the existing `var/fleet/fleet.db`
  (`fleet_files`, `fleet_files_fts`, `index_state`), created by the indexer via
  `CREATE TABLE IF NOT EXISTS`; `atlas_fleet.py`'s `SCHEMA_SQL` is untouched.
- **Reuse, not fork**: repotrack's pure indexer helpers and the fleet's
  `setup_clone` / `update_clone` public surface are consumed as-is; the subtensor
  singleton (`repotrack`) and the reconcile pipeline are unchanged.
- **Operator actions**: run `fleet index` once to backfill, then register
  `atlas-fleet` in the Hermes MCP config alongside `atlas-repo`.
- **Dependencies**: none new (stdlib + SQLite FTS5, already relied on).
