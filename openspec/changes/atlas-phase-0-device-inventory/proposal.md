# Proposal: atlas-phase-0-device-inventory

Governing document: [prd.md](../../../prd.md) (Atlas PRD v0.1.0, 2026-07-11). This change implements the Phase 0 device inventory capability only (PRD §12.1, ATLAS-ENV-001). It does not install, remove, or modify any software.

## Why

Atlas will be deployed on an existing Raspberry Pi whose current state (installed software, services, prior Hermes installs, repositories, secrets locations, storage headroom) is unknown. The PRD forbids changing the device before its state is observed (§5.5 no hidden assumptions, ATLAS-ENV-003 "assess, not assume"). A trustworthy, read-only, redacted inventory is the entry gate for every later phase: the removal plan (ATLAS-ENV-002), hardening assessment (ATLAS-ENV-003), and Hermes installation (Phase 1) all depend on it.

## What Changes

- Add a read-only device inventory script that collects the ATLAS-ENV-001 item list: hardware model/architecture; CPU, RAM, NVMe capacity, partitions, filesystem usage; OS and kernel versions; users and service accounts; Atlas-relevant installed packages; containers and images; systemd services; listening ports; scheduled jobs and timers; existing Hermes files/version; existing repositories and application directories; environment/secret file locations (paths only, never values); backup configuration; firewall status; remote access configuration; temperature and NVMe health where supported.
- Define a versioned, machine-readable output schema for the inventory report, with per-item support status (`collected`, `unsupported-on-device`, `permission-denied`, `error`) so unknowns stay explicit rather than silently absent.
- Enforce redaction requirements: secret values, API keys, tokens, key material, and sensitive environment values never appear in the report or in script output (ATLAS-SEC-007 applied to inventory output).
- Produce a human-reviewable classification worksheet listing every discovered item with a proposed disposition of `preserve`, `migrate`, `remove`, or `decision required` — proposals only; nothing is deleted, stopped, or modified (ATLAS-ENV-001 scenario).
- Record an audit trail of each inventory run (when it ran, what it collected, what failed).
- Explicitly out of scope: any destructive or mutating action; the removal process itself (ATLAS-ENV-002, separate change); the hardening change proposal (ATLAS-ENV-003 assessment consumes this inventory but is a separate change); Hermes installation; all later phases.

## Capabilities

### New Capabilities

- `device-inventory`: Read-only collection of the Raspberry Pi's hardware, OS, software, service, network, storage, and health state into a versioned, redacted, machine-readable report with explicit per-item collection status, plus a preserve/migrate/remove/decision-required classification worksheet for user review. No mutation of device state.

### Modified Capabilities

None — this is the first change in the project; no existing specs.

## Impact

- **Code**: New inventory script (target host is Linux aarch64; script must be runnable on the Pi with standard tooling). New output schema definition and classification worksheet template. Tests runnable off-device with fixtures.
- **Device**: Zero state change. The script performs reads only; commands with side effects are prohibited by spec.
- **Dependencies**: Prefer stock OS tooling already present on the Pi; any additional dependency must be recorded and justified (ATLAS-SEC-005). Exact OS/tooling availability is unknown until first run — the schema's per-item status states absorb this.
- **Decisions preserved, not resolved**: PRD §21 questions 1–11 (Pi model, OS, what to preserve, reinstall vs cleanup, access method, exposure, LLM provider, budget, privacy boundary, backup target, telemetry) remain open. The inventory informs them; it does not answer them.
- **Downstream**: Output contract feeds the future removal-plan and hardening-assessment changes; the report format should therefore be stable and versioned.
