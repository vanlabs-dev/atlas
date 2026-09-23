## MODIFIED Requirements

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
