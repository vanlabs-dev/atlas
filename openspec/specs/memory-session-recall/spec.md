# memory-session-recall Specification

## Purpose
TBD - created by archiving change atlas-phase-1-memory-and-session-recall. Update Purpose after archive.
## Requirements
### Requirement: Memory approval gating verification
The verifier SHALL confirm from the installed Hermes configuration that memory and
skill writes require operator approval (ATLAS-MEM-003, initial deployment policy).
The configuration paths SHALL come from the install record, not hardcoded locations.
A configuration whose approval state cannot be determined SHALL be reported as an
explicit unknown and MUST block acceptance — it is never assumed enabled.

#### Scenario: Approval gating verified
- **WHEN** the Hermes configuration explicitly requires approval for memory writes
- **THEN** the approval-gating check reports `ok` citing the config location

#### Scenario: Indeterminate gating fails closed
- **WHEN** no recognized approval setting is found in the configuration
- **THEN** the check reports `unknown` with remediation guidance
- **AND** the overall verdict cannot be acceptance

### Requirement: Scripted evaluation procedure
The change SHALL provide a scripted operator procedure implementing the
ATLAS-MEM-006 evaluation set as concrete, repeatable steps with exact prompts,
documented synthetic values, and expected outcomes, covering all seven items:
preference retention, correction replacement (ATLAS-MEM-004), stale-memory removal,
duplicate prevention, prior-session lookup (ATLAS-MEM-002), secret rejection
(ATLAS-MEM-005), and separation of personal memory from Bittensor facts
(ATLAS-MEM-001). The procedure SHALL define a credential-shaped but clearly
synthetic **canary secret** with a fixed recognizable prefix, and a distinctive
**recall marker phrase**, both consumed by the verifier's automated checks. Each
step SHALL name the attestation the verifier expects for it.

#### Scenario: Procedure covers the full evaluation set
- **WHEN** the procedure document is reviewed against ATLAS-MEM-006
- **THEN** every one of the seven evaluation items has a scripted step with exact
  prompts, expected outcome, and a named attestation

#### Scenario: Step cannot be completed as scripted
- **WHEN** a procedure step cannot be induced in the live session (e.g. no memory
  is ever proposed)
- **THEN** the deviation is recorded rather than improvised around
- **AND** the corresponding attestation is withheld, blocking acceptance

### Requirement: Operator attestation of interactive memory behaviors
Interactive memory behaviors — the approval prompt appearing with proposed content,
correction replacing rather than duplicating, stale-memory removal, duplicate
prevention, prior-session lookup from a new session, secret rejection, and
domain separation in live use — SHALL be performed by the operator following the
scripted procedure and supplied to the verifier as explicit per-item attestations.
The verifier SHALL record each attestation (item, attesting operator, timestamp)
in the report and MUST NOT mark an unattested item as passed.

#### Scenario: Attested items recorded
- **WHEN** the operator supplies attestations for all seven evaluation items
- **THEN** the report lists each as attested with operator and timestamp

#### Scenario: Missing attestation blocks acceptance
- **WHEN** any evaluation item lacks its attestation
- **THEN** that item reports not-attested and the verdict is not acceptance

### Requirement: Memory hygiene scan
The verifier SHALL scan the Hermes memory files (`MEMORY.md`, `USER.md`, located
via the install record's data directory) and report as findings, with redacted
excerpts only: credential-shaped material (ATLAS-MEM-005), the procedure's canary
secret, and bulk Bittensor/domain-corpus-shaped content (ATLAS-MEM-001). Memory
file sizes SHALL be recorded as evidence. The scan distinguishes memory files from
session transcripts: the canary legitimately appears in session content and is a
finding only inside memory files.

#### Scenario: Canary found in memory is a finding
- **WHEN** the canary secret appears in `MEMORY.md` or `USER.md` after the procedure
- **THEN** the report contains a secret-rejection finding with a redacted excerpt
- **AND** the verdict is not acceptance

#### Scenario: Canary in session transcript is not a memory finding
- **WHEN** the canary appears only in session history, not in memory files
- **THEN** the memory hygiene scan reports `ok` and notes the expected location

#### Scenario: Domain dump in memory is a finding
- **WHEN** memory files contain bulk Bittensor corpus-shaped content
- **THEN** the report contains a separation finding with a redacted excerpt

### Requirement: Session store recall evidence
The verifier SHALL confirm, opening the Hermes session store strictly read-only,
that the store exists at the recorded data directory, its full-text search surface
is present, and the procedure's recall marker phrase is findable via a read-only
search query (ATLAS-MEM-002). A missing, locked, or unreadable store SHALL be
reported as an explicit unknown with guidance — never guessed around, and never
opened writable.

#### Scenario: Recall marker found
- **WHEN** the session store is readable and the recall marker phrase is planted
- **THEN** the session-store check reports `ok` with the search evidence

#### Scenario: Unreadable store fails closed
- **WHEN** the session store cannot be opened read-only
- **THEN** the check reports the explicit status (`permission-denied`, locked, or
  missing) and the verdict cannot be acceptance

### Requirement: Read-only memory verification
The verifier SHALL NOT modify device state: no Hermes configuration writes, no
memory or session content created or altered by repo code, no service operations.
Its only writes SHALL be schema-validated report files created `0600` in gitignored
`var/memory/`. Checks needing privilege the invoking user lacks SHALL report
`permission-denied` rather than escalate; checks not applicable to the installed
Hermes version SHALL report `unsupported-on-device`. The interactive procedure is
performed by the operator in a live Hermes session and is the only place memory or
session content changes.

#### Scenario: No mutation during verification
- **WHEN** the verifier completes a full run
- **THEN** no Hermes configuration, memory file, or session content has been
  changed by the verifier
- **AND** the only new files are its 0600 reports in `var/memory/`

#### Scenario: Unreadable file reported, not escalated
- **WHEN** a check needs a file the invoking user cannot read
- **THEN** that check reports `permission-denied` with the path
- **AND** the verifier neither prompts for nor uses sudo

### Requirement: Fail-closed memory acceptance verdict
The verifier SHALL emit a single overall verdict consuming the install record as
its path source; a missing or incomplete install record yields no verdict.
Acceptance SHALL be reported only when every automated check is `ok` (or covered by
a documented exception recorded and reproduced in the report) and every evaluation
item is attested. Any finding, missing attestation, or unresolved unknown SHALL
result in a non-accepted verdict naming each blocking item. The verdict and
evidence SHALL be suitable for recording in the decision log, including the
ATLAS-MEM-006 evidence needed for the PRD §21 Q19 decision.

#### Scenario: Clean run accepted
- **WHEN** all automated checks report `ok` and all seven attestations are present
- **THEN** the verdict is accepted and the report summarizes the evidence for the
  decision log

#### Scenario: One unknown blocks acceptance
- **WHEN** all checks pass except one reporting an unresolved unknown
- **THEN** the verdict is not-accepted and lists that check as the blocker

#### Scenario: Missing install record yields no verdict
- **WHEN** `var/hermes/install-record.json` is absent or incomplete
- **THEN** the verifier reports what is missing and issues no acceptance verdict

