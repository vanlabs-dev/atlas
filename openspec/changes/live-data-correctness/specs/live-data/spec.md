## MODIFIED Requirements

### Requirement: Rank-mode bar selection is cross-checked against the observed above-bar count

When the bar mode of a pass is `rank`, the chain pins theta to the Nth-largest
positive demand share, so exactly N subnets with positive demand sit at or
above the bar at the block where the chain recalculates theta. The live-data
component SHALL exploit this as a correctness check on its own share
pipeline: each pass in rank mode SHALL persist the count of subnets whose
computed demand share is positive and at or above the bar, alongside the
effective N, and SHALL record a health event when that count diverges from N
by more than the configured tolerance.

The tolerance SHALL be at least one. The chain holds theta fixed between
recalculations (every 360 blocks) while the moving prices keep advancing,
so between recalculations the Nth subnet sits on the bar and may count on
either side of it; a divergence of exactly one is the expected boundary
condition, not disagreement with the chain. A divergence of two or more
indicates that the share inputs, the normalization universe, or the theta
read disagrees with the chain's selection rule and SHALL be reported.

The count SHALL be taken from the pass's computed demand shares, NOT from the
tracked side state. Side tracking applies a hysteresis band that deliberately
holds a subnet on its previous side while its share sits near the bar; that
smoothing is an Atlas-side artefact and MUST NOT be able to present itself as
disagreement with the chain.

This check validates the share inputs, the normalization universe, and the
theta read together against the chain's own selection rule, without
recomputing theta locally. A divergence SHALL NOT suppress crossing events or
block persistence; it is a signal that the share pipeline and the chain
disagree, reported for the operator, not an error that discards the pass.

#### Scenario: Agreeing count passes silently

- **WHEN** a rank-mode pass observes an above-bar count within tolerance of
  the effective N
- **THEN** the count and N are persisted with the pass and no health event is
  recorded

#### Scenario: Boundary subnet does not raise an alarm

- **WHEN** a rank-mode pass observes an above-bar count of N minus one or N
  plus one
- **THEN** the count is persisted and no health event is recorded, because
  the Nth subnet sits on a bar the chain fixed at an earlier block

#### Scenario: Hysteresis cannot fake a divergence

- **WHEN** a subnet sits inside the hysteresis band and its tracked side
  therefore still reflects the previous pass
- **THEN** the above-bar count still counts it by its computed share against
  the bar, so the check reports agreement with the chain

#### Scenario: Diverging count raises a health event

- **WHEN** a rank-mode pass observes an above-bar count differing from the
  effective N by more than the configured tolerance
- **THEN** a health event records the observed count, the effective N, and
  the reference block, and the pass still persists its observation and any
  crossing events

#### Scenario: Check does not apply in q-mass mode

- **WHEN** the bar mode of a pass is `q-mass`
- **THEN** no above-bar count check is applied, because q-mass selection
  implies no fixed count

### Requirement: Per-poll panel snapshot with computed demand share

Each pass that validates the TaoSwap subnets panel SHALL persist one snapshot
row per non-root subnet carrying the chain reference block, the panel's own
reference block, the computed demand share, and the panel fields the
briefing reads: moving price, spot price, emission share and its recorded
1-day and 30-day evolution, inflow, outflow, 24-hour volume, holder count,
market cap, active miners, miner burn, dereg risk level, prune rank,
immunity flag, contested and takeover-eligible flags, and the recorded name.
Fields absent from the panel SHALL persist as null, never as zero. Retention
SHALL be bounded by a configured number of days and pruned in the same pass.
A pass without a validated panel SHALL write no snapshot rows.

The panel SHALL be checked against the chain read of the same pass before
any row is written. When the panel's block trails the chain block by more
than the configured lag, or the panel holds fewer non-root rows than the
chain has non-root registered subnets, the pass SHALL record a health event
naming the lag or the counts and SHALL write no snapshot rows. The panel's
rows SHALL never be cut to a fixed count; a panel row the pass cannot place
SHALL fail the panel, not be dropped.

#### Scenario: Snapshot written with the share

- **WHEN** a pass computes demand shares and validates a current, complete
  panel
- **THEN** one snapshot row per non-root subnet is persisted with the chain
  block, the panel block, and that subnet's computed share

#### Scenario: Lagging panel writes nothing

- **WHEN** the panel's block trails the pass's chain block by more than the
  configured lag
- **THEN** a health event records both blocks and no snapshot rows are
  written for the pass

#### Scenario: Short panel writes nothing

- **WHEN** the panel holds fewer non-root rows than the chain has non-root
  registered subnets
- **THEN** a health event records both counts and no snapshot rows are
  written for the pass

#### Scenario: No silent truncation

- **WHEN** the provider returns more subnet rows than any earlier panel
- **THEN** every row is kept and validated, and none is dropped for its
  position in the list

#### Scenario: Missing field is null

- **WHEN** a panel entry lacks one of the snapshot fields
- **THEN** that column persists as null for that row

#### Scenario: Retention prune

- **WHEN** snapshot rows are older than the configured retention
- **THEN** they are removed in the same pass and the newest rows are kept

