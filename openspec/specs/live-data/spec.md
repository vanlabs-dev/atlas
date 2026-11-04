# live-data Specification

## Purpose
Serve current Bittensor data on the device, fail-closed: contract-validated
TaoSwap (keyless, first), TaoStats (keyed, quota-budgeted with headroom),
and CoinGecko (TAO/USD spot reference) adapters with typed pinned-schema
validation, per-endpoint freshness envelopes, persisted quota, bounded
observable retries, cross-provider disagreement surfacing, and read-only
Hermes tools whose answers carry provider and time metadata or state
unavailability plainly — never an invented or silently cached value
(PRD §12.7 ATLAS-API-001…008, §12.8 ATLAS-LIVE-001…009).

## Requirements

### Requirement: Contract discovery gates adapter construction

No production adapter SHALL be built for a provider endpoint until a
discovery script has made successful real calls to it (authenticated
where applicable) and produced a contract report covering the
ATLAS-API-003 items (base URL, auth, endpoints, parameters, status codes,
observed vs documented schema, nullability, pagination, units,
timestamps, rate-limit and timeout behavior, storage-affecting terms).
Discovery SHALL use multiple samples where shapes can vary
(ATLAS-API-004), SHALL include safe negative tests (ATLAS-API-005), and
MUST NOT exhaust quota or trigger abuse protections. TaoStats discovery
SHALL run under a hard call budget sized to the free tier and SHALL
confirm the real quota window. (ATLAS-API-001/002/003/004/005)

#### Scenario: Adapter blocked without discovery

- **WHEN** an adapter is requested for an endpoint with no approved
  contract report
- **THEN** the work is refused/blocked until the discovery report exists
  and its operator gates are recorded

#### Scenario: Discovery stays inside the budget

- **WHEN** TaoStats discovery runs
- **THEN** total calls stay at or under the configured cap with paced
  spacing, and the report records how many calls were spent

### Requirement: Typed validation before exposure

Every production response SHALL be validated against a pinned,
versioned, per-endpoint schema derived from confirmed documentation and
observed responses, before any value is exposed to Hermes.
(ATLAS-API-006)

#### Scenario: Valid response passes with typed values

- **WHEN** a provider response validates against the pinned schema
- **THEN** typed values (with units) are returned to the tool layer

#### Scenario: Validation precedes exposure

- **WHEN** any adapter code path returns data
- **THEN** that path demonstrably ran schema validation first (no bypass
  route exists)

### Requirement: Schema drift fails closed with a health event

If a provider response no longer validates: the request SHALL fail
closed; the body SHALL NOT be exposed as trusted data; audit metadata MAY
be retained per the retention policy; an integration-health event SHALL
be created; the failure SHALL be reported as schema drift, never a
guessed mapping. (ATLAS-API-007)

#### Scenario: Drifted response rejected

- **WHEN** a response fails schema validation
- **THEN** the tool returns a structured schema-drift error, an
  integration_health event is stored, and no value from the body reaches
  Hermes

### Requirement: Secret handling

Provider keys SHALL be stored outside source control (0600 `.env`),
readable only by the executing account, redacted from every log, error,
report, and audit path, never returned by any Atlas tool, never stored in
Hermes memory, and independently rotatable. (ATLAS-API-008)

#### Scenario: Key never leaks through the tool surface

- **WHEN** any tool result, error payload, audit line, or report is
  produced — including auth-failure errors
- **THEN** it contains no key material (redaction verified by tests)

### Requirement: Live requests hit the provider

Every live tool operation SHALL perform a fresh provider call; a
current/latest/now-class request is never answered from cache. A cached
last-known value MAY be returned only when explicitly requested and SHALL
arrive labelled as a historical snapshot with its age.
(ATLAS-LIVE-001/004)

#### Scenario: Live call on every invocation

- **WHEN** a live tool is invoked without the explicit last-known option
- **THEN** a provider request is made and no cached value is substituted

#### Scenario: Failure returns unavailable, not stale data

- **WHEN** the provider call fails and no last-known value was requested
- **THEN** the tool returns a structured live-unavailable result whose
  metadata may state that a labelled snapshot exists, without including
  its value

### Requirement: Freshness envelopes from confirmed semantics

Each live operation SHALL have a configured freshness policy —
must-hit-provider, maximum upstream timestamp age, maximum local response
age, expected update frequency, documented provider caching — sourced
from the discovery report and operator-approved. No freshness threshold
SHALL be invented before the provider contract is understood.
(ATLAS-LIVE-002)

#### Scenario: Envelope violation flags the result

