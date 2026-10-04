# Spec Delta

## ADDED Requirements

### Requirement: Every Telegram message uses the house layout

Every message Atlas sends to Telegram (notifier classes, pulse briefing,
probe watch, runtime upgrade reports, CLI test alert) SHALL render in one
layout: a severity marker, a headline stating the effect, one meaning
sentence, labelled key figures, provenance in an expandable details fold,
and a final `Next:` line only when an action exists. The layout SHALL NOT
change which events page or when.

#### Scenario: Alert reads top-down

- **WHEN** a gate-crossing alert is rendered
- **THEN** line one is the severity marker and a headline naming the subnet,
  its recorded name, and the crossing direction; the next line explains the
  effect in one sentence; key figures follow as labelled lines; block,
  source, and timestamp sit in the details fold

#### Scenario: No action, no next line

- **WHEN** a message has no follow-up action
- **THEN** it ends on its last fact or its details fold, with no `Next:`
  line

#### Scenario: Probe and upgrade reports share the renderer

- **WHEN** the probe watch or the runtime upgrade job sends a report
- **THEN** it is rendered as Telegram HTML in the house layout and falls
  back to plain text on an HTTP 400

### Requirement: Severity marker by event outcome

The first character of every message SHALL be one severity marker chosen
from a fixed set: 🔴 act now, 🟠 watch, 🟢 good news, 🔵 for information,
✅ done or recovered. The marker SHALL be chosen deterministically from the
event's class and recorded fields. It SHALL NOT change delivery behaviour.

#### Scenario: Crossing direction sets the marker

- **WHEN** a subnet with emission enabled rises above the bar
- **THEN** the message starts with 🟢, and a fall below the bar starts
  with 🔴

#### Scenario: Emission-off crossing is informational

- **WHEN** a crossing is recorded for a subnet with emission disabled
- **THEN** the message starts with 🔵 and states that the subnet earns zero
  either way

### Requirement: Subnets are named in every message

Every message that refers to a subnet SHALL name it with the most recent
recorded panel-snapshot name, as `Subnet N (Name)` in alerts and
`Name (N)` in briefing lists. When no name is recorded, the message SHALL
show the subnet number alone. Names are recorded data and SHALL be escaped
and never glossed.

#### Scenario: Name is shown when recorded

- **WHEN** an alert concerns subnet 49 and the latest snapshot names it
  `Nepher Robotics`
- **THEN** the headline reads `Subnet 49 (Nepher Robotics)`

#### Scenario: Missing name degrades to the number

- **WHEN** no snapshot records a name for the subnet
- **THEN** the message shows `Subnet N` with no empty parentheses

### Requirement: Times and numbers are formatted for reading

Timestamps SHALL render as Telegram `tg-time` entities so the reader sees
local time, with a UTC text fallback in the entity and in plain text. Raw
ISO timestamps SHALL NOT appear outside the details fold. Integers SHALL
use thousands separators. The emission-gate bar SHALL be shown as a
percentage everywhere. Alpha prices SHALL show three significant figures.

#### Scenario: Timestamp renders as local time

- **WHEN** an event observed at `2026-10-02T19:02:20.932792+00:00` renders
- **THEN** the HTML body carries a `tg-time` entity for that instant with a
  `Fri 2 Oct, 19:02 UTC` fallback, and no microsecond timestamp appears in
  the body

#### Scenario: Bar is a percentage in both paths

- **WHEN** the bar value 0.008581 appears in an alert or a briefing
- **THEN** it renders as `0.858%`

### Requirement: Links ride inline keyboard buttons

When a message refers to an external page Atlas can address from recorded
data (a GitHub compare or commit page, a taostats subnet page), the link
SHALL be sent as an inline keyboard URL button, not pasted into the body.
Messages SHALL NOT carry a button to the LAN board. A failed button URL
SHALL NOT block delivery.

#### Scenario: Repository alert links the diff

- **WHEN** a significant repository range from `prev` to `new` is delivered
- **THEN** the message carries one button opening the GitHub compare page
  for `prev...new` on the tracked repository

#### Scenario: No board button

- **WHEN** any message is sent
- **THEN** none of its buttons opens the LAN board

## MODIFIED Requirements

### Requirement: Notifications render with safe Telegram HTML

Outbound notifications SHALL be sent with Telegram HTML parse mode. All
dynamic values (SHAs, paths, commit subjects, provider text, subnet names)
SHALL be HTML-escaped after scrubbing and before send. The renderer SHALL only
emit tags supported by the Telegram Bot API (`b`, `i`, `code`, `pre`,
`blockquote expandable`, `tg-time`) and SHALL produce a body already within the
configured message size limit with balanced tags; rendered HTML SHALL NOT be
truncated after rendering. Link previews SHALL be disabled through
`link_preview_options`; the removed `disable_web_page_preview` field SHALL
NOT be sent. Message bodies SHALL follow the
house layout defined in this capability. Message bodies SHALL NOT contain em
or en dashes (the renderer
normalizes any imported from stored data). On an HTTP 400 (rejected formatting), the notifier
SHALL retry once as plain text (the untagged structured text, never the raw
HTML source, with the same link buttons) so a rendering fault never
suppresses an alert, and SHALL record the fallback.

