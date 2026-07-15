## Context

`subnet-repo-fleet` maintains ~104 blobless subnet clones under
`var/fleet/clones/<netuid>/`, tracked in `var/fleet/fleet.db` (`slots` keyed by
netuid → fingerprint, **epoch**, status, `default_branch`, `local_sha`). The
blobless clones are `--no-checkout` then `checkout <default_branch>`, so the
default-branch working tree **is materialized on disk** — readable exactly like
repotrack's single subtensor clone.

`repotrack` already proves the search pattern for one repo:
- `atlas_repo.py` — `files` + `files_fts` (FTS5), `run_index` (full / incremental
  / rebuild), and pure helpers `_indexable` (extension allowlist + `max_file_bytes`
  + binary sniff), `_walk_tree`, `local_sha`, `working_tree_dirty`.
- `atlas_repo_server.py` — read-only stdio JSON-RPC MCP server: `repo_search`
  (FTS `MATCH` + `bm25` + `snippet`, path + SHA provenance), `repo_file`
  (bounded, staleness-guarded), `repo_status`. Structured errors, fail-closed,
  size-capped redacted audit jsonl, store opened `mode=ro`.

Constraint from the task: **keep the subtensor singleton and the reconcile
pipeline untouched** — reuse via the public surface, do not fork. `run_index` is
inherently single-repo (whole-table `DELETE` on rebuild, `UNIQUE(path)`, one
`meta` indexed SHA), so a shared multi-repo index cannot call it verbatim, but
its *pure* helpers are directly reusable.

The fleet is **already deployed with 104 clones**; they will not re-clone, so an
explicit backfill path is mandatory.

## Goals / Non-Goals

**Goals:**
- A read-only, provenance-cited FTS surface letting Hermes search subnet source
  across the whole fleet, or scoped to one netuid.
- Generalize repotrack's `files`/`files_fts` pattern into one shared index that
  scales across ~104 repos with unified cross-subnet ranking.
- Keep the index in step with reconcile automatically; make backfill/repair an
  explicit operator command.
- Preserve every fleet invariant: read-only, per-slot + global fail-closed,
  provenance-cited, never build/execute subnet code, epochs never mix.

**Non-Goals:**
- Diffing / change-alerts over the fleet (`fleet_changes`-style surfacing of
  recorded ranges) — a sibling feature, explicitly deferred by the fleet
  proposal. This change is *search*.
- Any change to the subtensor singleton (`repotrack`) or to the reconcile
  clone/update/epoch logic.
- Semantic / embedding search, cross-branch indexing (only the checked-out
  default branch is indexed), or indexing historical blobs.

## Decisions

### D1 — One shared `(netuid, epoch)`-scoped index (not per-repo)
A single index in `var/fleet/fleet.db`:
```sql
CREATE TABLE fleet_files (
    id INTEGER PRIMARY KEY, netuid INTEGER NOT NULL, epoch INTEGER NOT NULL,
    path TEXT NOT NULL, indexed_sha TEXT NOT NULL, byte_size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL, UNIQUE (netuid, path));
CREATE VIRTUAL TABLE fleet_files_fts USING fts5(path, content);  -- rowid = fleet_files.id
CREATE TABLE index_state (
    netuid INTEGER PRIMARY KEY, epoch INTEGER NOT NULL, indexed_sha TEXT NOT NULL,
    indexer_schema TEXT NOT NULL, files INTEGER NOT NULL, indexed_at TEXT NOT NULL);
```
Search reuses repotrack's exact join, adding an optional netuid filter and
cross-subnet `bm25`:
```sql
SELECT ff.netuid, ff.path, ff.indexed_sha,
       snippet(fleet_files_fts, 1, '>>', '<<', ' … ', 24)
FROM fleet_files_fts JOIN fleet_files ff ON ff.id = fleet_files_fts.rowid
WHERE fleet_files_fts MATCH ?  [AND ff.netuid = ?]
ORDER BY bm25(fleet_files_fts) LIMIT ?;
```
The server enriches each hit with the slot's `github_repo` (join `slots` on
netuid) for provenance. `index_state` is the per-slot analogue of repotrack's
single `meta` indexed SHA: it drives incremental-vs-full and `fleet_file`
staleness.

*Why over per-repo:* `fleet_search(query)` with no netuid ranks across all
subnets with one `bm25` query and one `mode=ro` connection, and the server can
join index rows to slot metadata in-process. Per-repo DBs would force a
104-way fan-out with no global ranking and 104 connections per search.
*Cost:* cannot call `run_index` verbatim — but its pure helpers are reused, so
no logic is duplicated.