- **WHEN** a validated response carries an upstream timestamp older than
  the operation's approved maximum age
- **THEN** the result's freshness status says so (e.g. `aged-upstream`)
  rather than presenting the value as current

### Requirement: Live response metadata envelope

Every successful live result SHALL include: provider, logical operation,
request completion time, upstream timestamp where available, block/chain
reference where available, units, validation status, and freshness
status. (ATLAS-LIVE-003)

#### Scenario: Metadata present on success

- **WHEN** any live tool returns a value
- **THEN** all applicable envelope fields are present, and Hermes can cite
  provider + time for the answer

### Requirement: Provider disagreement is surfaced, not resolved

When comparable values (TAO/USD across the configured price providers —
TaoSwap and the CoinGecko reference; **TaoStats SHALL NOT be called for
routine price checking**, per the Q30 refinement preserving its quota)
disagree beyond the operator-approved tolerance, the result SHALL contain
all values with source metadata, be marked conflicting, and be logged;
Atlas SHALL NOT select one as correct without a recorded validation rule,
and SHALL NOT average. (ATLAS-LIVE-005, Q30)

#### Scenario: Divergent prices marked conflicting

- **WHEN** per-provider TAO/USD values deviate pairwise beyond tolerance
- **THEN** the response carries every value + source, `conflicting: true`,
  and a logged discrepancy event

#### Scenario: Price checking spends no TaoStats quota

- **WHEN** `live_price` runs
- **THEN** no TaoStats call is made and the quota ledger shows no
  TaoStats consumption from price operations

#### Scenario: Partial provider failure stays partial

- **WHEN** one price provider fails and others succeed
- **THEN** the result returns the successful values with per-provider
  status instead of failing entirely

### Requirement: TaoStats quota budget persists with headroom

The TaoStats adapter SHALL enforce a local quota ledger against the
confirmed per-minute and per-window limits (free-tier design target:
5/min, 10,000/day-or-month as confirmed), persisted across restarts,
reserving interactive capacity per the configured policy, exposing
remaining capacity while distinguishing local estimates from
provider-reported limits, and failing visibly when capacity is exhausted.
The self-imposed per-minute cap SHALL be strictly below the provider
limit (operator refinement: never attempt to fill 5/min).
(ATLAS-LIVE-006)

#### Scenario: Pacing never fills the provider limit

- **WHEN** multiple TaoStats calls are requested within one minute
- **THEN** calls beyond the self-cap (below 5/min) are refused or
  deferred — the provider limit itself is never approached

#### Scenario: Quota survives restart

- **WHEN** calls are made, the process restarts, and usage is queried
- **THEN** the ledger reflects the pre-restart calls

#### Scenario: Exhausted quota fails visibly

- **WHEN** the configured budget for the window is spent
- **THEN** further TaoStats calls return a structured quota-exhausted
  error without contacting the provider

### Requirement: No provider is assumed unlimited

TaoSwap and any keyless provider SHALL NOT be assumed rate-unlimited:
rate behavior SHALL be documented from terms, headers, and safe observed
calls before polling or concurrency is configured, and a politeness
budget (serial, spaced calls) SHALL apply where limits are unknown.
(ATLAS-LIVE-007)

#### Scenario: Unknown limit recorded as unknown

- **WHEN** discovery finds no documented TaoSwap rate limit
- **THEN** the contract report records "unknown" with the politeness
  policy applied — never "unlimited"

### Requirement: Bounded observable retries

Retries SHALL be bounded and endpoint-specific: idempotent GETs only, at
most the configured attempts with jitter, never on 429 or schema drift;
TaoStats retries consume quota. Every attempt and final failure SHALL be
observable in the audit log. (ATLAS-LIVE-008)

#### Scenario: No retry storm on provider outage

- **WHEN** a provider is down and a live tool is called
- **THEN** at most the configured attempts occur, each audited, ending in
  a structured failure

### Requirement: Auditable call retention

For every provider call Atlas SHALL retain: provider, operation,
secret-redacted request parameters, request and response times, status
code, schema version, validation result, response hash, and error
category. Raw bodies are NOT retained as trusted data; at most a
size-capped, redacted, labelled last-response cache exists in gitignored
`var/`. (ATLAS-LIVE-009, Q29)

#### Scenario: Audit record per call

- **WHEN** any provider call completes (success or failure)
- **THEN** an audit record with the required fields is appended

### Requirement: Live evidence tools for Hermes

