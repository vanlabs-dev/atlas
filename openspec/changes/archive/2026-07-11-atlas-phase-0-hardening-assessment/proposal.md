# Proposal: atlas-phase-0-hardening-assessment

Governing document: [prd.md](../../../prd.md) (ATLAS-ENV-003). Consumes the clean-baseline inventory produced by the archived `atlas-phase-0-device-inventory` change and the operator decisions in [docs/decisions.md](../../../docs/decisions.md).

## Why

ATLAS-ENV-003 requires the project to *assess, not assume* the Pi's hardening state, and permits proposing hardening changes only after the current state is observed. That state is now observed: the first inventory run (`20260711T062206Z-5be02d8f`, Pi 5, fresh Debian 13) already surfaced concrete gaps — no firewall tooling installed, SSH password authentication at its default (enabled), X11 forwarding on, rpcbind exposed on 0.0.0.0:111. Before Hermes and any Atlas service lands on this device (Phase 1), the operator needs a complete, evidence-backed hardening assessment and a concrete proposed hardening plan to approve or amend.

## What Changes

- Add a read-only hardening assessor that evaluates every ATLAS-ENV-003 assessment area: unprivileged service execution; SSH authentication and exposed ports; firewall rules; unattended security updates or documented update process; secret file permissions; log permissions; backup encryption and destination; service restart policy; time synchronization; disk space thresholds; remote frontend exposure.
- The assessor consumes the latest device-inventory report as its primary evidence and runs a small set of additional read-only probes for facts the inventory does not yet capture (time-sync status, unattended-upgrades configuration, log directory permissions), reusing the inventory tool's probe machinery, status envelope, and redaction filter.
- Each assessment area produces an explicit verdict — `ok`, `finding` (with evidence and a proposed remediation), `decision-required` (operator input needed, e.g. backup destination), or `not-applicable-yet` (e.g. frontend exposure before a frontend exists) — never a silent pass.
- Output is a machine-readable assessment JSON plus a human-reviewable **proposed hardening plan** (Markdown): per finding, the proposed change, why, the exact commands or config edits that *would* be applied, rollback notes, and an approval checkbox. Nothing is applied by this change.
- Explicitly out of scope: applying any hardening change (that is the follow-up change, gated on operator approval of the plan); OS reinstalls; installing packages; modifying sshd, firewall, or any configuration; Hermes installation.

## Capabilities

### New Capabilities

- `hardening-assessment`: Read-only evaluation of the device's security posture against the ATLAS-ENV-003 area list, grounded in inventory-report evidence plus minimal supplementary read-only probes, producing per-area verdicts with evidence and a proposed (not applied) hardening plan for operator approval.

### Modified Capabilities

None. (`device-inventory` is consumed as-is via its versioned report schema; no requirement changes.)

## Impact

- **Code**: new `hardening/` module reusing `inventory/atlas_inventory.py` internals (probe execution, envelopes, redaction, schema-validation helper) as a library — transfer is via git, so the single-file constraint no longer forces duplication. Tests off-device with fixture reports; integration run in WSL.
- **Device**: zero state change; assessment is read-only. Runs unprivileged; areas needing privilege report `permission-denied` evidence rather than escalating.
- **Decisions consumed**: PRD §21 Q3–Q5 (resolved). **Decisions surfaced, not made**: backup destination (Q10), remote access scope (Q6), disk thresholds — these appear as `decision-required` verdicts and block the *follow-up apply change*, not this assessment.
- **Downstream**: the approved plan becomes the input spec for the follow-up `atlas-phase-1-apply-hardening` change; the assessment JSON feeds Phase 6 health reporting later.