### Requirement: Live runtime spec_version changes are recorded

The live-data component SHALL persist the last-seen live runtime `spec_version`
(with its reference block and observation time) and SHALL record a durable
upgrade event whenever a validated live chain-head response reports a
`spec_version` different from the last recorded one. The `spec_version` SHALL
be read first through keyless RPC at a finalized block, with TaoStats as
fallback only when every RPC endpoint fails. The read SHALL run on its own
hourly schedule and SHALL NOT depend on the repository update succeeding.
The upgrade record SHALL be
written only from a live, typed-validated response (never from stale or
unvalidated data) and SHALL capture the previous `spec_version`, the new
`spec_version`, the reference block, and the source used. A restart SHALL NOT
re-emit an upgrade for an already-recorded `spec_version`.

A TaoStats reading SHALL be used only when its freshness status is `fresh`.
A `spec_version` lower than the last recorded one SHALL be recorded only from
RPC; from any other source it SHALL record a health event and SHALL leave the
last-seen value, block and observation time unchanged.

#### Scenario: New live spec_version records an upgrade

- **WHEN** a validated live chain-head reports a `spec_version` different from the
  last recorded one
- **THEN** an upgrade event is persisted with the previous `spec_version`, the new
  `spec_version`, and the reference block, and the last-seen value is advanced

#### Scenario: Unchanged spec_version records no upgrade

- **WHEN** a validated live chain-head reports the same `spec_version` as the last
  recorded one
- **THEN** no upgrade event is written and the last-seen observation time is
  updated

#### Scenario: Upgrade detection never uses stale data

- **WHEN** a live chain-head request fails or its response fails validation
- **THEN** no `spec_version` upgrade is recorded and the last recorded value is
  left unchanged

#### Scenario: Aged TaoStats head is ignored

- **WHEN** a validated TaoStats chain head is older than its freshness limit
- **THEN** no `spec_version` is recorded from it and the last recorded value,
  block and observation time are left unchanged

#### Scenario: Lower spec from TaoStats is not recorded

- **WHEN** a fresh TaoStats chain head reports a `spec_version` lower than the
  last recorded one
- **THEN** no upgrade event is written, the last-seen value is unchanged, and
  a health event records both values

#### Scenario: Lower spec from RPC is recorded

- **WHEN** keyless RPC at a finalized block reports a `spec_version` lower
  than the last recorded one
- **THEN** an upgrade event is persisted with source `rpc` and the last-seen
  value is set to the lower version

#### Scenario: TaoStats down

- **WHEN** TaoStats fails and a keyless RPC endpoint answers
- **THEN** the `spec_version` is read and recorded from RPC with source `rpc`

#### Scenario: Repository update failing

- **WHEN** the repository update service fails
- **THEN** the hourly `spec_version` read still runs

### Requirement: Daily network vitals are persisted from keyless calls

The live-data component SHALL fetch the TaoSwap network statistics and daily
TAO/USD close through the existing contract-validated adapters and persist
one vitals row per upstream data date carrying that date, total staked TAO,
root and subnet stake, subnet stake share, new accounts, subnet registration
cost, and the TAO/USD close. The fetch SHALL count against no TaoStats
quota, SHALL follow the existing validation and freshness envelope, and a
failed or invalid fetch SHALL record a health event and persist nothing.

The expected newest data date is the UTC day before the pass. Each pass
SHALL fetch until a row for that date exists, so a provider that lags
between one and two days does not skip a date. A row SHALL never be
replaced: a response whose date is already stored writes nothing. A
response whose freshness status is not `fresh` SHALL write nothing and
SHALL record a health event, at most once per expected date. Dates the provider never served are not backfilled.

#### Scenario: One vitals row per day

- **WHEN** the vitals fetch returns a data date that has no row
- **THEN** one row is persisted for that date, and later passes that see the
  same date do not add or replace a row

#### Scenario: Lagging provider is retried, not skipped

- **WHEN** the provider still serves the date before the expected one
- **THEN** nothing is written, no existing row changes, and the next pass
  fetches again

#### Scenario: Expected date stored stops the fetch

- **WHEN** a row for the expected newest data date already exists
- **THEN** the pass makes no vitals call

#### Scenario: Aged vitals persist nothing

- **WHEN** the network statistics response is older than its freshness limit
- **THEN** a health event is recorded and no vitals row is written

#### Scenario: Invalid vitals persist nothing

- **WHEN** the vitals response fails validation
- **THEN** a health event is recorded and no vitals row is written

## ADDED Requirements

### Requirement: Demand shares are computed from chain storage over the chain's emit-to universe

The live-data component SHALL compute per-subnet demand shares the way the
running runtime does, from chain storage read at the gate pass's own
finalized block: each subnet's moving price (`SubnetMovingPrice`) is
weighted by `(1 - MinerBurned)`, with the burn clamped to 0..1, and the
weights are normalized over the chain's emit-to universe. That universe is
every non-root registered subnet that has a recorded first-emission block,
has its subtoken enabled, and allows network registration. A subnet outside
that universe SHALL receive no share and SHALL count as absent for side
tracking.