#### Scenario: Dynamic values are escaped

- **WHEN** a message containing user- or repo-derived text is rendered as HTML
- **THEN** every `&`, `<`, and `>` in dynamic values is escaped and the message
  is accepted by Telegram

#### Scenario: Formatting rejection falls back to plain text

- **WHEN** a send with HTML parse mode returns HTTP 400
- **THEN** the notifier retries the same event once as plain text and records the
  fallback, and the delivery is not lost to the formatting error

#### Scenario: Link previews are disabled with the current field

- **WHEN** any message is sent
- **THEN** the request carries `link_preview_options` with previews disabled
  and does not carry `disable_web_page_preview`

### Requirement: Alert headlines and glosses are rendered from recorded fields only

Every alert class SHALL render the house layout: a plain-language
headline stating what happened, jargon glossed in parentheses at first use
per the approved lexicon, and the class's sourced facts. A gloss SHALL be
attached only inside a composed body sentence. It SHALL NOT be inserted into
the headline, a key-figure label, or recorded text (commit subjects, pallet
labels, verdict text, file paths, subnet names). When a concrete follow-up action
exists, a final next-action line SHALL state it; alerts with no warranted
action SHALL omit the line rather than emit boilerplate. Headlines,
glosses, and next-action lines SHALL be deterministic templates
interpolating only values already recorded in the source stores; renderers
SHALL NOT fetch, compute, or infer new facts. Because renderers never
validate at render time, the approved uncertainty vocabulary is realized in
alerts through per-figure source labels (provider, chain RPC, block, or
commit), which MAY sit in the details fold, plus explicit `dated` / `n/a`
markers on stale or absent elements; per-figure `confirmed` tags SHALL NOT be
added.

#### Scenario: Headline uses only recorded fields

- **WHEN** a gate-crossing alert is rendered for a subnet whose recorded
  demand share crossed the recorded bar
- **THEN** the headline states the subnet, its recorded name, and the
  direction using only recorded fields, and each figure keeps its source
  label in the message

#### Scenario: Cooldown suppresses delivery, never records loss

- **WHEN** a crossing event is recorded but suppressed by the per-netuid
  cooldown
- **THEN** no message is sent for that event, it is recorded in the ledger
  as `suppressed` exactly as today, and the next delivered page for that
  netuid renders under the same verdict-led layout

#### Scenario: Source labels carry the confirmation story

- **WHEN** a figure renders in a fact line
- **THEN** it keeps its recorded source label (provider, chain RPC, block,
  or commit) in the body or the details fold; elements known to be stale or
  absent are marked `dated` with their timestamp or `n/a`, and no guessed
  value is presented

#### Scenario: Layout holds within the size budget

- **WHEN** any class renders a worst-case recorded fixture
- **THEN** the verdict-led body stays within the configured message size
  limit with balanced tags and no post-render truncation

#### Scenario: Recorded text is never glossed

- **WHEN** a commit subject, pallet label, or verdict contains a glossed
  term such as `basket` or `dTAO`
- **THEN** that text renders exactly as recorded, with no gloss inserted

#### Scenario: Headlines carry no gloss

- **WHEN** a headline contains a glossed term such as `runtime spec`
- **THEN** the headline renders without the gloss, and the gloss attaches
  at the first body sentence that uses the term, if any

### Requirement: Repository and live-chain state are explicitly distinguished

Every repository alert SHALL mark itself as a source-code (repository) event,
distinct from the live chain, and SHALL state both the tracked-repository
`spec_version` and the current live `spec_version` in a plain sentence that
says whether the code is live, not yet live, or behind the live chain. The live
`spec_version` SHALL be read read-only from the live-data store. A repository
alert SHALL NOT imply that the live chain changed.

#### Scenario: Repo alert states both clocks

- **WHEN** a repository alert is delivered and a live `spec_version` is available
- **THEN** the message shows the repository `spec_version` and the live
  `spec_version`, says in words whether the code is live yet, and is
  labelled a repository (source-code) event

#### Scenario: Live spec unavailable degrades honestly

- **WHEN** the live `spec_version` cannot be read
- **THEN** the repository alert is still delivered, marked as a repository event,
  and states that the live comparison is unavailable rather than omitting the
  distinction

