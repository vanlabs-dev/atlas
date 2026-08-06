## MODIFIED Requirements

### Requirement: Gate-crossing is an instant-tier class with per-netuid cooldown

The notifier SHALL page confirmed emission-gate crossing events (either
direction) as a distinct instant-tier class, reading the livedata
gate-event store read-only past a persisted watermark. Alerts within a
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

- **WHEN** the scan finds an unseen confirmed gate-crossing event outside
  the netuid's cooldown window
- **THEN** one alert is delivered stating direction, share, bar, margin,
  figure sources, the active bar mode, and the bar's movement, and the event
  is marked in the delivery ledger

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

## ADDED Requirements

### Requirement: Chain-parameter change is a distinct instant-tier class

The notifier SHALL page recorded chain-parameter transitions as a sixth
distinct instant-tier class, reading the livedata chain-parameter event
store read-only past its own persisted watermark, independent of every other
class's watermark. A transition of a root-settable economic knob is
unconditionally material and rare, so this class SHALL have no cooldown and
no digest tier — every recorded transition pages once.

The alert body SHALL state the parameter name, the previous and new values,
the provenance of each, the reference block, and a short configured
description of what the parameter governs, as single-fact lines in the
established message style (HTML with plain-text fallback, no em or en
dashes). The configured description is operator-supplied text and SHALL be
escaped by the same renderer path as every other interpolated value.

Where a transition changes the emission-gate bar's selection mode, the body
SHALL say so explicitly rather than leaving the reader to infer it from the
numeric value. Where a bar-parameter transition caused the same pass to
re-seed every subnet's gate side, the body SHALL state that the bar was
re-priced for all subnets and that per-subnet crossing alerts were
deliberately withheld for that pass, so the absence of crossing pages is
legible rather than looking like a gap.

When the class is disabled it SHALL be absent from the scan without affecting
the other classes.

#### Scenario: Recorded transition pages once

- **WHEN** the scan finds an unseen chain-parameter transition event
- **THEN** one alert is delivered stating the parameter, both values, both
  provenances, the reference block, and what the parameter governs, and the
  event is marked in the delivery ledger

#### Scenario: No cooldown suppresses a knob flip

- **WHEN** a second transition of the same parameter is recorded shortly
  after a paged one
- **THEN** it is paged as well, with no cooldown suppression applied

#### Scenario: Gate mode change is stated in words

- **WHEN** the transition is a rank change that moves the bar between
  rank-pinned and q-mass selection
- **THEN** the body states the resulting selection mode explicitly

#### Scenario: Re-seeded pass is explained, not silent

- **WHEN** the transition is a bar-parameter change whose pass re-seeded all
  gate sides
- **THEN** the body states that the bar was re-priced for every subnet and
  that per-subnet crossing pages were withheld for that pass

#### Scenario: Configured description is escaped

- **WHEN** the configured description contains characters significant to the
  message markup
- **THEN** it is escaped by the shared renderer and the message is delivered
  intact or falls back to plain text

#### Scenario: Class watermark is independent

- **WHEN** the chain-parameter class fails or is disabled
- **THEN** no other class's watermark is affected and the remaining classes
  are scanned unchanged

#### Scenario: Disabled class is inert

- **WHEN** the chain-parameter-change class is disabled in configuration
- **THEN** the scan processes the other classes unchanged and no
  chain-parameter watermark advances
