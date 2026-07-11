# repotrack — subtensor repository tracking

Phase 3 (`atlas-phase-3-subtensor-repository-tracking`): a verified,
non-shallow clone of the mainnet subtensor repository on the Pi, with a
safe journaled update process, per-range change records, an incremental
SQLite/FTS5 file index, and the read-only `atlas-repo` MCP server for
Hermes. Requirements: PRD §12.6 ATLAS-REPO-001…009, §12.10
ATLAS-TOOL-001…004.

## Identity validation (ATLAS-REPO-001) — before anything else

1. `python3 repotrack/atlas_repo.py validate-identity`
   Reports GitHub metadata for the claimed repo (canonical full name —
   a rename/transfer shows up as `moved_or_renamed` — archived flag,
   default branch, clone URL) and writes a 0600 report under
   `var/repotrack/`. Report only; no state is created.
2. The **operator** confirms owner/name, canonical clone URL, default
   branch, and which branch/release represents mainnet, and records the
   confirmation in `docs/decisions.md`.
3. Reference that entry in [config.json](config.json)
   `confirmed_decision`. Until then `setup`/`update` refuse to run —
   any uncertainty blocks setup.

Validated 2026-07-12: `RaoFoundation/subtensor` is canonical (the
historical `opentensor/subtensor` redirects to it), default branch
`main`, not archived, not a fork.

## Commands

```
python3 repotrack/atlas_repo.py setup    # full clone → var/repotrack/subtensor/
                                         #  verifies non-shallow + pinned branch,
                                         #  disables the push URL (ATLAS-REPO-002/003)
python3 repotrack/atlas_repo.py update   # journaled pipeline (ATLAS-REPO-004/005/006)
python3 repotrack/atlas_repo.py index    # full (re)build of the file index
python3 repotrack/atlas_repo.py status   # every ATLAS-REPO-007 freshness field
```

The `update` pipeline, in order: pinned remote-identity check → clean
working-tree check → `fetch` (branch + tags) → SHA recording →
fast-forward, or deterministic reset when upstream rewrote history
(recorded as non-fast-forward; never a merge) → change record (commits,
files ±, tags, labelled machine summary) → incremental index (changed
paths only; an indexer schema bump forces a recorded full rebuild).
Every run is journaled in `update_runs` with start/finish/status/error;
any failure preserves the last good state (ATLAS-REPO-008). No build or
test of subtensor is ever invoked (ATLAS-REPO-009).

## Store

`var/repotrack/repotrack.db` (gitignored, device-local): `update_runs`,
`change_ranges`, `files` + `files_fts` (FTS5), `audit`, `meta`
(fetch/index bookkeeping). Change-record summaries carry the fixed
prefix `[machine summary — not verified effect]`.

## MCP server (Hermes registration is an operator action)

`atlas_repo_server.py` — stdio JSON-RPC, four read-only tools:
`repo_search` (FTS with path + SHA provenance; zero hits return
structured `no-repository-evidence`), `repo_file` (bounded read, served
only while tree-clean and index-SHA == local SHA), `repo_changes`,
`repo_status` (reports **stale/unavailable, never falsely current**).
The store opens read-only; the server has no mutating git path and the
clone's push URL is disabled anyway. Only write: the size-capped
redacted `var/repotrack/tool-audit.jsonl` (ATLAS-TOOL-004).

Register alongside `atlas-kb`:

```yaml
# hermes config.yaml (mcp servers section)
atlas-repo:
  command: python3
  args: ["/home/pi/atlas/repotrack/atlas_repo_server.py"]
```

## Scheduling — gated on PRD §21 Q20 (open)

`update` is manual until the operator records a polling interval. When
Q20 is decided: record it in `docs/decisions.md`, set
`update_interval_hours` in config.json, and install the timer
(template below — **not installed by this change**):

```ini
# /etc/systemd/system/atlas-repotrack-update.service
[Unit]
Description=Atlas subtensor repository update
[Service]
Type=oneshot
User=pi
ExecStart=/usr/bin/python3 /home/pi/atlas/repotrack/atlas_repo.py update

# /etc/systemd/system/atlas-repotrack-update.timer
[Unit]
Description=Atlas subtensor repository update timer
[Timer]
OnCalendar=daily        # ← replace per the recorded Q20 decision
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
```

Until then, `update_interval_hours` × `stale_multiplier` only drives
the honesty policy: `status`/`repo_status` report `stale` when the last
successful fetch is older than that window.

## Re-pinning / re-sync

If the repository moves again: re-run `validate-identity`, record a new
operator confirmation, update `identity` + `confirmed_decision` in
config.json. `update` aborts on any remote-URL mismatch, so a stale pin
fails closed rather than following an unexpected remote.

## Tests (off-device)

```
cd repotrack/tests && python3 -m unittest discover -s .
```

Fixture git repos exercise every pipeline path (fast-forward, upstream
rewrite → deterministic reset, dirty-tree abort, identity-mismatch
abort, fetch failure preserving state, no-change), the index filters
and incremental/rebuild modes, and the full MCP tool contract including
fail-closed and staleness refusals. The Pi run is acceptance.
