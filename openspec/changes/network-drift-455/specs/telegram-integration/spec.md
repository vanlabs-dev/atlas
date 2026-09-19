## MODIFIED Requirements

### Requirement: Chain-parameter change is a distinct instant-tier class

The notifier SHALL page recorded chain-parameter transitions as a sixth
distinct instant-tier class, reading the livedata chain-parameter event
store read-only past its own persisted watermark, independent of every other
class's watermark. A transition of a root-settable economic knob is
unconditionally material and rare, so this class SHALL have no cooldown and
no digest tier — every recorded transition pages once.

Netuid-keyed items are the exception to one page per event, and only in how
the pages are grouped. A root-origin call can write one netuid-keyed item for
many subnets at a single block, and paging each one would bury the fact in
its own volume. Unseen transitions of ONE netuid-keyed item sharing ONE
reference block SHALL therefore be delivered as a single alert stating the
item, the direction of the change, the count of subnets affected, and the
netuid list. Each collapsed transition SHALL still be recorded individually
in the delivery ledger against its own event identifier, so the collapse
changes how the facts are presented and never which facts are retained. Where
the netuid list is too long for the message, it SHALL be truncated with the
count stated in full and the truncation made explicit, never silently
shortened. Transitions of different items, or of one item at different
reference blocks, SHALL NOT be collapsed together.

The alert body SHALL state the parameter name, the previous and new values,
the provenance of each, the reference block, and a short configured
description of what the parameter governs, as single-fact lines in the
established message style (HTML with plain-text fallback, no em or en
dashes). For a collapsed batch the previous and new values are the shared
direction of the change. The configured description is operator-supplied text
and SHALL be escaped by the same renderer path as every other interpolated
value.

Where a transition changes the emission-gate bar's selection mode, the body
SHALL say so explicitly rather than leaving the reader to infer it from the
numeric value. Where a bar-parameter transition caused the same pass to
re-seed every subnet's gate side, the body SHALL state that the bar was
re-priced for all subnets and that per-subnet crossing alerts were
deliberately withheld for that pass, so the absence of crossing pages is
legible rather than looking like a gap.

Where the transition is of the pool-side emission switch, the body SHALL name
it as the switch and not as the emission gate, and SHALL state that a subnet
turned off keeps distributing alpha while losing its TAO injection, so the
reader does not read it as a change in demand.

When the class is disabled it SHALL be absent from the scan without affecting
the other classes.

#### Scenario: Recorded transition pages once

- **WHEN** the scan finds an unseen chain-parameter transition event
- **THEN** one alert is delivered stating the parameter, both values, both
  provenances, the reference block, and what the parameter governs, and the
  event is marked in the delivery ledger

#### Scenario: A same-block batch is one page, not many

- **WHEN** the scan finds many unseen transitions of one netuid-keyed item
  sharing one reference block
- **THEN** one alert is delivered stating the item, the direction, the count
  and the netuid list, and every collapsed event is marked individually in
  the delivery ledger

#### Scenario: A long netuid list truncates visibly

- **WHEN** a collapsed batch carries more netuids than the message can hold
- **THEN** the count is stated in full, the list is truncated, and the
  truncation is stated rather than left implicit

#### Scenario: Different items at one block are not merged

- **WHEN** two different netuid-keyed items record transitions at the same
  reference block
- **THEN** each item is delivered as its own alert

#### Scenario: The emission switch is named as a switch

- **WHEN** the transition is of the pool-side emission switch
- **THEN** the body names the switch, not the emission-gate bar, and states
  that alpha distribution continues while TAO injection stops

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
