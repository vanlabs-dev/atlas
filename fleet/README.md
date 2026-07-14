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

## Commands

```
python3 fleet/atlas_fleet.py status                       # registry summary
python3 fleet/atlas_fleet.py reconcile --identity-file F   # manual / seed pass
python3 fleet/atlas_fleet.py reconcile --max-new N         # override per-pass bound
python3 fleet/atlas_fleet.py reconcile                     # auto source (live TaoStats subnet/identity)
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

## Status (2026-07-15)

Deployed and seeded on the Pi: **104 active blobless clones** (~851 MB),
10 unreachable (backed off), 1 invalid-url, 14 no-repo = 129 subnets. The
reconcile pipeline is accepted on-device (blobless, push-disabled,
token-safe, per-slot fail-closed all verified against real data). Search
indexing / MCP / Telegram fleet alerts remain deferred to later features.

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
