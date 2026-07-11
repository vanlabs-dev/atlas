# knowledge-base Specification (delta)

## ADDED Requirements

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
Ingest SHALL split each corpus file into heading-level knowledge units, each
preserving: source file identifier and hash, heading path, line range,
coverage date, per-unit temporal scope where the text is dated, evidence
state, and conflict/supersession links (ATLAS-KB-008/010). Units SHALL be
stored in a single local SQLite database with an FTS5 index
(ATLAS-RET-002); no vector store is built unless a benchmark run proves
full-text retrieval insufficient.

#### Scenario: Unit provenance retrievable
- **WHEN** any unit is returned by search or evidence lookup
- **THEN** its source file, heading path, coverage date, temporal scope,
  and evidence state are included

#### Scenario: Temporal scope preserved
- **WHEN** a corpus statement is explicitly dated (e.g. an emission model
  era)
- **THEN** its unit carries that temporal scope, distinct from the corpus
  coverage date

### Requirement: Validation report and operator activation gate
Ingest SHALL stage units (inactive) and produce a validation report:
structure analysis (headings, code blocks, duplicates — ATLAS-KB-002),
secret-scan results, unit counts by evidence state, and every marked
conflict/supersession candidate. Activation SHALL be a separate explicit
operator action recorded in the store's audit table; the tools SHALL serve
only activated knowledge and fail closed with an explicit
not-activated error otherwise (ATLAS-KB-005/006). For this curated corpus,
`confirmed` units record the operator's curation plus in-file citations as
their supporting evidence (documented ATLAS-KB-003/004 interpretation).

#### Scenario: Staged until approved
- **WHEN** ingest completes but activation has not been performed
- **THEN** knowledge tools return a structured not-activated error rather
  than serving staged content

#### Scenario: Activation audited
- **WHEN** the operator activates an ingest run
- **THEN** the audit table records the run id, actor, and timestamp

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
read-only tools — `knowledge_search`, `knowledge_get_evidence`,
`knowledge_status` — which replaces the `atlas-test` server in the Hermes
configuration. Search results SHALL be source-bound (content plus
provenance and evidence state, ATLAS-RET-003); zero-hit queries SHALL
return a structured insufficient-evidence result, never model-filled prose
(ATLAS-RET-004). Every error SHALL be structured per ATLAS-TOOL-002
(category, component, retry-safety, user-safe message, correlation id).
The server SHALL open the store read-only, SHALL NOT expose SQL, shell,
file, or HTTP surfaces (ATLAS-TOOL-003), and SHALL append a redacted
audit line per call (ATLAS-TOOL-004) as its only write.

#### Scenario: Source-bound search result
- **WHEN** `knowledge_search` matches units
- **THEN** each result includes content, source, heading path, dates,
  evidence state, and conflict flags

#### Scenario: Insufficient evidence is explicit
- **WHEN** a query matches no active unit
- **THEN** the tool returns a structured insufficient-evidence result

#### Scenario: Structured errors
- **WHEN** the store is missing, unreadable, or not activated
- **THEN** the tool returns an ATLAS-TOOL-002 structured error, and the
  server neither crashes nor guesses

### Requirement: Retrieval benchmark gate
The change SHALL provide a tagged benchmark battery run through the live
Hermes deployment with the knowledge tools enabled, covering: exact
factual questions, paraphrases, historical-vs-current questions across the
emission-model eras, the conviction conflict, unsupported questions, and
adversarial current-data questions re-testing the MV-RI-4 failure mode
(answers must be dated corpus facts or explicit refusals — never presented
as live data). A read-only scorer SHALL locate exchanges in the session
store by tag and score expected-evidence markers (including whether the
knowledge tool was actually called on domain questions — ATLAS-RET-001
evidence), judging results against an operator-approved threshold sheet;
flagged value-shaped answers in the unsupported/adversarial sets require
operator classification. Acceptance of this benchmark ALSO closes the
deferred ATLAS-HERMES-003 retrieval-benchmark criterion (recorded in the
decision log).

#### Scenario: Evidence-based scoring
- **WHEN** the scorer evaluates a benchmark exchange
- **THEN** it checks expected-evidence markers and tool-call evidence from
  the session store, not answer prose alone

#### Scenario: Adversarial current-data question
- **WHEN** a benchmark question asks for current/live data
- **THEN** a passing answer gives dated corpus facts or an explicit
  cannot-verify — a value presented as live is a finding

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
