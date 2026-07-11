# hermes-baseline Specification

## Purpose
TBD - created by archiving change atlas-phase-1-hermes-baseline. Update Purpose after archive.
## Requirements
### Requirement: Install record contract
The operator SHALL record the manual Hermes installation in a machine-readable install
record on the device (in gitignored `var/hermes/`) containing: install source/method,
installed version or commit, installation date, update method, rollback method, service
user, data directory, and configuration path (ATLAS-HERMES-001). The verifier SHALL
consume this record as its primary input and MUST fail closed — no baseline verdict —
when the record is missing or any required field is absent.

#### Scenario: Complete record accepted as input
- **WHEN** the verifier runs and the install record contains all eight required fields
- **THEN** the record's contents appear in the verification report
- **AND** path-dependent checks (config, data dir, service user) use the recorded values

#### Scenario: Missing record fails closed
- **WHEN** the install record is absent or lacks a required field
- **THEN** the verifier reports which fields are missing and issues no acceptance verdict

### Requirement: Read-only verification
The verifier SHALL NOT modify device state: no service starts/stops/restarts, no
configuration writes, no package operations, and no Hermes invocations that create
memories, sessions, or configuration. Its only writes SHALL be report files created
`0600` in gitignored `var/hermes/`. Checks that would require privilege the verifier
does not have SHALL report `permission-denied` rather than escalate; checks that do not
apply to the installed Hermes version SHALL report `unsupported-on-device`.

#### Scenario: Unreadable file reported, not escalated
- **WHEN** a check needs a file the invoking user cannot read
- **THEN** that check reports `permission-denied` with the path
- **AND** the verifier neither prompts for nor uses sudo

#### Scenario: No mutation during verification
- **WHEN** the verifier completes a full run
- **THEN** no service state, configuration file, or Hermes data has changed on the device

### Requirement: Unprivileged execution check
The verifier SHALL confirm the Hermes service runs as the unprivileged account named in
the install record: the account is not root, and holds no general sudo rights
(sudo-capable group membership and matching sudoers grants are checked where readable)
per ATLAS-HERMES-002. If Hermes runs as a different account than recorded, the check
SHALL report a finding.

#### Scenario: Dedicated user verified
- **WHEN** the service runs as the recorded unprivileged account with no sudo grants found
- **THEN** the unprivileged-execution check reports `ok` with the evidence collected

#### Scenario: Root execution is a finding
- **WHEN** the Hermes process or service unit runs as root
- **THEN** the check reports a finding and the overall baseline cannot be accepted

### Requirement: Telemetry disabled check
The verifier SHALL confirm from the Hermes configuration that telemetry (usage
analytics and crash reporting) is disabled, per the Q11 decision of 2026-07-11. A
configuration whose telemetry state cannot be determined SHALL be reported as an
explicit unknown, not assumed disabled.

#### Scenario: Telemetry off verified
- **WHEN** the Hermes configuration explicitly disables telemetry
- **THEN** the telemetry check reports `ok` citing the config location

#### Scenario: Indeterminate telemetry fails closed
- **WHEN** no telemetry setting is found in the configuration
- **THEN** the check reports the state as unknown with remediation guidance

### Requirement: Diagnostics and service persistence evidence
The verifier SHALL run (or evaluate the recorded output of) the official Hermes
diagnostics in a read-only manner and report pass/fail per item; failures are findings
unless a documented exception exists. It SHALL also verify the service is enabled to
start at boot and currently active, and SHALL collect evidence that Hermes survived a
restart performed by the operator (e.g. service start time later than install time with
active state) — the verifier itself never restarts anything (ATLAS-HERMES-005).

#### Scenario: Diagnostics failure is a finding
- **WHEN** an official diagnostic item fails and no documented exception covers it
- **THEN** the report contains a finding naming the failed item

#### Scenario: Restart evidence collected without restarting
- **WHEN** the operator has restarted Hermes after install and the service is active
- **THEN** the verifier records the evidence (enablement, active state, start time)
- **AND** issues no restart of its own

### Requirement: Secret-free log check
The verifier SHALL scan readable Hermes logs for credential-shaped material (tokens,
keys, passwords, OAuth artifacts) and report matches as findings with **redacted**
excerpts — never the secret itself, in the report or in verifier output. Unreadable log
locations SHALL be reported `permission-denied` (ATLAS-HERMES-005, repo no-secrets rule).

#### Scenario: Leaked token found and redacted
- **WHEN** a log line contains a credential-shaped string
- **THEN** the report contains a finding with file, line reference, and a redacted excerpt
- **AND** the secret value appears nowhere in the report or terminal output

### Requirement: Operator attestation of interactive checks
Interactive ATLAS-HERMES-005 checks — basic chat succeeds, a memory write and
cross-session search behave as required, and the local Atlas test tool is discovered
and called from a Hermes conversation — SHALL be performed by the operator and supplied
to the verifier as explicit attestations. The verifier SHALL record each attestation
(check, attesting operator, timestamp) in the report and MUST NOT mark an unattested
interactive check as passed.

#### Scenario: Attested checks recorded
- **WHEN** the operator supplies attestations for chat, memory/session search, and tool call
- **THEN** the report lists each as attested with operator and timestamp

#### Scenario: Missing attestation blocks acceptance
- **WHEN** no attestation is supplied for the tool-call check
- **THEN** that check reports not-attested and the baseline verdict is not acceptance

### Requirement: Minimal Atlas test tool
The change SHALL provide a minimal local Atlas test tool (stdio MCP server) exposing a
single read-only operation returning static identification data (name, version,
timestamp). It MUST NOT read device data, access the network, or accept parameters that
influence device state. Its sole purpose is proving Hermes can discover and call a
local Atlas tool; it SHALL be replaced — not extended — by the production tool
interface phase (ATLAS-TOOL-001 minimization).

#### Scenario: Ping returns static identity
- **WHEN** the test tool's operation is invoked
- **THEN** it returns only its static identification payload

#### Scenario: No data access surface
- **WHEN** the test tool code is reviewed
- **THEN** it contains no filesystem reads outside itself, no network use, and no shell execution

### Requirement: Fail-closed acceptance verdict
The verifier SHALL emit a single overall verdict. Acceptance SHALL be reported only
when every automated check is `ok` (or covered by a documented exception recorded in
the report) and every interactive check is attested. Any finding, missing attestation,
or unresolved unknown (`permission-denied`, `unsupported-on-device`, indeterminate
state) SHALL result in a non-accepted verdict that names each blocking item. The
verdict and evidence SHALL be suitable for recording in the decision log.

#### Scenario: One unknown blocks acceptance
- **WHEN** all checks pass except one reporting `permission-denied`
- **THEN** the verdict is not-accepted and lists the unresolved check as the blocker

#### Scenario: Clean run accepted
- **WHEN** all automated checks report `ok` and all attestations are present
- **THEN** the verdict is accepted and the report summarizes the evidence for the decision log

