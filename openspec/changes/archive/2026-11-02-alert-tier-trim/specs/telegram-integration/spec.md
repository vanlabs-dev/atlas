## MODIFIED Requirements

### Requirement: Fleet signal events are delivered as tiered classes from a watermarked source

The notifier SHALL consume the fleet signal event queue as an additional scan
source with its own durable watermark stored in the notifier's ledger (never
in the fleet store, which the notifier SHALL open strictly read-only), seeded
by `init` under the existing rule (seeding sends nothing; a seeded watermark
never rolls back; enabling late never replays history). It SHALL deliver
narrative-cluster, watchlist hit, and econ-code change according to each
class's registered delivery tier. Digest lines (term adoptions, post-cluster
adopters, truncated-range notices, minor and cooldown econ lines) SHALL each
take the tier of their source class, resolved from the line's dedup-key
prefix. Only a line whose source class resolves to `instant` SHALL be kept
for a digest; it SHALL ride the durable pending-digest mechanics (never
paged on its own, never dropped once kept). A line whose source class is
unknown or not `instant` SHALL be skipped. The `signal-digest` class SHALL be
registered explicitly. No fleet signal class SHALL page by virtue of being a
fleet signal class; the tier registry alone decides. Delivery priority SHALL
place paging fleet signal alerts below the live chain-runtime-upgrade class
and above churn digests in the same scan. Failure to deliver SHALL follow the
existing contract: fleet reconciliation and extraction are never affected,
and undelivered events remain past the watermark for the next scan.

#### Scenario: Cluster event pages once on the next scan

- **WHEN** the next scheduled scan runs after extraction queued a
  narrative-cluster event (the fleet unit and the scan's unit fire
  independently) and the class is registered at the instant tier
- **THEN** exactly one immediate alert is sent for it and the signal-source
  watermark advances past it

#### Scenario: Adoption lines never page

- **WHEN** only digest lines from an instant-tier source class are pending
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

#### Scenario: Shadowed source class sends no digest line

- **WHEN** the fleet queue holds a `cluster-follow` line while
  `narrative-cluster` is at the shadow tier
- **THEN** the line is not kept for any digest and the watermark advances

#### Scenario: Unknown digest source is skipped

- **WHEN** a digest line's dedup-key prefix maps to no class
- **THEN** the line is not kept for any digest

### Requirement: Every class carries a delivery tier

Each notifier class SHALL carry a configured delivery tier: `instant`,
`briefing`, or `shadow`. Only `instant` classes SHALL page on the scan that
finds their events. Events of `briefing` classes SHALL be recorded in the
ledger as `briefed` with their watermarks advanced, and SHALL surface only as
inputs to the pulse briefing. Loading the configuration SHALL fail when any
class is at the `briefing` tier while the briefing is disabled, so no class
can be routed to an edition that is never sent. Changing a class's tier SHALL
require no code change and SHALL affect no other class. Class content
requirements elsewhere in this specification describe the message a class
renders when it pages; the tier decides whether it pages.

#### Scenario: Briefing-tier event does not page

- **WHEN** the briefing is enabled and a scan finds a new event of a class
  whose tier is `briefing`
- **THEN** no message is sent, the event is recorded as `briefed`, and the
  class watermark advances

#### Scenario: Briefing tier with the briefing off is refused

- **WHEN** `briefing.enabled` is false and any class is at the `briefing` tier
- **THEN** loading the configuration fails and names the class

#### Scenario: Tier is configuration

- **WHEN** the operator sets a shadow-tier class to `instant`
- **THEN** the next scan pages that class's new events as its content
  requirement describes, and no other class changes behaviour

### Requirement: Subnet registry changes are an instant class

The notifier SHALL provide a `subnet-registry` class at the `instant` tier
that pages when the set of netuids in the panel snapshot changes between
passes (a netuid appears or disappears). A change of a subnet's recorded
chain name SHALL be emitted under the delivery-only class `subnet-rename`,
registered at the `shadow` tier. The message SHALL state the netuid, the
change, the previous and new name where applicable, and the reference blocks
on both sides. A first-ever snapshot SHALL seed the set without paging.

#### Scenario: New netuid pages

- **WHEN** a netuid is present in the latest snapshot and absent from the
  previous one
- **THEN** one `subnet-registry` message states the registration with both
  reference blocks

#### Scenario: Deregistration pages

- **WHEN** a netuid is absent from the latest snapshot and present in the
  previous one
- **THEN** one `subnet-registry` message states the deregistration

#### Scenario: Rename is recorded, not sent

- **WHEN** a subnet's chain name changes between snapshots
- **THEN** no message is sent and the event is recorded as `shadowed` under
  `subnet-rename`

#### Scenario: Seed is silent

- **WHEN** the first panel snapshot is recorded
- **THEN** no `subnet-registry` message is sent

### Requirement: Knowledge ingestion is a briefing-tier class that asks for no action

The `knowledge-ingestion` class SHALL be registered at the `shadow` tier.
The alert wording, when it surfaces, SHALL state that new facts are already in
use when the upgrade job has activated the run, and SHALL NOT tell the
operator to review or activate. The class's events SHALL stay recorded in the
ledger.

#### Scenario: Ingest does not page

- **WHEN** a knowledge run finishes with 30 units
- **THEN** no message is sent and the event is recorded as `shadowed`

#### Scenario: Rollback

- **WHEN** the operator sets the tier back to `instant`
- **THEN** the next scan pages new knowledge events, and no other class
  changes behaviour

### Requirement: A crossing with emission already off is recorded and not sent

A confirmed gate crossing for a subnet whose pool-side emission switch is
off SHALL be recorded in the ledger as `shadowed` and SHALL NOT be sent. The
event SHALL be emitted under its own delivery-only class,
`gate-crossing-no-effect`, whose tier is `shadow`, so that flipping the tier
restores the page. The crossing cooldown and eligibility state of the
`gate-crossing` class SHALL NOT be changed by these events.

#### Scenario: Subnet with emission off crosses

- **WHEN** subnet 103 has its emission switch off and its demand share falls
  below the bar
- **THEN** no message is sent, the event is recorded as `shadowed` under
  `gate-crossing-no-effect`, and a later crossing for a subnet with emission
  on still pages

## ADDED Requirements

### Requirement: Only high econ verdicts can page

The notifier SHALL emit a fleet econ event under the `econ-code` class only
when its verdict significance is `high`. Every other econ event (`med`,
`unjudged`, or no verdict) SHALL be emitted under the delivery-only class
`econ-code-minor`. Both classes SHALL ship at the `shadow` tier, so no econ
event pages until the operator promotes `econ-code` under the promotion rule.

#### Scenario: Shipped tiers send no econ alert

- **WHEN** a scan reads econ events with `high` and `med` verdicts under the
  shipped config
- **THEN** no message is sent and both are recorded as `shadowed`

#### Scenario: A promoted class pages high verdicts only

- **WHEN** `econ-code` is at `instant` and a scan reads an econ event with a
  `high` verdict
- **THEN** one `econ-code` message is sent

#### Scenario: Medium verdict is recorded only

- **WHEN** a scan reads an econ event with a `med` or `unjudged` verdict
- **THEN** no message is sent and the event is recorded as `shadowed` under
  `econ-code-minor`
