## ADDED Requirements

### Requirement: Delivery honours the registered class tier

The notifier SHALL read each class's registered delivery tier and SHALL route
accordingly: an `instant` class pages; a `briefing` class is recorded as
briefed and carried in the next pulse edition; a `shadow` class is recorded
and carried nowhere. A `shadow` class SHALL still advance its source
watermark, so a later promotion delivers only events created after the tier
change and never replays a backlog.

Every class SHALL be recorded in the delivery ledger whatever its tier, with a
status naming the tier that governed it, so the ledger remains a complete
account of what was detected and what was sent.

#### Scenario: Shadow class sends nothing but advances

- **WHEN** a scan finds unseen events of a shadow-tier class
- **THEN** nothing is sent, each event is recorded in the ledger against the
  shadow tier, and the source watermark advances past them

#### Scenario: Promotion does not replay a backlog

- **WHEN** a class is promoted from shadow to instant
- **THEN** only events created after the tier change are paged, and events
  recorded while it was shadow are not re-sent

#### Scenario: Briefing class rides the edition

- **WHEN** a scan finds unseen events of a briefing-tier class
- **THEN** no page is sent, the events are recorded as briefed, and they are
  carried in the next pulse edition

#### Scenario: Ledger names the governing tier

- **WHEN** any event is processed by a scan
- **THEN** its ledger row records the tier that governed its delivery

### Requirement: Root-rotation is a delivered class rendered from recorded fields

The notifier SHALL deliver root-rotation events, reading the livedata
root-rotation store read-only past a persisted watermark, at whatever tier the
class is registered. The class SHALL be registered at the `shadow` tier on
introduction.

The alert body SHALL state the destination netuid, the previous and new
aggregate share, the number of contributing validators, the weighting basis,
and the block reference, as single-fact lines in the established message style
(HTML with plain-text fallback, no em or en dashes). Where the aggregate map
is unweighted, the body SHALL say so rather than presenting the share as a
share of dividend flow. Every figure SHALL come from the recorded event; the
renderer SHALL NOT compute, estimate, or infer a figure the event does not
carry.

When the class is disabled it SHALL be absent from the scan without affecting
the other classes.

#### Scenario: Rotation event renders its recorded figures

- **WHEN** a root-rotation event is delivered
- **THEN** the body states destination netuid, previous and new share,
  contributing validator count, weighting basis, and block reference, each
  taken from the recorded event

#### Scenario: Unweighted aggregate is labelled

- **WHEN** the event's weighting basis is unweighted
- **THEN** the body states that the share is unweighted and does not describe
  it as a share of dividend flow

#### Scenario: Class starts silent

- **WHEN** root-rotation events are first produced
- **THEN** the class is at the shadow tier, the events are recorded, and
  nothing is sent

#### Scenario: Disabled class is inert

- **WHEN** the root-rotation class is disabled in configuration
- **THEN** the scan processes the other classes unchanged and no
  root-rotation watermark advances

## MODIFIED Requirements

### Requirement: Fleet signal events are delivered as tiered classes from a watermarked source

The notifier SHALL consume the fleet signal event queue as an additional scan
source with its own durable watermark stored in the notifier's ledger (never
in the fleet store, which the notifier SHALL open strictly read-only), seeded
by `init` under the existing rule (seeding sends nothing; a seeded watermark
never rolls back; enabling late never replays history). It SHALL deliver
narrative-cluster, watchlist hit, and econ-code change according to each
class's registered delivery tier, and term-adoption lines
(including post-cluster adopters and truncated-range notices) as digest
content carried under the existing durable pending-digest mechanics (never
paged, never dropped). No fleet signal class SHALL page by virtue of being a
fleet signal class; the tier registry alone decides. Delivery priority SHALL
place paging fleet signal alerts below
the live chain-runtime-upgrade class and above churn digests in the same scan.
Failure to deliver SHALL follow the existing contract: fleet reconciliation
and extraction are never affected, and undelivered events remain past the
watermark for the next scan.

#### Scenario: Cluster event pages once on the next scan

- **WHEN** the next scheduled scan runs after extraction queued a
  narrative-cluster event (the fleet unit and the scan's unit fire
  independently) and the class is registered at the instant tier
