## Context

`repotrack/atlas_repo.py` maintains one subtensor clone: an operator-pinned
identity (ATLAS-REPO-001, confirmed in `docs/decisions.md`), a full non-shallow
clone with the push URL disabled, and a journaled `update` pipeline
(remote-identity check → clean-tree check → fetch → fast-forward or
deterministic reset, never merge → recorded change range → incremental index).
Its per-range primitives are already **injectable** — `_git(clone_dir, ...)`,
`_collect_range(clone_dir, prev, new)`, `run_index(conn, clone_dir, index_cfg,
changed_paths)`, `clone_size_bytes(clone_dir)` all take the clone path (not the
global config) as arguments. Only `setup`, `update`, `require_confirmed_identity`,
and `load_config` are bound to the singleton.

`livedata/atlas_live.py` runs the fail-closed live pipeline: a contract
discovery gate precedes every adapter, responses are typed-validated against a
pinned per-endpoint schema before exposure, quota is a persisted ledger with
headroom (TaoStats self-cap 2/min, 10k/month, 20% interactive reserve),
freshness envelopes and per-call audit records are mandatory, and failures
return `live-unavailable` rather than stale or guessed data. Adding an operation
means: a pinned schema, an entry in `config.json` `operations`, and a
post-processor in `POSTPROCESSORS`.

Confirmed during scrutiny (not assumed):
- On-chain `SubnetIdentity` carries `github_repo` (alongside `subnet_name`,
  `subnet_contact`, `subnet_url`, `discord`, `description`, `logo_url`,
  `additional`), set by the subnet owner. Example: subnet 1 (Apex) →
  `github.com/macrocosm-os/apex`.
- TaoStats exposes it at `GET /api/subnet/identity/v1` (paginated, `page` /
  `limit`, max 200), and separately `GET /api/dev_activity/latest/v1?netuid=`
  reports per-subnet GitHub activity (a later optimization, not used in the MVP).
- The netuid slot count is dynamic and grows; nothing is hardcoded to 128.

## Goals / Non-Goals

**Goals:**
- Maintain a local, continuously updated clone of every subnet that publishes a
  usable `github_repo` on-chain, keyed by netuid, with per-slot recorded change
  ranges — the substrate for later features.
- Detect and act on identity churn: repo edits, slot re-registration, and
  deregistration, without mixing distinct projects' history on one slot.
- Never destabilise the fleet on a bad chain read; never block the fleet on one
  bad repo; never execute subnet code; never blow the Pi's disk.
- Reuse the acceptance-passed repo-update primitives; leave the subtensor
  singleton untouched.

**Non-Goals:**
- No FTS indexing of fleet clones, and no Hermes/MCP surface over them (deferred
  to the feature changes that will consume the fleet).
- No Telegram alerting on fleet events (deferred).
- No change to `repotrack`'s singleton control flow, schema, or the subtensor
  identity gate.
- No local subtensor node and no `bittensor` SDK dependency — chain identity
  comes through the existing TaoStats HTTP path only.
- No `dev_activity`-gated fetching in the MVP (noted as a future optimization).

## Decisions

### 1. Chain identity source: TaoStats `subnet/identity`, behind the discovery gate

Add one live operation, `subnet_identity_taostats`
(`GET /api/subnet/identity/v1`), that returns the validated
`netuid → { github_repo, subnet_name, owner_ss58, block_reference }` map. It
runs through the **same** machinery as every other live operation: the contract
discovery gate first (`livedata/discover_taostats.py` samples the real endpoint
under the free-tier budget, records fields / nullability / pagination / the real
quota window, and the operator approves it in `docs/decisions.md`), then a
pinned `schemas/taostats/subnet-identity.v1` schema, a post-processor, quota
accounting, freshness, and an audit record. Pagination is handled by fetching
successive pages until exhausted; a page set that cannot be completed is
degraded (see Decision 3).

**Provenance is honest.** Atlas reads the identity from TaoStats, a third-party
indexer of the chain, not from the chain directly. The map is recorded as
"TaoStats-reported chain identity at block B." This is acceptable because the
worst case of a wrong value is cloning a wrong *public* repo that is never
executed, and schema-validation + freshness already guard against garbage; but
the reconciler treats the source as fallible (Decision 3), never as ground truth
that can trigger destructive action on a single read.

