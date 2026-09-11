## Purpose

Composes the public shinogi.dev edition from facts already recorded in the
Atlas stores and publishes it into the shinogi checkout, so that a page
readable by anyone carries only recorded, dated, operator-free figures and
names every input it does not have.

## ADDED Requirements

### Requirement: Composition is a read-only pass over recorded facts

Composing an edition SHALL make no chain call, no provider call, and no
model call. Every store the composer reads SHALL be opened read-only, and
a store that is absent or unreadable SHALL yield a named gap in the
sections that depend on it rather than an error or an omitted section.

Each figure on the page SHALL trace to a stored row and SHALL carry that
row's reference block or observation date. The composer SHALL NOT
estimate, interpolate, or carry a prior value forward as current.

#### Scenario: No store is opened for writing

- **WHEN** an edition is composed
- **THEN** every Atlas store is opened read-only and no row in any of
  them is inserted, updated, or deleted

#### Scenario: Absent store degrades to a gap

- **WHEN** a store the composer reads does not exist
- **THEN** compose returns an edition, the sections that depend on that
  store name the missing input, and the pass reports success

#### Scenario: No outbound call

- **WHEN** an edition is composed
- **THEN** no chain, provider, or model request is issued

### Requirement: The edition satisfies the frozen page contract

The composer SHALL emit a single self-contained HTML document that
satisfies the accepted `public-pulse` contract of the shinogi repository:
the `SHINOGI` wordmark, an as-of element, and the five section landmarks
`network`, `movers`, `mining`, `attention`, `code-narrative` in that
order, with `Code` and `Narrative` subheadings inside the last one.

Every figure the edition reports SHALL be present in the delivered
document. The composer SHALL NOT emit anything that fetches, requests or
derives a reported figure in the browser, and SHALL NOT emit an external
asset other than a typeface source. Every section landmark SHALL be
present on every edition, including an edition whose every input is
missing, and SHALL remain legible with scripting disabled.

#### Scenario: Landmark order holds on a full edition

- **WHEN** an edition composes with facts in every section
- **THEN** the five landmarks are present in the contract order

#### Scenario: Landmark order holds on an empty edition

- **WHEN** an edition composes with no facts at all
- **THEN** the five landmarks are still present in the contract order
  and each body names its missing input

#### Scenario: No data is fetched in the browser

- **WHEN** the composed document is inspected
- **THEN** it carries no data-fetch call and no external asset other
  than a typeface source

#### Scenario: Legible with scripting off

- **WHEN** every script element is removed from the composed document
- **THEN** the five landmarks, the wordmark and the as-of line are all
  still present

### Requirement: The as-of line states compose time and the recorded block

When an edition is published, the as-of line SHALL state the compose time
in UTC and the newest chain block recorded in the panel snapshot. When no
panel snapshot block is recorded, the as-of line SHALL name that gap and
SHALL NOT show a block number.

#### Scenario: Block is recorded

- **WHEN** a panel snapshot block exists at compose time
- **THEN** the as-of line states the UTC compose time and that block
  number

#### Scenario: Block is missing

- **WHEN** no panel snapshot block is recorded
- **THEN** the as-of line states the UTC compose time, names the missing
  block, and shows no number in its place

### Requirement: Stale bounds are per input

Each input SHALL be judged against its own stale bound, not a single
page-wide window.

The emission-gate bar SHALL use the briefing stale bound of twenty-six
hours and SHALL be named stale, without its figure presented as current,
when its newest observation is older than that. Network vitals SHALL be
shown with their observation date and SHALL NOT be named stale for age
alone. Panel movers SHALL use the window since the previous shinogi
publish, or the six hours before compose when no previous publish exists.

#### Scenario: Bar past its bound

- **WHEN** the newest gate observation is older than twenty-six hours
- **THEN** the network section names the bar stale with its observation
  time and does not present theta, rank, or the above-bar count as
  current

#### Scenario: Vitals older than six hours

- **WHEN** the newest network vitals row is more than six hours old
- **THEN** the network section shows its figures with the observation
  date and does not name them stale

#### Scenario: Mover window follows the previous publish

- **WHEN** a previous shinogi publish exists
- **THEN** movers are ranked over the window since that publish, not
  over a fixed six hours

### Requirement: Deltas compare against the previous shinogi publish

