# Atlas Hardening Assessment (Phase 0)

Read-only security-posture assessment of the Atlas target device, per PRD
requirement **ATLAS-ENV-003** via OpenSpec change `atlas-phase-0-hardening-assessment`.

## What it does — and does not do

- **Assesses, never assumes**: every verdict is grounded in observed evidence —
  the latest device-inventory report (`var/inventory/report-*.json`) plus a
  handful of supplementary read-only probes.
- **Proposes, never applies**: findings produce a hardening *plan* with the
  exact commands/edits that *would* run, impact, and rollback notes — each item
  behind an unchecked `- [ ] approved` marker. Applying anything is a separate
  OpenSpec change, gated on your approval of the plan.
- Read-only, never self-elevates, all output redacted and written 0600 into
  gitignored `var/hardening/`, per-run audit record. Same operational envelope
  as the inventory tool.

## Relationship to the inventory tool

This module **imports** probe execution, redaction, the status envelope, and
schema validation from [`inventory/atlas_inventory.py`](../inventory/atlas_inventory.py)
— there is exactly one implementation of "read-only probe" and one redaction
filter in this repo. The pinned import surface is verified by
`tests/test_import_surface.py`. Code reaches the Pi via `git pull`, so
multi-file layout is fine (the inventory file itself remains single-file for
its paste fallback).

## The 11 assessment areas (ATLAS-ENV-003)

unprivileged service execution · SSH authentication and exposed ports ·
firewall rules · unattended security updates · secret file permissions ·
log permissions · backup encryption and destination · service restart policy ·
time synchronization · disk space thresholds · remote frontend exposure

Each gets exactly one verdict: `ok`, `finding` (with evidence + proposed
remediation), `decision-required` (names the operator decision), or
`not-applicable-yet` (names the reassessment trigger). No composite score.

## Usage

```sh
# Assess using the newest inventory report in var/inventory/
python3 hardening/atlas_hardening.py assess

# Or point at a specific report / output location
python3 hardening/atlas_hardening.py assess --inventory-report var/inventory/report-<id>.json --output-dir var/hardening

# Print the assessment JSON schema
python3 hardening/atlas_hardening.py dump-schema
```

Exit codes: `0` assessment complete (findings are the product, not an error),
`3` incomplete (some areas lacked evidence — consider a privileged re-run of
the *inventory*), `1` fatal (e.g. invalid inventory report).

## Tests

```sh
python -m unittest discover -s hardening/tests -v
```
