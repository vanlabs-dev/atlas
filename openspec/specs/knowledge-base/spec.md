# knowledge-base Specification

## Purpose
Serve a validated, dated Bittensor corpus to Hermes through the read-only `atlas-kb` tools, measured against a fixed question battery.

## Requirements

### Requirement: Corpus snapshot with recorded provenance
The repo SHALL carry a verbatim snapshot of the confirmed July 2026 corpus
(the three grounding files) together with recorded origin (source repo and
path), sync date, and per-file SHA-256 hashes. Ingest SHALL operate only on
the snapshot and MUST verify the recorded hashes before ingesting. The
original files in the source repo MUST NOT be modified or deleted by
anything in this repo — the ATLAS-KB-007 deletion gate is closed as
not-applicable by this requirement.

#### Scenario: Hash-verified ingest
- **WHEN** ingest runs against the corpus snapshot
- **THEN** each file's SHA-256 is verified against the recorded value before
  any unit is created
- **AND** a mismatch aborts the ingest naming the file

#### Scenario: Originals untouched
- **WHEN** any knowledge-base operation runs
- **THEN** no file outside the repo snapshot and gitignored `var/` is
  written or deleted

### Requirement: Intake record
Every ingest run SHALL record, per ATLAS-KB-001: filename, byte size,
SHA-256, intake date, declared coverage date, parser version, and a unique
run identifier — queryable from the store and reproduced in the validation
report.

#### Scenario: Complete intake record
- **WHEN** an ingest run completes
- **THEN** the store contains all ATLAS-KB-001 fields for that run

### Requirement: Provenance-preserving knowledge units
Ingest SHALL split each corpus file into block-level knowledge units: one
top-level list item, numbered item, bold-led entry, or paragraph within its
`#`, `##` or `###` section, with nested and continuation lines kept in their
parent block, except that a block longer than 1,500 characters is split at
its nested items. Each unit SHALL preserve: source file identifier and hash, the
full heading path, line range, coverage date, per-unit temporal scope where
the text is dated (month-year phrases and ISO `YYYY-MM-DD` dates), evidence
state, conflict/supersession links (ATLAS-KB-008/010), and a kind: `fact`,
`correction` (a known wrong claim and its fix), or `procedure` (writing or
publishing workflow). The kind SHALL come from a checked-in heading map;
every heading in that map SHALL exist in the corpus, or the test suite
fails. Units SHALL be stored in a single local SQLite database with an FTS5
index (ATLAS-RET-002); no vector store is built unless a benchmark run
proves full-text retrieval insufficient.

#### Scenario: Unit provenance retrievable
- **WHEN** any unit is returned by search or evidence lookup
- **THEN** its source file, heading path, line range, coverage date,
  temporal scope, evidence state and kind are included

#### Scenario: Temporal scope preserved
- **WHEN** a corpus statement is explicitly dated (e.g. an emission model
  era, or an ISO date such as 2026-10-14)
- **THEN** its unit carries that temporal scope, distinct from the corpus
  coverage date

#### Scenario: Block granularity
- **WHEN** a section holds several top-level list items
- **THEN** each item is its own unit with the section's heading path, and
  no unit spans two top-level items

#### Scenario: Orphaned kind mapping fails
- **WHEN** a corpus heading named in the kind map is renamed or removed
- **THEN** the knowledge test suite fails and names the unmatched entry

### Requirement: Validation report and operator activation gate
Ingest SHALL stage units (inactive) and produce a validation report:
structure analysis (headings, code blocks, duplicates, ATLAS-KB-002),
secret-scan results, unit counts by evidence state, and every marked
conflict/supersession candidate. Activation SHALL be a separate explicit
action recorded in the store's audit table, taken either by the operator
or by the runtime upgrade job after every upgrade gate has passed and its
push is confirmed on the remote. The upgrade job SHALL record the actor
`atlas-upgrade` and SHALL NOT activate a run with rejected units. The
tools SHALL serve only activated knowledge and fail closed with an
explicit not-activated error otherwise (ATLAS-KB-005/006). For this
curated corpus, `confirmed` units record the operator's curation plus
in-file citations as their supporting evidence (documented
ATLAS-KB-003/004 interpretation).

#### Scenario: Staged until approved
- **WHEN** ingest completes but activation has not been performed
- **THEN** knowledge tools return a structured not-activated error rather
  than serving staged content

#### Scenario: Activation audited
- **WHEN** the operator activates an ingest run
- **THEN** the audit table records the run id, actor, and timestamp

