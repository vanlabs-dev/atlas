# fleet — subnet repository fleet tracking

OpenSpec change `subnet-repo-fleet`: a chain-driven reconciliation layer
over the singleton `repotrack` tracker. The chain is the desired state
(for each netuid, the on-chain `SubnetIdentity.github_repo`); a local
registry + a fleet of clones under gitignored `var/fleet/` are the actual
state. Each pass clones what is new, updates what exists, re-points what
churned, and discards what deregistered — reusing repotrack's journaled
update primitives and never building, testing, or executing subnet code.

Downstream uses of the maintained clones (search, diffing, alerts) are
out of scope here; this delivers the self-healing, change-tracked fleet
those features build on.

## Identity source (the "on chain detail") — discovery-gated

The desired map comes from the live-data TaoStats subnet-identity
operation (`GET /api/subnet/identity/v1`, paginated) →
`netuid → { github_repo, subnet_name, owner }`. Per the live-data
"discovery gates adapter construction" rule, that operation is built only
after `livedata/discover_taostats.py` samples the endpoint under the
free-tier budget and the operator records the contract in
`docs/decisions.md`. Provenance is **TaoStats-reported chain identity at
block B**, not chain-verified.

Until that gate is complete, `reconcile` has no automatic source and fails
closed; seed or drive a pass manually with `--identity-file` (a bare list
of `{netuid, github_repo, owner_ss58, subnet_name}` or a full live-result
envelope).

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

## Commands

```
python3 fleet/atlas_fleet.py status                       # registry summary
python3 fleet/atlas_fleet.py reconcile --identity-file F   # manual / seed pass
python3 fleet/atlas_fleet.py reconcile --max-new N         # override per-pass bound
python3 fleet/atlas_fleet.py reconcile                     # auto source (pending §1)
```

`GITHUB_TOKEN` (optional) is read from the 0600 `.env`, injected per git
invocation via `GIT_CONFIG_*` (never argv, never the clone's on-disk
config), and registered for redaction. Absent, the fleet clones
anonymously with a smaller per-pass budget.

## Scheduling — every 6h, independent of repotrack

Unit files in [systemd/](systemd/); installation needs sudo:

```
sudo cp ~/atlas/fleet/systemd/atlas-fleet.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-fleet.timer
```

Verify with `systemctl list-timers atlas-fleet.timer` and
`python3 fleet/atlas_fleet.py status`.

## Before enabling — operator decisions

1. Run the live-data discovery gate for `subnet/identity` and record the
   contract approval in `docs/decisions.md` (unblocks the automatic
   source and the pinned schema).
2. Record the once-off fleet **tracking-policy** confirmation in
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
