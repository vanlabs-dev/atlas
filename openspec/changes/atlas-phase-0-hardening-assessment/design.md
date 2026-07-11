# Design: atlas-phase-0-hardening-assessment

## Context

The device-inventory capability (archived change, main spec at `openspec/specs/device-inventory/spec.md`) is live: the Pi 5 runs fresh Debian 13, and inventory run `20260711T062206Z-5be02d8f` is the clean baseline. Known observations already queued in [docs/decisions.md](../../../docs/decisions.md): no firewall tooling, SSH `PasswordAuthentication` at default (enabled), `X11Forwarding yes`, rpcbind on 0.0.0.0:111, avahi active. The operator plans SSH credential rotation and key-only auth. Transfer to the Pi is `git pull`; code no longer needs to be single-file (inventory's D1a fallback stands, but this change may import from it).

## Goals / Non-Goals

**Goals:**

- One read-only assessor covering all 11 ATLAS-ENV-003 areas with explicit verdicts.
- Reuse of the inventory module's probe machinery, redaction, envelopes, and schema validator — no second implementation of any of those.
- A hardening plan the operator can approve line-by-line, detailed enough that the follow-up apply-change needs no re-analysis.
- Fixture-tested off-device; one integration run in WSL; acceptance run on the Pi by the operator.

**Non-Goals:**

- Applying any hardening (follow-up change `atlas-phase-1-apply-hardening`, gated on plan approval).
- Resolving operator decisions (backup target, remote-access scope, disk thresholds) — these surface as `decision-required`.
- Continuous monitoring or scheduled re-assessment (Phase 6 territory).
- CIS-benchmark-style exhaustive auditing — scope is exactly the ATLAS-ENV-003 list, proportionate to a single-user device.

## Decisions

### D1: Import the inventory module as a library, don't fork it

`hardening/atlas_hardening.py` imports `Probe`, `run_probe`, `redact`, `schema_validate`, and the envelope constants from `inventory/atlas_inventory.py` (path-based import; both live in the same git checkout on every machine that matters). Rationale: the inventory file is the reviewed, tested implementation of "read-only probe with explicit status"; duplicating it would fork the redaction filter — exactly the drift the single-choke-point design (inventory D4) exists to prevent. Alternative considered: extending the inventory's probe table and schema to v2 — rejected because assessment items are not inventory facts (they're judgements over facts), and mixing them would blur the inventory's "observation only" contract.

### D2: Inventory report is the primary evidence; supplementary probes are minimal

The assessor takes `--inventory-report <path>` (default: newest `report-*.json` in `var/inventory/`), validates it against the embedded inventory schema, and draws evidence from it for: SSH config and ports, firewall tooling, secret file permissions, filesystem usage, packages, services. Supplementary probes only for facts the inventory lacks: `timedatectl show` (time sync), unattended-upgrades config (read `/etc/apt/apt.conf.d/20auto-upgrades` and `50unattended-upgrades`), `/var/log` permission stat, and `systemctl show sshd -p Restart`-style restart-policy reads. Rationale: one source of truth per fact; if a fact is generally useful it should graduate into the inventory probe table (schema v2) rather than live only here.

### D3: Verdict model is a fixed 11-row table, one row per ATLAS-ENV-003 area

Areas are enumerated in code as a fixed tuple (mirroring the inventory's fixed 16 categories) so omission is structurally impossible. Each evaluator is a pure function `(inventory_report, probe_results) -> Verdict` returning `ok | finding | decision-required | not-applicable-yet` with evidence references and, for findings, a remediation proposal. No composite score — PRD §11.1 rejects false-precision scoring, and a single number would hide exactly the per-area accountability ATLAS-ENV-003 wants.

### D4: Plan format is operator-first Markdown backed by JSON

JSON output (versioned schema v1, embedded + generated file, same pattern as inventory) is the machine contract; the Markdown plan renders findings as approval-ready items: proposed change, why (with evidence), exact commands/edits *that would run*, impact, rollback, `- [ ] approved` checkbox. Baseline expectations encoded per area (e.g. SSH: key-only auth, no root login, X11 off; firewall: default-deny inbound with SSH allowed; updates: unattended security updates on; time: NTP active). These expectations are the assessor's opinion — the operator approves or strikes each item; nothing is authoritative until approved.

### D5: Same operational envelope as the inventory

Unprivileged by default, never self-elevates, outputs 0600 into gitignored `var/hardening/`, per-run audit record, fail-visible (invalid inventory input → exit 1 with no verdicts; partial probe evidence → verdicts that say so). Exit codes: 0 = assessment complete (regardless of findings — findings are the product, not an error), 3 = assessment incomplete (some areas lacked evidence), 1 = fatal.

## Risks / Trade-offs

- [Baseline expectations could be wrong for this operator's context (e.g. they may want password auth kept)] → Expectations produce *proposals*, not actions; every item is individually approvable, and `decision-required` exists for genuinely operator-owned choices.
- [Evidence drawn from a stale inventory report] → The assessor records the consumed report's run id and age, warns when it exceeds a configurable age, and the operator can rerun the inventory first.
- [Library import couples the two tools; a refactor of the inventory file could break the assessor] → Both live in one repo with one test suite; a small import-surface test pins the shared API (`Probe`, `run_probe`, `redact`, `schema_validate`).
- [Unprivileged run can't read some evidence (e.g. `/etc/ssh/sshd_config` is world-readable on Debian, but some areas may deny)] → Denied evidence yields incomplete verdicts and exit 3, mirroring the inventory's explicit-unknowns rule; the operator can choose a privileged re-run.

## Migration Plan

Nothing to migrate; new module in the existing repo. Rollback = delete `hardening/`. The follow-up apply-change is where device state changes and where rollback planning matters.

## Open Questions

- Backup destination (PRD §21 Q10) and remote-access scope (Q6) — surfaced by the assessment as `decision-required`; must be answered before the *apply* change, not before this one.
- Disk usage thresholds (ATLAS-BACKUP-005) — the assessment proposes candidate thresholds from the observed 3%-used baseline; operator confirms.
- Whether rpcbind/avahi should be disabled — proposed as findings; operator decides (they may want mDNS for LAN discovery).