#### Scenario: Gated automatic activation
- **WHEN** the upgrade job activates an ingest run after a confirmed push
- **THEN** the audit table records the run id, actor `atlas-upgrade`, and
  timestamp

#### Scenario: No automatic activation before push
- **WHEN** an upgrade attempt fails at any gate or at push
- **THEN** its staged run is not activated and the prior run stays active

### Requirement: Known-supersession handling
Units whose claims are known to be superseded or contradicted — starting
with the conviction activation reported 2026-07-12 (corpus says ownership
transfer is "NOT yet active") — SHALL be ingested with evidence state
`conflicting`, carrying a note that links the decision-log entry. Retrieval
SHALL surface the conflict (state + note) with every such unit and MUST NOT
return the claim as unqualified confirmed fact until the conflict is
resolved by recorded evidence (ATLAS-KB-009/010, ATLAS-RET-005).

#### Scenario: Conviction conflict surfaced
- **WHEN** a search returns a unit about conviction ownership transfer
- **THEN** the result carries evidence state `conflicting` and the note
  referencing the reported activation

#### Scenario: No silent overwrite
- **WHEN** new information contradicts an active unit
- **THEN** both records are retained and linked, neither returned as
  unqualified confirmed fact

### Requirement: Read-only knowledge tools for Hermes
The change SHALL provide a local stdio MCP server exposing exactly three
read-only tools (`knowledge_search`, `knowledge_get_evidence`,
`knowledge_status`), which replaces the `atlas-test` server in the Hermes
configuration. Search results SHALL be source-bound (content plus
provenance and evidence state, ATLAS-RET-003) and bounded: at most 1,500
characters of content per result, with a `truncated` flag when cut, and
run-level fields (run id, coverage date) once per response rather than per
result. The default result count SHALL be 5 and the maximum 10.
`knowledge_get_evidence` SHALL return the unit, the full text of its
section, and any conflicting units in the same source. Zero-hit queries
SHALL return a structured insufficient-evidence result, never model-filled
prose (ATLAS-RET-004). Every error SHALL be structured per ATLAS-TOOL-002
(category, component, retry-safety, user-safe message, correlation id).
The server SHALL open the store read-only, SHALL NOT expose SQL, shell,
file, or HTTP surfaces (ATLAS-TOOL-003), and SHALL append a redacted
audit line per call (ATLAS-TOOL-004) as its only write. The server SHALL
keep serving a store written by the previous schema (no kind column, no
rebuilt index) until the next activation, and `knowledge_status` SHALL
report the store's index version (null when not rebuilt).

#### Scenario: Source-bound search result
- **WHEN** `knowledge_search` matches units
- **THEN** each result includes unit id, kind, content, source, heading
  path, line range, temporal scope, evidence state, and the conflict note
  when one exists

#### Scenario: Bounded payload
- **WHEN** a search returns 5 results from the current corpus
- **THEN** no result's content exceeds 1,500 characters and a cut result
  carries `truncated: true`

#### Scenario: Evidence carries section context
- **WHEN** `knowledge_get_evidence` is called with a unit id from a search
  result
- **THEN** the result includes that unit and the full text of the section
  it belongs to

#### Scenario: Insufficient evidence is explicit
- **WHEN** a query matches no active unit
- **THEN** the tool returns a structured insufficient-evidence result

#### Scenario: Structured errors
- **WHEN** the store is missing, unreadable, or not activated
- **THEN** the tool returns an ATLAS-TOOL-002 structured error, and the
  server neither crashes nor guesses

#### Scenario: Previous-schema store still served
- **WHEN** the server runs against a store whose index was built before
  this change
- **THEN** search returns active units, and `knowledge_status` reports
  index version null

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

### Requirement: Read-only envelope and fail-closed verdict
All knowledge-base code SHALL follow the repo envelope: unprivileged,
redaction applied to all outputs, store and reports under gitignored
`var/knowledge/` with 0600 report files, benchmark scoring fail-closed
with named blockers, documented exceptions reproduced in reports, and exit
codes matching the repo's verifiers (0 accepted, 3 not-accepted, 4 no
verdict on invalid inputs, 1 fatal). Ingest and activation mutate only the
knowledge store; nothing else on the device changes.

#### Scenario: Envelope respected
- **WHEN** any knowledge-base command runs
- **THEN** writes are confined to `var/knowledge/` (plus the benchmark's
  `var/` outputs) and no privilege is acquired

