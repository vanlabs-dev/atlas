# signal-effectiveness-gate Specification

## Purpose
Governs which alert classes are allowed to page the operator, by requiring
every netuid-scoped class to be measured against the fleet baseline before it
earns an instant tier and to keep being measured after it loses one.

## Requirements

### Requirement: Every netuid-scoped alert class is registered with a delivery tier

The system SHALL maintain a registry of netuid-scoped alert classes in which
each class declares exactly one delivery tier: `instant`, `briefing`, or
`shadow`. A class not present in the registry SHALL NOT be delivered. The
registry SHALL be configuration, so a tier change requires no code change and
is reversible by reverting the value.

Registration SHALL be independent of detection: a class's detector, its
cooldowns, and its recording behaviour SHALL be unaffected by its tier.

#### Scenario: Unregistered class cannot page

- **WHEN** an event is produced for a class absent from the tier registry
- **THEN** the event is recorded and no alert is delivered for it

#### Scenario: Tier is reversible configuration

- **WHEN** a class's tier value is changed back to its previous value
- **THEN** delivery behaviour returns to the previous behaviour and no stored
  event, entry, or outcome row is altered

### Requirement: A shadow-tier class records and is measured but never pages

A class at the `shadow` tier SHALL produce and persist its events, SHALL have
each event entered into the effectiveness ledger exactly as an instant-tier
event is, and SHALL NOT be delivered as an alert or included in a briefing
edition. A shadow class SHALL be reported by the effectiveness command
alongside delivered classes, so its measurement accrues before any decision is
taken about it.

A newly introduced netuid-scoped class SHALL default to `shadow`.

#### Scenario: New class starts silent

- **WHEN** a netuid-scoped alert class is introduced without an explicit tier
- **THEN** it is registered at the shadow tier, its events are recorded and
  entered into the ledger, and nothing is delivered

#### Scenario: Shadow events are measured like instant events

- **WHEN** a shadow-tier event is created and its configured horizons come due
- **THEN** entry price and outcome rows are recorded against the fleet
  baseline over identical windows, exactly as for an instant-tier event

#### Scenario: Shadow class appears in the effectiveness report

- **WHEN** the effectiveness command runs while a class is at the shadow tier
- **THEN** that class's per-horizon medians, counts, and pending tallies are
  reported

### Requirement: Promotion to instant requires a filled ledger read that beats the baseline

A class SHALL be promoted from `shadow` or `briefing` to `instant` only by an
explicit operator decision recorded in the project decision log, taken against
an effectiveness read in which that class has at least a configured minimum
number of filled outcomes at the 7-day horizon and a median return exceeding
the fleet-median baseline over the same windows.

The recorded decision SHALL state the class, the horizon, the filled count,
the class median, and the baseline median as read at the time of the decision.
A promotion SHALL NOT be justified by a horizon whose outcomes are majority
pending.

#### Scenario: Insufficient sample blocks promotion

- **WHEN** a class's 7-day horizon has fewer filled outcomes than the
  configured minimum
- **THEN** the class is not eligible for promotion and the effectiveness
  report states that its sample is insufficient

#### Scenario: Majority-pending horizon cannot justify promotion

- **WHEN** a class's horizon has more pending outcomes than filled outcomes
- **THEN** that horizon is not eligible to justify a promotion, whatever its
  median shows

#### Scenario: Promotion is recorded with its evidence

- **WHEN** a class is promoted to the instant tier
- **THEN** the decision log carries the class, horizon, filled count, class
  median, and baseline median that justified it

### Requirement: A demoted class keeps recording and keeps being measured

Demoting a class SHALL change only its delivery. Its detector, verdicts,
cooldowns, event rows, ledger entries, and outcome fills SHALL continue
unchanged, so a demotion can be reversed on later evidence and so a class
demoted on a half-filled horizon can still mature.

Demotion SHALL be recorded in the project decision log with the effectiveness
read that justified it, stated as filled count, class median, and baseline
median per horizon.

#### Scenario: Demotion does not stop measurement

- **WHEN** a class is demoted from instant to briefing
- **THEN** its later events are still created, entered into the ledger, and
  filled at every configured horizon

#### Scenario: Demotion is recorded with its evidence

- **WHEN** a class is demoted
- **THEN** the decision log carries the per-horizon filled counts, class
  medians, and baseline medians that justified it

#### Scenario: Reversal restores paging without backfilling pages

- **WHEN** a demoted class is later promoted again
- **THEN** events created while it was demoted are not paged retroactively and
  only events after the tier change are delivered
