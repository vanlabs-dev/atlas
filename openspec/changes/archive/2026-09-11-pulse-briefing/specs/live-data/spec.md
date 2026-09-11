## ADDED Requirements

### Requirement: Per-poll panel snapshot with computed demand share

Each pass that validates the TaoSwap subnets panel SHALL persist one snapshot
row per non-root subnet carrying the reference block, the computed demand
share, and the panel fields the briefing reads: moving price, spot price,
emission share and its recorded 1-day and 30-day evolution, inflow, outflow,
24-hour volume, holder count, market cap, active miners, miner burn, dereg
risk level, prune rank, immunity flag, contested and takeover-eligible flags,
and the recorded name. Fields absent from the panel SHALL persist as null,
never as zero. Retention SHALL be bounded by a configured number of days and
pruned in the same pass. A pass without a validated panel SHALL write no
snapshot rows.

#### Scenario: Snapshot written with the share

- **WHEN** a pass computes demand shares from a validated panel
- **THEN** one snapshot row per non-root subnet is persisted at the pass's
  reference block including that subnet's computed share

#### Scenario: Missing field is null

- **WHEN** a panel entry lacks one of the snapshot fields
- **THEN** that column persists as null for that row

#### Scenario: Retention prune

- **WHEN** snapshot rows are older than the configured retention
- **THEN** they are removed in the same pass and the newest rows are kept

### Requirement: Daily network vitals are persisted from keyless calls

Once per calendar day the live-data component SHALL fetch the TaoSwap network
statistics and daily TAO/USD close through the existing contract-validated
adapters and persist one vitals row carrying the upstream date, total staked
TAO, root and subnet stake, subnet stake share, new accounts, subnet
registration cost, and the TAO/USD close. The fetch SHALL count against no
TaoStats quota, SHALL follow the existing validation and freshness envelope,
and a failed or invalid fetch SHALL record a health event and persist
nothing for that day.

#### Scenario: One vitals row per day

- **WHEN** the daily vitals fetch succeeds
- **THEN** one row is persisted for that upstream date and repeated passes
  that day do not add another

#### Scenario: Invalid vitals persist nothing

- **WHEN** the vitals response fails validation
- **THEN** a health event is recorded and no vitals row is written

## MODIFIED Requirements

### Requirement: Demand shares are computed over the chain's emit-to universe from validated panel data only

The live-data component SHALL compute per-subnet demand shares as
`moving_price x (1 - miner_burn)` normalized over ALL non-root subnets in
the typed-validated TaoSwap subnets panel from the same pass;
emission-disabled subnets SHALL be included in the normalization, matching
the chain's bar computation, with `emission_is_enabled` carried as an
annotation rather than a filter. If the panel is unavailable or fails
validation, no shares SHALL be computed and no gate events SHALL be
produced for that pass. Share computation SHALL never trigger additional
provider calls beyond the existing panel poll.

A panel entry whose moving price is zero or missing SHALL remain in the
normalization universe with a zero weight, but SHALL be treated as a missing
observation for side tracking: it SHALL NOT produce a crossing to or from a
zero share, and it SHALL count toward that subnet's absence threshold. A
live subnet with a pool cannot have a zero moving price, so a zero is a gap
in the panel, not a demand reading.

#### Scenario: Shares from a valid panel

- **WHEN** a validated subnets panel is available for the pass
- **THEN** demand shares are computed over all non-root panel subnets and
  normalized to sum to 1

#### Scenario: Emission-disabled subnets stay in the universe

- **WHEN** the panel reports subnets with emission disabled
- **THEN** those subnets are included in the share normalization and their
  disabled state is carried as an annotation on any event they produce

#### Scenario: Zero price is a gap, not a crossing

- **WHEN** a subnet previously above the bar reports a zero or missing moving
  price in one pass
- **THEN** no crossing is recorded for that pass, the subnet's side is
  unchanged, and the pass counts toward its absence threshold

#### Scenario: No panel, no shares

