# Delta spec: telegram-integration (modified capability)

## MODIFIED Requirements

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
or en dashes (the renderer normalizes any imported from stored data). On an
HTTP 400 (rejected formatting), the notifier SHALL retry once as plain text
(the untagged structured text, never the raw HTML source) so a rendering
fault never suppresses an alert, and SHALL record the fallback.

#### Scenario: Dynamic values are escaped

- **WHEN** a message containing user- or repo-derived text is rendered as HTML
- **THEN** every `&`, `<`, and `>` in dynamic values is escaped and the message
  is accepted by Telegram

#### Scenario: Formatting rejection falls back to plain text

- **WHEN** a send with HTML parse mode returns HTTP 400
- **THEN** the notifier retries the same event once as plain text and records the
  fallback, and the delivery is not lost to the formatting error

## ADDED Requirements

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
