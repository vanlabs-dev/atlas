## MODIFIED Requirements

### Requirement: Root-settable chain parameters are watched for transitions

The live-data component SHALL maintain a configured watch set of discrete
root-settable chain storage items whose value governs network economics. The
set SHALL cover the emission-gate bar parameters (`EmissionBarRank`,
`EmissionBarQuantile`, `EmissionGateExponent`), whose values are supplied by
the gate poll of the same pass, and additionally read items not covered by
the gate poll: `RootWeightSettingEnabled`, the Root Reborn basket-curation
master switch, and `RootWeightsCap`, the per-destination concentration cap
on a root weight vector, observed at the root netuid entry. Each
independently read item SHALL be configured with its pinned pre-verified
storage key, its decoder (unsigned integer or boolean), its documented
per-runtime default, and a short description of what the parameter governs.
A netuid-keyed item in this set SHALL have its key derived for the named
entry with the hasher the chain declares for that item, and the derivation
SHALL be self-tested in the same way as the other derived keys. A boolean
decoder SHALL reject a payload that is the correct length but is neither the
encoded true nor the encoded false value.

This watch SHALL be the single durable record of bar-parameter change; a
transient in-memory change flag SHALL NOT be relied on as the record of a
parameter transition.

Independently read items SHALL be read against the same finalized block hash
as the gate poll when the gate poll runs in that pass. The watch SHALL NOT be
gated by the emission-gate kill-switch: when the gate signal is disabled, the
watch SHALL still run over its independently read items, obtaining its own
finalized block hash, so a curation-switch flip is not missed while the gate
signal is rolled back.

Each pass SHALL persist one observation per watched item carrying the decoded
value, its provenance (`explicit` or `assumed-default` for a null read), the
reference block, and the observation time. A failed or malformed read of one
independently read item SHALL record a health event and persist nothing for
that item, without preventing the other items in the pass from being
persisted: one unreadable knob does not blind the rest.

Because watched values are discrete, a transition SHALL be recorded whenever
a persisted observation's value differs from the most recent previously
persisted value for that item; no hysteresis, confirmation window, or
tolerance band applies. The first ever observation of an item SHALL seed its
history without recording a transition, since there is no previous value to
differ from. A transition event SHALL carry the item, the previous and new
values, both provenances, and the reference block. A provenance change alone
(`assumed-default` to `explicit`) at an unchanged value SHALL be recorded in
the observation history but SHALL NOT be emitted as a value transition.
Transition events SHALL be durable and SHALL NOT be re-emitted across
restarts, and SHALL never be written from an unvalidated read.

#### Scenario: Bar parameters are recorded without a second read

- **WHEN** a pass persists a gate observation
- **THEN** the effective N, q, and h of that observation are persisted as
  watched-item observations at the same reference block, with no additional
  storage read

#### Scenario: Independently read items share the gate poll's block

- **WHEN** the gate poll runs in a pass and obtains a finalized block
- **THEN** every independently read watched item is read at that same block
  hash and persisted with that reference block

#### Scenario: Root weights cap is observed at the root entry

- **WHEN** a pass runs the watch
- **THEN** `RootWeightsCap` is read at the root netuid entry through its
  derived key, decoded as an unsigned 16-bit integer, and persisted with its
  provenance; a null read persists the documented default as
  `assumed-default`

#### Scenario: Derived key for a netuid-keyed watch item is self-tested

- **WHEN** the watch derives the storage key for a netuid-keyed item
- **THEN** the derivation is checked against the pinned pre-verified keys
  before any read, and a mismatch blocks the read and records a health event

#### Scenario: Watch survives the gate kill-switch

- **WHEN** the emission-gate kill-switch is disabled and the watch is enabled
- **THEN** the watch obtains its own finalized block, reads and persists its
  independently read items, and records their transitions

#### Scenario: First observation seeds without a transition

- **WHEN** an item is observed for the first time and has no previously
  persisted value
- **THEN** the observation is persisted and no transition event is recorded

#### Scenario: Value change records a transition

- **WHEN** a persisted observation's value differs from the most recent
  previously persisted value for that item
- **THEN** one durable transition event is recorded carrying the item, both
  values, both provenances, and the reference block

#### Scenario: Provenance change alone is not a transition

- **WHEN** an item previously persisted as `assumed-default` is later read
  explicitly at the same value
- **THEN** the provenance change is visible in the observation history and no
  transition event is emitted

#### Scenario: Malformed boolean is rejected

- **WHEN** a boolean item's payload is one byte but is neither the encoded
  true nor the encoded false value
- **THEN** a health event records the failure and nothing is persisted for
  that item

#### Scenario: One unreadable item does not blind the pass

- **WHEN** one independently read item's read fails or decodes malformed
- **THEN** a health event records the failure, nothing is persisted for that
  item, and the remaining watched items are still observed and persisted

#### Scenario: Transitions are not re-emitted on restart

- **WHEN** the poll runs again after a restart with no further value change
- **THEN** no additional transition event is produced for the already
  recorded transition

#### Scenario: Disabled watch is inert

- **WHEN** the chain-parameter watch is disabled in configuration
- **THEN** no watched item is read or persisted, and the emission-gate poll
  and crossing detection continue unchanged

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
recalculations (every 360 blocks) while the panel EMA that Atlas normalises
continues to move, so between recalculations the Nth subnet sits on the bar
and may count on either side of it; a divergence of exactly one is the
expected boundary condition, not disagreement with the chain. A divergence of
two or more indicates that the panel data, the normalization universe, or the
theta read disagrees with the chain's selection rule and SHALL be reported.

The count SHALL be taken from the pass's computed demand shares, NOT from the
tracked side state. Side tracking applies a hysteresis band that deliberately
holds a subnet on its previous side while its share sits near the bar; that
smoothing is an Atlas-side artefact and MUST NOT be able to present itself as
disagreement with the chain.

This check validates the panel data, the normalization universe, and the
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