*Why co-locate in `fleet.db` (not a separate `fleet_index.db`):* the server
needs slot metadata (`github_repo`, `local_sha`, `default_branch`, `status`)
*and* index rows for every tool; one file = one `mode=ro` connection with
in-query joins. Precedent: repotrack keeps `files`/`files_fts` in the same
`repotrack.db` as everything else. The indexer owns its tables via
`CREATE TABLE IF NOT EXISTS`, so `atlas_fleet.py`'s `SCHEMA_SQL` is untouched.

### D2 — Hybrid indexing: inline on reconcile + standalone command
- **Inline**: reconcile keeps the index in step with the clone actions it
  performs. `clone`/`repoint`(active) → full walk of the new tree; `update` →
  incremental from the change range; `repoint`/`discard` → purge. The update
  path already computes the change range (`update_clone` → `range_data`), so
  incremental indexing reuses it — the intended `collect_range`-style reuse.
- **Standalone**: `python3 fleet/atlas_fleet.py index [--netuid N] [--rebuild]`
  reindexes active slots whose `index_state` is missing, whose `indexed_sha !=
  slots.local_sha`, or whose indexer schema bumped (or everything with
  `--rebuild`). Backfills the 104 existing clones and repairs. Passes stay
  light (index only what changed); backfill is the deliberate one-time full
  pass — matching the operator-run-backfill model.

