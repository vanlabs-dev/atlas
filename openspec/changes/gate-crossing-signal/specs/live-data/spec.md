# live-data — Delta: gate-crossing signal

## ADDED Requirements

### Requirement: Live emission-gate state is polled fail-closed at one finalized block

The live-data component SHALL poll the live emission-gate state — the gate
bar theta (`EmissionGateBar`), the bar quantile q (`EmissionBarQuantile`),
and the gate exponent h (`EmissionGateExponent`) — via a keyless
allowlisted JSON-RPC `state_getStorage` read of pinned, pre-verified
storage keys (hex constants in configuration with their names and
derivation documented alongside). All reads in one poll SHALL be issued
against a single finalized block hash obtained first, and the reference
block SHALL be persisted with the observation. Present values SHALL be
typed-validated (hex payload decoded as little-endian fixed-point and
bounds-checked: theta in [0,1), q in (0,1), h in [1,8]) before
persistence; an out-of-bounds decode SHALL record a health event and
persist nothing. A null read SHALL be handled as a defined state, not an
error: null q or h SHALL be persisted as the documented per-runtime
default marked `assumed-default`; null or zero theta SHALL be persisted as
gate-inactive. A failed request SHALL record a health event and persist
nothing — gate state is never written from stale or unvalidated data.

#### Scenario: Valid poll persists gate state with its reference block

- **WHEN** the gate poll obtains a finalized head and all reads decode and
  pass bounds checks
- **THEN** one gate-state observation with theta, q, h, the reference
  block, and the observation time is persisted

#### Scenario: Null parameter persists as assumed default

- **WHEN** the q or h storage read returns null at the reference block
- **THEN** the observation persists the documented per-runtime default for
  that parameter marked `assumed-default`, and a later non-null read is
  visible as a provenance change from `assumed-default` to explicit

#### Scenario: Null or zero theta persists as gate-inactive

- **WHEN** the theta storage read returns null or decodes to zero
- **THEN** the observation is persisted as gate-inactive and no crossing
  events are produced while the gate is inactive

#### Scenario: Failure or out-of-bounds persists nothing

- **WHEN** the RPC request fails, times out, or a present value decodes
  out of bounds
- **THEN** no gate-state observation is written, prior state is unchanged,
  and a health event records the failure

#### Scenario: Parameter changes are visible facts

- **WHEN** a persisted poll reports a q or h (value or provenance)
  differing from the previously persisted observation
- **THEN** the change is visible in the gate-state history and status
  output (no silent local assumption)

### Requirement: Demand shares are computed over the chain's emit-to universe from validated panel data only

The live-data component SHALL compute per-subnet demand shares as
`moving_price x (1 - miner_burn)` normalized over ALL non-root subnets in
the typed-validated TaoSwap subnets panel from the same pass —
emission-disabled subnets SHALL be included in the normalization, matching
the chain's bar computation, with `emission_is_enabled` carried as an
annotation rather than a filter. If the panel is unavailable or fails
validation, no shares SHALL be computed and no gate events SHALL be
produced for that pass. Share computation SHALL never trigger additional
provider calls beyond the existing panel poll.

#### Scenario: Shares from a valid panel

- **WHEN** a validated subnets panel is available for the pass
- **THEN** demand shares are computed over all non-root panel subnets and
  normalized to sum to 1

#### Scenario: Emission-disabled subnets stay in the universe

- **WHEN** the panel reports subnets with emission disabled
- **THEN** those subnets are included in the share normalization and their
  disabled state is carried as an annotation on any event they produce

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
de-duplication SHALL be the store row id. Lifecycle guards SHALL prevent
false crossings: the first observation of a subnet seeds its side without
an event; a subnet absent from the panel for a configured number of
consecutive polls has its side cleared, and its reappearance seeds
silently; a gate-inactive to gate-active transition re-seeds all sides
silently. A restart SHALL NOT re-emit events for already-recorded
crossings. A disabled kill-switch SHALL skip polling and event production
entirely.

#### Scenario: Confirmed crossing records one event

- **WHEN** a subnet's share moves from above the bar to below the
  hysteresis band (or the reverse) and stays outside the band for the
  configured consecutive polls
- **THEN** exactly one gate-crossing event is recorded with direction,
  share, theta, previous side, and its annotation

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
