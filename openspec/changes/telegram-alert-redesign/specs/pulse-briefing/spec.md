# Spec Delta

## ADDED Requirements

### Requirement: Each edition has a distinct header

The first line of each edition SHALL start with an edition marker, ☀️ for
the daily and 🗓️ for the weekly, followed by the edition name and its date
or date range. Editions SHALL NOT use the alert severity markers.

#### Scenario: Daily header

- **WHEN** a daily edition for 2026-10-03 renders
- **THEN** its first line is `☀️ Atlas daily · Sat 3 Oct`

#### Scenario: Weekly header

- **WHEN** a weekly edition for the window 2026-09-27 to 2026-10-03 renders
- **THEN** its first line is `🗓️ Atlas weekly · 27 Sep to 3 Oct`

### Requirement: Each edition opens with a rule-based summary

Each edition SHALL open, under its header, with one summary line composed
by fixed rules from the edition's own figures: the TAO price move, the
largest demand-share or price mover, and the count of rule changes and
high-impact incentive changes when non-zero. The line SHALL make no model
call and SHALL state no figure absent from the edition.

#### Scenario: Quiet day is called quiet

- **WHEN** an edition records no crossings and no rule changes
- **THEN** the summary line starts with `Quiet day.`

#### Scenario: Summary figures match the body

- **WHEN** the summary names a mover and a percentage
- **THEN** the same mover and percentage appear in that edition's body

### Requirement: High-impact incentive changes section

The edition SHALL list every incentive-code verdict of significance `high`
recorded in its window, one line each, as `Name (N): what changed`, with
the verdict text clipped on a word boundary. Medium verdicts SHALL NOT be
counted or listed. When the window holds no high verdict, the section SHALL
be omitted. The weekly edition SHALL show at most five lines in the body and
the rest in the details fold.

#### Scenario: Only high verdicts appear

- **WHEN** the window holds one high and eight medium verdicts
- **THEN** the section shows one named line and no medium count

#### Scenario: No high verdict omits the section

- **WHEN** the window holds no high verdict
- **THEN** the edition has no incentive changes section

## MODIFIED Requirements

### Requirement: Fixed sections in fixed order with deltas

The briefing SHALL render fixed sections in a fixed order: network, chain
rule changes, biggest price moves, biggest demand-share moves, watch list,
high-impact incentive changes, then a details fold for system health. A
section with no lines SHALL be omitted. Each section SHALL be a short list
of single-fact lines. Where a prior edition exists, each figure SHALL be
accompanied by its change since that edition (or since the window start for
windowed figures), and the direction of change SHALL be stated in words the
lexicon approves. The first edition SHALL render without deltas and say so.
Line vocabulary SHALL come from the approved lexicon and gloss map. Subnets
SHALL be named `Name (N)` and SHALL NOT use the `SN` form.

#### Scenario: Ordered sections

- **WHEN** a briefing renders
- **THEN** the sections appear in the fixed order and each contains only
  single-fact lines

#### Scenario: Delta against the previous edition

- **WHEN** a prior edition of the same kind exists
- **THEN** each figure that has a prior value shows its change since that
  edition

#### Scenario: First edition has no deltas

- **WHEN** no prior edition exists
- **THEN** the briefing renders current values and states that it is the
  first edition

#### Scenario: Removed content stays out

- **WHEN** any edition renders
- **THEN** it contains no total staked, subnet share of stake, new accounts,
  ownership contested, medium verdict count, pushed-subnet count, repository
  re-point, model adoption, cluster, or mining board line

### Requirement: Network section content

The network section SHALL state: TAO/USD with its change over the window
and the date of the vitals it comes from; the current bar as a percentage,
its change over the window, the above-bar count, and the number of
crossings in the window; and the live runtime spec version, as a range when
it changed in the window. When a matching repository range is recorded, its
release subject SHALL appear in the details fold. Root-settable parameter transitions recorded in
the window SHALL render in their own chain rule changes section, named per
subnet in plain words, with a set-then-reset pair on one subnet merged into
one line.

#### Scenario: Vitals carry their date

- **WHEN** network vitals are rendered
- **THEN** the TAO price carries the date of the observation it comes from

#### Scenario: Release subject joins the spec version

- **WHEN** the live runtime spec has a matching repository range with a
  recorded commit subject
- **THEN** the network section states the spec version and the details
  fold states that subject

#### Scenario: Spec change shows the range

- **WHEN** the live runtime spec moved from 470 to 472 inside the window
- **THEN** the network section shows `Runtime spec 470 → 472`

#### Scenario: Set-then-reset is one line

- **WHEN** one subnet's parameter went from 0 to 62258 and back to 0 inside
  the window
- **THEN** the chain rule changes section shows one line for it saying the
  value was set, then reset to 0

### Requirement: Subnets section content

The briefing SHALL show the three largest alpha price moves and the three
largest demand-share moves beyond their configured thresholds, each as
`Name (N): from → to, change`. Block numbers SHALL NOT appear in these
lines. The watch list SHALL show the three non-immune subnets with the
lowest deregistration prune rank in the latest snapshot, whatever their risk
level, numbered 1 to 3. Hovering subnets SHALL appear as one `At the bar`
line naming each one.

#### Scenario: Movers cite both ends

- **WHEN** a price or share mover is listed
- **THEN** the line states the value at the window start and at the window
  end, and the change between them

#### Scenario: Critical subnets are not dropped

- **WHEN** the latest snapshot ranks five `critical` subnets ahead of the
  `high` ones
- **THEN** the watch list shows the first three of those critical subnets

#### Scenario: Immune subnets are excluded

- **WHEN** the subnet with prune rank 1 is in its immunity period
- **THEN** the watch list skips it and shows the next three non-immune
  subnets

#### Scenario: Hoverers are a count

- **WHEN** subnets are flagged as hovering at the bar
- **THEN** the watch list shows one `At the bar` line naming each of them

### Requirement: Atlas section content

The system health fold SHALL state provider health over the window
(failures and drift events by provider), the above-bar count distribution
over the window, TaoStats quota used against its ceiling, the last
knowledge ingest date, the date of the price data, and any class whose
watermark has not advanced inside its expected interval. These lines SHALL
render only inside the expandable details fold.

#### Scenario: Cross-check distribution is visible

- **WHEN** the system health fold renders
- **THEN** it states how many polls in the window observed each above-bar
  count

### Requirement: Bounded size and priority truncation

An edition SHALL fit within a configured number of Telegram messages. When
the composed content exceeds the bound, the details fold SHALL shrink
first, then whole lines SHALL be dropped from the lowest-priority section
upward, and the edition SHALL state how many lines were omitted. The
network section SHALL never be truncated. The last line of the final
message SHALL be the next action when one exists; otherwise the edition
SHALL end on its last section. No edition SHALL link to the LAN board.

#### Scenario: Overflow drops whole low-priority lines

- **WHEN** the composed edition exceeds the message bound
- **THEN** the fold shrinks first, whole lines are then removed starting
  from the lowest-priority section, the network section is intact, and the
  omission count is stated

#### Scenario: Closing line

- **WHEN** an edition is rendered with no next action
- **THEN** it ends on its last section and carries no board link

## REMOVED Requirements

### Requirement: Code, narrative, and mining section content

**Reason**: The operator removed the pushed-subnet count, the medium verdict
count, repository re-points, model adoptions, cluster events, and the mining
board from the briefing on 2026-10-04. High-impact verdicts move to their
own section.
**Migration**: High verdicts render in the "High-impact incentive changes
section". Cluster events still page through the narrative-cluster class.
The mining board stays on the LAN board and in subnt.