The composer SHALL persist the edition's figure set on a successful
publish and SHALL compare each figure that has a prior value against the
figure set of the previous shinogi publish. Deltas SHALL NOT be derived
from the Telegram briefing watermark or its figure set.

A change that rounds to zero SHALL be suppressed rather than shown, and a
figure that did not move SHALL simply carry no delta.

When no previous shinogi publish exists, the edition SHALL state that it
is the first edition and SHALL show no figure deltas.

#### Scenario: First edition

- **WHEN** no previous shinogi figure set is stored
- **THEN** the page states that it is the first edition and shows
  current values with no deltas

#### Scenario: Later edition

- **WHEN** a previous shinogi figure set is stored
- **THEN** each figure with a prior value shows its change against that
  set

#### Scenario: A delta that rounds to zero is not shown

- **WHEN** a figure is unchanged from the previous publish
- **THEN** no delta is rendered beside it

#### Scenario: Telegram state is not read for deltas

- **WHEN** deltas are computed
- **THEN** the notifier ledger and its briefing figure keys are not read

#### Scenario: Figures persist only on publish

- **WHEN** an edition composes but is not published
- **THEN** the stored figure set is unchanged, so the next edition still
  compares against the last published one

### Requirement: Operator-only material is excluded

The published document SHALL NOT contain wallet addresses, keys or seed
material, Telegram identifiers, LAN or device addresses, provider quota
figures, exploit paths, the mining budget band, rent, hardware rung, or
any Atlas health, watermark, or next-action line.

The attention rows SHALL state netuid, recorded name, and a short public
reason only. They SHALL NOT state the numeric attention score, a
direction cue, or a board thesis sentence.

#### Scenario: Banned strings absent

- **WHEN** the composed document is inspected
- **THEN** it contains none of the operator-only material listed above

#### Scenario: Attention row shape

- **WHEN** an attention row renders
- **THEN** it carries a netuid, a recorded name or a named name gap, and
  one short public reason, and carries no score, cue, or thesis

#### Scenario: Publish refuses a leaking document

- **WHEN** a composed document contains a banned operator string
- **THEN** the pass fails closed, nothing is written to the shinogi
  checkout, and the failure is reported

### Requirement: Attention rows are ranked, capped, and named

The attention section SHALL list at most ten subnets ordered by the fleet
attention score descending, and SHALL omit any subnet whose attention
signal is unpaired emission opacity.

Each row's reason SHALL be derived from the recorded attention signal's
own components, not from its category alone. The dominant category is
near-constant across the fleet, so a fixed phrase per category renders a
list of identical lines that tells a reader nothing. A derived reason
SHALL state direction in words and SHALL NOT state the numeric score,
a direction-cue glyph, or a board thesis sentence. An unrecognised
category SHALL render as a named gap, never as a raw token.

Rows that share a reason SHALL be grouped, and each group SHALL state its
reason once with its membership count, so that repetition is stated
rather than repeated and an exception is visible.

A row whose recorded on-chain name is absent SHALL name that gap and
SHALL NOT invent a name. When no row remains after the cap and the
opacity filter, the section SHALL name that gap.

#### Scenario: One category, two directions

- **WHEN** two subnets share the dominant attention category but differ
  in the direction of that signal
- **THEN** their reasons read differently

#### Scenario: Rows sharing a reason are grouped

- **WHEN** several rows carry the same reason
- **THEN** they render as one group stating that reason once with its
  count

#### Scenario: No reason carries a score or a glyph

- **WHEN** any reason is rendered
- **THEN** it contains no numeric score and no direction-cue glyph

#### Scenario: Cap and order

- **WHEN** more than ten scored subnets qualify
- **THEN** the ten highest-scoring qualifying subnets render, in
  descending score order

#### Scenario: Unpaired opacity omitted

- **WHEN** a scored subnet's attention signal is unpaired emission
  opacity
- **THEN** it does not appear in the attention section

#### Scenario: Missing name

- **WHEN** a qualifying subnet has no recorded on-chain name
- **THEN** its row names the missing name and shows no substitute

#### Scenario: No rows remain

- **WHEN** no subnet qualifies
- **THEN** the section names the gap and lists no rows

### Requirement: Charts are drawn from recorded series

Where a recorded series exists, the edition MAY render it as a chart. A
chart SHALL be drawn from stored rows only, SHALL be delivered inside the
document, and SHALL carry no external asset and no browser-side call.

