# live-data — Delta: gate-crossing signal

## ADDED Requirements

### Requirement: Live emission-gate state is polled fail-closed

The live-data component SHALL poll the live emission-gate state — the gate
bar theta (`EmissionGateBar`), the bar quantile q (`EmissionBarQuantile`),
and the gate exponent h (`EmissionGateExponent`) — via a keyless
allowlisted JSON-RPC `state_getStorage` read of fixed, name-derived storage
keys, and SHALL persist one gate-state observation per successful poll
(theta, q, h, endpoint, observation time). Responses SHALL be typed-validated
(hex payload decoded as little-endian fixed-point and bounds-checked: theta
in [0,1), q in (0,1), h in [1,8]) before persistence. A failed request or a
response failing validation SHALL record a health event and persist nothing
— gate state is never written from stale or unvalidated data.

#### Scenario: Valid poll persists gate state

- **WHEN** the gate poll returns responses that decode and pass bounds
  checks
- **THEN** one gate-state observation with theta, q, h, and the observation
  time is persisted

#### Scenario: Failure persists nothing

- **WHEN** the RPC request fails, times out, or the payload fails
  validation
- **THEN** no gate-state observation is written, prior state is unchanged,
  and a health event records the failure

#### Scenario: Parameter changes are visible facts

- **WHEN** a persisted poll reports a q or h differing from the previously
  persisted values
- **THEN** the change is visible in the gate-state history and status
  output (no silent local assumption of the defaults)

### Requirement: Demand shares are computed from validated panel data only

The live-data component SHALL compute per-subnet demand shares as
`moving_price x (1 - miner_burn)` normalized over subnets reported
emission-enabled, using only the typed-validated TaoSwap subnets panel from
the same pass. If the panel is unavailable or fails validation, no shares
SHALL be computed and no gate events SHALL be produced for that pass. Share
computation SHALL never trigger additional provider calls beyond the
existing panel poll.

#### Scenario: Shares from a valid panel

- **WHEN** a validated subnets panel is available for the pass
- **THEN** demand shares are computed over the emission-enabled subnets and
  normalized to sum to 1

#### Scenario: No panel, no shares

- **WHEN** the subnets panel is unavailable or invalid for the pass
- **THEN** no shares are computed and no gate events are recorded for that
  pass

### Requirement: Gate-crossing events are durable, hysteresis-guarded, and never replayed

The live-data component SHALL track each subnet's gate side (above or below
theta) and SHALL record a durable gate-crossing event only when the
subnet's demand share exits a configured relative hysteresis band around
theta on a configured number of consecutive polls. Each event SHALL persist
the netuid, direction, share, theta, previous side, observation time, and a
deterministic event id. The first observation of a subnet SHALL seed its
side without recording an event. A restart SHALL NOT re-emit events for
already-recorded crossings. A disabled kill-switch SHALL skip polling and
event production entirely.

#### Scenario: Confirmed crossing records one event

- **WHEN** a subnet's share moves from above the bar to below the
  hysteresis band (or the reverse) and stays outside the band for the
  configured consecutive polls
- **THEN** exactly one gate-crossing event is recorded with direction,
  share, theta, previous side, and a deterministic event id

#### Scenario: Wobble inside the band records nothing

- **WHEN** a subnet's share fluctuates within the hysteresis band around
  theta across polls
- **THEN** no gate-crossing event is recorded and the subnet's side is
  unchanged

#### Scenario: First observation seeds silently

- **WHEN** a subnet is observed for the first time after deploy
- **THEN** its gate side is seeded and no event is recorded

#### Scenario: Restart does not replay

- **WHEN** the component restarts after recording a crossing
- **THEN** the recorded crossing is not re-emitted and the seeded sides are
  preserved
