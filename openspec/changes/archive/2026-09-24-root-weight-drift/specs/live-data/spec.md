## ADDED Requirements

### Requirement: Root-settable chain parameters are watched against the spec 469 runtime

The live-data component SHALL maintain a configured watch set of discrete
root-settable chain storage items whose value governs network economics. The
set SHALL cover the emission-gate bar parameters (`EmissionBarRank`,
`EmissionBarQuantile`, `EmissionGateExponent`), whose values are supplied by
the gate poll of the same pass, and additionally read items not covered by
the gate poll, including `BasketConcentrationCap`, the largest share of a
fund's value one holding may reach through a `swap_basket` buy. Each
independently read item SHALL be configured with its pinned pre-verified
storage key, its decoder (unsigned integer or boolean), its documented
per-runtime default, and a short description of what the parameter governs.
A netuid-keyed item in this set SHALL have its key derived for the named
entry with the hasher the chain declares for that item, and the derivation
SHALL be self-tested in the same way as the other derived keys. A boolean
decoder SHALL reject a payload that is the correct length but is neither the
encoded true nor the encoded false value.

The watch set SHALL NOT contain an item that is absent from the live runtime
metadata. `RootWeightSettingEnabled` and `RootWeightsCap`, retired at spec
469, SHALL NOT be read. Their stored observation and transition history SHALL
be kept unchanged, and their removal SHALL NOT record a transition.

This watch SHALL be the single durable record of bar-parameter change; a
transient in-memory change flag SHALL NOT be relied on as the record of a
parameter transition.

Independently read items SHALL be read against the same finalized block hash
as the gate poll when the gate poll runs in that pass. The watch SHALL NOT be
gated by the emission-gate kill-switch: when the gate signal is disabled, the
watch SHALL still run over its independently read items, obtaining its own
finalized block hash, so a basket-parameter flip is not missed while the gate
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

#### Scenario: Basket concentration cap is observed as a plain value

- **WHEN** a pass runs the watch
- **THEN** `BasketConcentrationCap` is read at its pinned plain storage key,
  decoded as an unsigned 16-bit integer, and persisted with its provenance;
  a null read persists the documented default 4096 as `assumed-default`

#### Scenario: First cap observation seeds silently

- **WHEN** `BasketConcentrationCap` is observed for the first time
- **THEN** its observation is persisted and no transition is recorded

#### Scenario: Retired items are not read

- **WHEN** a pass runs the watch
- **THEN** no read of `RootWeightSettingEnabled` or `RootWeightsCap` is made,
  no observation or transition is written for them, and their earlier rows
  are unchanged

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

## REMOVED Requirements

### Requirement: Root-settable chain parameters are watched for transitions

**Reason**: Spec 469 removed `RootWeightSettingEnabled` and `RootWeightsCap`,
which this requirement names and reads. Replaced by "Root-settable chain
parameters are watched against the spec 469 runtime", which keeps every other
rule and scenario and watches `BasketConcentrationCap` instead.

**Migration**: None. Stored observations and transitions for the retired
items stay as history.

### Requirement: Root weight vectors are read at the gate-poll block and aggregated into a destination map

**Reason**: Spec 469 retired `set_root_weights` and cleared `Weights[ROOT]`.
No validator vector exists to read, so the aggregate map is always empty.

**Migration**: None. Stored `root_vectors` and `root_destination_map` rows
stay as history. A replacement signal on `swap_basket` is a separate change.

### Requirement: A material shift in the aggregate root destination map is recorded as an event

**Reason**: The destination map it compares no longer exists at spec 469.

**Migration**: None. Stored `rotation_events` rows stay as history and are
no longer read by any component.
