# hardening-assessment Specification

## Purpose
TBD - created by archiving change atlas-phase-0-hardening-assessment. Update Purpose after archive.
## Requirements
### Requirement: Assessment is observation-based and read-only
The hardening assessment SHALL derive every verdict from observed evidence: the most recent valid device-inventory report and/or its own read-only probes. It MUST NOT assume any state, and it MUST NOT modify the device — no package installation, configuration change, service change, or file mutation. Supplementary probes SHALL follow the same read-only, no-self-elevation, redaction, and status-envelope rules as the device-inventory capability.

#### Scenario: No state change after assessment
- **WHEN** a full assessment run completes
- **THEN** device configuration, packages, services, and files are unchanged
- **AND** the only files created are the assessment outputs in the designated output directory

#### Scenario: Missing evidence is not assumed
- **WHEN** an assessment area's evidence cannot be observed (probe unsupported or permission-denied)
- **THEN** the area's verdict reflects the missing evidence explicitly
- **AND** the assessor does not substitute an assumed or default state

### Requirement: Full ATLAS-ENV-003 area coverage
A full assessment SHALL evaluate every ATLAS-ENV-003 area: unprivileged service execution; SSH authentication and exposed ports; firewall rules; unattended security updates or documented update process; secret file permissions; log permissions; backup encryption and destination; service restart policy; time synchronization; disk space thresholds; and remote frontend exposure. No area may be silently omitted from the output.

#### Scenario: Every area appears in the output
- **WHEN** an assessment run completes
- **THEN** the assessment output contains one entry per ATLAS-ENV-003 area
- **AND** each entry carries a verdict and its supporting evidence reference

### Requirement: Explicit per-area verdicts
Each assessment area SHALL receive exactly one verdict: `ok` (observed state meets the baseline expectation, with evidence), `finding` (a gap was observed; must include evidence and a proposed remediation), `decision-required` (the area depends on an unresolved operator decision; must name the decision), or `not-applicable-yet` (the area concerns a component that does not exist yet; must say what will trigger reassessment). Verdicts MUST NOT be merged, averaged, or summarized into a single score.

#### Scenario: Observed gap becomes a finding
- **WHEN** the evidence shows SSH password authentication enabled or no firewall rules present
- **THEN** the area verdict is `finding` with the observed evidence quoted or referenced
- **AND** a proposed remediation is attached

#### Scenario: Unresolved operator decision surfaces as decision-required
- **WHEN** an area depends on an open decision (for example the external backup destination, PRD §21 Q10)
- **THEN** the verdict is `decision-required` naming that decision
- **AND** the assessor does not invent a default

#### Scenario: Future component is not falsely assessed
- **WHEN** the area concerns the not-yet-built monitoring frontend
- **THEN** the verdict is `not-applicable-yet` with the reassessment trigger stated
- **AND** it is not reported as `ok`

### Requirement: Evidence-grounded output
Every verdict SHALL reference its evidence: the inventory report run id and item path, or the supplementary probe envelope. The assessment output SHALL record which inventory report (run id, hash or path) it consumed and reject an inventory report that fails schema validation.

#### Scenario: Stale or invalid inventory input rejected
- **WHEN** the assessor is given an inventory report that fails schema validation
- **THEN** the run fails visibly without producing verdicts
- **AND** the error names the validation failure

#### Scenario: Verdict traceability
- **WHEN** the operator reads any verdict
- **THEN** the referenced evidence identifies exactly where the observation came from

### Requirement: Proposed hardening plan without execution
For every `finding`, the assessment SHALL produce a proposed remediation in a human-reviewable hardening plan: what would change, why, the exact commands or configuration edits that would be applied, expected impact, and rollback notes. Producing the plan MUST NOT execute any of it. The plan SHALL state that each item requires explicit operator approval and that application happens only through a separate approved change.

#### Scenario: Plan is generated but nothing executes
- **WHEN** the assessment produces a plan proposing firewall installation and SSH key-only authentication
- **THEN** no package is installed and no configuration is edited
- **AND** each plan item carries an unchecked approval marker for the operator

#### Scenario: Plan items are actionable
- **WHEN** the operator approves a plan item
- **THEN** the item contains enough detail (commands/edits, impact, rollback) for the follow-up change to implement it without re-deriving the intent

### Requirement: Versioned, redacted assessment outputs
The assessment SHALL emit a machine-readable JSON output conforming to a versioned schema stored in the repository, plus the Markdown plan, plus a per-run audit record. All outputs SHALL pass the redaction filter, contain no secret values, and be written with owner-only (0600) permissions.

#### Scenario: Outputs validate and are private
- **WHEN** an assessment run completes
- **THEN** the JSON output validates against its declared schema version
- **AND** all output files have owner-only permissions and contain no secret values

#### Scenario: Failed run still audited
- **WHEN** an assessment run fails partway
- **THEN** an audit record exists stating what ran, what failed, and when