Emission-disabled subnets SHALL stay in the normalization, matching the
chain's bar computation, with their pool-side emission switch, read at the
same block, carried as an annotation rather than a filter. The chain selects
the bar over the share distribution first and applies that switch
afterwards, zeroing and redistributing the TAO side only. A subnet that
earns no TAO still sits in the distribution the bar is drawn from.

If the chain read fails, or any item the share needs fails for any netuid in
the universe, no shares SHALL be computed and no gate events SHALL be
produced for that pass, and a health event SHALL record the cause. The
TaoSwap subnets panel SHALL NOT feed the shares or the crossing events; an
unavailable or invalid panel SHALL NOT stop a pass that has a valid chain
read.

A universe member whose moving price is zero or unset SHALL remain in the
normalization with a zero weight, but SHALL be treated as a missing
observation for side tracking: it SHALL NOT produce a crossing to or from a
zero share, and it SHALL count toward that subnet's absence threshold.

#### Scenario: Shares from a valid chain read

- **WHEN** the gate pass reads moving prices, burns and the emit-to filters
  at its finalized block
- **THEN** demand shares are computed over the emit-to universe and
  normalized to sum to 1, and every value carries that block

#### Scenario: Subnet outside the emit-to universe gets no share

- **WHEN** a registered subnet has no first-emission block, or its subtoken
  is disabled, or it does not allow registration
- **THEN** it is left out of the normalization, receives no share, and
  counts toward its absence threshold

#### Scenario: Emission-disabled subnets stay in the universe

- **WHEN** a subnet in the emit-to universe has its pool-side emission switch
  off
- **THEN** it is included in the share normalization and its disabled state
  is carried as an annotation on any event it produces

#### Scenario: A missing burn is a failed read, not zero burn

- **WHEN** the burn of a non-root subnet in the universe is absent from the
  map or cannot be decoded
- **THEN** no shares are computed for the pass, no gate events are recorded,
  and a health event names the item and the netuid

#### Scenario: Zero price is a gap, not a crossing

- **WHEN** a subnet previously above the bar reports a zero or unset moving
  price in one pass
- **THEN** no crossing is recorded for that pass, the subnet's side is
  unchanged, and the pass counts toward its absence threshold

#### Scenario: Panel outage does not stop the gate

- **WHEN** the TaoSwap subnets panel is unavailable or invalid but the chain
  read succeeds
- **THEN** shares are computed and crossing events are recorded as usual, and
  no panel snapshot rows are written for the pass

#### Scenario: No chain read, no shares

- **WHEN** the chain read of the share items fails for the pass
- **THEN** no shares are computed and no gate events are recorded for that
  pass

### Requirement: Theta pins are checked exactly when the node still holds the state

In rank mode, when the pass's block is within the configured age of the
latest 360-block theta recalculation and the node still serves state at the
block before it, the component SHALL recompute demand shares at that earlier
block and count shares at or above the theta read at the recalculation
block. The count SHALL equal N exactly, or every positive share when fewer
than N are positive. Any other count SHALL record a health event.

#### Scenario: Exact count at the pin is silent

- **WHEN** the shares at the block before the latest recalculation put
  exactly N subnets at or above the pinned theta
- **THEN** the result is persisted with the pass and no health event is
  recorded

#### Scenario: Off-by-one at the pin is reported

- **WHEN** the shares at the block before the latest recalculation put N
  minus one or N plus one subnets at or above the pinned theta
- **THEN** a health event records the count, N, and both blocks

#### Scenario: Pruned state skips the check

- **WHEN** the node no longer serves state at the block before the latest
  recalculation, or the pass is older than the configured age
- **THEN** the exact check is recorded as skipped, no health event is
  recorded, and the hourly tolerance check still applies

### Requirement: Dense per-subnet maps treat a missing key as a failed read

Each netuid-keyed storage item in a batched read SHALL declare its coverage:
every registered subnet, every non-root registered subnet, or sparse. For a
dense item, a registered subnet with no key SHALL be recorded as a per-netuid
read failure for that item, never as the runtime default. The universe of
registered subnets SHALL come from the same block's read. Sparse items keep
the runtime default for an absent key.

#### Scenario: Missing owner is a failure, not "owns nothing"

- **WHEN** a non-root registered subnet has no `SubnetOwner` key at the read
  block
- **THEN** that netuid is reported as a failed read for the owner item and
  no consumer receives the all-zero default account for it

#### Scenario: Truncated key list is caught

- **WHEN** the key enumeration of a dense item returns fewer keys than the
  registered subnet count
- **THEN** every registered subnet without a key is reported as a failed
  read for that item

#### Scenario: Sparse item keeps its default

- **WHEN** a sparse item such as the identity name has no key for a
  registered subnet
- **THEN** the absence is reported as unset, not as a failure

## REMOVED Requirements

### Requirement: Demand shares are computed over the chain's emit-to universe from validated panel data only

**Reason**: Shares now come from chain storage at the gate block over the chain's own emit-to universe; the panel's non-root set and the "accepted deviation" no longer apply.
**Migration**: Replaced by "Demand shares are computed from chain storage over the chain's emit-to universe". Panel checks moved to "Per-poll panel snapshot with computed demand share".
