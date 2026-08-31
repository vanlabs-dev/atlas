## ADDED Requirements

### Requirement: Every class carries a delivery tier

Each notifier class SHALL carry a configured delivery tier, `instant` or
`briefing`. Only `instant` classes SHALL page on the scan that finds their
events. Events of `briefing` classes SHALL be recorded in the ledger as
`briefed` with their watermarks advanced, and SHALL surface only as inputs
to the pulse briefing. Default tiers SHALL be: `instant` for
`chain-runtime-upgrade`, `chain-parameter-change`, `subnet-registry`, and
the Atlas fail-closed condition; `briefing` for every other class. Changing
a class's tier SHALL require no code change and SHALL affect no other class.
Class content requirements elsewhere in this specification describe the
message a class renders when it pages; the tier decides whether it pages.

#### Scenario: Briefing-tier event does not page

- **WHEN** a scan finds a new event of a class whose tier is `briefing`
- **THEN** no message is sent, the event is recorded as `briefed`, and the
  class watermark advances

#### Scenario: Tier is configuration

- **WHEN** the operator sets a briefing-tier class back to `instant`
- **THEN** the next scan pages that class's new events as its content
  requirement describes, and no other class changes behaviour

### Requirement: Subnet registry changes are an instant class

The notifier SHALL provide a `subnet-registry` class that pages when the set
of netuids in the panel snapshot changes between passes (a netuid appears or
disappears) or a subnet's recorded chain name changes. The message SHALL
state the netuid, the change, the previous and new name where applicable,
and the reference blocks on both sides. A first-ever snapshot SHALL seed the
set without paging.

#### Scenario: New netuid pages

- **WHEN** a netuid is present in the latest snapshot and absent from the
  previous one
- **THEN** one `subnet-registry` message states the registration with both
  reference blocks

#### Scenario: Seed is silent

- **WHEN** the first panel snapshot is recorded
- **THEN** no `subnet-registry` message is sent

### Requirement: Persistent fail-closed state pages once

When a provider, the gate poll, or the chain-parameter watch has recorded
only failures for longer than a configured window, the notifier SHALL page
one message naming the component, the first failure time, and the last
recorded good observation, and SHALL NOT page again for that component
until it has recovered and failed anew.

#### Scenario: Prolonged outage pages once

- **WHEN** a component has recorded only failures for longer than the window
- **THEN** exactly one message is sent for that outage

## MODIFIED Requirements

### Requirement: Live chain-runtime-upgrade is a distinct high-priority class

The notifier SHALL provide a `chain-runtime-upgrade` class that fires when the
live runtime `spec_version` changes, based on the live-data upgrade record. Its
message SHALL be marked as a live-chain (enacted) event, distinct from repository
alerts, and SHALL state the previous and new live `spec_version` and the
reference block. When the repository store holds a range whose recorded spec
delta matches the upgrade, the message SHALL additionally state that range's
release commit subject and its top touched areas, so the upgrade message
explains the change it announces; when no matching range is recorded, the
message SHALL say the repository evidence is not yet tracked. Crossing a
governance threshold (e.g. conviction ownership at `spec_version` >= 425)
SHALL be surfaced within this class.

#### Scenario: Live spec change fires a chain upgrade alert

- **WHEN** the live-data store records a live `spec_version` change
- **THEN** a `chain-runtime-upgrade` alert is delivered, marked as a live-chain
  event, stating the previous and new live `spec_version` and reference block

#### Scenario: Matching range supplies the release subject

- **WHEN** a repository range with the same spec delta is recorded
- **THEN** the alert states that range's release commit subject and top
  touched areas

#### Scenario: No matching range is stated

- **WHEN** no repository range with that spec delta is recorded
- **THEN** the alert states that repository evidence is not yet tracked

#### Scenario: Governance threshold is surfaced

- **WHEN** a live `spec_version` change crosses a configured governance threshold
- **THEN** the chain-upgrade alert notes the threshold crossing

### Requirement: Fleet signal events are delivered as tiered classes from a watermarked source

The notifier SHALL consume the fleet signal event queue as an additional scan
source with its own durable watermark stored in the notifier's ledger (never
in the fleet store, which the notifier SHALL open strictly read-only), seeded
by `init` under the existing rule (seeding sends nothing; a seeded watermark
never rolls back; enabling late never replays history). It SHALL recognise
four classes: narrative-cluster, watchlist hit, econ-code change, and
term-adoption digest lines (including post-cluster adopters and
truncated-range notices). Each SHALL be delivered according to its
configured tier: at `briefing` tier (the default) events are recorded as
briefed and surface in the pulse briefing's code and narrative sections; at
`instant` tier the first three page immediately and adoption lines ride the
existing durable pending-digest mechanics (never paged, never dropped).
Delivery priority for instant fleet alerts SHALL place them below the live
chain-runtime-upgrade class and above churn digests in the same scan.
Failure to deliver SHALL follow the existing contract: fleet reconciliation
and extraction are never affected, and undelivered events remain past the
watermark for the next scan.

