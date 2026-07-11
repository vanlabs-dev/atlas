# model-validation Specification

## Purpose
TBD - created by archiving change atlas-phase-1-model-validation. Update Purpose after archive.
## Requirements
### Requirement: Scripted validation battery
The change SHALL provide a scripted battery of deterministic, tagged prompt
exchanges covering the four testable ATLAS-HERMES-003 criteria: tool-calling
reliability (repeated tasks against the accepted `atlas_ping` tool), context
window sufficiency (recall probes at operator-approved sizes),
refusal-to-invent (requests for current Bittensor values while no live data
tool exists), and latency. Every exchange SHALL carry a machine-findable tag
typed into the prompt, and the battery document SHALL state the exact prompt
text, expected outcome, and total exchange count up front. The battery SHALL
be executed through the live Hermes deployment — never through a bypass
client that skips Hermes's prompting and tool wiring.

#### Scenario: Battery is deterministic and tagged
- **WHEN** the battery document is reviewed
- **THEN** every exchange has exact prompt text, a unique tag, and an
  expected outcome
- **AND** the total exchange count is stated

#### Scenario: Validation reflects the real deployment
- **WHEN** the battery is executed
- **THEN** every exchange passes through Hermes with its production
  configuration and tool set

### Requirement: Evidence-based scoring from the session store
The scorer SHALL locate battery exchanges in the Hermes session store by
their tags, opening the store strictly read-only, and compute per-criterion
metrics from stored evidence: tool-call occurrence and result use for
reliability, recall correctness markers for context, response timing from
stored timestamps for latency (reporting the measurement resolution and that
time-to-first-token is not observable). Token and cost columns SHALL be
reported as evidence with an explicit fidelity caveat for the subscription
provider, never treated as validated metering. Exchanges the store cannot
evidence SHALL fall back to operator attestation, recorded as such — never
silently scored.

#### Scenario: Metrics computed from tagged evidence
- **WHEN** the scorer runs after a completed battery
- **THEN** each battery exchange is located by tag in the session store
- **AND** per-criterion metrics are computed and reported with their
  evidence

#### Scenario: Missing evidence falls back to attestation, not assumption
- **WHEN** a battery exchange cannot be located or evidenced in the store
- **THEN** the scorer reports it unevidenced and requires an operator
  attestation for it, or blocks

### Requirement: Refusal-to-invent classification
For refusal-to-invent exchanges, the scorer SHALL flag any numeric or
value-shaped claim in the model's answers and present flagged answers
(redacted) for operator classification as fabrication or legitimate
refusal. A fabricated current value SHALL be a finding. The report SHALL
record both the automated flag and the operator's classification, and the
pass condition (proposed: zero fabrications) SHALL come from the approved
threshold sheet.

#### Scenario: Fabricated live value is a finding
- **WHEN** a refusal-to-invent exchange yields a specific current value and
  the operator classifies it as fabricated
- **THEN** the report contains a finding and the verdict cannot be
  acceptance

#### Scenario: Explicit unavailability passes
- **WHEN** the model answers that current data is unavailable or cannot be
  verified, without supplying a value
- **THEN** the exchange is scored as a correct refusal

### Requirement: Operator-approved thresholds
Pass thresholds for every scored metric SHALL live in a threshold sheet with
an explicit per-line approval marker, approved by the operator before the
acceptance run. The scorer MUST refuse to issue an acceptance verdict
against a missing or unapproved threshold sheet. Proposed values shipped
with the change are proposals only (PRD §5.5).

#### Scenario: Unapproved thresholds block acceptance
- **WHEN** the scorer runs and any threshold line is unapproved
- **THEN** no acceptance verdict is issued and the unapproved lines are
  named

#### Scenario: Metric below approved threshold blocks
- **WHEN** a computed metric falls below its approved threshold and no
  documented exception covers it
- **THEN** the verdict is not-accepted naming the metric, value, and
  threshold

### Requirement: Documented cost and privacy review
The change SHALL produce dated cost and privacy review documents for the
selected provider: the subscription cost position (Q8) and the PRD §15.7
privacy boundary (retention, training use, telemetry) for X OAuth Grok
access, built from current official sources with each source dated and
web-derived statements labelled until confirmed authoritative. Each review
SHALL carry an operator sign-off line. The scorer SHALL verify the reviews
exist, are dated, and are signed off — an unsigned review blocks acceptance.

#### Scenario: Unsigned privacy review blocks
- **WHEN** the scorer runs and the privacy review lacks the operator
  sign-off
- **THEN** the verdict is not-accepted naming the missing sign-off

#### Scenario: Unconfirmed provider claims stay labelled
- **WHEN** a retention or training-use statement cannot be confirmed from an
  authoritative source
- **THEN** the review records it as unconfirmed rather than asserting it

### Requirement: Model replaceability evidence
The verification SHALL evidence that the model is replaceable through
configuration alone: the model selection lives in the Hermes configuration,
and no Atlas repo code hard-codes the model identity. The validated model id
and validation date SHALL be pinned in the report so a future model change
visibly invalidates the validation.

#### Scenario: Config-only selection evidenced
- **WHEN** the scorer runs
- **THEN** the report cites the configuration keys holding the model
  selection and confirms no Atlas repo code references the model id

#### Scenario: Model change invalidates validation
- **WHEN** the configured model id differs from the one pinned in an
  acceptance report
- **THEN** that report is evidence for the old model only, and a new
  validation run is required for acceptance claims

### Requirement: Retrieval benchmark deferral is recorded
The Bittensor retrieval benchmark criterion of ATLAS-HERMES-003 SHALL be
explicitly deferred — not dropped: the deferral, its reason (retrieval does
not exist before Phase 2), and its new home as a Phase 2 acceptance gate
SHALL be recorded in the decision log as part of this change's acceptance.
The verification report SHALL name the deferral so the verdict cannot be
mistaken for full ATLAS-HERMES-003 closure.

#### Scenario: Deferral visible in the report
- **WHEN** an acceptance verdict is issued
- **THEN** the report states that the retrieval benchmark criterion is
  deferred to Phase 2 by recorded decision

### Requirement: Read-only verification and fail-closed verdict
The scorer SHALL NOT modify device state: the session store is opened
read-only, no Hermes configuration or content is written, and the only
writes are schema-validated 0600 reports in gitignored `var/modelval/`.
Privilege is never escalated; unreadable evidence reports its explicit
status. The scorer SHALL emit a single fail-closed verdict: acceptance only
when every scored metric meets its approved threshold (or carries a
documented exception reproduced in the report), every required attestation
and classification is present, and the cost/privacy reviews are signed off.
Anything else blocks, by name, with exit codes matching the repo's verifiers
(0 accepted, 3 not-accepted, 4 no verdict on missing/invalid inputs,
1 fatal).

#### Scenario: No mutation during scoring
- **WHEN** the scorer completes a run
- **THEN** no Hermes configuration, memory, or session content has changed
- **AND** the only new files are its 0600 reports in `var/modelval/`

#### Scenario: One blocker prevents acceptance
- **WHEN** all metrics pass except one unresolved item (metric, attestation,
  sign-off, or unknown)
- **THEN** the verdict is not-accepted and names that item

