## 1. Indexer module + shared schema (TDD)

- [x] 1.1 Add `fleet/tests/test_fleet_index.py`: failing tests for
  `ensure_schema` creating `fleet_files` / `fleet_files_fts` / `index_state`
  idempotently in a fresh `fleet.db`, and asserting `atlas_fleet.SCHEMA_SQL` is
  not modified (reconcile tables still created independently).
- [x] 1.2 Create `fleet/atlas_fleet_index.py` with a lazy `_repotrack()` import
  (stdlib-pure at import, like `atlas_fleet._repotrack`), `INDEXER_SCHEMA_VERSION`,
  and `ensure_schema(connection)` creating the three tables via
  `CREATE TABLE IF NOT EXISTS` / `CREATE VIRTUAL TABLE IF NOT EXISTS`. Make 1.1 pass.

## 2. index_slot / purge_slot / freshness (TDD)

- [x] 2.1 Add tests: `index_slot` full walk indexes only allowlisted/in-size/
  non-binary files (reusing repotrack `_indexable`/`_walk_tree`), writes rows
  keyed by `(netuid, path)` carrying `epoch`+`indexed_sha`, and records
  `index_state`; two netuids sharing a path both persist; incremental
  `index_slot(changed_paths=...)` adds/updates/removes only those paths and
  restamps `index_state`.
- [x] 2.2 Add tests for the full-vs-incremental guard (mirror `run_index`:522):
  `index_slot` no-ops when `index_state` already matches `(local_sha, epoch,
  schema)`; falls back to a FULL walk when `changed_paths` is given but there is
  no current baseline (no `index_state`, epoch changed, or schema bumped); full
  mode purges the netuid's rows first (scoped, never a whole-table wipe).
- [x] 2.3 Add tests: `purge_slot(netuid)` removes all rows + `index_state` for a
  netuid; `purge_slot(netuid, epoch)` removes only that epoch's rows;
  `index_freshness(netuid?)` reports indexed vs local SHA, stale flag, file count.
- [x] 2.4 Implement `index_slot` (freshness short-circuit + full/incremental
  decision), `purge_slot`, `index_freshness` in `atlas_fleet_index.py`, scoping
  every DELETE/INSERT to the netuid. Make 2.1–2.3 pass.

## 3. search() over the shared index (TDD)

- [x] 3.1 Add tests: `search(connection, query, netuid=None, max_results)` returns
  ranked hits (FTS `MATCH` + `bm25` + `snippet`) citing netuid/path/indexed_sha;
  global search spans subnets; `netuid=` restricts to one; a re-pointed slot's
  old-epoch unique term is absent after purge; zero-match returns empty.
- [x] 3.2 Implement `search` (the join query from design.md). Make 3.1 pass.

## 4. Config: polyglot index filter

- [x] 4.1 Add an `index` block to `fleet/config.json` (`extensions` polyglot
  allowlist per design D4, `max_file_bytes` 512 KiB); update the config
  `_comment`. Wire the indexer to read it and pass to `_indexable`.
- [x] 4.2 Add a test that the shipped config `index` block loads and drives the
  filter (a `.ts`/`.go`/`.sol` file is indexed; an unlisted/oversized/binary
  file is skipped).

## 5. Inline indexing on reconcile — directive seam, per-slot fail-closed (TDD)