Hermes SHALL access live data only through named read-only MCP operations
(price, subnets, metagraph, network stats, validators, hyperparameters,
account, events, integration status). There is no generic
query/URL/SQL/shell surface. Errors SHALL be structured
(category, component, retry_safe, user-safe message, correlation id), and
the integration-status tool SHALL report health events, per-provider
last-success, and remaining quota. (ATLAS-TOOL-002/003/004)

#### Scenario: Current-data question answered with provenance

- **WHEN** Hermes is asked a current-price question with the `atlas-live`
  tools available
- **THEN** the answer cites provider and timestamp from the tool's
  metadata envelope (or states unavailability), never an invented value

#### Scenario: Status tool reports health and quota

- **WHEN** `live_status` is called
- **THEN** it returns integration-health events, per-provider
  last-success times, and remaining quota (local estimate vs
  provider-reported)

#### Scenario: Former metagraphed questions have a named tool

- **WHEN** Hermes is asked about validators, a subnet's hyperparameters,
  a coldkey's history, or recent chain events
- **THEN** a named `atlas-live` tool answers it (`live_validators`,
  `live_hyperparams`, `live_account`, `live_events`) with the metadata
  envelope, and no tool accepts a free-form URL, path or query

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

### Requirement: Subnet identity operation exposes the netuid-to-repository map

The live-data component SHALL provide a named operation that returns the
subnet-identity map — for each netuid, its on-chain `github_repo`, subnet name,
and owner — obtained from TaoStats (`GET /v1/subnets/identities`, formerly `/api/subnet/identity/v1`). The operation
SHALL be built only after its contract is established through the discovery gate
(real sampled calls under the free-tier budget, recording fields, nullability,
pagination, and the real quota window, operator-approved in the decision log),
SHALL validate every response against a pinned versioned schema before exposure,
SHALL account for its calls in the persisted TaoStats quota ledger with the
configured headroom, and SHALL carry the standard live metadata envelope
(provider, request time, reference block, units, validation status, freshness).
The operation SHALL paginate to completion and SHALL expose whether the returned
map is complete; an incomplete or drifted response SHALL fail closed as an
unavailable/degraded result rather than returning a short or guessed map. Empty
or absent `github_repo` values SHALL be preserved as such, never inferred.

#### Scenario: Identity map validated before exposure

- **WHEN** the subnet-identity operation is invoked and the provider responds
- **THEN** the response is schema-validated and, on success, returns the
  netuid-keyed identity map with the standard metadata envelope and a
  completeness indicator

#### Scenario: Degraded identity response fails closed

- **WHEN** the subnet-identity response fails schema validation, is stale beyond
  its freshness envelope, or cannot be paginated to completion
- **THEN** the operation returns a structured unavailable/degraded result and
  does not expose a partial or guessed map

#### Scenario: Identity calls respect the TaoStats budget

- **WHEN** the subnet-identity operation runs
- **THEN** its calls are recorded in the persisted quota ledger under the
  self-imposed cap below the provider limit, and are refused when the budget is
  exhausted

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

### Requirement: Storage-key derivation is self-tested against pre-verified keys

The live-data component SHALL provide a storage-key derivation helper that
computes a Substrate storage prefix from a pallet name and an item name, so
that netuid-keyed maps can be read without pinning a key per subnet.

The helper SHALL be verified against the pinned, live-verified gate storage
keys already recorded in configuration. A derivation that does not reproduce
those pinned keys exactly SHALL be treated as a fault and SHALL prevent any
derived-key read from being attempted, because a wrong prefix returns empty
results that are indistinguishable from an empty map.

Where a map's key layout is not known in advance, the component SHALL
enumerate the map prefix and derive the key layout from the observed key
tail rather than assuming a hasher. The hasher SHALL be treated as a
property of the individual storage item, not of the pallet: items on one
pallet may use different hashers. Where the observed layout carries a hash
alongside the key, the component SHALL confirm it by recomputing that hash
from the recovered key, so that a tail of merely the right length is not
accepted as a recovered key.

#### Scenario: Derivation reproduces the pinned keys

- **WHEN** the helper derives the storage keys for the pinned gate items
- **THEN** each derived key equals the pinned pre-verified key exactly

#### Scenario: A failed self-test blocks derived reads

- **WHEN** the derivation does not reproduce a pinned key
- **THEN** no derived-key storage read is attempted and the fault is
  recorded, rather than proceeding and reporting empty maps

#### Scenario: An empty map is distinguished from a wrong prefix

- **WHEN** a map prefix enumeration returns no keys
- **THEN** the result is only reported as an empty map if a control map
  known to be populated returns keys in the same pass

### Requirement: Multi-key chain state is read in batches at one finalized block

