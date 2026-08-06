## MODIFIED Requirements

### Requirement: Live emission-gate state is polled fail-closed at one finalized block

The live-data component SHALL poll the live emission-gate state — the gate
bar theta (`EmissionGateBar`), the bar rank N (`EmissionBarRank`), the bar
quantile q (`EmissionBarQuantile`), and the gate exponent h
(`EmissionGateExponent`) — via a keyless allowlisted JSON-RPC
`state_getStorage` read of pinned, pre-verified storage keys (hex constants
in configuration with their names and derivation documented alongside). All
reads in one poll SHALL be issued against a single finalized block hash
obtained first, and the reference block SHALL be persisted with the
observation.

Present values SHALL be typed-validated before persistence, decoded by the
codec the chain declares for that item: theta, q, and h as little-endian
fixed-point (`U64F64`) bounds-checked to theta in [0,1), q in (0,1), h in
[1,8]; N as a little-endian unsigned 16-bit integer bounds-checked to
[0, 65535]. Decoding a fixed-point payload as an integer, or the reverse,
SHALL NOT occur — the codec is a property of the item, not of the poll. An
out-of-bounds or malformed decode SHALL record a health event and persist
nothing.

A null read SHALL be handled as a defined state, not an error: null N, q, or
h SHALL be persisted as the documented per-runtime default marked
`assumed-default`; null or zero theta SHALL be persisted as gate-inactive. A
failed request SHALL record a health event and persist nothing — gate state
is never written from stale or unvalidated data.

Each observation SHALL additionally persist the derived **bar mode**: `rank`
when the effective N is greater than zero (theta is pinned to the Nth-largest
positive demand share and q is inert), and `q-mass` when the effective N is
zero (theta is the q-mass crossing share). The bar mode SHALL be derived from
the effective N of the same observation — including an `assumed-default` N —
so no observation records a bar whose selection mechanism is unstated.

The decoded bar parameters of each persisted observation (N, q, h, each with
its provenance) SHALL be supplied to the chain-parameter watch as that pass's
observed values, so a bar parameter is read once per pass and one record of
its history exists.

#### Scenario: Valid poll persists gate state with its reference block

- **WHEN** the gate poll obtains a finalized head and all reads decode and
  pass bounds checks
- **THEN** one gate-state observation with theta, N, q, h, the derived bar
  mode, the reference block, and the observation time is persisted

#### Scenario: Rank decodes with its own codec

- **WHEN** the `EmissionBarRank` read returns a present value
- **THEN** it is decoded as a little-endian unsigned 16-bit integer, not as
  fixed-point, and a payload that is not a valid u16 records a health event
  and persists nothing

#### Scenario: Null parameter persists as assumed default

- **WHEN** the N, q, or h storage read returns null at the reference block
- **THEN** the observation persists the documented per-runtime default for
  that parameter marked `assumed-default`, and a later non-null read is
  visible as a provenance change from `assumed-default` to explicit

#### Scenario: Bar mode follows the effective rank

- **WHEN** the effective N of an observation is greater than zero, whether
  read explicitly or applied as an `assumed-default`
- **THEN** the observation records bar mode `rank`
- **AND** when the effective N is zero the observation records bar mode
  `q-mass`

#### Scenario: Null or zero theta persists as gate-inactive

- **WHEN** the theta storage read returns null or decodes to zero
- **THEN** the observation is persisted as gate-inactive and no crossing
  events are produced while the gate is inactive

#### Scenario: Failure or out-of-bounds persists nothing

- **WHEN** the RPC request fails, times out, or a present value decodes
  out of bounds
- **THEN** no gate-state observation is written, prior state is unchanged,
  and a health event records the failure

#### Scenario: Bar parameters feed the watch once per pass

- **WHEN** a gate observation persists successfully
- **THEN** its decoded N, q, and h with their provenances are the values the
  chain-parameter watch records for that pass, with no second storage read of
  those items

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

Lifecycle guards SHALL prevent false crossings: the first observation of a
subnet seeds its side without an event; a subnet absent from the panel for a
configured number of consecutive polls has its side cleared, and its
reappearance seeds silently; a gate-inactive to gate-active transition
re-seeds all sides silently; and **a pass in which a bar-parameter transition
is recorded (a change in the effective N, q, or h) SHALL re-seed all sides
silently, recording no crossing events for that pass**. A bar-parameter
change re-prices the bar for every subnet at once, so the crossings it
induces are a property of the parameter change and are reported by the
chain-parameter transition, not as per-subnet demand events. A restart SHALL
NOT re-emit events for already-recorded crossings. A disabled kill-switch
SHALL skip polling and event production entirely.

#### Scenario: Confirmed crossing records one event

- **WHEN** a subnet's share moves from above the bar to below the
  hysteresis band (or the reverse) and stays outside the band for the
  configured consecutive polls
- **THEN** exactly one gate-crossing event is recorded with direction,
  share, theta, the previous observation's theta, previous side, and its
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

## ADDED Requirements

### Requirement: Root-settable chain parameters are watched for transitions

The live-data component SHALL maintain a configured watch set of discrete
root-settable chain storage items whose value governs network economics. The
set SHALL cover the emission-gate bar parameters (`EmissionBarRank`,
`EmissionBarQuantile`, `EmissionGateExponent`), whose values are supplied by
the gate poll of the same pass, and additionally read items not covered by
the gate poll — starting with `RootWeightSettingEnabled`, the Root Reborn
basket-curation master switch. Each independently read item SHALL be
configured with its pinned pre-verified storage key, its decoder (unsigned
integer or boolean), its documented per-runtime default, and a short
description of what the parameter governs. A boolean decoder SHALL reject a
payload that is the correct length but is neither the encoded true nor the
encoded false value.

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
persisted — one unreadable knob does not blind the rest.

Because watched values are discrete, a transition SHALL be recorded whenever
a persisted observation's value differs from the most recent previously
persisted value for that item — no hysteresis, confirmation window, or
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
above the bar. The live-data component SHALL exploit this as a correctness
check on its own share pipeline: each pass in rank mode SHALL persist the
count of subnets whose computed demand share is positive and at or above the
bar, alongside the effective N, and SHALL record a health event when that
count diverges from N by more than a configured tolerance.

The count SHALL be taken from the pass's computed demand shares, NOT from the
tracked side state. Side tracking applies a hysteresis band that deliberately
holds a subnet on its previous side while its share sits near the bar; that
smoothing is an Atlas-side artefact and MUST NOT be able to present itself as
disagreement with the chain.

This check validates the panel data, the normalization universe, and the
theta read together against the chain's own selection rule, without
recomputing theta locally. A divergence SHALL NOT suppress crossing events or
block persistence — it is a signal that the share pipeline and the chain
disagree, reported for the operator, not an error that discards the pass.

#### Scenario: Agreeing count passes silently

- **WHEN** a rank-mode pass observes an above-bar count within tolerance of
  the effective N
- **THEN** the count and N are persisted with the pass and no health event is
  recorded

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