A series with too few points to mean anything SHALL render no chart
rather than a misleading one. A series that is not recorded SHALL yield
no chart, and its section SHALL still state its facts and its gaps.

A chart SHALL NOT introduce a figure the page does not otherwise report,
and SHALL NOT estimate, interpolate or smooth a value it was not given.

#### Scenario: A chart is inline and self-contained

- **WHEN** a chart is rendered
- **THEN** it is present in the delivered document and requests nothing

#### Scenario: Too few points

- **WHEN** a series holds fewer than two recorded points
- **THEN** no chart is rendered for it

#### Scenario: Absent series

- **WHEN** the store behind a chart is absent
- **THEN** the chart is omitted and the section still names its facts
  and gaps

### Requirement: The seven-day push count is the stored fact

The code group SHALL report how many tracked subnets pushed in the last
seven days from the stored seven-day activity fact. It SHALL NOT compute
that count over the publish window.

#### Scenario: Seven-day fact used

- **WHEN** the code group composes
- **THEN** the push count is read from the stored seven-day activity
  measure and is not recomputed over the six-hour or since-last-publish
  window

### Requirement: Publishing is gated on the facts and one-directional

The publish step SHALL compare the composed document against the
committed document by a content hash taken with the as-of line excluded,
and SHALL commit and push only when that hash differs. The as-of line
carries the compose time, which moves on every pass; including it would
make the gate hold never and commit a new timestamp over unchanged facts
at every cadence interval.

When the hash is unchanged, the pass SHALL make no commit and no push,
SHALL leave the published document in place with the compose time of the
edition that is published, and SHALL report that the edition was
unchanged.

Before writing, the pass SHALL bring the checkout up to date with its
remote by fast-forward only. The shinogi repository holds its own page
contract and test, so a commit made there directly would otherwise leave
the checkout behind and every later push rejected, which an unattended
pass cannot resolve. A checkout that has diverged SHALL fail closed
rather than be merged.

Commits SHALL be authored as the personal identity and SHALL carry no
attribution trailer. Atlas SHALL NOT read the shinogi repository for any
input to an edition; bringing the checkout up to date is repository
state, not an edition input.

#### Scenario: Checkout behind its remote

- **WHEN** the checkout is behind the remote and can fast-forward
- **THEN** it is fast-forwarded and the edition publishes on top

#### Scenario: Checkout diverged from its remote

- **WHEN** the checkout holds commits the remote does not, and is also
  behind it
- **THEN** the pass fails closed naming the divergence and writes nothing

#### Scenario: Facts unchanged and the clock has moved

- **WHEN** a later pass composes the same facts at a later compose time
- **THEN** no commit and no push occur, the pass reports no change, and
  the published page keeps the earlier as-of time

#### Scenario: A fact moved

- **WHEN** any fact on the page differs from the committed document
- **THEN** the document is written, committed under the personal
  identity with no attribution trailer, and pushed

#### Scenario: Publish stays one-directional

- **WHEN** an edition is composed
- **THEN** no file in the shinogi checkout other than the published
  document is read as an input to that edition

### Requirement: Publishing is separately disableable and fails closed

Composition and publication SHALL each be independently disableable by
configuration. When publication is disabled, the composer SHALL still
produce the document and report where it would have been written.

When the shinogi checkout is missing, is not a repository, or has no
usable push credential, the pass SHALL fail closed with a named reason,
SHALL leave the checkout unchanged, and SHALL NOT create or move any
credential.

#### Scenario: Publication disabled

- **WHEN** publication is disabled in configuration
- **THEN** the edition composes, nothing is written to the checkout, and
  the pass reports the intended destination

#### Scenario: Checkout missing

- **WHEN** the configured shinogi checkout does not exist
- **THEN** the pass fails closed naming that reason and writes nothing

#### Scenario: Remote unreachable

- **WHEN** the remote cannot be reached
- **THEN** the pass fails closed before writing anything, and the
  checkout is untouched

#### Scenario: Push refused

- **WHEN** the remote is reachable but refuses the write
- **THEN** the pass fails closed naming that reason, the local commit
  is left recoverable, nothing is reset, and no credential is created
  or moved

#### Scenario: Git can never wait on a prompt

- **WHEN** any git command the pass runs would ask for a credential
- **THEN** it fails immediately instead of blocking
