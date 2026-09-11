## Purpose

Delivers a scheduled Telegram briefing that reads the network and subnet
state Atlas already records and reports it as change since the last edition,
so the operator samples the pulse on a rhythm instead of receiving an event
stream.

## ADDED Requirements

### Requirement: The briefing is composed from recorded state only

The briefing SHALL be built exclusively from rows already persisted in the
livedata, fleet, repotrack, knowledge, and notifier stores, opened read-only.
Composing a briefing SHALL trigger no provider call and no model call. Every
figure SHALL be traceable to a stored row with a reference block or
timestamp, and every line SHALL be a recorded fact or a comparison of two
recorded facts. A section whose inputs are absent or older than a configured
staleness bound SHALL state that the input is unavailable or omit the line;
it SHALL NOT estimate, interpolate, or carry a value forward as current.

#### Scenario: No provider or model call during composition

- **WHEN** a briefing is composed
- **THEN** no network request and no Hermes invocation is made, and the
  provider audit and judge budget are unchanged

#### Scenario: Stale input is named, not reused

- **WHEN** a section's newest input is older than its staleness bound
- **THEN** the section states the input's age or omits the line, and no
  value is presented as current

### Requirement: Fixed sections in fixed order with deltas

The briefing SHALL render fixed sections in a fixed order: network, subnets,
code, narrative, mining, atlas. Each section SHALL be a short list of
single-fact lines. Where a prior edition exists, each figure SHALL be
accompanied by its change since that edition (or since the window start for
windowed figures), and the direction of change SHALL be stated in words the
lexicon approves. The first edition SHALL render without deltas and say so.
Line vocabulary SHALL come from the approved lexicon and gloss map.

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

### Requirement: Network section content

The network section SHALL state: the live runtime spec version and, when a
matching repository range is recorded, the release subject; any root-settable
parameter transition recorded since the previous edition; the current theta,
its change over the window, the effective rank, and the above-bar count; the
number of gate side changes in the window; TAO/USD, total staked TAO, the
subnet share of stake, and new accounts per day from the most recent network
vitals, with their date.

#### Scenario: Release subject joins the spec version

- **WHEN** a runtime upgrade recorded in the window has a matching repository
  range with a recorded commit subject
- **THEN** the network section states the new spec version with that
  subject

#### Scenario: Vitals carry their date

- **WHEN** network vitals are rendered
- **THEN** each figure carries the date of the observation it comes from

### Requirement: Subnets section content

The subnets section SHALL rank movers over the window from the panel
snapshot: alpha price movers up and down beyond a configured threshold,
demand-share movers, net capital flow leaders, subnets whose dereg risk is
high or whose immunity ends inside the window, and subnets whose ownership
became contested or takeover-eligible. Each mover line SHALL name the subnet
by netuid and recorded chain name, state the from and to values, and cite the
reference blocks. Hovering subnets SHALL be summarised as a count with their
netuids, not listed as individual crossings.

#### Scenario: Movers cite both ends

- **WHEN** a price or share mover is listed
- **THEN** the line states the value at the window start and end with their
  reference blocks

#### Scenario: Hoverers are a count

- **WHEN** subnets flagged as hovering recorded crossings in the window
- **THEN** the subnets section reports them as one line with a count and
  netuids

### Requirement: Code, narrative, and mining section content

The code section SHALL state how many tracked subnets pushed in the window,
list material incentive-code changes (verdict `high`) with subnet, one-line
verdict, and commit, state the count of `med` verdicts, and list repository
re-points. The narrative section SHALL list model-identifier adoptions and
cluster events in the window and SHALL exclude dependency-kind terms. The
mining section SHALL state the board head, the ranked and cut counts, and
entries and exits of the top ten since the previous edition, and SHALL state
when the budget band is unset.

#### Scenario: Dependency terms are excluded

- **WHEN** the narrative section is composed
- **THEN** only model-identifier terms and cluster events appear

#### Scenario: Top-ten membership change

- **WHEN** a subnet entered or left the mining board's top ten since the
  previous edition
- **THEN** the mining section names it and the direction

### Requirement: Atlas section content

The atlas section SHALL state provider health over the window (failures and
drift events by provider), the rank cross-check status (the above-bar count
distribution over the window), TaoStats quota used against its ceiling, the
last knowledge ingest date, and any class whose watermark has not advanced
inside its expected interval.

#### Scenario: Cross-check distribution is visible

- **WHEN** the atlas section renders
- **THEN** it states how many polls in the window observed each above-bar
  count

### Requirement: Scheduled editions with durable watermarks

A daily edition SHALL be sent once per calendar day at or after a configured
hour, and a weekly edition once per week on a configured weekday, each
gated by a durable per-edition watermark in the notifier ledger so a restart
or a repeated scan cannot send an edition twice. If the scan at the
configured hour fails, the next scan that day SHALL send it. The weekly
edition SHALL use a seven-day window and SHALL replace, not accompany, the
daily edition on its day. A disabled briefing SHALL send nothing and SHALL
leave the other classes unchanged.

#### Scenario: One daily edition

- **WHEN** several scans run after the configured hour on one day
- **THEN** exactly one daily edition is delivered and the watermark records
  it

#### Scenario: Missed hour is caught up

- **WHEN** the scan at the configured hour does not complete
- **THEN** the next completed scan that day delivers the edition

#### Scenario: Weekly replaces daily

- **WHEN** the configured weekday's edition is due
- **THEN** one weekly edition is sent and no daily edition is sent that day

### Requirement: Bounded size and priority truncation

An edition SHALL fit within a configured number of Telegram messages. When
the composed content exceeds the bound, lines SHALL be dropped from the
lowest-priority section upward, whole lines only, and the edition SHALL
state how many lines were omitted. The network section SHALL never be
truncated. The last line of the final message SHALL be the next action when
one exists, otherwise the board link.

#### Scenario: Overflow drops whole low-priority lines

- **WHEN** the composed edition exceeds the message bound
- **THEN** whole lines are removed starting from the lowest-priority section,
  the network section is intact, and the omission count is stated

#### Scenario: Closing line

- **WHEN** an edition is rendered
- **THEN** its final line is the next action if one exists, otherwise the
  LAN board link