*Alternatives considered.* (a) `bittensor` SDK / btcli against finney — the
truest read, rejected: it adds a heavy dependency Atlas deliberately avoids and
duplicates a source Atlas already has. (b) Run the subtensor node Atlas already
clones — rejected: large resource step for one field. (c) The curated
`taostat/subnets-infos` GitHub JSON — rejected: a human-curated file, staler and
less authoritative than the API's chain mirror.

### 2. Reconciliation model: desired (chain) vs actual (registry) → bounded plan

The controller is a reconcile loop, not a tracker. Each pass:

1. Refresh the identity map (Decision 1). If degraded, **stop** (Decision 3).
2. Load the registry (actual state). Compute a per-slot plan by comparing the
   validated desired map to the registry:

```
   desired[netuid]        registry[netuid]        action
   ─────────────────      ─────────────────       ─────────────────────────────
   repo, fp=X             absent                   CLONE (new slot)
   repo, fp=X             present, fp=X, active    UPDATE (git fetch)
   repo, fp=X'            present, fp=X (≠)         REPOINT (discard + clone, new epoch)
   no github_repo         present or absent        NO-REPO (record, no clone)
   absent from desired    present                  DISCARD (deregistered)
```

3. Execute the plan, **bounded**: at most `max_new_clones_per_pass` CLONE/REPOINT
   operations per pass; UPDATE all currently-active clones (cheap fetches). The
   registry `status` per slot (`pending` → `cloning` → `active`, plus
   `no-repo` / `unreachable` / `quarantined` / `invalid-url`) makes the whole
   pass **idempotent and resumable**: an interrupted cold-start simply continues
   next pass, and re-running a completed pass is a no-op. This spreads the day-one
   ~100-clone burst across several passes and caps blast radius and GitHub
   abuse-throttle exposure.

*Why bounded + resumable rather than one big run:* cold-start is the only moment
with 100+ clones; a single unbounded pass risks a multi-hour run, partial-failure
ambiguity, and tripping GitHub's unauthenticated abuse limits. Bounding turns it
into a self-healing convergence.

### 3. Mass-discard guard: degraded identity data is inert, never destructive

DISCARD and REPOINT are the only destructive actions, and both are driven by the
identity map. A truncated, unvalidated, stale, or incompletely-paginated map
could make many subnets *look* absent or changed. Therefore removals and
re-points are acted on **only** when the identity fetch for the pass is
`status: ok`, schema-valid, within its freshness envelope, and paginated to
completion. On any degradation the pass **makes no destructive change** and
preserves last good state (the same fail-closed posture `livedata` already takes
by returning `live-unavailable`). CLONE and UPDATE of already-known-good slots
may still proceed from the registry, but a slot is never discarded or repointed
on the strength of a fetch that could be wrong. This is the single most important
safety property: it prevents a bad chain read from triggering a fleet-wide
re-clone thrash.

### 4. Identity fingerprint + epochs: one mechanism for edit, re-registration, and rename

A subnet's identity can change three ways, and the design collapses them to one
comparison:

- **Fingerprint** `fp = hash(owner_ss58 ‖ normalize(github_repo))`. It
  deliberately **excludes** `subnet_name`, so a display-name rename alone does
  **not** trigger a re-clone. **Discovery finding (2026-07-14):** the TaoStats
  `subnet/identity` endpoint does not carry the owner ss58 (it lives on
  `subnet/latest`), so the identity source supplies `owner_ss58 = None` and the
  fingerprint keys on the normalized repo URL alone. This is sufficient: a
  re-registration is a different project, which means a different `github_repo`,
  so the repo-URL change re-points the slot. The `owner ‖ repo` form is retained
  in the function so owner enrichment (a second `subnet/latest` join) can be
  added later without reworking the mechanism.
- If `fp` is unchanged → normal UPDATE (git fetch).
- If `fp` changed → REPOINT: the slot is now a different project (owner edited
  the repo, or the slot was deregistered and re-registered). Discard the old
  clone, clone the new repo, and open a new **identity epoch** for the slot.

