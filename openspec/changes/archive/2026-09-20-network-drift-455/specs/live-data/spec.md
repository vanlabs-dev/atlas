## MODIFIED Requirements

### Requirement: Netuid-keyed economic parameters are watched for per-subnet transitions

The live-data component SHALL extend its chain-parameter watch to cover
storage items that are keyed by netuid rather than global, recording one
observation per subnet per pass and emitting a transition when a subnet's
value differs from its own most recent previously recorded value.

The watch set SHALL include the miner registration collateral lock share,
which governs how much of a subnet's registration price is locked as
recoverable-only-by-earning collateral rather than burned. The mechanism is
live in the runtime and currently unset network-wide, so the first
observation of each subnet SHALL seed history without emitting a transition,
and a later nonzero value SHALL emit one.

The watch set SHALL also include the per-subnet **pool-side emission
switch**, a root-settable boolean that decides whether a subnet receives TAO
injection at all. It is NOT the emission-gate bar: the bar is a continuous
function of demand share, while this switch is binary and moves only when a
root-origin call writes it. A subnet with the switch off keeps distributing
alpha to its participants but its TAO-side share is zeroed and redistributed
across the subnets whose switch is on, so a subnet with substantial demand
share can earn no TAO at all. Because the switch is invisible in every other
recorded figure, an unwatched transition is indistinguishable from the market
and SHALL therefore be watched.

The switch SHALL be read in the same batched read at the gate poll's
finalized block as the other netuid-keyed items, adding no provider call. A
subnet with no entry for the switch SHALL be recorded as off, because the
runtime treats an absent entry as disabled, and that state SHALL be
distinguishable in the record from a read that failed.

A per-subnet transition event SHALL carry the netuid, the previous and new
values, and the reference block. A failed read for one subnet SHALL NOT
prevent the remaining subnets from being recorded.

#### Scenario: Dormant parameter seeds without a transition

- **WHEN** a netuid-keyed watched item is observed for the first time and is
  unset across every subnet
- **THEN** history is seeded for each subnet and no transition is emitted

#### Scenario: A subnet enabling collateral emits a transition

- **WHEN** a subnet's collateral lock share changes from unset to a nonzero
  value
- **THEN** a transition event is recorded carrying that netuid, both values,
  and the reference block

#### Scenario: First observation of the emission switch seeds every subnet

- **WHEN** the pool-side emission switch is observed for the first time
- **THEN** every subnet's state is seeded, including subnets with no entry
  recorded as off, and no transition is emitted

#### Scenario: A root flip of the emission switch emits one transition per subnet

- **WHEN** a subnet's pool-side emission switch changes between passes
- **THEN** a transition event is recorded for that netuid carrying both
  values and the reference block, whatever the subnet's demand share or
  miner burn

#### Scenario: A batch flip records every affected subnet

- **WHEN** one pass observes the pool-side emission switch changed for many
  subnets at the same reference block
- **THEN** a transition event is recorded for each affected netuid, each
  carrying that same reference block

#### Scenario: An absent switch entry is off, not unread

- **WHEN** a subnet has no stored entry for the pool-side emission switch
  and the batched read otherwise succeeded
- **THEN** that subnet is recorded as off rather than as a failed read

#### Scenario: One unreadable subnet does not blind the rest

- **WHEN** one subnet's watched value fails to decode
- **THEN** that subnet records nothing and every other subnet's observation
  is persisted

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

Including subnets whose pool-side emission switch is off is correct and
SHALL NOT be changed: the chain selects the bar over the share distribution
first and applies that switch afterwards, zeroing and redistributing the
TAO side only. A subnet that earns no TAO still sits in the distribution the
bar is drawn from.

The chain's own emit-to set is narrower than the panel's non-root set in one
respect: it also requires a subnet to have a recorded first-emission block,
to have its subtoken enabled, and to allow network registration. The
component SHALL record that its normalization universe is the panel's
non-root set rather than that filtered set, and SHALL treat the difference as
accepted rather than unknown: the excluded subnets carry small shares, and
the rank cross-check is the standing measure of whether the deviation has
grown material. A cross-check divergence beyond tolerance SHALL be read as a
possible universe divergence and not only as a panel fault.

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

#### Scenario: The recorded universe is the panel's non-root set

- **WHEN** the normalization universe is reported alongside a pass
- **THEN** it is stated as the panel's non-root priced set, naming the
  chain's additional emit-to filters as an accepted deviation

#### Scenario: Zero price is a gap, not a crossing

- **WHEN** a subnet previously above the bar reports a zero or missing moving
  price in one pass
- **THEN** no crossing is recorded for that pass, the subnet's side is
  unchanged, and the pass counts toward its absence threshold

#### Scenario: No panel, no shares

- **WHEN** the subnets panel is unavailable or invalid for the pass
- **THEN** no shares are computed and no gate events are recorded for that
  pass
