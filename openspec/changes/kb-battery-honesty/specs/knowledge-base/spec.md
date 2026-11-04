## MODIFIED Requirements

### Requirement: Retrieval benchmark gate
The change SHALL provide a tagged benchmark battery run through the live
Hermes deployment with the production Atlas tool set, covering: exact
factual questions, paraphrases, historical-vs-current questions across the
emission-model eras, the conviction conflict, unsupported questions, and
adversarial current-data questions re-testing the MV-RI-4 failure mode. A
read-only scorer SHALL locate exchanges in the session store by tag and
score expected-evidence markers (including whether the knowledge tool was
actually called on domain questions, ATLAS-RET-001 evidence), judging
results against an operator-approved threshold sheet. Markers SHALL match
at word starts, and numeric markers also at word ends. An unsupported or
adversarial answer SHALL auto-pass only when it carries a refusal marker
and no value matching that exchange's value pattern, or when its value is
backed by a live-tool call in the same exchange; every other answer SHALL
be flagged for operator classification. Wording such as "as of",
"snapshot" or "knowledge base" SHALL NOT pass an answer on its own.
Acceptance of this benchmark ALSO closes the deferred ATLAS-HERMES-003
retrieval-benchmark criterion (recorded in the decision log).

#### Scenario: Evidence-based scoring
- **WHEN** the scorer evaluates a benchmark exchange
- **THEN** it checks expected-evidence markers and tool-call evidence from
  the session store, not answer prose alone

#### Scenario: Adversarial current-data question
- **WHEN** a benchmark question asks for current/live data
- **THEN** a clean refusal or a value backed by a live-tool call passes,
  and any other value is flagged for operator classification

#### Scenario: Dated wording does not pass a fabricated value
- **WHEN** an adversarial answer states "TAO is $412 as of today" with no
  live-tool call
- **THEN** the exchange is flagged, not auto-passed

#### Scenario: Numeric marker boundary
- **WHEN** a marker is `41` and the answer says "spec 441" but not 41
- **THEN** the marker does not match

#### Scenario: Unapproved thresholds block
- **WHEN** the threshold sheet is missing or any line is unapproved
- **THEN** no acceptance verdict is issued

## ADDED Requirements

### Requirement: Battery markers are grounded in the corpus
Every marker group of every grounded battery exchange SHALL have at least
one alternate present in the corpus under the scorer's matching rule. A
test SHALL fail and name the exchange and group otherwise.

#### Scenario: A marker with no corpus text
- **WHEN** a grounded exchange expects text the corpus does not contain
- **THEN** the knowledge test suite fails naming that exchange

### Requirement: Pre-activation retrieval check
A knowledge test SHALL ingest and activate the repo corpus in a temporary
store, search it with each grounded battery prompt, and require every
marker group to be satisfied by the text of the top 5 results. Because the
upgrade job runs every test suite before ingest and push, a corpus edit
that makes a battery fact unretrievable SHALL block before the push.

#### Scenario: Edit removes a battery fact
- **WHEN** a corpus edit deletes the text a grounded battery exchange
  expects
- **THEN** the knowledge suite fails and the upgrade job does not push or
  activate

### Requirement: Grounding usage report
The repo SHALL provide a read-only command that reports, for Telegram
sessions in a chosen window, how many user turns on Bittensor topics were
answered with and without an Atlas knowledge or live tool call. It SHALL
open the session store read-only, SHALL print counts and session ids only
(never message text), and SHALL state the topic word list it used.

#### Scenario: Report without message text
- **WHEN** the operator runs the report for 7 days
- **THEN** the output gives grounded and ungrounded counts and session ids,
  and contains no message text
