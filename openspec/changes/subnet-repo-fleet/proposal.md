## Why

Atlas tracks exactly one repository — mainnet subtensor — with an
operator-pinned identity confirmed once in `docs/decisions.md`
(ATLAS-REPO-001) and a robust journaled update pipeline (fetch →
fast-forward-or-reset → change record → index). The operator wants the same
freshness for the **subnet repositories**: keep a local, continuously updated
clone of every subnet's code repo on the Pi, so later features can read and
compare live subnet source on-device.

The subtensor design does not scale to this as-is. Its three load-bearing
assumptions all break for a subnet fleet:

- **Identity is static and human-confirmed.** A subnet's repo is not pinned by
  an operator — it is published *on-chain* in the subnet's `SubnetIdentity`
  (`github_repo`), which the owner can edit, and the netuid slot itself can be
  deregistered and re-registered by a completely different project. There is no
  way to hand-confirm ~100+ moving targets in `decisions.md`.
- **Confirmation is a global gate.** Today any uncertainty blocks the whole
  tracker. For a fleet, one malformed or unreachable repo must not stall the
  other 127.
- **The clone is full-history and trusted.** Non-shallow clones of 100+
  arbitrary third-party repos would exhaust the Pi's disk, and subnet code is
  untrusted (anyone who can register a subnet can publish a `github_repo`).

So this change is not a second tracker. It is a **reconciliation layer**: the
chain is the desired state (`netuid → github_repo`), the local clones are the
actual state, and a controller clones what is new, updates what exists,
re-points what churned, and discards what deregistered — reusing the existing,
acceptance-passed repo-update primitives underneath.

Downstream uses of the maintained clones (search, diffing, alerts) are
explicitly out of scope here; this change delivers only the self-healing,
change-tracked fleet those features will build on.

## What Changes

- Add a **TaoStats subnet-identity operation** to `live-data`
  (`GET /api/subnet/identity/v1`, paginated), behind the existing contract
  discovery gate and typed-schema validation, exposing the validated
  `netuid → { github_repo, subnet_name }` map. (Discovery confirmed the
  endpoint does not carry the owner ss58, so the fingerprint keys on the repo
  URL — see design.md.) The whole ~129-subnet map is one call at `limit=200`;
  trivial quota. The on-chain source is `SubnetIdentity.github_repo`; provenance
  is recorded as **TaoStats-reported chain identity**, not chain-verified.
- Add a new **`subnet-repo-fleet`** capability and a `fleet/` module that
  reconciles the chain identity map against a local **registry** and a fleet of
  clones under gitignored `var/fleet/<netuid>/`:
  - **Reconcile** desired-vs-actual into a per-slot plan (clone / update /
    re-point / discard). Idempotent, resumable, and **bounded** (at most N new
    clones per pass) so cold-start spreads across passes.
  - **Fail-closed per slot**: an unreachable, malformed, oversized, or
    non-GitHub repo is skipped and recorded, never blocking the fleet. The
    operator confirms the tracking **policy** once; individual repos are not
    hand-confirmed.
  - **Mass-discard guard**: removals are acted on only when the identity fetch
    is validated, fresh, and complete (all pages). A degraded fetch skips the
    pass and preserves last good state — a partial response is never read as a
    wave of deregistrations.
  - **Identity churn** (owner edited `github_repo`, or the slot was
    re-registered by a new project) is detected by a fingerprint
    `hash(owner ‖ normalized_github_repo)`; on change the old clone is discarded
    and the new repo cloned, and the slot's change history is segmented into a
    new **identity epoch** so two projects' commits never mix under one netuid.
  - **Minimal-footprint, never-executed clones**: `--filter=blob:none`
    (blobless — full commit graph, blobs on demand), the remote's default branch
    (no GitHub API call), `--no-recurse-submodules`, push URL disabled, per-repo
    size and file-count caps with quarantine on breach, and **no build, test, or
    execution of subnet code, ever**.
  - **Per-slot change records** reusing the repository tracker's recorded range
    shape (commits, per-file additions/deletions, tags, machine summary),
    epoch-scoped in a shared `var/fleet/fleet.db`.
- Add a **separate `atlas-fleet` timer** at a modest cadence (default every 6h),
  independent of the hourly subtensor service: one identity refresh, then a
  bounded set of clone/fetch operations.

Deferred to later feature changes (explicitly not built here): FTS indexing of
fleet clones, any Hermes/MCP search surface over them, Telegram alerting on
fleet events, and the `dev_activity` optimization that would fetch only repos
the chain reports as changed.

## Capabilities

### New Capabilities
- `subnet-repo-fleet`: chain-driven reconciliation of a local fleet of subnet
  code repositories — validated identity source, idempotent bounded reconcile
  with a mass-discard guard, fingerprint-based churn handling with epoch-scoped
  change history, minimal-footprint never-executed clones with per-slot
  fail-closed isolation, and scheduled bounded refresh.

### Modified Capabilities
- `live-data`: add one discovery-gated, typed-validated TaoStats operation that
  returns the `netuid → github_repo` identity map for the reconciler, under the
  same quota-with-headroom, freshness-envelope, and auditable-retention rules as
  every other live operation.

## Impact

- Code: new `fleet/` module (`atlas_fleet.py` reconciler + CLI, registry store),
  reusing repotrack's already-injectable primitives (`_git`, `_collect_range`,
  `run_index`, `clone_size_bytes`) without changing `repotrack/atlas_repo.py`'s
  singleton control flow. New `livedata` operation + pinned schema
  (`schemas/taostats/subnet-identity.v1`) + post-processor; `livedata/config.json`
  gains the `subnet_identity_taostats` operation.
- Data: new gitignored `var/fleet/` (clones) and `var/fleet/fleet.db` (registry
  + epoch-scoped change ranges). No change to `var/repotrack/` or
  `var/livedata/`.
- Config/secrets: optional `GITHUB_TOKEN` in the 0600 `.env` (redacted, used
  per-invocation via `-c http.extraHeader`, never persisted to remote config)
  to raise git rate limits; anonymous operation still works with a smaller
  per-pass budget.
- Ops: new `fleet/systemd/atlas-fleet.{service,timer}` (operator installs with
  sudo, as with the repotrack timer). Requires a `docs/decisions.md` entry for
  the discovery gate on the new TaoStats operation and for the once-off fleet
  tracking-policy confirmation.
- Physical: disk on the Pi is the primary constraint; blobless clones plus a
  disk ceiling (stop cloning new + alert) bound it. No change to the subtensor
  tracker, its schema, the notifier, or any other capability.
