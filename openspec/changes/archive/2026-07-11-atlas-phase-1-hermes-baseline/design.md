# Design: atlas-phase-1-hermes-baseline

## Context

The operator installs Hermes manually on the hardened Pi (decision 2026-07-11); this
change ships only read-only acceptance tooling. The repo already has two read-only
tools with a shared implementation core: `inventory/atlas_inventory.py` owns probe
execution, redaction, the status envelope, and schema validation; the hardening
assessor imports that surface rather than duplicating it. A hard constraint is that
**Hermes's concrete on-device shape (config format, telemetry keys, diagnostics
command, service unit) is unknown until the operator's install happens** — the design
must degrade to explicit unknowns rather than guesses (PRD §5.5, repo fail-closed rule).

## Goals / Non-Goals

**Goals:**

- A `hermes/` module matching the established tool layout: verifier script, schema,
  tests, docs, README.
- Machine-checkable ATLAS-HERMES-001/002/005 checks plus recorded operator
  attestations, producing one fail-closed verdict suitable for the decision log.
- A minimal stdio MCP test tool proving the Hermes↔Atlas tool path.

**Non-Goals:**

- Installing, configuring, restarting, or otherwise mutating Hermes or the device.
- ATLAS-HERMES-003 model validation (Grok benchmark/cost/latency) — separate gate.
- Any production Atlas tool, MCP framework, or generic check engine (PRD §5.6).

## Decisions

1. **Layout mirrors `hardening/`**: `hermes/atlas_hermes_verify.py` (verifier),
   `hermes/testtool/atlas_test_tool.py`, `hermes/schema/`, `hermes/tests/`,
   `hermes/docs/`, `hermes/README.md`. The verifier imports probe execution,
   redaction, envelope, and schema validation from `inventory/atlas_inventory.py` —
   one implementation of "read-only probe" stays true; the import surface is pinned
   by a test as in `hardening/`.

2. **Install record is a JSON file the operator fills in**, from a template at
   `hermes/docs/install-record.template.json`, living at
   `var/hermes/install-record.json` (device-sensitive, gitignored). Eight required
   fields per ATLAS-HERMES-001. Alternative considered: recording it straight into
   `docs/decisions.md` — rejected as primary input because the verifier needs
   machine-readable values (paths, service user) to drive checks; the decision log
   gets the human summary after acceptance.

3. **Attestations are CLI inputs, not a second file**: e.g.
   `--attest chat --attest memory-session-search --attest tool-call`, with the
   attesting operator defaulting to the invoking user and timestamps recorded at run
   time. Rationale: attestations are per-run facts about what the operator just did;
   a persistent attestation file could go stale and imply automation that doesn't
   exist. The report is the durable record.

4. **Checks parameterized by the install record, fail-closed on unknowns.** Config
   and data paths come from the record. The telemetry check searches the recorded
   config for known-shape telemetry settings and reports `unknown` when none is
   found; the diagnostics check runs the diagnostics command **named in the install
   record** (read-only invocation) and reports `unsupported-on-device` if none is
   recorded. Alternative — hardcoding Hermes config keys now — rejected: we would be
   inventing facts about software not yet installed. Expect a small follow-up commit
   after the real install to pin observed key names into the checks and fixtures.

5. **Service checks via systemd, both system and user scope.** The verifier inspects
   unit state (`is-enabled`, `is-active`, `User=`, start timestamp) for the unit
   named in the install record, checking system scope then the service user's user
   scope. Restart survival is evidenced (enabled + active + start time after install
   date), never performed. Sudo-rights check reads group membership and world-readable
   sudoers material; unreadable sudoers content reports `permission-denied`.

6. **Test tool is stdlib-only JSON-RPC over stdio** implementing the minimal MCP
   surface (`initialize`, `tools/list`, `tools/call`) with one tool, `atlas_ping`,
   returning static identity JSON. Alternative — the official `mcp` Python SDK —
   rejected for now: it adds a runtime dependency to the device for ~150 lines of
   stable protocol, and the tool's whole point is to be inert and reviewable. If the
   real Hermes handshake rejects the hand-rolled server during acceptance, switching
   to the SDK is the documented fallback and touches only `testtool/`.

7. **Secret scan reuses the inventory redaction patterns** over readable Hermes log
   locations (from the install record's data dir plus journal output for the unit),
   reporting redacted excerpts only. OAuth artifacts (the X OAuth flow's tokens) are
   added to the pattern set.

## Risks / Trade-offs

- [Hermes specifics unknown pre-install] → All Hermes-shape assumptions live in the
  install record and one checks table; unknowns are explicit verdict states, and a
  post-install pinning commit is planned rather than pretended away.
- [Hand-rolled MCP server rejected by Hermes] → Acceptance exercises the real
  handshake; documented fallback to the official SDK, isolated in `testtool/`.
- [Restart evidence is heuristic (timestamps), not proof] → Combined with the
  operator having actually performed the restart in the interactive session; the
  report states exactly what evidence was collected, never more.
- [Attestations are honor-based] → Deliberate: pretending to automate interactive
  checks would be a false guarantee. The report names the attesting operator and
  time, which matches how prior acceptance was recorded in this repo.
- [Journal access may need privilege] → Same posture as the hardening assessor:
  run unprivileged first; where journald denies access, the check reports
  `permission-denied` and the operator may rerun under sudo per the documented
  operational note.

## Open Questions

- Exact Hermes diagnostics command, config format, and telemetry keys — resolved by
  the operator's install; captured in the install record and then pinned in checks.
- Whether Hermes runs as a systemd service at all under the chosen install method
  (vs. tmux/CLI process). If not a unit, service checks report their evidence as
  `unsupported-on-device` and the enablement question returns to the operator.
