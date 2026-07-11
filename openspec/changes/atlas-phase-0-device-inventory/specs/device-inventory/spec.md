# device-inventory Specification

Delta spec for change `atlas-phase-0-device-inventory`. Implements PRD requirement ATLAS-ENV-001 and its scenario, plus the redaction obligations of ATLAS-SEC-007 as they apply to inventory output.

## ADDED Requirements

### Requirement: Read-only operation
The inventory process SHALL perform only read operations against the device. It MUST NOT install, remove, upgrade, stop, start, restart, enable, disable, reconfigure, or delete any package, container, service, file, user, firewall rule, scheduled job, or repository. Commands invoked by the inventory script MUST be individually reviewable and MUST NOT include mutating flags or subcommands.

#### Scenario: No state change after a full run
- **WHEN** a full inventory run completes on the device
- **THEN** installed packages, containers, services, users, scheduled jobs, firewall rules, and application files are byte-for-byte unchanged
- **AND** the only new files created are the inventory report, classification worksheet, and audit record in the designated output directory

#### Scenario: Collection failure does not trigger remediation
- **WHEN** any collection command fails or a data source is missing
- **THEN** the inventory records the failure for that item and continues
- **AND** it does not attempt to install tooling, change permissions, or otherwise modify the device to make collection succeed

### Requirement: Inventory coverage
A full inventory run SHALL attempt to collect every item listed in ATLAS-ENV-001: hardware model and architecture; CPU, RAM, NVMe capacity, partitions, and filesystem usage; operating system and kernel versions; configured users and service accounts; installed packages relevant to Atlas; containers and images; systemd services; listening ports; scheduled jobs and timers; existing Hermes files and version, if present; existing repositories and application directories; environment files and secret locations without printing secret values; backup configuration; firewall status; remote access configuration; and temperature and NVMe health where supported.

#### Scenario: All categories present in report
- **WHEN** a full inventory run completes
- **THEN** the report contains one section per ATLAS-ENV-001 item category
- **AND** no category is silently omitted, even when collection failed or the item does not apply to the device

#### Scenario: Existing Hermes installation is detected
- **WHEN** the device contains Hermes files from a prior installation
- **THEN** the report records their location and the installed version where determinable
- **AND** the files are left untouched

### Requirement: Explicit per-item collection status
Every inventory item SHALL carry an explicit collection status of `collected`, `unsupported-on-device`, `permission-denied`, or `error`. An item that could not be collected MUST NOT be reported as absent, empty, or healthy; unknown values SHALL remain visibly unknown.

#### Scenario: Sensor not supported on device
- **WHEN** the device does not expose a temperature or NVMe health interface
- **THEN** the corresponding item is reported with status `unsupported-on-device`
- **AND** no fabricated or default value is emitted

#### Scenario: Insufficient permissions
- **WHEN** a collection command requires privileges the executing account lacks
- **THEN** the item is reported with status `permission-denied` and the command that failed is named
- **AND** the run continues with the remaining items and exits with a status distinguishing partial from complete collection

### Requirement: Versioned machine-readable output schema
The inventory report SHALL be emitted in a machine-readable format conforming to a versioned schema stored in the repository. The report SHALL record the schema version, script version, collection start and finish times, executing account, and device identifier. Schema changes SHALL increment the version.

#### Scenario: Report validates against the schema
- **WHEN** an inventory run produces a report
- **THEN** the report validates against the schema version it declares

#### Scenario: Downstream consumer reads a report
- **WHEN** a later Atlas change (removal planning or hardening assessment) parses a stored report
- **THEN** the declared schema version identifies the exact structure to parse
- **AND** reports from older schema versions remain identifiable and are not misread

### Requirement: Secret redaction
The inventory SHALL record the paths, ownership, and permissions of environment files and secret locations, and MUST NOT record secret values. Report, worksheet, audit record, logs, and console output MUST NOT contain API keys, tokens, passwords, private keys, seed phrases, authorization headers, or secret environment variable values. The implementation SHALL apply a redaction filter to all captured command output before it is written anywhere.

#### Scenario: Environment file discovered
- **WHEN** the inventory discovers a file matching secret-bearing patterns (for example `.env`, key files, credential stores)
- **THEN** the report lists the file path, owner, and permission bits
- **AND** no line of the file's contents appears in any output

#### Scenario: Secret leaks through command output
- **WHEN** a collection command unexpectedly emits a value matching a secret pattern (for example a token in a process argument list)
- **THEN** the value is replaced with a redaction marker before being written to the report, audit record, or logs

### Requirement: Classification worksheet
After collection, the inventory SHALL produce a human-reviewable worksheet listing each discovered software item, service, container, repository, and application directory with a proposed disposition of `preserve`, `migrate`, `remove`, or `decision required`, together with the evidence for the proposal. The worksheet is a proposal only: producing it MUST NOT delete, stop, or modify anything, and no disposition SHALL be executed by this capability.

#### Scenario: Stale software discovered
- **WHEN** the inventory finds existing Hermes or Bittensor-related software
- **THEN** the worksheet classifies each item as `preserve`, `migrate`, `remove`, or `decision required`
- **AND** nothing is deleted automatically
- **AND** the user receives the worksheet for review before any destructive action is planned

#### Scenario: Ambiguous item
- **WHEN** an item cannot be confidently classified from the collected evidence
- **THEN** it is marked `decision required` with the open question stated
- **AND** it is not defaulted to `remove` or `preserve`

### Requirement: Run audit record
Every inventory run SHALL produce an audit record containing the run identifier, start and finish times, script and schema versions, executing account, per-item collection status summary, and any errors encountered. Audit records SHALL be retained alongside the reports they describe.

#### Scenario: Completed run is auditable
- **WHEN** an inventory run finishes, successfully or not
- **THEN** an audit record exists that states what ran, when, as whom, what was collected, and what failed
- **AND** the record contains no secret values
