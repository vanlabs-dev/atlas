## ADDED Requirements

### Requirement: The edition is a set of schema-valid data files

The composer SHALL emit each edition as exactly six data files:
`edition.json`, `network.json`, `movers.json`, `mining.json`,
`attention.json` and `code.json`. Each file SHALL validate against the
subnt data schema, major version 1, and SHALL declare `schema` as
`subnt/1.0`.

The five section files SHALL carry the sections `network`, `movers`,
`mining`, `attention` and `code-narrative` respectively, with `Code` and
`Narrative` blocks inside the last one. Every section file SHALL be
written on every edition, including an edition whose every input is
missing; a section with no recorded facts SHALL carry a lead and gaps
that name the missing input.

Every section file SHALL carry the same `composed_at` and `block` as
`edition.json`. Every section and every block SHALL be `public`; this
change emits no subscriber block.

Each fact SHALL carry its display text as composed by Atlas, and its
numeric value where one is recorded. A fact's `ref_block` or `observed`
value SHALL come from that fact's own stored row, never from the edition
block.

No text value SHALL contain an em dash.

#### Scenario: Full edition validates

- **WHEN** an edition composes with facts in every section
- **THEN** six files are produced, each validates against the schema,
  and the section files appear in the contract order

#### Scenario: Empty edition validates

- **WHEN** an edition composes with every store absent
- **THEN** six files are still produced, each validates against the
  schema, and each section's lead or gaps name its missing input

#### Scenario: One edition across the files

- **WHEN** the six files of one edition are inspected
- **THEN** every section file carries the `composed_at` and `block` of
  `edition.json`

#### Scenario: A file that fails the schema is not written

- **WHEN** a composed file does not validate against the schema
- **THEN** the pass fails closed naming the file and the failing path,
  and nothing is written to the subnt checkout

#### Scenario: The schema cannot be loaded

- **WHEN** the schema file or the validator is unavailable
- **THEN** the pass fails closed naming that reason and writes nothing

### Requirement: The Atlas schema copy matches the subnt schema

Atlas SHALL hold its own copy of the subnt data schema and SHALL validate
against that copy. A test SHALL fail when the Atlas copy differs from the
schema in a subnt checkout that is present, and SHALL be skipped when no
subnt checkout is present.

#### Scenario: Copies agree

- **WHEN** a subnt checkout is present and its schema file matches the
  Atlas copy byte for byte
- **THEN** the drift test passes

#### Scenario: Copies drift

- **WHEN** the subnt schema file differs from the Atlas copy
- **THEN** the drift test fails naming both paths

### Requirement: The publish job produces no HTML

The publish job SHALL NOT compose, render, scan or write an HTML
document. It SHALL NOT write, modify or delete `index.html` or any other
file in the subnt checkout outside the data directory.

#### Scenario: Publish writes data files only

- **WHEN** a pass publishes an edition
- **THEN** the commit it makes touches only the six data files

#### Scenario: Stale page left alone

- **WHEN** the subnt checkout holds a root `index.html`
- **THEN** the pass neither reads nor changes it

## MODIFIED Requirements

### Requirement: The as-of line states compose time and the recorded block

When an edition is published, `edition.json` SHALL state the compose time
in UTC, to the second, as `composed_at`, and the newest chain block
recorded in the panel snapshot as `block`. When no panel snapshot block is
recorded, `block` SHALL be null and SHALL NOT carry a substitute number.

#### Scenario: Block is recorded

- **WHEN** a panel snapshot block exists at compose time
- **THEN** `edition.json` states the UTC compose time and that block
  number

#### Scenario: Block is missing

- **WHEN** no panel snapshot block is recorded
- **THEN** `edition.json` states the UTC compose time and `block` is
  null in every file of the edition

### Requirement: Deltas compare against the previous subnt publish

The composer SHALL persist the edition's figure set on a successful
publish and SHALL compare each figure that has a prior value against the
figure set of the previous subnt publish. Deltas SHALL NOT be derived
from the Telegram briefing watermark or its figure set.

A change that rounds to zero SHALL be suppressed rather than shown, and a
figure that did not move SHALL carry a null delta. A delta SHALL state its
direction as `up`, `down` or `flat` alongside its text.

When no previous subnt publish exists, `edition.json` SHALL set
`first_edition` true and `previous_composed_at` null, and no fact SHALL
carry a delta. Otherwise `first_edition` SHALL be false and
`previous_composed_at` SHALL state the compose time of the previous
publish.

#### Scenario: First edition

- **WHEN** no previous subnt figure set is stored
- **THEN** `first_edition` is true, `previous_composed_at` is null, and
  no fact carries a delta

#### Scenario: Later edition

- **WHEN** a previous subnt figure set is stored
- **THEN** each figure with a prior value carries its change against
  that set, and `previous_composed_at` states that publish's time

#### Scenario: A delta that rounds to zero is not shown

- **WHEN** a figure is unchanged from the previous publish
- **THEN** its delta is null

#### Scenario: Telegram state is not read for deltas

- **WHEN** deltas are computed
- **THEN** the notifier ledger and its briefing figure keys are not read

#### Scenario: Figures persist only on publish

- **WHEN** an edition composes but is not published
- **THEN** the stored figure set is unchanged, so the next edition still
  compares against the last published one

### Requirement: Operator-only material is excluded