- **THEN** exactly one immediate alert is sent for it and the signal-source
  watermark advances past it

#### Scenario: Adoption lines never page

- **WHEN** only term-adoption digest events are pending
- **THEN** no immediate alert is sent and the lines are durably retained until
  included in a delivered digest

#### Scenario: Ordering within a mixed scan

- **WHEN** one scan holds a chain-runtime-upgrade event, a paging fleet signal
  alert, and pending churn
- **THEN** the chain upgrade is delivered first, the fleet signal alert next,
  and churn rides the digest

#### Scenario: Demoted fleet class does not page

- **WHEN** a scan holds econ-code events while that class is registered at the
  briefing tier
- **THEN** no page is sent for them, they are recorded as briefed, and the
  watermark advances

#### Scenario: Briefing tier records without paging

- **WHEN** the next scan runs after extraction queued a narrative-cluster
  event and the class tier is `briefing`
- **THEN** no message is sent, the event is recorded as briefed, and the
  signal-source watermark advances past it


### Requirement: Gate-crossing is an instant-tier class with per-netuid cooldown

The notifier SHALL page emission-gate crossing events that the live-data
component has marked eligible for delivery, in either direction, as a distinct
instant-tier class, reading the livedata
gate-event store read-only past a persisted watermark. A crossing that is not
yet eligible SHALL be left for a later scan; a crossing marked reversed SHALL
be recorded as reversed and never paged, and its watermark SHALL advance past
it. Alerts within a
per-netuid cooldown window SHALL be recorded but not paged — never dropped.
The alert body SHALL state the netuid, direction, demand share, bar value,
margin, and the source of each figure (panel-derived share vs chain-read
bar) as single-fact lines in the established message style (HTML with
plain-text fallback, no em or en dashes), and SHALL note when the crossing
subnet is currently emission-disabled (the crossing is informational — the
subnet earns zero either way).

The body SHALL additionally state the bar's active selection mode recorded
with the crossing — rank-pinned (naming the effective rank) or q-mass
(naming the effective quantile) — so the reader is never left to infer the
mechanism behind the bar figure.

Because a rank-pinned bar is itself a demand share and therefore moves, the
body SHALL state whether the bar moved between the crossing's observation and
the previous one, so a subnet the bar descended onto is never presented as a
subnet whose demand rose. Where the recorded bar movement alone accounts for
the crossing, the body SHALL attribute it to the bar rather than to the
subnet.

When the class is disabled it SHALL be absent from the scan without affecting
the other classes.

#### Scenario: Confirmed crossing pages once

- **WHEN** the scan finds an unseen gate-crossing event marked eligible for
  delivery and outside the netuid's cooldown window
- **THEN** one alert is delivered stating direction, share, bar, margin,
  figure sources, the active bar mode, and the bar's movement, and the event
  is marked in the delivery ledger

#### Scenario: Reversed crossing is recorded, never paged

- **WHEN** the scan finds a crossing marked reversed
- **THEN** it is recorded in the ledger as reversed, no page is sent, and the
  watermark advances past it

#### Scenario: Not-yet-eligible crossing waits

- **WHEN** the scan finds a confirmed crossing whose durability window has not
  elapsed
- **THEN** no page is sent, the watermark does not advance past it, and a
  later scan reconsiders it

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

- **WHEN** a further eligible crossing event for the same netuid falls inside
  the cooldown window
- **THEN** the event is recorded in the ledger as suppressed and no page is
  sent

#### Scenario: Legacy crossing without a recorded mode still renders

- **WHEN** a crossing recorded before bar-mode tracking is paged
- **THEN** the body renders without asserting a bar mode or a bar movement

#### Scenario: Disabled class is inert

- **WHEN** the gate-crossing class is disabled in configuration
- **THEN** the scan processes the other classes unchanged and no
  gate-crossing watermark advances

#### Scenario: Briefing tier records the crossing

- **WHEN** the scan finds an unseen confirmed gate-crossing event and the
  class tier is `briefing`
- **THEN** the event is recorded as briefed, no page is sent, and the
  crossing is available to the briefing's subnets section

#### Scenario: Hovering crossing does not page

- **WHEN** the class tier is `instant` and the crossing carries the hovering
  annotation
- **THEN** the event is recorded as suppressed and no page is sent