**Epochs** keep history unambiguous. Recorded change ranges are keyed by
`(netuid, epoch)` where an epoch is `(fingerprint, first_seen_block)`. A REPOINT
closes the current epoch and starts a new one, so a downstream query over
netuid N never blends subnet-A's commits with subnet-B's after a slot recycled.
The clone directory is keyed by **netuid only** (`var/fleet/<netuid>/`) and blown
away + recreated on REPOINT — matching the operator's "discard the old repo,
switch the SN# to the new project" intent — while the epoch table preserves the
provenance trail.

### 5. Fleet clone policy: minimal footprint, never executed, reuse the primitives

The fleet's `setup`/`update` orchestration is new, but it drives repotrack's
existing injectable primitives; the subtensor singleton's `update()` is not
touched. Fleet policy differs from the subtensor policy on exactly the points the
threat model and disk budget demand:

| Aspect            | subtensor singleton        | subnet fleet                          |
| ----------------- | -------------------------- | ------------------------------------- |
| History           | full (non-shallow)         | **blobless** `--filter=blob:none`     |
| Branch            | operator-pinned (`main`)   | **remote default HEAD** (no API call) |
| Submodules        | n/a                        | **`--no-recurse-submodules`**         |
| Push URL          | disabled                   | disabled                              |
| Identity gate     | global, human-confirmed    | **per-slot skip**, policy-confirmed   |
| Size              | trusted                    | **capped → quarantine on breach**     |
| Build/test/run    | never                      | **never** (enforced, untrusted code)  |

- **Blobless** keeps disk small (full commit graph, blobs fetched on demand).
  The recorded-range step (`_collect_range` → `git diff --numstat prev..new`)
  realises only the *changed* files' blobs on demand — by design, still far
  cheaper than full history.
- **Remote default branch** avoids a GitHub API call per repo (the 60/hr
  unauthenticated API limit would die at ~60 subnets); `git clone` checks out
  the remote's default branch on its own. The resolved branch is recorded; a
  later change to the remote default is detected on reconcile.
- **URL normalization + validation** turns the free-text on-chain field
  (`org/repo`, trailing `.git`, `https://`, non-GitHub hosts, junk) into a
  canonical clone URL, or marks the slot `invalid-url` and skips it.
- **Caps → quarantine**: per-repo clone-size and file-count ceilings defend
  against git bombs and million-file repos; a breach aborts the clone, marks the
  slot `quarantined`, and moves on.
- **Never execute**: no build, no test, no hooks, no submodule fetch, no
  install. This is the hard line that makes cloning arbitrary third-party code
  safe.

*Reuse boundary:* `fleet/atlas_fleet.py` imports and calls repotrack's pure
primitives. If any needed primitive is too tightly bound to underscore-private
internals, it is promoted to a documented internal helper in `repotrack` rather
than copy-pasted (no band-aid duplication of the update pipeline). A full merge
of the two orchestrators into one is a possible future simplification but is out
of scope here to avoid destabilising the acceptance-passed singleton.

### 6. Store: one shared `fleet.db`

A single gitignored `var/fleet/fleet.db` holds the **registry**
(`netuid → github_repo (normalized), owner_ss58, fingerprint, epoch,
default_branch, status, local_sha, clone_size_bytes, first_seen_block,
last_reconciled, last_fetch_success`) and epoch-scoped **change ranges** (the
repotrack range shape, plus `netuid` and `epoch` columns). One shared store —
rather than a repotrack-style per-clone DB — is chosen because the later features
will want fleet-wide queries ("what changed across all subnets since X"), which a
single store answers directly. An `audit` table mirrors repotrack's actor/action
journalling.

### 7. Scheduling: separate timer, modest cadence, bounded work

A new `atlas-fleet.timer` runs the reconcile on its own cadence (default every
6h), **independent** of the hourly subtensor `repotrack` service. Rationale: the
`netuid → repo` map moves slowly, per-repo commit cadence does not need 1h
granularity for a substrate, and 100+ fetches should not crowd the subtensor
window. Each pass spends one-to-two TaoStats calls (identity refresh, cheap) then
a bounded set of git operations. Freshness/staleness per slot reuses the
repotrack pattern (a slot is stale after N missed cadences).

