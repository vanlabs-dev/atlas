# fleet — subnet repository fleet tracking

OpenSpec change `subnet-repo-fleet`: a chain-driven reconciliation layer
over the singleton `repotrack` tracker. The chain is the desired state
(for each netuid, the on-chain `SubnetIdentity.github_repo`); a local
registry + a fleet of clones under gitignored `var/fleet/` are the actual
state. Each pass clones what is new, updates what exists, re-points what
churned, and discards what deregistered — reusing repotrack's journaled
update primitives and never building, testing, or executing subnet code.

The self-healing, change-tracked fleet is the substrate; the **fleet-search**
change (see below) builds the first downstream use — a read-only code-search
surface over the clones. Diffing / alerts remain out of scope.

## Identity source (the "on chain detail") — discovery-gated

The desired map comes from the live-data TaoStats subnet-identity
operation (`GET /api/subnet/identity/v1`, paginated) →
`netuid → { github_repo, subnet_name }`. The endpoint does **not** carry
the subnet owner ss58, so the fleet fingerprint keys on the normalized
repo URL (a re-registration is a different project with a different repo).
Provenance is **TaoStats-reported chain identity**, not chain-verified.

The automatic source is built and working: a bare `reconcile` pages the
identity map to completion (the whole ~129-subnet map is one call at
`limit=200`) and reconciles. `reconcile --identity-file` still drives a
manual/seed pass from a bare list of
`{netuid, github_repo, owner_ss58, subnet_name}` or a full live-result
envelope.

Per the live-data "discovery gates adapter construction" rule, the
endpoint contract is recorded in `docs/decisions.md`. That entry is
currently **PROPOSED**; the operator ratifies it via the on-device
`discover_taostats.py` run (identity probes included) and records the
once-off fleet tracking-policy confirmation.

## Invariants

- **Blobless clones** (`--filter=blob:none --no-checkout`): the file-count
  cap gates the tree *before* any blob is fetched; blobs for the working
  tree and for change-record diffs are fetched on demand. Full commit
  graph, not shallow.
- **Never executed**: no build, test, install, hook, or submodule fetch
  (`--no-recurse-submodules`); the push URL is disabled.
- **Per-repo caps → quarantine**: size (git object bytes) and tracked-file
  count; a breach removes the clone and marks the slot `quarantined`.
- **Per-slot fail-closed**: an unreachable, invalid-URL, oversized, or
  disk-limited repo is recorded and skipped, never blocking other slots.
  A repo that will not clone (placeholder URL, private repo the
  public-read-only token cannot see, deleted/moved) is retried with an
  escalating **backoff** (`unreachable_backoff_hours`) so it stops burning
  a clone slot every pass; a fix (new repo URL → new fingerprint) re-points
  immediately, bypassing the backoff. Per-slot failures are recorded by
  status, never counted as process errors, so the scheduled unit stays
  healthy while dead repos exist.
- **Mass-discard guard**: `discard` and `repoint` run only when the
  identity fetch is validated, fresh, and paginated to completion; a
  degraded fetch makes no destructive change and only advances known-good
  slots.
- **Identity fingerprint + epochs**: `fingerprint = hash(owner ‖
  normalized_repo)` excludes the subnet name (a rename never re-points).
  A fingerprint change re-points the slot (discard + reclone) and opens a
  new epoch; change ranges are keyed by `(netuid, epoch)` so two projects'
  history never mixes on one recycled slot.
- **Disk ceiling**: below `min_free_bytes` free, new clones are held as
  `disk-limited` and retried when space frees.

## Store — `var/fleet/fleet.db` (gitignored, device-local)

- `slots` — netuid → identity, fingerprint, epoch, status
  (`active` / `pending` / `no-repo` / `invalid-url` / `quarantined` /
  `unreachable` / `disk-limited`), branch, local SHA, size, timestamps.
- `epochs` — per-netuid identity epochs (opened/closed, block).
- `change_ranges` — repotrack's recorded range shape (commits, per-file
  ±, tags), scoped to `(netuid, epoch)`.
- `audit` — one redacted row per reconcile action.
- `fleet_files` + `fleet_files_fts` + `index_state` — the shared FTS index
  (change: fleet-search), scoped by `(netuid, epoch)`; owned by
  `atlas_fleet_index.py`, created on first index run (the reconcile store's
  own schema is untouched).

## Commands

```
python3 fleet/atlas_fleet.py status                       # registry summary
python3 fleet/atlas_fleet.py reconcile --identity-file F   # manual / seed pass
python3 fleet/atlas_fleet.py reconcile --max-new N         # override per-pass bound
python3 fleet/atlas_fleet.py reconcile                     # auto source (live TaoStats subnet/identity)
python3 fleet/atlas_fleet.py index                         # backfill/repair the search index (all active slots)
python3 fleet/atlas_fleet.py index --netuid N              # (re)index one subnet
python3 fleet/atlas_fleet.py index --rebuild               # purge + full re-walk
```