#### Scenario: Briefing tier records without paging

- **WHEN** the next scan runs after extraction queued a narrative-cluster
  event and the class tier is `briefing`
- **THEN** no message is sent, the event is recorded as briefed, and the
  signal-source watermark advances past it

#### Scenario: Cluster event pages once on the next scan

- **WHEN** the class tier is `instant` and the next scan runs after
  extraction queued a narrative-cluster event
- **THEN** exactly one immediate alert is sent for it and the watermark
  advances past it

#### Scenario: Adoption lines never page

- **WHEN** only term-adoption digest events are pending
- **THEN** no immediate alert is sent and the lines are durably retained until
  included in a delivered digest or briefing

#### Scenario: Ordering within a mixed scan

- **WHEN** one scan holds a chain-runtime-upgrade event, an instant-tier
  fleet signal alert, and pending churn
- **THEN** the chain upgrade is delivered first, the fleet signal alert next,
  and churn rides the digest

### Requirement: Gate-crossing is an instant-tier class with per-netuid cooldown

The notifier SHALL provide a `gate-crossing` class for confirmed
emission-gate crossing events (either direction), reading the livedata
gate-event store read-only past a persisted watermark. Its default tier
SHALL be `briefing`: crossings are recorded as briefed and reported in the
pulse briefing as demand-share movers, with hovering subnets summarised as a
count. At `instant` tier the class SHALL page as follows. Alerts within a
per-netuid cooldown window SHALL be recorded but not paged, never dropped,
and crossings carrying the hovering annotation SHALL be recorded but not
paged. The alert body SHALL state the netuid, direction, demand share, bar
value, margin, and the source of each figure (panel-derived share vs
chain-read bar) as single-fact lines in the established message style (HTML
with plain-text fallback, no em or en dashes), and SHALL note when the
crossing subnet is currently emission-disabled (the crossing is
informational; the subnet earns zero either way).

The body SHALL additionally state the bar's active selection mode recorded
with the crossing, rank-pinned (naming the effective rank) or q-mass
(naming the effective quantile), so the reader is never left to infer the
mechanism behind the bar figure.

Because a rank-pinned bar is itself a demand share and therefore moves, the
body SHALL state whether the bar moved between the crossing's observation and
the previous one, so a subnet the bar descended onto is never presented as a
subnet whose demand rose. Where the recorded bar movement alone accounts for
the crossing, the body SHALL attribute it to the bar rather than to the
subnet.

When the class is disabled it SHALL be absent from the scan without affecting
the other classes.

#### Scenario: Briefing tier records the crossing

- **WHEN** the scan finds an unseen confirmed gate-crossing event and the
  class tier is `briefing`
- **THEN** the event is recorded as briefed, no page is sent, and the
  crossing is available to the briefing's subnets section

#### Scenario: Confirmed crossing pages once

- **WHEN** the class tier is `instant` and the scan finds an unseen confirmed
  gate-crossing event outside the netuid's cooldown window without the
  hovering annotation
- **THEN** one alert is delivered stating direction, share, bar, margin,
  figure sources, the active bar mode, and the bar's movement, and the event
  is marked in the delivery ledger

#### Scenario: Hovering crossing does not page

- **WHEN** the class tier is `instant` and the crossing carries the hovering
  annotation
- **THEN** the event is recorded as suppressed and no page is sent

#### Scenario: Bar mode is named from the crossing's own observation

- **WHEN** a crossing is paged
- **THEN** the body names the bar mode recorded with that crossing rather
  than a configured or assumed mechanism

#### Scenario: Bar-driven crossing is attributed to the bar

- **WHEN** the crossing's recorded bar movement alone accounts for the side
  change and the subnet's share did not materially move
- **THEN** the body attributes the crossing to the bar moving, not to a
  change in the subnet's demand

#### Scenario: Cooldown records without paging

- **WHEN** a further crossing event for the same netuid falls inside the
  cooldown window
- **THEN** the event is recorded in the ledger as suppressed and no page is
  sent

#### Scenario: Legacy crossing without a recorded mode still renders

- **WHEN** a crossing recorded before bar-mode tracking is paged
- **THEN** the body renders without asserting a bar mode or a bar movement

#### Scenario: Disabled class is inert

- **WHEN** the gate-crossing class is disabled in configuration
- **THEN** the scan processes the other classes unchanged and no
  gate-crossing watermark advances