## Risks / Trade-offs

- **[Disk exhaustion on the Pi — the primary physical risk]** → blobless clones
  cut footprint by an order of magnitude vs full history; a configured disk
  ceiling stops new CLONEs and records an alert-worthy status when headroom runs
  low, so the fleet degrades to "track what fits" rather than filling the disk.
  Actual headroom is an operator input (Open Questions).
- **[A bad TaoStats read triggers destructive fleet churn]** → the mass-discard
  guard (Decision 3) makes DISCARD/REPOINT inert unless the identity fetch is
  validated, fresh, and complete; a degraded pass changes nothing destructive.
- **[Untrusted third-party code on the device]** → never built, tested, run, or
  submodule-fetched; blobless + size/file caps + quarantine bound the content;
  push URL disabled. Cloning and reading files is the entire surface, and it is
  local and read-only.
- **[GitHub throttling the Pi during cold-start]** → bounded new-clones-per-pass
  spreads the burst; an optional `GITHUB_TOKEN` (redacted, per-invocation
  header, never persisted) raises limits when present, and anonymous mode simply
  uses a smaller per-pass budget.
- **[TaoStats identity is a mirror, possibly stale/wrong]** → provenance is
  recorded as TaoStats-reported (not chain-verified); fingerprint compares owner
  + repo so transient name noise is ignored; schema validation + freshness gate
  the input; the guard makes single bad reads non-destructive.
- **[Two netuids share one repo URL]** → MVP clones per netuid (cheap when
  blobless); URL-level de-duplication is a possible later optimization, not
  needed for correctness.
- **[Blobless diff needs network at change-record time]** → true, `numstat`
  realises changed blobs on demand; this is intentional and bounded to changed
  files, and a fetch failure degrades that slot's record honestly (recorded
  `index/record failed`) without corrupting state — same posture as repotrack.

## Migration Plan

Additive and off the critical path. New module, new store, new live operation,
new timer; nothing existing changes behavior. Rollout:

1. Land code; run `livedata/discover_taostats.py` for the new identity endpoint
   off-device / on-device under budget; operator approves the contract in
   `docs/decisions.md` and the schema is pinned.
2. Operator records the once-off fleet **tracking-policy** confirmation in
   `docs/decisions.md` (the policy-level analogue of ATLAS-REPO-001: "track
   chain-reported subnet `github_repo`s under the fleet policy," not a per-repo
   confirmation).
3. `git pull` on the Pi; run the reconciler once by hand to seed a bounded first
   batch; verify the registry and a sample clone.
4. Operator installs `atlas-fleet.{service,timer}` with sudo; the fleet converges
   over subsequent passes.

Rollback is `systemctl disable --now atlas-fleet.timer` and removing
`var/fleet/`; no other component is affected. The live operation can be left in
place (it is inert unless called).

## Resolved (operator, 2026-07-14)

- **Disk budget.** Ample headroom on the Pi. `var/fleet/` is not disk-bound in
  practice; the configured disk ceiling stays in as a safety rail (stop new
  clones + `disk-limited` status) rather than a binding cap on how many repos are
  tracked.
- **`GITHUB_TOKEN`.** Supported. When present in the 0600 `.env` it is used for
  git operations (per-invocation `-c http.extraHeader`, never persisted to remote
  config, registered for redaction) to raise rate limits and smooth cold-start;
  anonymous operation remains a valid fallback with a smaller per-pass budget.

## Open Questions

- **Exact identity response fields.** `github_repo` presence is confirmed; the
  precise field names, nullability, and pagination shape are pinned by the
  discovery gate before the adapter is built (this is the gate's job, not a
  guess here).
- **Cadence + per-pass bound.** 6h / N-new-clones-per-pass are starting points
  to tune after the first on-device convergence.
- Out of scope, flagged for later changes: `dev_activity`-gated fetching (fetch
  only repos the chain reports as changed), FTS indexing, the Hermes/MCP search
  surface, and Telegram fleet alerts.