*Incremental is only sound in one case* (mirrors repotrack update, `atlas_repo.py`
lines 776–783, and `run_index`'s own guard line 522): a **clean fast-forward**
update with a **complete (non-truncated) changed-path list**, against a slot that
**already has a current-schema index at this epoch**. Every other case falls back
to a **full walk**:
- `files_truncated` (range > `MAX_FILES_RECORDED`) — the path list is incomplete.
- `not fast_forward` (history rewritten → deterministic reset) — paths don't
  describe the net tree delta reliably.
- `record-failed` update (clone advanced to `new_sha` but `update_clone` returned
  no `range`) — no path list at all.
- No `index_state` for the netuid, or a bumped indexer schema, or an epoch change
  — no valid baseline to patch (covers the deployed-but-unindexed 104 and re-points).
- `no-change` update — **no index work at all** (the slot is already at its
  indexed SHA; unindexed standing slots are covered by backfill, not by walking
  every unchanged repo every pass).

`index_slot(conn, netuid, epoch, clone_dir, index_cfg, changed_paths=None,
local_sha=None)` implements this: it short-circuits to a no-op when
`index_state` already matches `(local_sha, epoch, schema)`; else picks
**incremental** iff `changed_paths` is given AND a current baseline exists,
otherwise **full** (which first deletes the netuid's rows — scoped, never a
whole-table wipe — then walks). All DELETE/INSERT are scoped by netuid.

### D2a — Integration seam: `_apply_action` returns an index directive
Reconcile must commit the slot transition durably **before** indexing, and an
index failure must roll back **only** the index — never the clone/update it
recorded (mirrors repotrack committing the change record at line 774, then
indexing in a separate try/rollback at 785–787). So:
- `_apply_action` does slot writes **and cheap purges in the same transaction**:
  a `discard` purges the netuid's index rows alongside the slot delete, and a
  `repoint` purges the prior epoch's rows alongside closing the old epoch — so
  no search ever returns a hit for a gone slot/project (no orphan window).
- For the **expensive walk** (`clone`/`repoint`/`update` full or incremental),
  `_apply_action` returns an **index directive** (`netuid`, `epoch`, `clone_dir`,
  `changed_paths`, `local_sha`). The reconcile loop `commit()`s the action, then
  runs the directive via the indexer inside its own `try/except` that
  `rollback()`s the index and records `index-failed` on any error, then commits.
  A dead/unreadable repo therefore never fails the pass and never loses the slot
  transition — the per-slot fail-closed contract, extended to indexing.

### D3 — Index staleness is observable and self-correcting
An inline index that failed or was skipped leaves `index_state.indexed_sha !=
slots.local_sha`; `fleet_file` refuses to serve that slot (staleness guard),
`fleet_status` reports it stale, and the next successful update or a `fleet index`
run repairs it. The store is never left claiming currency it cannot prove.

### D4 — File filter reuses `_indexable`, broadened for polyglot code
`fleet/config.json` gains an `index` block; the indexer passes it to repotrack's
`_indexable`. Extensions broadened beyond subtensor's Rust-centric list to:
`.rs .toml .md .py .js .ts .tsx .jsx .go .sol .move .vy .java .rb .c .h .cpp
.hpp .sh .yml .yaml .json .txt .cfg .ini .proto`, `max_file_bytes` 512 KiB. The
size cap + binary sniff naturally drop lockfiles/minified bundles; no name-pattern
exclusion in v1 (YAGNI). Blobless clones already cap tracked files (`caps.max_files`
50000) and per-file size, bounding total index growth.

### D5 — Three-tool read-only MCP server, cloning `atlas_repo_server.py`
`fleet/atlas_fleet_server.py`, server name `atlas-fleet`:
- `fleet_search(query, netuid?, max_results?)` — global or netuid-scoped FTS;
  hits cite `netuid + github_repo + path + indexed_sha + snippet`; zero hits →
  structured `no-fleet-evidence`. The query is tokenized through repotrack's
  `_TOKEN` allowlist regex and rebuilt as `"tok" OR "tok"` so FTS5 operators in
  the query can never inject or error the MATCH (parity with `repo_search`); a
  supplied `netuid` is validated as a positive integer.
- `fleet_file(netuid, path, start_line?, end_line?)` — bounded read from
  `clones/<netuid>/`; `netuid` validated and its slot must exist; path-escape
  guarded (`realpath` prefix check); served only while that slot is `active`,
  tree-clean, and `index_state.indexed_sha == <clone's live local SHA>` (read
  live, as repotrack does — not the persisted `slots.local_sha`, which can lag a
  concurrent pass); else a structured staleness/unavailable refusal.
- `fleet_status(netuid?)` — `fleet_status()` summary + index coverage (indexed /
  stale slot counts, total indexed files); per-netuid detail when given (status,
  `local_sha`, indexed SHA, stale bool, file count). Reports stale/unavailable,
  never falsely current.

Same scaffolding as atlas-repo: stdlib JSON-RPC over stdio, structured errors
(category / component / retry_safe / correlation id), store `mode=ro`,
fail-closed when the index is absent (`fleet-search-unavailable`), and one write
only — the size-capped redacted `var/fleet/tool-audit.jsonl`.

## Risks / Trade-offs

- **Concurrent reconcile writes vs `mode=ro` reads** → reconcile commits per
  action, so write transactions are short; the server's `mode=ro` connection
  uses `timeout=5` and rides over them. Identical to repotrack (server reads
  `repotrack.db` while `update` writes it); no WAL divergence introduced.
- **Index staleness between reconcile passes / after backfill drift** →
  `index_state` per slot makes staleness observable; `fleet_file` refuses to
  serve when `indexed_sha != local_sha`; `fleet_status` reports stale slots. The
  operator runs `fleet index` to backfill/repair.
- **Epoch recycling mixing two projects' code** → all index rows carry `epoch`;
  `repoint` purges the old epoch before re-indexing the new one, and `discard`
  purges all epochs, so a recycled netuid never returns a prior project's files.
- **Index growth on the Pi** → bounded by the clone caps + the 512 KiB per-file
  cap + extension allowlist; expected on the order of the clone footprint's
  fraction, stored in device-local gitignored `var/`. `--rebuild` reclaims.
- **A repo's default branch is huge / mostly binary** → `_indexable` skips
  binaries and oversized files; `caps.max_files` already quarantines oversized
  trees at clone time, so they never reach the indexer.

## Migration Plan

1. Land code + tests off-device (TDD, `fleet/tests`).
2. On the Pi: `git pull`, then `python3 fleet/atlas_fleet.py index` to backfill
   all 104 active slots; verify with `fleet_status`.
3. Register `atlas-fleet` in the Hermes MCP config alongside `atlas-repo`
   (operator action). Before backfill the server fails closed as
   `fleet-search-unavailable`, so early registration is harmless.
4. No schema migration of existing tables; index tables are additive and created
   on first index run. Rollback = stop the server and drop the three index
   tables; the reconcile pipeline and clones are unaffected.

## Open Questions

None outstanding — index architecture (shared, `(netuid, epoch)`-scoped),
indexing timing (hybrid inline + standalone backfill), tool surface (three
tools), and backfill/registration order (operator runs `fleet index` first) were
settled in brainstorming.
