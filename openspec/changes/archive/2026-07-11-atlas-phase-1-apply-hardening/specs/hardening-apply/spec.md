# hardening-apply Specification

Delta spec for change `atlas-phase-1-apply-hardening`. First device-mutating capability; governed by ATLAS-ENV-003 (apply only what was observed and approved) and ATLAS-SEC-*.

## ADDED Requirements

### Requirement: Approved scope only
The apply capability SHALL implement exactly the items carrying an operator approval record in the referenced hardening plan, and MUST NOT apply, bundle, or improvise any change outside that approved set. Each apply script SHALL name the plan run id and item it implements.

#### Scenario: Unapproved item cannot ride along
- **WHEN** the approved plan contains 6 items
- **THEN** exactly 6 apply scripts exist, each traceable to its plan item
- **AND** no script performs changes beyond its named item

### Requirement: One item at a time with per-item verification
Items SHALL be applied individually in the documented safe order. Each item SHALL provide `check` (read-only current-state report), `apply`, `verify` (read-only confirmation of the intended end state), and `rollback` operations. A failed `apply` or `verify` SHALL stop the sequence; the next item MUST NOT start until the current item verifies.

#### Scenario: Verification gates progression
- **WHEN** an item's `verify` fails after `apply`
- **THEN** the sequence stops with the failure reported
- **AND** the item's rollback guidance is presented before anything else runs

#### Scenario: Idempotent re-run
- **WHEN** `apply` runs for an item already in the desired state
- **THEN** it reports already-compliant and changes nothing

### Requirement: SSH lockout prevention protocol
For items that can sever SSH access (firewall enablement, password-authentication disable), the process SHALL: keep the existing SSH session open throughout; syntax-check firewall rules before loading (`nft -c`); load firewall rules non-persistently and verify a NEW SSH connection succeeds before persisting; and disable password authentication only after key-only access has been re-verified in a fresh session. Password authentication SHALL be the final item applied.

#### Scenario: Firewall staged before persisted
- **WHEN** the nftables item applies
- **THEN** the ruleset is syntax-checked, then loaded without enabling the service
- **AND** only after a new SSH connection succeeds is the ruleset persisted and the service enabled

#### Scenario: Password auth disabled last
- **WHEN** the password-authentication item is attempted before all other approved items verified
- **THEN** the documented order forbids it and the runbook stops

### Requirement: No credential handling
Apply scripts MUST NOT embed, prompt for, store, or log any password or secret. Privilege SHALL come from the operator's own sudo context; automation MAY drive the scripts only when passwordless sudo is already available (`sudo -n`), and MUST otherwise hand execution to the operator.

#### Scenario: Sudo requires a password
- **WHEN** `sudo -n true` fails on the device
- **THEN** automated execution declines and instructs the operator to run the item themselves
- **AND** no password prompt is ever answered by automation

### Requirement: Audit trail of every action
Every `check`, `apply`, `verify`, and `rollback` invocation SHALL append a structured record (timestamp, item, action, outcome, detail) to a persistent audit log on the device. Failed actions SHALL be recorded as faithfully as successful ones (ATLAS-SEC-008).

#### Scenario: Failed apply is audited
- **WHEN** an `apply` step fails midway
- **THEN** the audit log contains the failure record with the error detail

### Requirement: Closed-loop acceptance via re-assessment
After all approved items are applied, the existing hardening assessor SHALL be re-run. The change is accepted only when the previously-`finding` areas covered by approved items report `ok`, and no previously-`ok` area regressed.

#### Scenario: Re-assessment confirms the fix
- **WHEN** all 6 items are applied and verified
- **THEN** a fresh assessment reports `ok` for ssh-authentication-and-exposed-ports, firewall-rules, and unattended-security-updates
- **AND** secret-file-permissions, log-permissions, service-restart-policy, and time-synchronization remain `ok`

### Requirement: Per-item rollback
Each item SHALL have a tested-by-review rollback procedure restoring the pre-apply state, executable independently of other items. Rollbacks SHALL be audited like applies.

#### Scenario: Single item reverted
- **WHEN** the operator rolls back one item (for example re-enabling avahi)
- **THEN** only that item's state reverts and the audit log records the rollback
