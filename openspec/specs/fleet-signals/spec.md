# fleet-signals Specification

## Purpose
Turn the subnet-repo fleet's recorded change ranges into operator
trading signals: a (netuid, epoch)-scoped term ledger (manifest
dependencies + model-id strings), novelty-gated narrative-cluster /
watchlist / econ-code detection queued for tiered Telegram delivery,
and an effectiveness ledger (alpha-price-in-TAO entry snapshots plus
horizon outcomes vs a fleet-median baseline) — read-only over clones,
per-range fail-closed, never executing subnet code.

## Requirements
### Requirement: Term extraction is diff-scoped, bounded, and never executes subnet code
The signals module SHALL derive terms exclusively from fleet `change_ranges`
rows past a durable extraction watermark, by diffing `prev_sha..new_sha`
restricted to the configured scan surface. It SHALL fetch only the blobs those
diffs require, SHALL never build, install, import, or execute fleet code, and
SHALL cap per-range work: a range exceeding the configured changed-file or
commit caps is processed manifests-only (model-id pass skipped) and the
truncation is recorded and surfaced as a digest line.

#### Scenario: Normal range extraction
- **WHEN** a reconcile records a change range whose `files_json` includes a manifest on the scan surface
- **THEN** extraction diffs only the matching paths, parses added lines into normalized terms, and advances the watermark past the range

#### Scenario: Giant range degrades instead of failing open
- **WHEN** a change range exceeds the configured file or commit caps
- **THEN** only manifest paths are extracted, the model-id pass is skipped, and the range is marked truncated with one digest line reflecting it

#### Scenario: Range with no scan-surface files is free
- **WHEN** a complete, fast-forward change range touches no path on the scan surface
- **THEN** no diff is run, no blobs are fetched, and the watermark still advances past the range

#### Scenario: Truncated or non-fast-forward record never takes the free path
- **WHEN** a change range's recorded file list is truncated or the range is non-fast-forward
- **THEN** extraction rebuilds the changed-path list itself with a capped `git diff --name-only` before deciding, and degrades visibly (never silently skips) if caps are exceeded

### Requirement: Scan surface v1 is manifests plus model-id strings, with noise exclusions
The v1 scan surface SHALL be: (a) dependency terms parsed from
`requirements*.txt`, `pyproject.toml`, `package.json`, `Cargo.toml`,
`setup.py`/`setup.cfg`, with lockfiles (`package-lock.json`, `yarn.lock`,
`poetry.lock`, `Cargo.lock`, `uv.lock`) excluded; and (b) model-identifier
strings matched by configured regex families over added lines in
`*.py|*.json|*.yaml|*.yml|*.toml|.env.example`, excluding `vendor/`,
`node_modules/`, and test paths. Dependency terms SHALL be normalized
(lowercased, extras and version specifiers stripped). The model-id extractor
SHALL be disableable via config without redeploy. Extracted input SHALL be
bounded as untrusted: term length and terms-per-range SHALL be capped (overflow
dropped with a digest note), and watchlist regex entries SHALL be validated at
load — an invalid pattern is skipped and surfaced in status, never a failure.

#### Scenario: Lockfile churn produces no terms
- **WHEN** a change range's only manifest-like change is a lockfile
- **THEN** no terms are extracted from it

#### Scenario: Model-id kill-switch
- **WHEN** `signals.model_ids` is off in config
- **THEN** extraction runs manifests-only and no model-id terms or events are produced

#### Scenario: Hostile manifest cannot flood the ledger
- **WHEN** a range adds more terms than the per-range cap or a term exceeding the length cap
- **THEN** the overflow is dropped, one digest note records the truncation, and the pass completes normally

### Requirement: The ledger records first adoption per (term, netuid, epoch)
The module SHALL persist, in additive tables in the fleet store, a global term
registry and one adoption row per `(term, netuid, epoch)` capturing adoption
time, commit SHA, and source file. Re-appearances of an already-adopted term in
the same `(netuid, epoch)` SHALL be ignored. Adoptions SHALL be keyed by epoch
so a re-pointed slot never inherits a predecessor project's adoptions. The
reconcile store's own schema SHALL remain untouched.

#### Scenario: Duplicate adoption ignored
- **WHEN** a term already recorded for `(netuid, epoch)` appears again in a later range
- **THEN** no new adoption row and no event are produced