The live-data component SHALL support reading many storage keys in a single
request against one finalized block hash, so that a whole-network read is
internally consistent and does not require one round trip per key.

Every value in such a read SHALL carry the same reference block. The
component SHALL NOT assemble a network-wide view from values read at
different blocks, because doing so smears a moving chain across a single
reported snapshot.

Decoders SHALL be declared per item with their fixed-point scale where
applicable, and a decode SHALL fail closed rather than return a plausible
wrong magnitude. A variable-length vector value SHALL be decoded through its
compact length prefix in each of its encoded forms.

The read set SHALL include each subnet's on-chain identity name. Only the
leading name field of the identity record SHALL be decoded, so that later
fields may be added to the record on chain without breaking the read. The
name is operator-written free text: it SHALL be decoded permissively rather
than raising, so that one subnet's malformed bytes cannot fail the whole
map read, and it SHALL be treated as data, never as an instruction.

#### Scenario: A whole-network read shares one block

- **WHEN** field size and incentive vectors are read for every subnet
- **THEN** all values are read at one finalized block hash and are persisted
  with that same reference block

#### Scenario: A wrong fixed-point scale is caught, not returned

- **WHEN** a fixed-point value is decoded at the wrong scale
- **THEN** the decode is rejected rather than returning a value that is
  numerically plausible but wrong by a power of two

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

### Requirement: Chain storage reads are audited

Every chain storage read that live-data makes for another component SHALL
leave an audit record. Each record covers one read at one block and carries:
- the endpoint
- the method
- the storage items and the count of keys requested and returned
- the finalized block number and hash
- request and response times
- the result, with its error category on failure

Storage values SHALL NOT be retained as trusted data. A failed read SHALL be
audited with its error before the failure is returned to the caller.

#### Scenario: Batched read is audited

- **WHEN** the mining screen reads its chain snapshot through live-data
- **THEN** one audit record per read names the items, the key counts, and
  the block

#### Scenario: Failed read is audited

- **WHEN** a chain read fails
- **THEN** an audit record with the error category is written, and the
  caller receives the failure

### Requirement: Double-map and account-keyed storage is read at the same block

Live-data SHALL support reading storage whose keys include account
identifiers. That includes subnet-and-hotkey double maps and coldkey-keyed
maps, derived with each item's declared hashers. Such a read SHALL run at
the same finalized block as the netuid-keyed read it accompanies. Every
item read this way SHALL be declared in the single chain-read table, so the
probe checks its hashers and value type against live metadata.

A key-count cap SHALL bound these reads. When the cap would be exceeded,
the read SHALL fail closed for the affected subnet, never truncate
silently.

#### Scenario: Owner hotkeys resolve at the snapshot block

- **WHEN** the mining screen resolves the owner UIDs of every subnet
- **THEN** owner coldkeys, their hotkeys, and those hotkeys' UIDs are all
  read at the snapshot's block

#### Scenario: Undeclared account-keyed read

- **WHEN** a reader reads an account-keyed item missing from the chain-read
  table
- **THEN** the live-data tests fail naming the item

#### Scenario: Cap exceeded fails closed

- **WHEN** a subnet owner's coldkey owns more hotkeys than the cap
- **THEN** that subnet's owner set is recorded unread, its owner
  reconciliation fails, and it receives no net figure

### Requirement: Subnet registration settings are watched

The chain-parameter watch SHALL read `NetworkImmunityPeriod`,
`NetworkLockReductionInterval` and `NetworkRateLimit` from the
SubtensorModule pallet as plain `u64` items on pinned keys, at the gate
poll's finalized block. Each item SHALL be declared in the chain-read list,
so the hourly probe checks it. A value change SHALL record a transition; a
first observation SHALL seed without one.

#### Scenario: Immunity change records a transition

- **WHEN** a watched `NetworkImmunityPeriod` of 864000 is followed by an
  observation of 432000
- **THEN** one chain-parameter transition is recorded with both values

#### Scenario: First observation seeds silently

- **WHEN** `NetworkLockReductionInterval` is observed for the first time
- **THEN** the observation is stored and no transition is recorded

#### Scenario: Declared for the probe

- **WHEN** the chain-read probe runs
- **THEN** it checks all three items against live metadata as `u64`
  storage values with no key hasher

### Requirement: Subnet hyperparameters are read chain-first

