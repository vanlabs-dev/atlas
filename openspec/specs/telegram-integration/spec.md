# telegram-integration Specification

## Purpose
TBD - created by archiving change atlas-phase-5-telegram. Update Purpose after archive.

## Requirements

### Requirement: Inbound gateway uses the supported Hermes mechanism

The inbound Telegram conversation channel SHALL be the native NousResearch
Hermes gateway, configured by the operator per current official Hermes
documentation (ATLAS-TG-001). Atlas contributes no gateway code — only a
setup note and acceptance verification. The bot token SHALL live only in the
Pi's 0600 `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`) or equivalent gateway
config; it MUST NOT appear in the repository, logs, chat output, or any
command line.

#### Scenario: Token is never exposed

- **WHEN** the gateway is running and any output (logs, chat, ledger,
  audit) is produced
- **THEN** the bot token value does not appear in it, and no repository
  file contains the token value

### Requirement: Access restricted to allowlisted identifiers

The Telegram bot SHALL accept commands and return operational data only
from explicitly allowlisted numeric Telegram user identifiers
(`TELEGRAM_ALLOWED_USERS`, and the group-scoped equivalents where groups
are used). Unknown users SHALL receive no operational data (ATLAS-TG-002).
Allowed identifiers are operator-supplied device configuration and MUST NOT
be committed to the repository.

#### Scenario: Approved account can query Hermes

- **WHEN** an allowlisted user sends a message to the bot
- **THEN** Hermes processes it and replies through the gateway

#### Scenario: Unauthorized account is rejected

- **WHEN** a user whose numeric ID is not allowlisted messages the bot
  (including inside an allowed group)
- **THEN** the bot returns no operational data and the attempt is not
  serviced

### Requirement: Commands are explicitly allowlisted and non-destructive

Non-admin Telegram commands SHALL be limited to an explicit allowlist
(`user_allowed_commands`). Destructive system administration over Telegram
SHALL be out of scope for this release; no command SHALL mutate the device,
Hermes memory/skills outside existing approval gates, or any wallet
(ATLAS-TG-006). Atlas holds no wallet secrets and none SHALL be reachable
through Telegram.

#### Scenario: Non-allowlisted command is refused

- **WHEN** a non-admin allowlisted user issues a command not in
  `user_allowed_commands` (and not `/help` or `/whoami`)
- **THEN** the command is not executed

#### Scenario: No destructive administration path exists

- **WHEN** the command surface is reviewed
- **THEN** no Telegram command performs destructive system administration
  or any wallet operation

### Requirement: Supported initial scope

The Telegram scope SHALL include conversation with Hermes and outbound
operational notifications for five event classes: repository update, live-provider
API schema-drift, knowledge-ingestion completion/review-needed, live
chain-runtime-upgrade (ATLAS-TG-003), and emission-gate crossing. Investment and
portfolio alerts SHALL be deferred (PRD Phase 7). Service-failure notifications
are deferred until a Hermes service unit exists; the notifier design SHALL leave
that class addable without rework.

#### Scenario: An enabled class delivers

- **WHEN** a repository update, a schema-drift health event, a
  knowledge-ingestion event, a live chain-runtime-upgrade, or a confirmed
  emission-gate crossing occurs and the class is enabled
- **THEN** a source- and time-labelled notification is delivered once to the
  allowlisted operator

#### Scenario: Deferred classes are absent

- **WHEN** the notifier configuration is reviewed
- **THEN** no investment/portfolio alert class is present, and adding
  service-failure later requires only a new event adapter, not a redesign

### Requirement: Repository alerts are tiered by significance

The notifier SHALL classify each tracked commit range as `significant` or
`churn` before deciding how to notify. Classification SHALL be deny-by-default:
`churn` is an explicit configured allowlist of non-protocol top-level directories
(e.g. `.github/`, `docs/`, `website/`, `vendor/`, `sdk/`), and a range SHALL be
`churn` only when its changed paths are provably a subset of that allowlist and
no runtime `spec_version` change is recorded. Every other range — a
`spec_version` change, a touch of any protocol-facing directory (`pallets/`,
`runtime/`, `precompiles/`, `common/`), a touch of any top-level directory not in
the churn allowlist, or a range whose recorded file list is known-incomplete
(truncated or non-fast-forward) — SHALL be `significant`. Classification SHALL be
derived from recorded facts (changed file paths and the recorded `spec_version`
delta), not re-fetched from the remote.

#### Scenario: Spec bump or protocol change is significant

