# Tasks: atlas-phase-1-hermes-baseline

## 1. Module scaffolding and contracts

- [x] 1.1 Create `hermes/` layout (verifier stub, `testtool/`, `schema/`, `tests/`, `docs/`, `README.md`) mirroring `hardening/` conventions
- [x] 1.2 Write `hermes/docs/install-record.template.json` with the eight ATLAS-HERMES-001 fields plus optional `diagnostics_command` and `service_unit`, with per-field guidance comments in the docs
- [x] 1.3 Define the verification-report JSON schema in `hermes/schema/` (checks, verdict states incl. `permission-denied`/`unsupported-on-device`/`unknown`, attestations, overall verdict)
- [x] 1.4 Pin the import surface from `inventory/atlas_inventory.py` (probe execution, redaction, envelope, schema validation) with a `test_import_surface.py` like `hardening/`'s

## 2. Verifier checks (read-only)

- [x] 2.1 Install-record loading and validation: missing file or fields → no verdict, explicit list of gaps
- [x] 2.2 Unprivileged-execution check: service/process user matches record, not root, no sudo-capable groups or readable sudoers grants; unreadables → `permission-denied`
- [x] 2.3 Telemetry check against the recorded config path: explicit-disabled → `ok`; not found/indeterminate → `unknown` with remediation guidance
- [x] 2.4 Diagnostics check: run the record's `diagnostics_command` read-only and parse pass/fail; absent command → `unsupported-on-device`; failures → findings unless a documented exception is supplied
- [x] 2.5 Service persistence evidence: systemd unit enabled/active/user/start-time (system then user scope); no unit → `unsupported-on-device`; never start/stop/restart anything
- [x] 2.6 Secret-free log scan over the record's data dir logs and unit journal, reusing inventory redaction patterns extended with OAuth-token shapes; redacted excerpts only

## 3. Attestations and verdict

- [x] 3.1 `--attest` CLI inputs for `chat`, `memory-session-search`, `tool-call` with attesting operator (default invoking user) and run timestamp recorded in the report
- [x] 3.2 Fail-closed overall verdict: accepted only when all automated checks `ok`/excepted and all three attestations present; otherwise not-accepted naming every blocker
- [x] 3.3 Report writing: schema-validated JSON + human-readable Markdown summary, 0600, into gitignored `var/hermes/`, per-run id matching repo conventions

## 4. Atlas test tool

- [x] 4.1 Implement `hermes/testtool/atlas_test_tool.py`: stdlib-only stdio JSON-RPC MCP server (`initialize`, `tools/list`, `tools/call`) exposing static `atlas_ping`
- [x] 4.2 Tests: protocol handshake and tool call over pipes; a code-surface test asserting no filesystem reads outside the module, no network, no subprocess

## 5. Off-device verification (WSL)

- [x] 5.1 Unit tests for every check with fixtures (complete/incomplete install records, telemetry on/off/absent configs, logs with planted fake secrets, unit-state variants)
- [x] 5.2 Full-run integration test on WSL with a fixture install record: verdict not-accepted with correct blockers; then a fully-mocked green run yields accepted
- [x] 5.3 Confirm zero device mutation by review + test (no writes outside `var/hermes/`, no service commands other than read-only queries)

## 6. Operator documentation

- [x] 6.1 `hermes/README.md`: what the verifier does/never does, usage (unprivileged first, sudo rerun note for journal access), attestation meaning
- [x] 6.2 `hermes/docs/manual-install-notes.md`: what to capture during the manual install (install record fields, disable telemetry, dedicated unprivileged user, no secrets on command lines, restart once before verification)
- [x] 6.3 Update root `README.md` repo-layout and next-step sections for the new `hermes/` module

## 7. On-device acceptance (after the operator's manual install)

- [x] 7.1 Operator completes `var/hermes/install-record.json` from the template
- [x] 7.2 Operator performs interactive checks in Hermes (chat, memory write + cross-session search, discover and call `atlas_ping`) and restarts the service once
- [x] 7.3 Run the verifier on the Pi (unprivileged; sudo rerun only if journal checks report `permission-denied`) with the three attestations
- [x] 7.4 If Hermes's observed shape diverged from assumptions (config keys, diagnostics, unit), pin the observed facts into checks/fixtures and rerun
- [x] 7.5 Record the acceptance verdict and install-record summary in `docs/decisions.md`; archive the change
