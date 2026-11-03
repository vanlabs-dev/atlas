## MODIFIED Requirements

### Requirement: Instant events capture alpha-price context at creation
Every event of a registered netuid-scoped alert class SHALL snapshot the
affected subnet's alpha price in
TAO at its anchor time (a cluster event snapshots each member netuid), sourced
from the keyless TaoSwap subnets operation invoked through the live-data
layer's validated machinery, never a raw HTTP call, never a keyed or
quota-budgeted endpoint. The anchor time SHALL be the event's creation time,
except for a gate crossing, whose anchor SHALL be the time it became eligible
for delivery. Classes whose events originate outside the fleet
store SHALL be entered through the same path, so measurement coverage does not
depend on where an event was produced. At most one price fetch SHALL occur per
extraction pass, and its full per-subnet price vector SHALL be stored
(config-capped retention) so fleet baselines need no extra calls. The entry
price SHALL come from the earliest stored vector at or after the anchor time
and within the late-grace window (6 hours). An entry with no such vector once
the window has passed SHALL be marked unavailable, never filled from a later
vector. A failed fetch SHALL never delay, block, or suppress the event or its
delivery.

#### Scenario: Cluster snapshot covers all members from one fetch
- **WHEN** a cluster event with k member subnets is created during an extraction pass
- **THEN** one price fetch records entry prices for all k members and the full fleet vector is stored

#### Scenario: Price outage never blocks alerting
- **WHEN** the price fetch fails during a pass that emitted events
- **THEN** the events are queued and delivered normally with snapshots marked pending, and a later pass fills them only from a vector stored within the late-grace window

#### Scenario: Entry with no vector in the grace window is unavailable
- **WHEN** no price vector was stored between an event's anchor time and the end of its late-grace window
- **THEN** the entry and every horizon of that event are marked unavailable and no price from a later vector is used

#### Scenario: Gate crossing is anchored at eligibility
- **WHEN** a gate crossing observed at time T becomes eligible for delivery at time E
- **THEN** its entry price is taken at or after E and each horizon falls due at E plus the horizon

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
step in the hourly hook. The exit price SHALL come from the earliest stored
vector at or after the due time and within the late-grace window. A subnet
deregistered, price-less, re-registered inside the window, or with no vector in
the grace window SHALL be marked unavailable with its reason, never estimated.
The fleet baseline SHALL exclude every netuid re-registered inside the window.
An `effectiveness` command SHALL report, per alert class and horizon, the
filled count, the number of distinct event moments, the median paired excess
return (subnet return minus baseline over the same window), a 95% interval for
that median, the class and baseline medians, and pending/unavailable tallies,
as read-only measurement: the report SHALL derive no recommendations.

The report SHALL cover every registered measured class, including classes at
the `shadow` and `briefing` tiers, and SHALL state each class's current tier
alongside its figures, so a tier can never be argued for without the evidence
being visible next to it. Where a horizon has more pending than filled
outcomes, the report SHALL mark that horizon as not yet readable.

#### Scenario: Horizon fill compares like windows
- **WHEN** an event's 7-day horizon comes due and prices are available
- **THEN** the outcome row records the subnet's return and the fleet-median return over the same window

#### Scenario: Late exit is unavailable, not stretched
- **WHEN** no price vector was stored between a horizon's due time and the end of its late-grace window
- **THEN** that outcome is marked unavailable and no later vector is used as its exit

#### Scenario: Deregistered subnet is honest data
- **WHEN** an alerted subnet has deregistered before a horizon matures
- **THEN** that outcome row is marked unavailable and the effectiveness report counts it as such

#### Scenario: Re-registered netuid is not one subnet
- **WHEN** an alerted netuid is registered to a new subnet between the entry and the exit vector
- **THEN** that outcome is marked unavailable with reason re-registered, and the netuid is left out of the baseline for that window

#### Scenario: Interval resamples event moments
- **WHEN** a class's outcomes come from N distinct event moments with several netuids each
- **THEN** the interval is computed by resampling whole event moments with a fixed seed, so a repeated run gives the same interval

#### Scenario: Too few events for an interval
- **WHEN** a class horizon has fewer than 10 distinct event moments
- **THEN** the report gives its median excess return and no interval

#### Scenario: Effectiveness report is read-only
- **WHEN** the effectiveness command runs
- **THEN** it prints per-class, per-horizon figures with counts and changes no state

#### Scenario: Report names each class's tier
- **WHEN** the effectiveness command runs
- **THEN** every reported class carries its current delivery tier next to its figures

#### Scenario: Majority-pending horizon is marked unreadable
- **WHEN** a class's horizon holds more pending outcomes than filled ones
- **THEN** the report marks that horizon not yet readable rather than printing a median that invites a decision

## ADDED Requirements

### Requirement: Price vectors carry each subnet's registration block
Each stored price vector SHALL record, per netuid, the `NetworkRegisteredAt`
block read from chain in the same pass through a declared chain read. When that
read fails, the pass SHALL store no vector, as for a failed price fetch. Two
vectors SHALL count as one subnet's prices only when both carry the same
registration block for that netuid. A vector stored before this read existed
SHALL be judged from the netuid's current registration block and recorded
block-time anchors.

#### Scenario: Same registration at both ends
- **WHEN** the entry and exit vectors carry the same registration block for a netuid
- **THEN** the return between them counts as that subnet's return

#### Scenario: Registration read fails
- **WHEN** the price fetch succeeds but the registration read fails
- **THEN** no vector is stored for that pass and pending entries and outcomes wait for a later pass within their grace windows

#### Scenario: Older vector registered after its time
- **WHEN** a vector stored before this change predates the netuid's current registration
- **THEN** returns that start at that vector and end after the registration are unavailable for that netuid

#### Scenario: Older window wholly before a later registration
- **WHEN** both vectors of a window were stored before this change and before the netuid's current registration
- **THEN** the outcome is marked unverified, because an earlier re-registration cannot be ruled out, and the report counts it apart from filled outcomes

### Requirement: Past outcomes can be rescored under the current rules
The module SHALL provide a `rescore` command. It SHALL recompute every filled
or unavailable outcome from the stored vectors under the current entry, exit,
anchor and registration rules. It SHALL write the results to separate columns
and SHALL leave the original return, baseline and status values unchanged. The
command SHALL be idempotent. The effectiveness report SHALL read the rescored
values where they exist.

#### Scenario: Rescore keeps the original values
- **WHEN** `rescore` runs over outcomes filled before this change
- **THEN** each row's original return, baseline and status are unchanged and its rescored values sit in their own columns

#### Scenario: Rescore is idempotent
- **WHEN** `rescore` runs twice over the same store
- **THEN** the second run changes no value

#### Scenario: Stretched historical window is unavailable
- **WHEN** a historical gate-crossing 7-day outcome spans about 5 days because its due time was taken from the crossing
- **THEN** rescore recomputes it from the eligibility anchor, or marks it unavailable when no vector lies in the grace window