- **WHEN** the subnets panel is unavailable or invalid for the pass
- **THEN** no shares are computed and no gate events are recorded for that
  pass

### Requirement: Gate-crossing events are durable, hysteresis-guarded, and lifecycle-safe

The live-data component SHALL track each subnet's gate side (above or below
theta) and SHALL record a durable gate-crossing event only when the
subnet's demand share exits a configured relative hysteresis band around
theta on a configured number of consecutive polls. Each event SHALL persist
the netuid, direction, share, theta, previous side, emission-enabled
annotation, and observation time; the event identity used for downstream
de-duplication SHALL be the store row id.

Each event SHALL additionally persist the theta of the previous persisted
gate observation, so a crossing carries the evidence needed to distinguish a
share that moved from a bar that moved beneath a stationary share. A crossing
SHALL NOT be described, downstream or in status output, as a demand movement
when the recorded bar movement accounts for it.

A subnet that records more than a configured number of crossings inside a
configured window SHALL be flagged as hovering. While flagged, its crossings
SHALL still be recorded and SHALL carry a hovering annotation, so downstream
consumers can summarise rather than report them individually. The flag SHALL
clear when the subnet has stayed on one side for the full window.

Lifecycle guards SHALL prevent false crossings: the first observation of a
subnet seeds its side without an event; a subnet absent from the panel for a
configured number of consecutive polls has its side cleared, and its
reappearance seeds silently; a gate-inactive to gate-active transition
re-seeds all sides silently; and a pass in which a bar-parameter transition
is recorded (a change in the effective N, q, or h) SHALL re-seed all sides
silently, recording no crossing events for that pass. A bar-parameter change
re-prices the bar for every subnet at once, so the crossings it induces are
a property of the parameter change and are reported by the chain-parameter
transition, not as per-subnet demand events. A restart SHALL NOT re-emit
events for already-recorded crossings. A disabled kill-switch SHALL skip
polling and event production entirely.

#### Scenario: Confirmed crossing records one event

- **WHEN** a subnet's share moves from above the bar to below the
  hysteresis band (or the reverse) and stays outside the band for the
  configured consecutive polls
- **THEN** exactly one gate-crossing event is recorded with direction,
  share, theta, the previous observation's theta, previous side, and its
  annotation

#### Scenario: Hovering subnet is flagged and annotated

- **WHEN** a subnet records more than the configured number of crossings
  inside the configured window
- **THEN** it is flagged as hovering and each further crossing while flagged
  is recorded with the hovering annotation

#### Scenario: Hovering flag clears after a stable window

- **WHEN** a flagged subnet stays on one side for the full window
- **THEN** the flag is cleared and its next crossing is recorded without the
  annotation

#### Scenario: Bar-parameter change re-seeds instead of storming

- **WHEN** a pass records a transition in the effective N, q, or h
- **THEN** all sides are re-seeded from the current shares and theta, no
  crossing events are recorded for that pass, and the parameter transition
  alone reports the change

#### Scenario: Wobble inside the band records nothing

- **WHEN** a subnet's share fluctuates within the hysteresis band around
  theta across polls
- **THEN** no gate-crossing event is recorded and the subnet's side is
  unchanged

#### Scenario: First observation seeds silently

- **WHEN** a subnet is observed for the first time after deploy
- **THEN** its gate side is seeded and no event is recorded

#### Scenario: Netuid reuse cannot produce a phantom crossing

- **WHEN** a subnet is absent from the panel for the configured number of
  consecutive polls and a subnet later reappears under the same netuid
- **THEN** the stored side was cleared at the absence threshold and the
  reappearance seeds a fresh side without recording an event

#### Scenario: Gate reactivation re-seeds silently

- **WHEN** the gate transitions from inactive (null/zero theta) to active
- **THEN** all sides are re-seeded from the current shares and no events
  are recorded for the transition pass

#### Scenario: Restart does not replay

- **WHEN** the component restarts after recording a crossing
- **THEN** the recorded crossing is not re-emitted and the seeded sides are
  preserved
