## ADDED Requirements

### Requirement: Root weight vectors are read at the gate-poll block and aggregated into a destination map

The live-data component SHALL read every per-validator root weight vector at
the same finalized block as the emission-gate poll, over the existing keyless
JSON-RPC path, using the established storage-key derivation self-test and the
established batched multi-key read. The read SHALL enumerate the weight map's
entries at the root netuid and SHALL fetch every returned key in one batched
request at that block. A storage-enumeration or batch method that the endpoint
refuses SHALL NOT be used; the requirement is one enumeration call plus one
batched value read.

Each vector SHALL be decoded as a length-prefixed sequence of
(destination netuid, weight) pairs. A vector that fails to decode, a key whose
derivation does not match the observed key layout, or a batch that returns
fewer entries than were enumerated SHALL fail the read closed for that pass,
recording a health event and persisting no partial map, rather than storing a
map that understates a destination.

Each pass SHALL persist every validator's vector and an aggregate destination
map covering all destinations. The aggregate SHALL be stake-weighted by each
validator's root stake when that figure is available from the same pass, and
SHALL be recorded as unweighted and labelled unweighted when it is not.
The weighting basis SHALL be persisted with the map, so a consumer never has
to infer it.

The read SHALL be independently disableable, and SHALL NOT be gated by the
emission-gate kill switch, so disabling the gate signal cannot silently stop
observing root curation.

#### Scenario: One enumeration and one batched read at one block

- **WHEN** a pass reads root weight vectors
- **THEN** the map's entries at the root netuid are enumerated once, every
  returned key is read in one batched request at the gate poll's finalized
  block, and the block reference is persisted with the result

#### Scenario: Undecodable vector fails the pass closed

- **WHEN** any returned vector does not decode as a sequence of
  (netuid, weight) pairs
- **THEN** the pass records a health event, persists no vectors and no
  aggregate map for that pass, and the previous stored map is left intact

#### Scenario: Short batch is not treated as an empty vector

- **WHEN** the batched read returns fewer entries than were enumerated
- **THEN** the pass fails closed rather than recording the missing validators
  as having no destinations

#### Scenario: Weighting basis is always stated

- **WHEN** an aggregate destination map is persisted
- **THEN** it carries whether it is stake-weighted or unweighted, and an
  unweighted map is labelled unweighted wherever it is presented

#### Scenario: Root read survives a gate-signal rollback

- **WHEN** the emission-gate signal is disabled
- **THEN** the root weight vector read continues on the hourly pass

### Requirement: A material shift in the aggregate root destination map is recorded as an event

The component SHALL compare each pass's aggregate destination map against the
previously persisted map and SHALL record a durable root-rotation event when a
destination's share of the aggregate changes by more than a configured
threshold, or when a destination enters or leaves the map. Each event SHALL
persist the destination netuid, the previous and new shares, the number of
validators contributing to the change, the weighting basis, the block
reference, and the observation time.

The first persisted map SHALL seed silently without recording events. A pass
in which the curation master switch or the concentration cap transitions SHALL
re-seed the map silently and record no rotation events, because such a
transition re-prices every vector at once and is already reported by the
chain-parameter watch.

#### Scenario: Destination share moves past the threshold

- **WHEN** a destination's aggregate share changes by more than the configured
  threshold between two persisted maps
- **THEN** one root-rotation event is recorded carrying both shares, the
  contributing validator count, the weighting basis, and the block reference

#### Scenario: First map seeds silently

- **WHEN** the first aggregate destination map is persisted
- **THEN** it is stored and no rotation events are recorded

#### Scenario: Curation parameter transition re-seeds instead of storming

- **WHEN** a pass records a transition in the curation master switch or the
  concentration cap
- **THEN** the aggregate map is re-seeded, no rotation events are recorded for
  that pass, and the chain-parameter transition alone reports the change

#### Scenario: New destination is an event

- **WHEN** a destination netuid appears in the aggregate map that was absent
  from the previous map
- **THEN** one root-rotation event is recorded for its entry

## MODIFIED Requirements

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

A recorded crossing SHALL NOT be eligible for delivery until a configured
durability window has elapsed without an opposing crossing for the same
netuid. A crossing for which an opposing crossing is recorded inside that
window SHALL be marked reversed and SHALL NEVER become eligible for delivery;
both the crossing and its reversal SHALL be retained. Eligibility SHALL be a
persisted property of the event, so a restart cannot make a reversed crossing
deliverable. Because the bar is rank-pinned, a subnet at the bar oscillates by
construction, and an oscillation is a state reported by the standing briefing
line rather than an event.

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

#### Scenario: Hovering subnet is flagged and annotated

- **WHEN** a subnet records more than the configured number of crossings
  inside the configured window
- **THEN** it is flagged as hovering and each further crossing while flagged
  is recorded with the hovering annotation

#### Scenario: Hovering flag clears after a stable window

- **WHEN** a flagged subnet stays on one side for the full window
- **THEN** the flag is cleared and its next crossing is recorded without the
  annotation

#### Scenario: Crossing becomes eligible only after the durability window

- **WHEN** a confirmed crossing is recorded and the configured durability
  window elapses with no opposing crossing for that netuid
- **THEN** the event is marked eligible for delivery at that point and not
  before

#### Scenario: Reversed crossing is retained and never delivered

- **WHEN** an opposing crossing for the same netuid is recorded inside the
  durability window
- **THEN** both crossings are retained, the first is marked reversed, and
  neither becomes eligible for delivery

#### Scenario: Restart cannot resurrect a reversed crossing

- **WHEN** the component restarts after marking a crossing reversed
- **THEN** the crossing remains ineligible for delivery

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