- **WHEN** a tracked range changes the runtime `spec_version` or touches a
  protocol-facing directory
- **THEN** the range is classified `significant`

#### Scenario: Only-allowlisted churn is churn

- **WHEN** a tracked range touches only churn-allowlisted paths (`.github/`,
  `docs/`, `website/`, `vendor/`, `sdk/`) and records no `spec_version` change
- **THEN** the range is classified `churn`

#### Scenario: Unknown directory or incomplete record escalates

- **WHEN** a tracked range touches a top-level directory not in the churn
  allowlist, or its recorded file list is truncated or from a non-fast-forward
- **THEN** the range is classified `significant` rather than `churn`

### Requirement: Churn is digested, never paged and never dropped

Churn ranges SHALL NOT trigger an immediate notification and SHALL NOT be
silently discarded. Because the repository-update watermark advances past
processed ranges (churn included), a churn range SHALL be written to durable
pending-digest storage in the same operation that advances the watermark past it,
so it cannot be lost between scans. The notifier SHALL coalesce pending churn
into a low-priority digest that is carried by the next significant repository
alert or emitted as a periodic summary, and SHALL clear a range from pending
storage only once it has been included in a delivered digest. The digest SHALL
identify the coalesced ranges (head SHAs and dominant area) so the operator
retains an audit trail of skipped churn.

#### Scenario: Churn does not page immediately

- **WHEN** a churn range is detected and no significant range accompanies it
- **THEN** no immediate alert is sent and the range is durably retained as
  pending digest state before the watermark advances past it

#### Scenario: Churn survives across scans until digested

- **WHEN** the watermark advances past a churn range and later scans run before
  any significant alert
- **THEN** the churn range remains in pending storage and is not lost, and is
  still eligible for the next digest

#### Scenario: Pending churn rides the next significant alert

- **WHEN** a significant range is notified while churn ranges are pending
- **THEN** the significant alert includes a digest line naming the pending churn
  ranges, and the pending state is cleared

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
  `feat` / `fix` / `refactor` / `perf` and protocol-keyword subjects. When no
  such commit exists in the recorded range, the breakdown SHALL state plainly
  that the range contains no feature or fix commits rather than showing
  housekeeping commits.
- When `pallets/` files are present, **pallet-level labels** naming the
  pallets touched and, via the configured pallet map, the domain each governs
  (e.g. staking / emissions, governance params, dTAO economics), read from the
  second path segment of recorded file paths.

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

### Requirement: Repository and live-chain state are explicitly distinguished

Every repository alert SHALL mark itself as a source-code (repository) event,
distinct from the live chain, and SHALL state both the tracked-repository
`spec_version` and the current live `spec_version` with their delta. The live
`spec_version` SHALL be read read-only from the live-data store. A repository
alert SHALL NOT imply that the live chain changed.

#### Scenario: Repo alert states both clocks

- **WHEN** a repository alert is delivered and a live `spec_version` is available
- **THEN** the message shows the repository `spec_version`, the live
  `spec_version`, and their delta, and is labelled a repository (source-code)
  event

#### Scenario: Live spec unavailable degrades honestly

- **WHEN** the live `spec_version` cannot be read
- **THEN** the repository alert is still delivered, marked as a repository event,
  and states that the live comparison is unavailable rather than omitting the
  distinction

### Requirement: Live chain-runtime-upgrade is a distinct high-priority class

The notifier SHALL provide a `chain-runtime-upgrade` class that fires when the
live runtime `spec_version` changes, based on the live-data upgrade record. Its
message SHALL be marked as a live-chain (enacted) event, distinct from repository
alerts, and SHALL state the previous and new live `spec_version` and the
reference block. When the repository store holds a range whose recorded spec
delta matches the upgrade, the message SHALL additionally state that range's
release commit subject and its top touched areas, so the upgrade message
explains the change it announces; when no matching range is recorded, the
message SHALL say the repository evidence is not yet tracked. Crossing a
governance threshold (e.g. conviction ownership at `spec_version` >= 425)
SHALL be surfaced within this class.

#### Scenario: Live spec change fires a chain upgrade alert

- **WHEN** the live-data store records a live `spec_version` change
- **THEN** a `chain-runtime-upgrade` alert is delivered, marked as a live-chain
  event, stating the previous and new live `spec_version` and reference block

#### Scenario: Matching range supplies the release subject

- **WHEN** a repository range with the same spec delta is recorded
- **THEN** the alert states that range's release commit subject and top
  touched areas