#### Scenario: One blocker prevents acceptance
- **WHEN** the benchmark verdict is computed with any unresolved item
- **THEN** the verdict is not-accepted and names it

### Requirement: Status reports the active run

`knowledge_status` SHALL report the active run's id, coverage date, and
corpus files, taken from that run and not from the newest ingest. When a
staged run was ingested after the active run, the result SHALL name it as
`staged_newer_run`, with its id and coverage date. Otherwise the field
SHALL be null.

#### Scenario: Newer run staged, not active
- **WHEN** run 482 is active and run 486 is staged later
- **THEN** the status shows run 482 with its own coverage date, and
  `staged_newer_run` names run 486

#### Scenario: Newest run active
- **WHEN** the active run is the newest ingest
- **THEN** `staged_newer_run` is null

### Requirement: Search index holds active searchable units only
The full-text index SHALL contain exactly the active run's units whose kind
is `fact` or `correction`, tokenized with Porter stemming over unicode61.
Activation SHALL rebuild the index in the same transaction that changes the
active run, and SHALL record the index version in the store. A failed
rebuild SHALL leave the prior run active with its prior index. Ingest SHALL
NOT add staged units to the index. `procedure` units SHALL be stored and
reachable through `knowledge_get_evidence`, but never returned by search.

#### Scenario: Inactive runs do not affect ranking
- **WHEN** a store holds several ingest runs and one is activated
- **THEN** the index row count equals that run's searchable unit count

#### Scenario: Procedure units are not searched
- **WHEN** a query matches only a `procedure` unit's text
- **THEN** search returns insufficient-evidence for that unit's text, and
  `knowledge_get_evidence` with its id still returns it

#### Scenario: Rebuild failure keeps the prior run
- **WHEN** the index rebuild fails during activation
- **THEN** the previously active run stays active and searchable

### Requirement: Search query and ranking
The server SHALL build every full-text query from the user's text in code.
It SHALL drop stopwords, question words and single letters, keep domain
terms, and expand `SN<n>` to subnet, netuid, `sn<n>` and bare-number
alternatives. Terms the index does not hold SHALL NOT constrain ranking.
It SHALL first rank units matching all remaining held terms, then fill
remaining slots from units matching any of them. Ranking SHALL use bm25 with the heading path weighted
above the body. Stemming SHALL apply to both index and query, so an
inflected form matches its stem.

#### Scenario: Stemmed match
- **WHEN** a query is `halve`
- **THEN** search returns the halving units rather than
  insufficient-evidence

#### Scenario: Subnet shorthand
- **WHEN** a query names `SN82` and the corpus mentions subnet 82
- **THEN** the unit mentioning subnet 82 is among the results

#### Scenario: An unknown word does not empty the results
- **WHEN** a query pairs a corpus term with a word the corpus never uses,
  such as "staking pie"
- **THEN** results come from units matching the corpus term, ranked as if
  the unknown word were absent

#### Scenario: Question words do not steer ranking
- **WHEN** a query is "How does staking work?"
- **THEN** the first result is a unit from the `Staking` section

### Requirement: Retrieval evaluation
The repo SHALL carry a retrieval evaluation of at least 20 queries over the
real corpus. Each query names text that must appear in its top 5 results.
A test SHALL ingest and activate the real corpus in a temporary store and
fail when any query misses. The evaluation SHALL include every query the
2026-11-02 audit found failing.

#### Scenario: A removed fact fails the suite
- **WHEN** a corpus edit deletes the text an evaluation query expects
- **THEN** the knowledge test suite fails and names the query

### Requirement: Battery markers are grounded in the corpus
Every marker group of every grounded battery exchange SHALL have at least
one alternate present in the corpus under the scorer's matching rule. A
test SHALL fail and name the exchange and group otherwise.

#### Scenario: A marker with no corpus text
- **WHEN** a grounded exchange expects text the corpus does not contain
- **THEN** the knowledge test suite fails naming that exchange

### Requirement: Corpus polarity lint
The repo SHALL carry checked-in polarity rules, each naming one operation,
a predicate the subtensor source refutes for it, and that source. A test
SHALL fail when a `fact` unit states a rule's forbidden predicate about its
operation without nearby negation. `correction` units SHALL be exempt.

#### Scenario: A refuted claim returns
- **WHEN** a corpus edit states that the TAO paid to create a subnet is
  recycled
- **THEN** the knowledge test suite fails naming the rule and unit

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