### Requirement: Significant repository alerts carry a concise breakdown

A significant repository alert SHALL include an interpreted breakdown built
only from fields already recorded by the repository tracker (never re-fetched),
rendered as structured single-fact lines rather than a prose paragraph, passing
outbound redaction before rendering, and staying within the configured message
size budget. The breakdown SHALL contain:

- A **verdict line** stating in plain language what the range is, derived
  deterministically from recorded data by a fixed, ordered decision: an
  incomplete or non-fast-forward range is called out as low-confidence first; a
  `spec_version` change leads as a runtime spec bump; an unknown-class directory
  is surfaced as a new/unmapped area; otherwise the core-protocol share of line
  churn decides between a light protocol touch amid a large sync and a core
  protocol change, followed by node/network and a neutral fallback. The
  light-protocol-touch verdict SHALL be emitted only when core-protocol line
  churn is greater than zero, so the verdict never claims a protocol touch that
  did not occur. The share SHALL be computed from line churn (additions plus
  deletions), not file count.
- A **signal-versus-noise area split**: a line for core-protocol directories
  showing, per area, the changed-file count and the summed line churn
  (`+additions / −deletions`) computed from the recorded per-file additions and
  deletions; and a separate line for housekeeping directories showing counts
  only. The split SHALL use the configured area map, which classifies each
  top-level directory as core-protocol, node/network, housekeeping, or
  **unknown**. Housekeeping SHALL be allowlist-only: a top-level directory not
  present in the map SHALL be treated as unknown, not housekeeping, and SHALL be
  surfaced on its own line rather than hidden — mirroring the classifier's
  escalation of never-seen directories. Repo-root files (paths with no
  directory separator) SHALL be grouped under a synthetic housekeeping area so a
  large generated root file cannot present as a protocol area. When the recorded
  file list is truncated, the counts and churn are a lower bound and SHALL be
  rendered as such (e.g. a `≥` marker).
- A **filtered commit list** ranked by commit subject alone (the tracker
  records no commit-to-file mapping, so the list SHALL be presented as the most
  substantive subjects in the range, not as the commits that changed a given
  area). It SHALL exclude merge commits and commits whose subject is prefixed as
  `ci` / `test` / `docs` / `build` / `style`, and `chore` unless the subject
  names a release (`spec_version` / `version` / `release`); and SHALL prioritise
  `feat` / `fix` / `refactor` / `perf` and protocol-keyword subjects. A
  subject that repeats an earlier one in the range SHALL be listed once. The
  list SHALL show at most four subjects in the message body, outside the
  details fold, each with its conventional prefix removed. When no
  such commit exists in the recorded range, the breakdown SHALL state plainly
  that the range contains no feature or fix commits rather than showing
  housekeeping commits.
- When `pallets/` files are present, **pallet-level labels** naming the
  pallets touched and, via the configured pallet map, the domain each governs
  (e.g. staking / emissions, governance params, dTAO economics), read from the
  second path segment of recorded file paths. In the message body the
  domains SHALL be stated as plain area names; the pallet names and per-area
  counts SHALL sit in the details fold.

The breakdown SHALL NOT introduce any new data capture, re-fetch, or network
call, and SHALL degrade honestly (omitting a line rather than guessing) when a
recorded field is absent. Em dashes SHALL NOT appear in rendered output.

#### Scenario: Noise-dominated range is called out, signal is surfaced

- **WHEN** a significant range's changed files are mostly in housekeeping
  directories with only a light core-protocol touch
- **THEN** the verdict line states it is largely housekeeping with a light
  protocol touch, the protocol line shows the core-protocol areas with their
  file counts and line churn, and the housekeeping line lists the noise
  directories separately

#### Scenario: Runtime spec bump leads the verdict

- **WHEN** a range records a `spec_version` change
- **THEN** the verdict line leads with the runtime spec bump and its delta
  against the live chain, rather than presenting the release as generic
  churn

#### Scenario: Commit list filters out merge and housekeeping commits

- **WHEN** the recorded commits are a mix of merge, `ci`, `test`, and
  `feat` / `fix` subjects
- **THEN** the rendered commit list shows the `feat` / `fix` subjects and omits
  the merge and `ci` / `test` subjects; and when no feature or fix commit
  exists, the breakdown states that plainly

#### Scenario: Pallet touch is named and interpreted

- **WHEN** recorded file paths include `pallets/<name>/...` for a mapped pallet
- **THEN** the breakdown names the pallet and the domain it governs from the
  configured pallet map

#### Scenario: Unknown top-level directory is surfaced, not hidden

- **WHEN** a range changes files under a top-level directory absent from the
  configured area map
- **THEN** the directory is shown on its own new/unclassified-area line and the
  verdict marks it as a new or unmapped area, rather than being folded into
  housekeeping

