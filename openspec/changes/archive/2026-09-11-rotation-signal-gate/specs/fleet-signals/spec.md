## MODIFIED Requirements

### Requirement: Instant events capture alpha-price context at creation
Every event of a registered netuid-scoped alert class SHALL snapshot the
affected subnet's alpha price in
TAO at event creation (a cluster event snapshots each member netuid), sourced
from the keyless TaoSwap subnets operation invoked through the live-data
layer's validated machinery — never a raw HTTP call, never a keyed or
quota-budgeted endpoint. Classes whose events originate outside the fleet
store SHALL be entered through the same path, so measurement coverage does not
depend on where an event was produced. At most one price fetch SHALL occur per
extraction pass, and its full per-subnet price vector SHALL be stored
(config-capped retention) so fleet baselines need no extra calls. A failed
fetch SHALL leave the snapshot pending for retry on a later pass and SHALL
never delay, block, or suppress the event or its delivery.

#### Scenario: Cluster snapshot covers all members from one fetch
- **WHEN** a cluster event with k member subnets is created during an extraction pass
- **THEN** one price fetch records entry prices for all k members and the full fleet vector is stored

#### Scenario: Price outage never blocks alerting
- **WHEN** the price fetch fails during a pass that emitted events
- **THEN** the events are queued and delivered normally with snapshots marked pending, and a later pass fills them marked late

#### Scenario: Externally produced event is entered on the same terms
- **WHEN** a netuid-scoped event produced outside the fleet store is registered at the instant or shadow tier
- **THEN** it receives an entry price snapshot and outcome rows exactly as a fleet signal event does

#### Scenario: Shadow-tier event is snapshotted
- **WHEN** an event of a shadow-tier class is created
- **THEN** its entry price is snapshotted even though nothing will be delivered for it

#### Scenario: Demoted class keeps being snapshotted
- **WHEN** an event of a briefing-tier class is created
- **THEN** its entry price is snapshotted on the same terms as any other class, so the demotion can be reversed on later evidence

### Requirement: Outcome horizons are measured against a fleet baseline
For each event of a registered netuid-scoped alert class, whatever its
delivery tier, and each configured horizon (default 1, 7, and 30
days), the module SHALL record the subnet's alpha-price return alongside the
fleet-median return over the identical window, filled by an inline outcomes
step in the hourly hook. A subnet deregistered or price-less at horizon SHALL
be marked unavailable, never estimated. An `effectiveness` command SHALL
report, per alert class and horizon, alerted-subnet median return vs fleet
baseline with counts and pending/unavailable tallies, as read-only
measurement — the report SHALL derive no recommendations.

The report SHALL cover every registered measured class, including classes at
the `shadow` and `briefing` tiers, and SHALL state each class's current tier
alongside its figures, so a tier can never be argued for without the evidence
being visible next to it. Where a horizon has more pending than filled
outcomes, the report SHALL mark that horizon as not yet readable.

#### Scenario: Horizon fill compares like windows
- **WHEN** an event's 7-day horizon comes due and prices are available
- **THEN** the outcome row records the subnet's return and the fleet-median return over the same window

#### Scenario: Deregistered subnet is honest data
- **WHEN** an alerted subnet has deregistered before a horizon matures
- **THEN** that outcome row is marked unavailable and the effectiveness report counts it as such

#### Scenario: Effectiveness report is read-only
- **WHEN** the effectiveness command runs
- **THEN** it prints per-class, per-horizon medians vs baseline with counts and changes no state

#### Scenario: Report names each class's tier
- **WHEN** the effectiveness command runs
- **THEN** every reported class carries its current delivery tier next to its figures

#### Scenario: Majority-pending horizon is marked unreadable
- **WHEN** a class's horizon holds more pending outcomes than filled ones
- **THEN** the report marks that horizon not yet readable rather than printing a median that invites a decision

### Requirement: Econ-code changes are detected by path and alerted per range with a per-netuid cooldown
The module SHALL match `files_json` paths of each new change range against
configured econ-code path patterns (reward/incentive/scoring/emission/weights
vocabulary), with the same vendor/test exclusions, to identify **candidates**.
Detection SHALL use recorded path metadata only (no blob fetch). A candidate
SHALL NOT be emitted directly; it SHALL be routed through the econ-alert
intelligence gate, which reads the diff and returns a significance verdict, and
the gate's outcome SHALL determine emission: a `high`/`med` verdict emits one
event per matching `(netuid, change-range)` listing matched files,
commit count, and the verdict; a `low` verdict queues a digest line; a `none`
verdict emits nothing but SHALL be recorded. The delivery of an emitted event
SHALL be governed by the econ-code class's registered tier rather than by the
verdict, so the significance verdict continues to drive detection, cooldown,
and the ledger while the tier alone decides whether anything pages. Emission
SHALL be deduplicated by
change-range id. Cooldown SHALL be significance-aware: after an emitted
econ-code event for a netuid, further **`med` or `low`** matching candidates
within the configured cooldown window (default 24 h) SHALL queue digest lines
referencing the open alert instead of emitting, while a **`high`** verdict SHALL
break through the cooldown and emit; the cooldown SHALL suppress emission only,
never recording. When the gate cannot judge a candidate it SHALL emit an
`unjudged` event rather than dropping it, subject to the same dedup and
cooldown-breakthrough rules as a `med` verdict.

#### Scenario: Reward-path commit alerts once when material
- **WHEN** a change range touches files matching econ-code patterns, the gate returns a `high` or `med` verdict, and no cooldown is active for the netuid
- **THEN** exactly one econ-code event is emitted for that range, listing the matched files and carrying the verdict, and it is delivered according to the class's registered tier

#### Scenario: Cosmetic reward-path commit does not alert
- **WHEN** a change range matches econ-code patterns but the gate returns a `none` verdict and no high-stakes path is touched
- **THEN** no event and no digest line are emitted, and the verdict is recorded for audit

#### Scenario: Busy subnet is dampened, not silenced
- **WHEN** further `med` or `low` econ-matching candidates arrive for the same netuid within the cooldown window
- **THEN** they are recorded and queued as digest lines referencing the open alert, and no event is emitted

#### Scenario: A material change breaks through cooldown
- **WHEN** a `high`-verdict econ candidate arrives for a netuid already within its cooldown window
- **THEN** it emits an econ-code event rather than being demoted to a digest line

#### Scenario: A high verdict does not page while the class is demoted
- **WHEN** a `high`-verdict econ-code event is emitted while the econ-code class is registered at the briefing tier
- **THEN** the event is recorded, entered into the effectiveness ledger, and carried in the briefing, and no page is sent
