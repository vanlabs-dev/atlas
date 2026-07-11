# Proposal: atlas-phase-1-memory-and-session-recall

Governing documents: [prd.md](../../../prd.md) (§12.3, ATLAS-MEM-001…006; §16 Phase 1
exit criteria) and [docs/decisions.md](../../../docs/decisions.md): the Hermes baseline
acceptance of 2026-07-11 (Hermes v0.18.2 as user `pi`, Grok via X OAuth, MCP test tool
working) and the standing note that ATLAS-MEM behavior is the README's stated next step.

## Why

The Hermes baseline attested — once — that a memory write and a cross-session search
worked. That is compatibility evidence, not verification: two Phase 1 exit criteria
("personal memory proposal/approval works", "session recall test passes") and the
whole ATLAS-MEM requirement set (approval gating, correction handling, duplicate
prevention, secret rejection, personal/domain separation) currently rest on a single
unstructured attestation. PRD §5.5 forbids leaving that as assumption, and PRD §21
Q19 (keep memory writes approval-gated, or relax later?) cannot be answered without
the ATLAS-MEM-006 evaluation evidence this change produces.

## What Changes

- **A read-only memory/recall verifier** (`hermes/memory/atlas_memory_verify.py`,
  reusing the inventory probe/redaction/schema machinery like the baseline verifier):
  runs on the Pi, writes redacted 0600 reports into gitignored `var/memory/`, fails
  closed with explicit unknowns. Automated read-only checks:
  - **approval gating configured** — the Hermes configuration requires approval for
    memory (and skill) writes (ATLAS-MEM-003); an absent or unrecognized setting is a
    blocker, not a pass;
  - **memory hygiene scan** — Hermes memory files (`MEMORY.md`, `USER.md`) exist, stay
    bounded, contain no credential-shaped material (ATLAS-MEM-005) and no bulk
    Bittensor/domain content (ATLAS-MEM-001), and do not contain the procedure's
    synthetic canary secret after the rejection test;
  - **session store present and searchable** — the Hermes session SQLite store exists
    and its full-text search surface is present (ATLAS-MEM-002), opened strictly
    read-only.
- **A scripted operator procedure** (`hermes/memory/docs/procedure.md`) implementing
  the ATLAS-MEM-006 evaluation set as concrete, repeatable steps with exact prompts,
  synthetic canary values, and expected outcomes: preference retention, correction
  replacement (ATLAS-MEM-004), stale-memory removal, duplicate prevention,
  prior-session lookup, secret rejection, personal/domain separation.
- **Operator attestations for the interactive behaviors.** Only a real Hermes session
  can show the approval prompt, the correction flow, or a successful prior-session
  lookup. As in the baseline, the operator performs the procedure and passes
  `--attest` per check; the report records who attested what, when. Unattested
  interactive checks block acceptance.
- Explicitly out of scope: enabling automatic (unreviewed) memory writes — Q19 stays
  an operator decision informed by this evidence; any Hermes configuration change
  (if approval gating is off, the operator fixes it manually and re-runs); the
  Bittensor knowledge corpus and retrieval (Phase 2); ATLAS-HERMES-003 model
  validation; Telegram; any device mutation.

## Capabilities

### New Capabilities

- `memory-session-recall`: Verification that Hermes personal memory and session
  recall meet ATLAS-MEM-001…006 — approval-gated writes, correction without
  contradiction, secret rejection, personal/domain separation, cross-session
  recall — via automated read-only checks plus a scripted, attested operator
  procedure producing acceptance evidence.

### Modified Capabilities

None. (`hermes-baseline` is a precondition and stays as accepted; its verifier and
test tool are unchanged.)

## Impact

- **Device**: no mutation. The verifier only reads Hermes config, memory files, the
  session store (read-only mode), and logs; the only writes are reports into
  gitignored `var/memory/` (0600). The interactive procedure exercises Hermes
  conversationally, which necessarily writes memories/sessions — driven by the
  operator, not by repo code.
- **Repo**: new `hermes/memory/` directory (verifier, procedure doc, tests) nested
  under the existing Hermes verification area, mirroring `hardening/apply/` nesting.
- **Privilege**: none required. Everything runs as the Hermes user (`pi`); anything
  unreadable is reported `permission-denied`, never escalated.
- **Testing**: off-device (WSL) with fixture configs, memory files, and a fixture
  SQLite session store, per repo convention. The Pi run after the operator's
  procedure is the acceptance run.
- **Downstream**: produces the ATLAS-MEM-006 evidence PRD §21 Q19 needs, closes the
  remaining Phase 1 memory exit criteria, and clears the path to ATLAS-HERMES-003
  validation and Phase 2 corpus work.
