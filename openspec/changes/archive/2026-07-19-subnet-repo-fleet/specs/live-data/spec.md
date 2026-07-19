## ADDED Requirements

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