#### Scenario: No matching range is stated

- **WHEN** no repository range with that spec delta is recorded
- **THEN** the alert states that repository evidence is not yet tracked

#### Scenario: Governance threshold is surfaced

- **WHEN** a live `spec_version` change crosses a configured governance threshold
- **THEN** the chain-upgrade alert notes the threshold crossing

### Requirement: Notifications render with safe Telegram HTML

Outbound notifications SHALL be sent with Telegram HTML parse mode. All
dynamic values (SHAs, paths, commit subjects, provider text) SHALL be
HTML-escaped after scrubbing and before send. The renderer SHALL only emit tags
supported by the Telegram Bot API and SHALL produce a body already within the
configured message size limit with balanced tags; rendered HTML SHALL NOT be
truncated after rendering. Message bodies SHALL follow the verdict-led class
layout required by the `agent-voice` capability: a plain-language verdict
headline first, then fact sections composed of short single-fact lines, then
a next-action line when follow-up exists. Message bodies SHALL NOT contain em
or en dashes (the renderer
normalizes any imported from stored data). On an HTTP 400 (rejected formatting), the notifier
SHALL retry once as plain text (the untagged structured text, never the raw
HTML source) so a rendering fault never suppresses an alert, and SHALL record
the fallback.

#### Scenario: Dynamic values are escaped

- **WHEN** a message containing user- or repo-derived text is rendered as HTML
- **THEN** every `&`, `<`, and `>` in dynamic values is escaped and the message
  is accepted by Telegram

#### Scenario: Formatting rejection falls back to plain text

- **WHEN** a send with HTML parse mode returns HTTP 400
- **THEN** the notifier retries the same event once as plain text and records the
  fallback, and the delivery is not lost to the formatting error

### Requirement: Sensitive output is scrubbed before send

Every outbound Telegram message SHALL pass a fail-closed scrubber before
transmission. A message SHALL be refused (not truncated-and-sent) if it
would contain an API key, a secret path together with its value, an
environment dump, wallet secrets, or private diagnostics exceeding the
approved exposure policy (ATLAS-TG-004).

#### Scenario: Message with a secret is refused

- **WHEN** an outbound message body matches a secret/over-exposure pattern
- **THEN** the send is refused, the event is recorded as a scrub failure,
  and no secret-bearing message is transmitted

#### Scenario: Clean message passes

- **WHEN** an outbound message contains only source- and time-labelled
  operational data within the exposure policy
- **THEN** the scrubber passes it and it is sent

### Requirement: Delivery is recorded and de-duplicated

The notifier SHALL persist, for every notification event, a 0600 ledger
record containing: event identifier, creation time, attempted delivery
time, delivery status, retry count, and final failure (ATLAS-TG-005). The
system SHALL avoid duplicate alert floods by de-duplicating on event
identity and coalescing repeats within a configured window.

#### Scenario: Ledger captures the delivery lifecycle

- **WHEN** an event is created, attempted, and resolved (delivered or
  finally failed)
- **THEN** its ledger record carries all six fields with consistent
  timestamps and the final status

#### Scenario: Duplicate flood is suppressed

- **WHEN** the same event identity recurs within the coalescing window
- **THEN** it is suppressed or coalesced rather than re-delivered, and the
  suppression is recorded

### Requirement: Telegram failure does not affect core operation

A Telegram outage, invalid token, or send failure SHALL be caught and
recorded, and SHALL NOT disrupt Hermes conversation, the repository update
timer, live-data tools, or any other core function (PRD Phase 5 exit
criterion). Retries SHALL be bounded and observable.

#### Scenario: Delivery failure is isolated

- **WHEN** Telegram is unreachable or rejects a send
- **THEN** the failure is recorded with a final status after bounded
  retries, and core Atlas functions continue unaffected

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

### Requirement: Fleet signal alerts render in house style with class-specific dedup

Fleet signal alerts SHALL render as a short headline plus structured
single-fact lines with `·` separators, `<code>`-wrapped SHAs, safe Telegram
HTML with the established 400-fallback, and scrubbing of sensitive output.
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

### Requirement: Alert headlines and glosses are rendered from recorded fields only