#### Scenario: Truncated or incomplete range is low-confidence

- **WHEN** a delivered range has a truncated file list or a non-fast-forward
  history
- **THEN** the verdict states the range is large or incomplete and the affected
  area counts and churn are marked as lower bounds rather than presented as
  exact

#### Scenario: Breakdown reflects the recorded range

- **WHEN** a significant range is delivered
- **THEN** the message body states the commit count, the core-protocol areas
  with line churn, and the `spec_version` delta drawn from the recorded change
  range

#### Scenario: A repeated commit subject is listed once

- **WHEN** a recorded range contains two commits with the same subject
- **THEN** the commit list shows that subject once

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

The alert SHALL name the subnet number and recorded subnet name of a
netuid-keyed item in its headline, including when only one subnet changed.
The alert body SHALL state the parameter name, the previous and new values,
the provenance of each, the reference block, and a short configured
description of what the parameter governs, as single-fact lines in the
established message style (HTML with plain-text fallback, no em or en
dashes). When no description is configured for the parameter, the alert
SHALL say so and its next-action line SHALL name the configuration key to
add. For a collapsed batch the previous and new values are the shared
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

#### Scenario: A single-subnet change names the subnet

- **WHEN** the scan finds one unseen transition of a netuid-keyed item such
  as `SubnetEmissionEnabled[82]`
- **THEN** the headline names subnet 82 and its recorded name

#### Scenario: An undescribed parameter asks for its description

- **WHEN** a transition is recorded for a parameter with no configured
  description
- **THEN** the alert states that no description exists and its last line
  names the configuration key to add

### Requirement: Fleet signal alerts render in house style with class-specific dedup

Fleet signal alerts SHALL render in the house layout, with `<code>`-wrapped
SHAs, safe Telegram HTML with the established 400-fallback, and scrubbing of
sensitive output. Each subnet SHALL be named with its recorded subnet name.
A digest SHALL put each pending item on its own line, and SHALL merge items
for the same subnet and kind into one line.
Terms, file paths, subnet names, and **verdict text** originate in untrusted
repositories or from a model reading untrusted repositories, and SHALL be
HTML-escaped and length-bounded at render; such text is data and SHALL never be
interpreted as instructions. A cluster alert SHALL name the member subnets,
first mover with date and SHA, window span, and fleet-prevalence snapshot; a
watchlist alert SHALL name the term, subnet, and source file. An **econ-code
alert SHALL lead with the verdict** — a one-line `what_changed` headline and a
`why_it_matters` line, a blank-line separator, then a significance-and-direction
line — and SHALL place the SHA range, commit count, matched files, entry price,
and evidence into an expandable blockquote of labeled single-fact lines
(blank-line-separated groups), so the card is scannable at a glance rather than
a wall of text; the standing repositories-not-chain disclaimer SHALL be omitted
from this class. An econ-code candidate the gate could not judge SHALL render
with an explicit `unjudged` marker. When an entry-price snapshot is available
at render time, an instant alert SHALL carry the alpha price within that
details block; a pending snapshot omits it and SHALL never delay delivery.
Delivery SHALL be recorded in the ledger with class-specific dedup
keys — cluster: term + episode; watchlist: term + netuid + epoch; econ-code:
change-range id — so re-scans and retries never double-send.

#### Scenario: Econ-code alert leads with meaning
- **WHEN** an econ-code alert with a `high` or `med` verdict renders
- **THEN** it leads with the `what_changed` headline and `why_it_matters` line, shows significance and direction, and places SHA range, commit count, files, evidence, and any entry price in an expandable blockquote of labeled lines

#### Scenario: Verdict text is escaped and inert
- **WHEN** a verdict's `what_changed` or `why_it_matters` text contains HTML metacharacters or directive-like phrasing
- **THEN** the text is HTML-escaped and rendered as data, never interpreted as markup or instructions

#### Scenario: Unjudged alert is marked
- **WHEN** an econ-code candidate that could not be judged is delivered
- **THEN** the card carries an explicit `unjudged` marker in place of the verdict lines

#### Scenario: Econ-code alert is deduplicated by range

- **WHEN** a scan retries after a failed send of an econ-code alert for a
  change range
- **THEN** the alert is sent once and a subsequent scan does not re-send it
  for the same range id

#### Scenario: Cluster alert carries required facts

- **WHEN** a narrative-cluster alert renders
- **THEN** it contains the member subnets, the first mover with date and
  `<code>` SHA, the adoption window, and prevalence, as single-fact lines

#### Scenario: Digest items are one per line

- **WHEN** a fleet signal digest carries five pending items, two of them
  cooldown notes for the same subnet
- **THEN** the digest shows four item lines, with the two cooldown notes
  merged into one line for that subnet
