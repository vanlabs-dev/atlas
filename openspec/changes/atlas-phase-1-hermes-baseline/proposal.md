# Proposal: atlas-phase-1-hermes-baseline

Governing documents: [prd.md](../../../prd.md) (§12.2, ATLAS-HERMES-001…005) and the
decisions recorded 2026-07-11 in [docs/decisions.md](../../../docs/decisions.md):
hosted models allowed (Q9), first candidate Grok via X OAuth (Q7), ~$20/mo interactive
latency (Q8), LAN-only (Q6), all telemetry disabled (Q11), and the install-mode
decision that **the operator installs Hermes manually**.

## Why

Phase 0 and the hardening are accepted; the device is ready for Hermes. The operator
will run the install and interactive setup by hand, so the repo's job is not
installation — it is making the result **acceptable**: ATLAS-HERMES-005 defines six
acceptance checks, ATLAS-HERMES-001 requires a recorded install record, and today the
repo has no way to run or evidence any of them. Without this change, "Hermes works"
would rest on assumption, which PRD §5.5 forbids.

## What Changes

- **A read-only post-install verifier** (`hermes/atlas_hermes_verify.py`, matching the
  inventory/assessor conventions): runs on the Pi after the operator's manual install,
  produces a redacted 0600 report in gitignored `var/hermes/`, and fails closed with
  explicit unknowns. It checks, per ATLAS-HERMES-005 and related requirements:
  - install record present and complete (source, version, date, update/rollback
    method, service user, data dir, config path — ATLAS-HERMES-001);
  - Hermes runs as the recorded unprivileged account and holds no general sudo
    (ATLAS-HERMES-002);
  - telemetry disabled in the Hermes configuration (Q11 decision);
  - official diagnostics pass, or exceptions are documented;
  - Hermes logs contain no secrets (redacting scanner, same fail-closed posture as
    the hardening assessor);
  - service is enabled/active and survives restart — **verified as evidence, not
    performed**: the verifier never restarts anything.
- **Operator attestations for the interactive checks.** Basic chat, memory write +
  session search, and tool discovery/call are exercised by the operator in the
  interactive session; the verifier accepts explicit attestation inputs and records
  them (who/what/when) in the report rather than pretending to automate them.
- **A minimal read-only Atlas test tool** (stdio MCP server exposing a single static
  `atlas_ping`), because ATLAS-HERMES-005 requires that "a local Atlas test tool can
  be discovered and called" — impossible to check without one existing. It carries no
  data access; it exists solely to prove the Hermes↔Atlas tool path.
- **An install-record template** the operator fills in during the manual install
  (lives in `var/hermes/`, device-sensitive, never committed); the verifier consumes it.
- Explicitly out of scope: performing the installation, any device mutation, model
  benchmark validation beyond compatibility evidence (full ATLAS-HERMES-003 validation
  is its own later gate), Telegram, memory-policy configuration beyond what the
  operator sets interactively, and any production Atlas tools.

## Capabilities

### New Capabilities

- `hermes-baseline`: Post-install verification of a manually installed Hermes —
  automated read-only checks plus recorded operator attestations covering the
  ATLAS-HERMES-005 acceptance baseline, an install-record contract (ATLAS-HERMES-001),
  and a minimal test tool proving Hermes can discover and call a local Atlas tool.

### Modified Capabilities

None. (`device-inventory` and `hardening-assessment` are unchanged; the hardened
posture is a precondition, not a modification.)

## Impact

- **Device**: no mutation. The verifier and test tool are read-only; the only writes
  are reports into gitignored `var/hermes/` (0600). The operator's manual install is
  the mutating event and happens outside this change.
- **Repo**: new `hermes/` directory (verifier, test tool, tests, docs) alongside the
  existing `inventory/` and `hardening/` layout.
- **Privilege**: none required. Everything runs as the operating user; where a check
  needs unreadable files it reports `permission-denied` rather than escalating.
- **Testing**: off-device (WSL) with fixture configs and fake logs, per repo
  convention. The Pi run after the operator's install is the acceptance run.
- **Downstream**: acceptance here unblocks ATLAS-HERMES-003 model validation and the
  Phase 2 knowledge-base work; the `atlas_ping` test tool is the seed of the later
  production tool interface (ATLAS-TOOL-*), to be replaced, not extended, in that phase.
