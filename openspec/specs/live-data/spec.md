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
(price, subnets, metagraph, network stats, integration status) — no
generic query/URL/SQL/shell surface. Errors SHALL be structured
(category, component, retry_safe, user-safe message, correlation id), and
the integration-status tool SHALL report health events, per-provider
last-success, and remaining quota. (ATLAS-TOOL-002/003/004)

#### Scenario: Current-data question answered with provenance

- **WHEN** Hermes is asked a current-price question with the `atlas-live`
  tools available
- **THEN** the answer cites provider and timestamp from the tool's
  metadata envelope (or states unavailability) — never an invented value

#### Scenario: Status tool reports health and quota

- **WHEN** `live_status` is called
- **THEN** it returns integration-health events, per-provider
  last-success times, and remaining quota (local estimate vs
  provider-reported)

### Requirement: Live runtime spec_version changes are recorded

The live-data component SHALL persist the last-seen live runtime `spec_version`
(with its reference block and observation time) and SHALL record a durable
upgrade event whenever a validated live chain-head response reports a
`spec_version` different from the last recorded one. The upgrade record SHALL be
written only from a live, typed-validated response (never from stale or
unvalidated data) and SHALL capture the previous `spec_version`, the new
`spec_version`, and the reference block. A restart SHALL NOT re-emit an upgrade
for an already-recorded `spec_version`.

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

### Requirement: Subnet identity operation exposes the netuid-to-repository map

The live-data component SHALL provide a named operation that returns the
subnet-identity map — for each netuid, its on-chain `github_repo`, subnet name,
and owner — obtained from TaoStats (`GET /api/subnet/identity/v1`). The operation
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

#### Scenario: One unreadable subnet does not blind the rest

- **WHEN** one subnet's watched value fails to decode
- **THEN** that subnet records nothing and every other subnet's observation
  is persisted