Every alert class SHALL render a verdict-led layout: a plain-language
headline stating what happened and what it means, jargon glossed in
parentheses at first use per the approved lexicon, and the class's existing
sourced fact lines (all class-specific content requirements continue to
govern their fact sections unchanged). When a concrete follow-up action
exists, a final next-action line SHALL state it; alerts with no warranted
action SHALL omit the line rather than emit boilerplate. Headlines,
glosses, and next-action lines SHALL be deterministic templates
interpolating only values already recorded in the source stores; renderers
SHALL NOT fetch, compute, or infer new facts. Because renderers never
validate at render time, the approved uncertainty vocabulary is realized in
alerts through the existing per-figure source labels (provider, chain RPC,
block, or commit) plus explicit `dated` / `n/a` markers on stale or absent
elements; per-figure `confirmed` tags SHALL NOT be added.

#### Scenario: Headline uses only recorded fields

- **WHEN** a gate-crossing alert is rendered for a subnet whose recorded
  demand share crossed the recorded bar
- **THEN** the headline states the subnet, direction, and consequence using
  only the recorded netuid, share, bar, and event fields, with each figure
  in the fact lines still carrying its source label

#### Scenario: Cooldown suppresses delivery, never records loss

- **WHEN** a crossing event is recorded but suppressed by the per-netuid
  cooldown
- **THEN** no message is sent for that event, it is recorded in the ledger
  as `suppressed` exactly as today, and the next delivered page for that
  netuid renders under the same verdict-led layout

#### Scenario: Source labels carry the confirmation story

- **WHEN** a figure renders in a fact line
- **THEN** it keeps its recorded source label (provider, chain RPC, block,
  or commit); elements known to be stale or absent are marked `dated` with
  their timestamp or `n/a`, and no guessed value is presented

#### Scenario: Layout holds within the size budget

- **WHEN** any class renders a worst-case recorded fixture
- **THEN** the verdict-led body stays within the configured message size
  limit with balanced tags and no post-render truncation

### Requirement: Layout survives the size-shrink path

The message size-shrink path SHALL protect the verdict-led layout: the
expandable section SHALL absorb shrinkage first (as today), body fact
lines SHALL be dropped before the next-action line, and the headline
SHALL never be dropped or truncated into.

#### Scenario: Oversized message keeps verdict and action

- **WHEN** a rendered body exceeds the configured message size limit
- **THEN** the expandable content shrinks first, body lines drop before
  the next-action line, and the headline is always preserved intact

### Requirement: Every class carries a delivery tier

Each notifier class SHALL carry a configured delivery tier, `instant` or
`briefing`. Only `instant` classes SHALL page on the scan that finds their
events. Events of `briefing` classes SHALL be recorded in the ledger as
`briefed` with their watermarks advanced, and SHALL surface only as inputs
to the pulse briefing. Default tiers SHALL be: `instant` for
`chain-runtime-upgrade`, `chain-parameter-change`, `subnet-registry`, and
the Atlas fail-closed condition; `briefing` for every other class. Changing
a class's tier SHALL require no code change and SHALL affect no other class.
Class content requirements elsewhere in this specification describe the
message a class renders when it pages; the tier decides whether it pages.

#### Scenario: Briefing-tier event does not page

- **WHEN** a scan finds a new event of a class whose tier is `briefing`
- **THEN** no message is sent, the event is recorded as `briefed`, and the
  class watermark advances

#### Scenario: Tier is configuration

- **WHEN** the operator sets a briefing-tier class back to `instant`
- **THEN** the next scan pages that class's new events as its content
  requirement describes, and no other class changes behaviour

### Requirement: Subnet registry changes are an instant class

The notifier SHALL provide a `subnet-registry` class that pages when the set
of netuids in the panel snapshot changes between passes (a netuid appears or
disappears) or a subnet's recorded chain name changes. The message SHALL
state the netuid, the change, the previous and new name where applicable,
and the reference blocks on both sides. A first-ever snapshot SHALL seed the
set without paging.

#### Scenario: New netuid pages

- **WHEN** a netuid is present in the latest snapshot and absent from the
  previous one
- **THEN** one `subnet-registry` message states the registration with both
  reference blocks

#### Scenario: Seed is silent

- **WHEN** the first panel snapshot is recorded
- **THEN** no `subnet-registry` message is sent

### Requirement: Persistent fail-closed state pages once

When a provider, the gate poll, or the chain-parameter watch has recorded
only failures for longer than a configured window, the notifier SHALL page
one message naming the component, the first failure time, and the last
recorded good observation, and SHALL NOT page again for that component
until it has recovered and failed anew.

#### Scenario: Prolonged outage pages once

- **WHEN** a component has recorded only failures for longer than the window
- **THEN** exactly one message is sent for that outage

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