#### Scenario: Epoch isolation on re-point
- **WHEN** a slot re-points and a new epoch opens for the netuid
- **THEN** terms adopted under the prior epoch do not count as adoptions of the new project, and their first appearance under the new epoch is recorded fresh

### Requirement: Epoch open seeds adoptions from current manifest state
Because change ranges are recorded only on updates, at each epoch open (first
successful clone of a slot, or a re-point) the module SHALL seed adoptions
from the clone's current manifest blobs (bounded fetch of only those files),
dated at epoch open. Seeded epoch-open adoptions SHALL be ordinary adoptions,
eligible for novelty, cluster, and watchlist evaluation.

#### Scenario: New subnet's existing terms enter the ledger at clone time
- **WHEN** a newly registered subnet's repo is cloned and its manifests already declare a qualifying term
- **THEN** an adoption is recorded for that `(term, netuid, epoch)` dated at epoch open, without waiting for the term to change in a future range

#### Scenario: Re-pointed slot is seeded as a new project
- **WHEN** a slot re-points and the new project's manifests are seeded under the new epoch
- **THEN** the new project's terms are recorded fresh and participate in detection independently of the prior epoch's adoptions

### Requirement: Novelty-gated cluster detection emits one instant event per term episode
A term SHALL qualify for clustering only while its distinct-adopter count is
below the configured novelty ceiling. When the k-th distinct netuid adopts a
qualifying term within the trailing T-day window (k, T from config), the module
SHALL emit exactly one instant-tier cluster event carrying the member netuids,
first mover, window span, and fleet-prevalence snapshot. Later adopters of the
same episode SHALL produce digest lines referencing the cluster, never repeat
instant events.

#### Scenario: Cluster fires at the k-th adopter
- **WHEN** the k-th distinct netuid adopts a qualifying term within T days of the episode's first adoption
- **THEN** one instant cluster event is emitted naming all k members and the first mover

#### Scenario: Post-cluster adopters go to digest
- **WHEN** a further netuid adopts the term after the cluster event
- **THEN** a digest line referencing the existing cluster is produced and no instant event is emitted

#### Scenario: Common terms never cluster
- **WHEN** a term's adopter count already exceeds the novelty ceiling
- **THEN** new adoptions of it produce no cluster evaluation and no instant event

### Requirement: Watchlist terms alert on first adoption
The module SHALL match normalized extracted terms against a config watchlist of
plain strings and regex patterns, emitting one instant-tier event per
`(term, netuid, epoch)` on first match, independent of novelty or clustering. A
starter watchlist SHALL ship in config for the operator to edit.

#### Scenario: Watchlist hit
- **WHEN** a subnet's change range first adopts a term matching a watchlist entry
- **THEN** one instant watchlist event is emitted for that `(term, netuid, epoch)`

### Requirement: Econ-code changes are detected by path and alerted per range with a per-netuid cooldown
The module SHALL match `files_json` paths of each new change range against
configured econ-code path patterns (reward/incentive/scoring/emission/weights
vocabulary), with the same vendor/test exclusions, and emit one instant-tier
event per matching `(netuid, change-range)` listing matched files and commit
count. Detection SHALL use recorded path metadata only (no blob fetch), and the
event SHALL be deduplicated by change-range id. After an instant econ-code
event for a netuid, further matching ranges within the configured cooldown
window (default 24 h) SHALL queue digest lines referencing the open alert
instead of paging; the cooldown SHALL suppress paging only, never recording.

#### Scenario: Reward-path commit alerts once
- **WHEN** a change range touches files matching econ-code patterns and no cooldown is active for the netuid
- **THEN** exactly one instant econ-code event is emitted for that range, listing the matched files

#### Scenario: Busy subnet is dampened, not silenced
- **WHEN** further econ-matching ranges arrive for the same netuid within the cooldown window
- **THEN** they are recorded and queued as digest lines referencing the open alert, and no instant event is emitted

### Requirement: Backfill seeds silently; calibrate reports before any send
A standalone backfill command SHALL seed the term ledger from existing clone
history over manifest paths only (bounded per repo), set the extraction
watermark to the current newest change range, and emit no events. A calibrate
command SHALL replay the seeded ledger under candidate threshold grids and
report the historical clusters each would have fired, so the operator sets
thresholds from evidence. Model-id history SHALL NOT be backfilled in v1;
instead a one-shot `seed-modelids` pass SHALL record current model-id
prevalence from the existing fleet-search file index (read-only), as seeded
adoptions that count toward the novelty ceiling but never toward a cluster
window.