- [x] 5.1 Add tests in `fleet/tests` (fixture git origins): after `reconcile`, a
  cloned slot is fully indexed; a clean fast-forward `update` indexes
  incrementally from the change range and restamps `index_state`; a **truncated
  range**, a **non-fast-forward** advance, and a **record-failed** advance each
  trigger a FULL reindex (not a partial patch); a `no-change` update does no
  index work; a `repoint` purges the old epoch (old project's unique term gone)
  and indexes the new; a `discard` purges the netuid.
- [x] 5.2 Add tests for the transaction seam: the slot transition is committed
  even when indexing that slot raises (injected failure) — the recorded
  clone/update survives, only the index is rolled back, `index-failed` is
  recorded, and other slots still reconcile+index; discard/repoint purges happen
  in the slot-transition transaction (no orphan-hit window).
- [x] 5.3 Have `_apply_action` (a) do `discard` index purge and `repoint`
  old-epoch purge in the slot-transition transaction, and (b) RETURN an index
  directive (`netuid`, `epoch`, `clone_dir`, `changed_paths`, `local_sha`) for
  the walk — `changed_paths` set only on a clean, non-truncated fast-forward
  `update`; `None` (→ full) for clone/repoint/truncated/non-ff/record-failed; no
  directive for no-change or non-active outcomes. In the `reconcile` loop, after
  `connection.commit()`, run the directive via a lazy-imported indexer inside a
  `try/except` that rolls back the index and records `index-failed` on error,
  then commits. Do not fork any reconcile logic. Make 5.1–5.2 pass.

## 6. Standalone `index` CLI — backfill/repair (TDD)

- [x] 6.1 Add tests: `atlas_fleet.py index` indexes active slots missing an
  `index_state` row or whose `indexed_sha != local_sha`; `--netuid N` scopes to
  one; `--rebuild` discards+reindexes; prints a coverage summary. Backfills an
  already-cloned slot without it changing first.
- [x] 6.2 Add the `index` subcommand to `atlas_fleet.main` argparse + an
  `index_command` driver iterating `all_slots`. Make 6.1 pass.

## 7. Read-only MCP server `atlas-fleet` (TDD)

- [x] 7.1 Add `fleet/tests/test_fleet_server.py`: failing tool-contract tests for
  `initialize`/`tools/list` and each tool — `fleet_search` (global + netuid-scoped,
  provenance fields, `no-fleet-evidence` on zero match, FTS-operator query handled
  safely via allowlist tokenization, invalid netuid rejected), `fleet_file`
  (bounded read, path-escape refusal, unknown/uncloned-netuid refusal, staleness
  refusal when index != the clone's live local SHA or the tree is dirty),
  `fleet_status` (coverage + per-netuid + honest staleness).
- [x] 7.2 Create `fleet/atlas_fleet_server.py` cloning `atlas_repo_server.py`
  structure (stdio JSON-RPC, `mode=ro` store, structured errors with correlation
  ids). Reuse repotrack's `_TOKEN` allowlist tokenization for the FTS query;
  validate `netuid`; read the clone's live `local_sha` for the `fleet_file`
  staleness guard; enrich search hits with `github_repo` by joining `slots`.
  Make 7.1 pass.

## 8. Fail-closed + audit invariants (TDD)

- [x] 8.1 Add tests: every tool returns structured `fleet-search-unavailable` when
  the index tables / store are absent; every call appends a redacted, size-capped
  `var/fleet/tool-audit.jsonl` line; audit-write failure never breaks the tool.
- [x] 8.2 Implement the fail-closed guard + `AuditLog` (mirror atlas-repo). Make
  8.1 pass.

## 9. Docs + operator steps

- [x] 9.1 Update `fleet/README.md`: index architecture, the `index` command +
  backfill step, the `atlas-fleet` MCP tools, and the Hermes registration snippet
  (alongside `atlas-repo`). Note search indexing is no longer "deferred".
- [x] 9.2 Update the status/roadmap note (and the fleet memory pointer) to reflect
  fleet-search landed; record the operator steps (run `fleet index`, then register).

## 10. Validation

- [x] 10.1 Run `cd fleet/tests && python3 -m unittest discover -s .` and the
  repotrack suite; confirm all green and that repotrack/subtensor behavior is
  unchanged (no edits to `atlas_repo.py` beyond consuming its public helpers).
- [x] 10.2 `openspec validate fleet-search --strict` clean; self-review the change
  for placeholders/contradictions. Off-device tests are gate; Pi `fleet index` +
  `fleet_status` coverage is acceptance (operator).