The published data files SHALL NOT contain wallet addresses, keys or seed
material, Telegram identifiers, LAN or device addresses, provider quota
figures, exploit paths, the mining budget band, rent, hardware rung, or
any Atlas health, watermark, or next-action line.

The scan SHALL run on the exact serialised text of every file before any
write, and SHALL reject at least every token and pattern the subnt build
rejects: the v1 operator strings, SS58 addresses, private IPv4 addresses,
private key blocks, 32-byte hex secrets, Telegram bot tokens, and a line
opening with `next: `. It SHALL also reject an em dash.

The attention rows SHALL state netuid, recorded name, and a short public
reason only. They SHALL NOT state the numeric attention score, a
direction cue, or a board thesis sentence.

#### Scenario: Banned strings absent

- **WHEN** the composed files are inspected
- **THEN** they contain none of the operator-only material listed above

#### Scenario: Scan covers the subnt build list

- **WHEN** each token and pattern the subnt build bans is placed in a
  composed file
- **THEN** the Atlas scan reports it

#### Scenario: Attention row shape

- **WHEN** an attention row is composed
- **THEN** it carries a netuid, a recorded name or a null name with the
  gap named, and one short public reason, and carries no score, cue, or
  thesis

#### Scenario: Publish refuses a leaking document

- **WHEN** any composed file contains a banned operator string
- **THEN** the pass fails closed, nothing is written to the subnt
  checkout, and the failure names the file

### Requirement: Charts are drawn from recorded series

Where a recorded series exists, the edition MAY carry it as a `series`
in the data files. A series SHALL be taken from stored rows only, and its
caption SHALL state the figures it shows.

A series with fewer than two recorded points SHALL NOT be emitted. A
series that is not recorded SHALL yield no series, and its section SHALL
still state its facts and its gaps.

A series SHALL NOT introduce a figure the section does not otherwise
report, and SHALL NOT estimate, interpolate or smooth a value it was not
given.

#### Scenario: A chart is inline and self-contained

- **WHEN** a recorded series has two or more points
- **THEN** it appears in its section's file with its points and caption

#### Scenario: Too few points

- **WHEN** a series holds fewer than two recorded points
- **THEN** no series is emitted for it

#### Scenario: Absent series

- **WHEN** the store behind a series is absent
- **THEN** the series is omitted and the section still names its facts
  and gaps

### Requirement: Publishing is gated on the facts and one-directional

The publish step SHALL compare the composed files against the committed
files by a content digest taken with `composed_at`, `block` and
`previous_composed_at` excluded, and SHALL commit and push only when that
digest differs. Those fields move on every pass or every publish;
including them would make the gate hold never and commit new timestamps
over unchanged facts at every cadence interval.

When the digest is unchanged, the pass SHALL make no commit and no push,
SHALL leave the published files in place with the compose time of the
edition that is published, and SHALL report that the edition was
unchanged. A committed data file that is missing SHALL count as a change.

Before writing, the pass SHALL bring the checkout up to date with its
remote by fast-forward only. A checkout that has diverged SHALL fail
closed rather than be merged.

Commits SHALL be authored as the personal identity and SHALL carry no
attribution trailer. Atlas SHALL NOT read the subnt repository for any
input to an edition; bringing the checkout up to date and reading the
committed data files for the digest are repository state, not edition
inputs.

#### Scenario: Checkout behind its remote

- **WHEN** the checkout is behind the remote and can fast-forward
- **THEN** it is fast-forwarded and the edition publishes on top

#### Scenario: Checkout diverged from its remote

- **WHEN** the checkout holds commits the remote does not, and is also
  behind it
- **THEN** the pass fails closed naming the divergence and writes nothing

#### Scenario: Facts unchanged and the clock has moved

- **WHEN** a later pass composes the same facts at a later compose time
  and a later panel block
- **THEN** no commit and no push occur, the pass reports no change, and
  the published files keep the earlier `composed_at`

#### Scenario: A fact moved

- **WHEN** any fact in any data file differs from the committed files
- **THEN** all six files are written, committed under the personal
  identity with no attribution trailer, and pushed

#### Scenario: Committed data missing

- **WHEN** the checkout holds no committed data files
- **THEN** the edition is written, committed and pushed

#### Scenario: Publish stays one-directional

- **WHEN** an edition is composed
- **THEN** no file in the subnt checkout is read as an input to that
  edition

### Requirement: Publishing is separately disableable and fails closed

Composition and publication SHALL each be independently disableable by
configuration. When publication is disabled, the composer SHALL still
produce the data files, scan and validate them, and report the data
directory they would have been written to.

When the subnt checkout is missing, is not a repository, or has no
usable push credential, the pass SHALL fail closed with a named reason,
SHALL leave the checkout unchanged, and SHALL NOT create or move any
credential.

#### Scenario: Publication disabled

- **WHEN** publication is disabled in configuration
- **THEN** the edition composes, nothing is written to the checkout, and
  the pass reports the intended data directory

#### Scenario: Checkout missing

- **WHEN** the configured subnt checkout does not exist
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

## REMOVED Requirements

### Requirement: The edition satisfies the frozen page contract

**Reason**: subnt.dev builds its v2 page from `data/*.json`. Layout,
landmarks, scripting-off legibility and browser-fetch rules now belong to
the subnt repo's `public-pulse` contract and its build checks.

**Migration**: The data-file contract replaces it. See "The edition is a
set of schema-valid data files" and "The publish job produces no HTML".
