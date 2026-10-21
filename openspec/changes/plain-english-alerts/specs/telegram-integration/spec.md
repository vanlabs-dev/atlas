## MODIFIED Requirements

### Requirement: Alert headlines and glosses are rendered from recorded fields only

Every alert class SHALL render the house layout: a plain-language
headline stating what happened, jargon glossed in parentheses at first use
per the approved lexicon, and the class's sourced facts. A gloss SHALL be
attached only inside a composed body sentence. It SHALL NOT be inserted into
the headline, a key-figure label, or recorded text (commit subjects, pallet
labels, verdict text, file paths, subnet names). When a concrete follow-up action
exists, a final next-action line SHALL state it; alerts with no warranted
action SHALL omit the line rather than emit boilerplate. The deterministic
template SHALL interpolate only values already recorded in the source
stores, and renderers SHALL NOT fetch, compute, or infer new facts. The
plain-language wording of a paged alert MAY be replaced by the checked
rewrite defined in the `alert-plain-rewrite` capability, which changes
words only and never adds a fact; when the rewrite is absent or refused the
template SHALL be sent. Because renderers never
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

#### Scenario: Rewrite refused, template sent

- **WHEN** the plain-language rewrite for an alert fails its check
- **THEN** the alert is sent from the deterministic template with only
  recorded values

### Requirement: Severity marker by event outcome

The first character of every message SHALL be one severity marker chosen
from a fixed set: 🔴 act now, 🟠 watch, 🟢 good news, 🔵 for information,
✅ done or recovered. The marker SHALL be chosen deterministically from the
event's class and recorded fields. The rewrite SHALL NOT change it. It SHALL
NOT change delivery behaviour.

#### Scenario: Crossing direction sets the marker

- **WHEN** a subnet with emission enabled rises above the bar
- **THEN** the message starts with 🟢, and a fall below the bar starts
  with 🔴

#### Scenario: Emission-off crossing is informational

- **WHEN** a crossing is recorded for a subnet with emission disabled
- **THEN** the event keeps the 🔵 marker in its stored form, is recorded in
  the ledger, and no message is sent

## ADDED Requirements

### Requirement: Technical detail lives in the details fold

A paged alert SHALL carry at most two labelled key figures outside the fold.
Setting and storage item names, block numbers, run ids, commit SHAs and
ranges, file and line counts, raw stored values, source names and ISO
timestamps SHALL render inside the expandable details fold. The filler line
`Before: stored value. After: stored value.` SHALL NOT be emitted. A setting
description SHALL appear once, opening with a capital letter.

#### Scenario: Parameter alert keeps the setting name in the fold

- **WHEN** `SubnetEmissionEnabled` turns off for subnet 103
- **THEN** the headline and meaning sentence use no setting name, and the
  fold shows `SubnetEmissionEnabled, on → off`, the block and the source

#### Scenario: No duplicate description

- **WHEN** a setting has a configured `governs` description
- **THEN** that description appears once in the message, starting with a
  capital letter

### Requirement: Alerts use plain terms for chain concepts

Alert wording SHALL use the plain terms in the alert lexicon:
`reward cutoff` for the emission bar, `demand` for demand share, and
`version` for runtime spec in headlines and meaning sentences. The
technical term SHALL remain in the details fold. The alert lexicon and its
conformance test SHALL be updated to match. The inbound chat voice SHALL be
unchanged.

#### Scenario: Upgrade headline says version

- **WHEN** the live runtime spec moves from 481 to 482
- **THEN** the headline reads `Bittensor just updated its software (version
  482)` and the fold shows `Runtime spec 481 → 482`

### Requirement: Raw-scale chain values render as percentages

A chain-parameter alert for a setting configured with the unit `u16-fraction`
SHALL show each value as a percentage of 65,535 in the key figures and the
meaning sentence, and the raw values in the fold. A zero value SHALL render
as `0%`.

#### Scenario: Collateral lock share

- **WHEN** `CollateralLockShare` changes from 0 to 62,258
- **THEN** the key figure reads `0% → 95%` and the fold shows `0 → 62,258 (of
  65,535)`

### Requirement: Knowledge ingestion is a briefing-tier class that asks for no action

The `knowledge-ingestion` class SHALL be registered at the `briefing` tier.
The alert wording, when it surfaces, SHALL state that new facts are already in
use when the upgrade job has activated the run, and SHALL NOT tell the
operator to review or activate. The class's events SHALL stay recorded in the
ledger.

#### Scenario: Ingest does not page

- **WHEN** a knowledge run finishes with 30 units
- **THEN** no message is sent and the event is recorded as `briefed`

#### Scenario: Rollback

- **WHEN** the operator sets the tier back to `instant`
- **THEN** the next scan pages new knowledge events, and no other class
  changes behaviour

### Requirement: A crossing with emission already off is recorded and not sent

A confirmed gate crossing for a subnet whose pool-side emission switch is
off SHALL be recorded in the ledger as `briefed` and SHALL NOT be sent. The
event SHALL be emitted under its own delivery-only class,
`gate-crossing-no-effect`, whose tier is `briefing`, so that flipping the tier
restores the page. The crossing cooldown and eligibility state of the
`gate-crossing` class SHALL NOT be changed by these events.

#### Scenario: Subnet with emission off crosses

- **WHEN** subnet 103 has its emission switch off and its demand share falls
  below the bar
- **THEN** no message is sent, the event is recorded as `briefed` under
  `gate-crossing-no-effect`, and a later crossing for a subnet with emission
  on still pages

### Requirement: Pinned provider schemas match the provider's current reply

When a provider schema-drift alert has fired for more than seven days, the
pinned schema SHALL be repaired so the operation recovers, and a regression
test SHALL hold the repaired schema against a recorded reply.

#### Scenario: CoinGecko price operation recovers

- **WHEN** the `price_spot_coingecko` operation is called after the repair
- **THEN** the reply validates against the pinned schema and no new
  `schema-drift` event is recorded
