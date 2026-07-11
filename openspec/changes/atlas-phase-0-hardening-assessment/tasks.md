# Tasks: atlas-phase-0-hardening-assessment

## 1. Module scaffolding and shared-API pinning

- [x] 1.1 Create `hardening/` layout (assessor entry point, `schema/`, `tests/fixtures/`, docs) with a README stating the read-only guarantee and its relationship to the inventory tool; add an import-surface test pinning the reused inventory API (`Probe`, `run_probe`, `redact`, `schema_validate`, envelope constants)
- [x] 1.2 Define assessment JSON schema v1 (embedded source of truth + generated `schema/hardening-assessment.v1.schema.json` + sync test): run metadata, consumed inventory report reference (run id, path, age), fixed 11-area array with verdict enum `ok | finding | decision-required | not-applicable-yet`, evidence references, and remediation blocks for findings

## 2. Evidence layer

- [x] 2.1 Implement inventory-report loading: locate newest `var/inventory/report-*.json` (or `--inventory-report` path), validate against the inventory schema, reject invalid input fatally, record run id and age with staleness warning
- [x] 2.2 Implement the supplementary read-only probe set reusing inventory machinery: time sync (`timedatectl show`), unattended-upgrades config reads, `/var/log` permission stats, sshd service restart-policy read; document each probe's read-only justification in the probe review doc
- [x] 2.3 Tests: invalid/valid report handling, staleness warning, supplementary probe status mapping with fake executors

## 3. Area evaluators (one per ATLAS-ENV-003 area)

- [x] 3.1 Implement the fixed 11-area table and evaluators: unprivileged service execution, SSH auth + exposed ports, firewall rules, unattended updates, secret file permissions, log permissions, backup encryption/destination (`decision-required` until PRD Q10 resolved), service restart policy, time synchronization, disk space thresholds, remote frontend exposure (`not-applicable-yet`)
- [x] 3.2 Encode per-area baseline expectations (SSH key-only/no-root/X11-off; default-deny firewall with SSH allowed; unattended security updates on; NTP active; 0600-class secret files; sane log perms) as data reviewable in one place
- [x] 3.3 Tests per evaluator against fixture reports: the real Pi baseline (password auth default, no firewall, rpcbind exposed) produces the expected `finding` verdicts with evidence; a hardened fixture produces `ok`; missing evidence produces incomplete verdicts, never assumptions

## 4. Outputs

- [x] 4.1 Emit assessment JSON (validated pre-write, 0600, gitignored `var/hardening/` default) and per-run audit record; exit codes 0 complete / 3 incomplete-evidence / 1 fatal
- [x] 4.2 Implement the Markdown hardening plan renderer: per finding — proposed change, why + evidence reference, exact would-run commands/edits, impact, rollback, `- [ ] approved` checkbox; header states nothing was executed and application requires a separate approved change
- [x] 4.3 Tests: schema validation of emitted JSON, plan rendering from the Pi-baseline fixture (contains firewall + SSH items, all unchecked), redaction of planted secrets in outputs, audit on failed runs

## 5. Integration verification and acceptance evidence

- [x] 5.1 WSL integration run: assessor consumes a real inventory report generated in WSL, exits 0/3, JSON validates, all 11 areas present, before/after state snapshot confirms read-only
- [x] 5.2 Probe review pass for the supplementary probes (extend the review doc pattern from the inventory change)
- [x] 5.3 Document the Pi acceptance procedure: git pull, run assessor against the latest inventory report, operator reviews the plan, ticks/strikes approval boxes, resolves `decision-required` items in docs/decisions.md — approved plan becomes the input for the follow-up apply-hardening change
