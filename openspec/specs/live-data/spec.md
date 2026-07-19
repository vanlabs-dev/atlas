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
