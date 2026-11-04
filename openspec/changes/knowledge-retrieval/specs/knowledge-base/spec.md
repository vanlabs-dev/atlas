## MODIFIED Requirements

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

## ADDED Requirements

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
It SHALL drop stopwords and question words, keep domain terms, and expand
`SN<n>` to subnet, netuid and `sn<n>` alternatives. It SHALL first rank
units matching all remaining terms, then fill remaining slots from units
matching any term. Ranking SHALL use bm25 with the heading path weighted
above the body. Stemming SHALL apply to both index and query, so an
inflected form matches its stem.

#### Scenario: Stemmed match
- **WHEN** a query is `halve`
- **THEN** search returns the halving units rather than
  insufficient-evidence

#### Scenario: Subnet shorthand
- **WHEN** a query names `SN82` and the corpus mentions subnet 82
- **THEN** the unit mentioning subnet 82 is among the results

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