`live_hyperparams` SHALL read one subnet's hyperparameter storage items
from Finney at one finalized block, with the same key self-test and
fail-closed rules as other chain reads. TaoSwap's subnet record SHALL
supply each value the chain does not store, and SHALL cross-check each
value the chain does store. Every value SHALL carry its source: `chain`
(stored, with block), `taoswap` (chain storage unset, with TaoSwap's
upstream time), or `unavailable`. A value present in both sources that
differs SHALL be returned as a disagreement with both values, never
averaged or silently replaced. Spending TaoStats quota is not permitted.

#### Scenario: Stored values come from the chain

- **WHEN** `live_hyperparams` is called for a netuid whose `Tempo` and
  `ImmunityPeriod` are stored on chain
- **THEN** those values are returned with source `chain` and the finalized
  block number and hash they were read at

#### Scenario: Unset storage is filled from TaoSwap and labelled

- **WHEN** a hyperparameter's storage is unset on chain and TaoSwap
  reports a value for it
- **THEN** the value is returned with source `taoswap` and a note that
  chain storage is unset, never presented as a chain read

#### Scenario: Sources disagree

- **WHEN** a stored chain value and TaoSwap's value for the same item
  differ
- **THEN** the item is returned as `conflicting` with both values and
  their sources

#### Scenario: Chain unreachable

- **WHEN** every configured RPC endpoint fails or the key self-test fails
- **THEN** the tool returns TaoSwap values labelled `taoswap` with a
  health note that the chain read failed, or a structured
  live-unavailable result if TaoSwap also fails

#### Scenario: Unknown netuid

- **WHEN** the netuid is not a registered subnet in both sources
- **THEN** the tool returns a structured not-found error and no values

### Requirement: Validator, account and event data come from keyless TaoSwap

`live_validators`, `live_account` and `live_events` SHALL call TaoSwap
only, through operations covered by an approved TaoSwap contract report.
Each SHALL return a bounded, ranked result (a size cap stated in the
response), validate against a pinned schema before exposure, and carry
the live metadata envelope. Inputs SHALL be validated before any call: a
hotkey or coldkey must be a well-formed SS58 address, and a netuid or
block a non-negative integer. TaoSwap's rate behaviour is recorded from
the contract report and the existing politeness budget applies.

#### Scenario: Validators of one subnet

- **WHEN** `live_validators` is called with a netuid
- **THEN** it returns that subnet's validators ranked by stake, at most the
  stated cap, each with hotkey, identity name, stake, take and yield, plus
  the total count TaoSwap listed

#### Scenario: One validator

- **WHEN** `live_validators` is called with a hotkey
- **THEN** it returns that validator's subnets and top delegators, bounded,
  with the metadata envelope

#### Scenario: Malformed address refused before any call

- **WHEN** `live_account` or `live_validators` gets a value that is not a
  well-formed SS58 address
- **THEN** it returns a structured invalid-input error and makes no
  provider call

#### Scenario: Events for one block

- **WHEN** `live_events` is called with a block number
- **THEN** it returns that block's events with pallet, name and extrinsic
  index, and the block number as the block reference

#### Scenario: Adapter waits for discovery

- **WHEN** a new TaoSwap endpoint has no entry in an approved contract
  report
- **THEN** no tool calls it, and the change's discovery task must run and
  be recorded first

### Requirement: Miner-activity and consensus context is read at the mining snapshot block

Live-data SHALL read, at the finalized block of the mining snapshot, each
subnet's epoch consensus mode, pending pruning target, validator permits,
per-mechanism last-update and weight rows, the registration block of each
UID below the registered count, and the serving block of each axon. Every
item SHALL be declared in the chain-read table, and every substituted
default in the expected-default table.

#### Scenario: Context shares the economics block

- **WHEN** the mining snapshot is read
- **THEN** the context items carry the same block number and hash as the
  economics items

#### Scenario: Context failure does not fail the economics

- **WHEN** a context item fails to read or decode
- **THEN** that context is marked unread for the affected subnets, and the
  economics snapshot still succeeds

#### Scenario: Unknown consensus value fails closed

- **WHEN** a subnet's consensus entry holds an index other than Yuma or Null
- **THEN** that subnet's mode is unread, and no other subnet is affected

#### Scenario: Only the axon serving block is decoded

- **WHEN** an axon entry is read
- **THEN** only its serving block is decoded and returned, and its address,
  port and protocol are neither decoded nor stored

#### Scenario: Registration blocks are read for registered UIDs only

- **WHEN** a subnet has 256 registered UIDs
- **THEN** registration blocks are read for UIDs 0 to 255 and no
  enumerated stale entry is counted

#### Scenario: New reads join the probe

- **WHEN** the chain-read probe runs
- **THEN** it checks each new item's hashers, value type and, where one is
  substituted, its default against live metadata

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