`GITHUB_TOKEN` (optional) is read from the 0600 `.env`, injected per git
invocation via `GIT_CONFIG_*` (never argv, never the clone's on-disk
config), and registered for redaction. Absent, the fleet clones
anonymously with a smaller per-pass budget.

## Search index + MCP server (change: fleet-search)

Reconcile keeps a shared `(netuid, epoch)`-scoped FTS index in step with the
clones — a new clone / re-point fully indexes the tree, a clean fast-forward
update indexes incrementally (a truncated range, a history-rewrite reset, or a
record-failed advance fall back to a full walk), and discard / re-point purge in
the slot transaction so no search ever returns a hit for a gone slot. Indexing
is per-slot fail-closed and transactionally isolated: an index error rolls back
only the index, never the recorded clone/update. The index reuses repotrack's
pure `_indexable` / `_walk_tree` / `local_sha` helpers — it does not fork
`run_index`, and it never builds, tests, or executes subnet code.

`atlas_fleet_server.py` — stdio JSON-RPC, three read-only tools for Hermes:

- `fleet_search(query, netuid?, max_results?)` — FTS across all subnets (or one
  netuid), citing netuid + repository + path + indexed SHA + snippet; zero hits
  return `no-fleet-evidence`. The query is reduced to allowlisted tokens
  (FTS-operator-safe).
- `fleet_file(netuid, path, start_line?, end_line?)` — bounded read from a
  subnet's clone, served only while the slot is active, tree-clean, and its
  indexed SHA equals the clone's live local SHA (else a staleness refusal).
- `fleet_status(netuid?)` — fleet + index coverage (indexed / stale slot counts,
  total indexed files); per-netuid detail with honest staleness.

The store opens `mode=ro`; missing store or an unbuilt index fails closed as
`fleet-search-unavailable`. The only write is the size-capped redacted
`var/fleet/tool-audit.jsonl`. Register alongside `atlas-repo`:

```yaml
# hermes config.yaml (mcp servers section)
atlas-fleet:
  command: python3
  args: ["/home/pi/atlas/fleet/atlas_fleet_server.py"]
```

Before it is useful the index must exist: run `python3 fleet/atlas_fleet.py
index` once to backfill the already-cloned slots, verify coverage with
`fleet_status`, then register the server.

## Scheduling — every 6h, independent of repotrack

Unit files in [systemd/](systemd/); installation needs sudo:

```
sudo cp ~/atlas/fleet/systemd/atlas-fleet.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-fleet.timer
```

Verify with `systemctl list-timers atlas-fleet.timer` and
`python3 fleet/atlas_fleet.py status`.

## Status (2026-07-15)

Deployed and seeded on the Pi: **104 active blobless clones** (~851 MB),
10 unreachable (backed off), 1 invalid-url, 14 no-repo = 129 subnets. The
reconcile pipeline is accepted on-device (blobless, push-disabled,
token-safe, per-slot fail-closed all verified against real data).

**fleet-search** adds the shared FTS index + the read-only `atlas-fleet` MCP
server (see above); code landed and green off-device (124 fleet tests, repotrack
unchanged). Operator steps on the Pi: `git pull`, run `python3
fleet/atlas_fleet.py index` once to backfill the 104 clones, verify with
`fleet_status`, then register `atlas-fleet` in the Hermes config. Telegram fleet
alerts / diffing remain deferred to later features.

## Before it is self-maintaining — operator steps

1. Install the timer (sudo) so passes run every 6h — see Scheduling above.
2. Ratify the **PROPOSED** `subnet/identity` discovery-gate entry in
   `docs/decisions.md` (run `discover_taostats.py` on the Pi, confirm the
   contract, flip it to approved). The automatic source already works; this
   is the recorded operator approval, not a functional unblock.
3. Record the once-off fleet **tracking-policy** confirmation in
   `docs/decisions.md` (the policy-level analogue of ATLAS-REPO-001:
   "track chain-reported subnet `github_repo`s under the fleet policy,"
   not a per-repo confirmation).

## Tests (off-device)

```
cd fleet/tests && python3 -m unittest discover -s .
```

Fixture git origins exercise the full pipeline: URL normalization and
fingerprinting, the reconcile plan + mass-discard guard + bounding, the
blobless clone policy with size/file caps and token non-persistence, the
fetch → fast-forward-or-reset update with recorded ranges, re-point epoch
segmentation, deregistration with preserved provenance, the disk ceiling,
and the status/CLI surface. The Pi run is acceptance.