#### Scenario: Backfill emits nothing
- **WHEN** backfill runs over the existing fleet
- **THEN** adoptions and terms are seeded with historical dates, the watermark is set to the newest range, and zero events are queued

#### Scenario: Calibrate is read-only reporting
- **WHEN** calibrate runs with a grid of (k, T, novelty ceiling) candidates
- **THEN** it prints the clusters each candidate would have fired historically and changes no state

#### Scenario: Seeded model-id prevalence prevents cold-start clusters
- **WHEN** `seed-modelids` has recorded a model id as widely prevalent and subnets subsequently touch it in forward ranges
- **THEN** the term is over the novelty ceiling and produces no cluster event

### Requirement: Instant events capture alpha-price context at creation
Every instant-tier event SHALL snapshot the affected subnet's alpha price in
TAO at event creation (a cluster event snapshots each member netuid), sourced
from the keyless TaoSwap subnets operation invoked through the live-data
layer's validated machinery — never a raw HTTP call, never a keyed or
quota-budgeted endpoint. At most one price fetch SHALL occur per extraction
pass, and its full per-subnet price vector SHALL be stored (config-capped
retention) so fleet baselines need no extra calls. A failed fetch SHALL leave
the snapshot pending for retry on a later pass and SHALL never delay, block,
or suppress the event or its delivery.

#### Scenario: Cluster snapshot covers all members from one fetch
- **WHEN** a cluster event with k member subnets is created during an extraction pass
- **THEN** one price fetch records entry prices for all k members and the full fleet vector is stored

#### Scenario: Price outage never blocks alerting
- **WHEN** the price fetch fails during a pass that emitted events
- **THEN** the events are queued and delivered normally with snapshots marked pending, and a later pass fills them marked late

### Requirement: Outcome horizons are measured against a fleet baseline
For each instant-tier event and each configured horizon (default 1, 7, and 30
days), the module SHALL record the subnet's alpha-price return alongside the
fleet-median return over the identical window, filled by an inline outcomes
step in the hourly hook. A subnet deregistered or price-less at horizon SHALL
be marked unavailable, never estimated. An `effectiveness` command SHALL
report, per alert class and horizon, alerted-subnet median return vs fleet
baseline with counts and pending/unavailable tallies, as read-only
measurement — the report SHALL derive no recommendations.

#### Scenario: Horizon fill compares like windows
- **WHEN** an event's 7-day horizon comes due and prices are available
- **THEN** the outcome row records the subnet's return and the fleet-median return over the same window

#### Scenario: Deregistered subnet is honest data
- **WHEN** an alerted subnet has deregistered before a horizon matures
- **THEN** that outcome row is marked unavailable and the effectiveness report counts it as such

#### Scenario: Effectiveness report is read-only
- **WHEN** the effectiveness command runs
- **THEN** it prints per-class, per-horizon medians vs baseline with counts and changes no state

### Requirement: Extraction is per-range fail-closed and inline on reconcile
Extraction SHALL run inline after each reconcile pass records its ranges, and
SHALL also be invokable standalone. A range whose diff or parse fails SHALL be
marked failed and skipped without blocking other ranges or the reconcile;
extraction failures SHALL never count as reconcile process errors. Emitted
events SHALL be queued append-only in the fleet store for the notifier, and a
status command SHALL report watermark position, ledger counts, queued events,
and failed/truncated ranges. Because the notifier scan runs in a different
scheduled unit than the fleet reconcile, queued events SHALL be delivered by
the next notifier scan (up to one scheduling cycle later); same-run delivery
is NOT required. The fleet store SHALL support this cross-process pattern
(WAL journal mode and a busy timeout), and only fleet-side processes SHALL
write to it.

#### Scenario: One bad range never blocks the pass
- **WHEN** a range's diff fails (e.g., missing objects on a re-pointed slot)
- **THEN** that range is marked failed, remaining ranges are processed, and the reconcile outcome is unaffected

#### Scenario: Events survive the unit boundary
- **WHEN** the fleet unit queues events and the notifier's next scheduled scan runs in its own unit
- **THEN** the scan delivers exactly the queued events past its watermark, at most one cycle after they were queued

#### Scenario: Concurrent reader never corrupts or blocks the writer
- **WHEN** a notifier scan reads the event queue while a reconcile pass is writing the fleet store
- **THEN** both complete without error, the reader sees only committed events, and the reader makes no write to the fleet store
