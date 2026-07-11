# Tasks: atlas-phase-1-memory-and-session-recall

## 1. Module scaffolding and contracts

- [x] 1.1 Create `hermes/memory/` layout (verifier stub, `docs/`, `tests/`, `README.md`) mirroring the `hardening/apply/` nesting convention
- [x] 1.2 Define the verification-report JSON schema (checks incl. `unknown`/`permission-denied`/`unsupported-on-device` states, the seven attestations, canary/marker evidence, overall verdict) in the module
- [x] 1.3 Pin the import surfaces with a `test_import_surface.py`: probe/redaction/envelope/schema from `inventory/atlas_inventory.py`, attestation-recording and install-record helpers from `hermes/atlas_hermes_verify.py`

## 2. Pin observed Hermes v0.18.2 memory facts

- [x] 2.1 From the accepted on-device install (operator-provided redacted excerpts), record the concrete approval-gating config key(s), memory file locations, and session DB path/FTS table names into the checks and fixtures — fail closed (`unknown`) for anything not confirmed *(done 2026-07-12 via read-only SSH inspection, keys/structure only: `memory.write_approval` + `skills.write_approval`, default OFF when absent; `memories/MEMORY.md`+`USER.md`; `state.db` with FTS5 `messages_fts(content)`)*
- [x] 2.2 Note in the module docs whether memory-write and skill-write approval are one setting or two in v0.18.2 (design open question) *(two separate settings — see hermes/memory/README.md pinned-facts table)*

## 3. Scripted operator procedure

- [x] 3.1 Write `hermes/memory/docs/procedure.md`: seven scripted steps for the ATLAS-MEM-006 set (preference retention, correction replacement, stale removal, duplicate prevention, prior-session lookup, secret rejection, domain separation), each with exact prompts, expected outcome, deviation guidance, and its named `--attest` item
- [x] 3.2 Define the documented synthetic values in the procedure: canary secret (credential-shaped, fixed recognizable prefix) and recall marker phrase; state where each is expected (sessions) vs forbidden (memory files)

## 4. Verifier checks (read-only)

- [x] 4.1 Install-record loading via the pinned helper: missing/incomplete record → no verdict (exit 4) listing gaps
- [x] 4.2 Approval-gating check against the recorded config path: explicit approval-required → `ok`; absent → `finding` (pinned fact: v0.18.2 defaults the gate OFF, so absence is determinable); unreadable/unparseable → `unknown`/`permission-denied` with remediation guidance
- [x] 4.3 Memory hygiene scan over `MEMORY.md`/`USER.md`: credential-shaped matches, canary presence, bulk domain-content heuristic — findings with redacted excerpts only; record file sizes as evidence
- [x] 4.4 Session store check: open SQLite strictly read-only (`mode=ro`), confirm FTS5 surface, search for the recall marker; missing/locked/unreadable → explicit status, never a guess and never a writable open
- [x] 4.5 `--attest` inputs for the seven evaluation items with attesting operator and timestamp recorded in the report
- [x] 4.6 Fail-closed overall verdict and report writing (schema-validated JSON + Markdown summary + audit record, 0600, gitignored `var/memory/`), exit codes matching the baseline verifier (0/3/4/1)

## 5. Off-device verification (WSL)

- [x] 5.1 Unit tests per check with fixtures: gating on/off/absent configs, memory files clean/with planted fake secret/with canary/with domain dump, fixture SQLite session DBs (marker present/absent/FTS missing), incomplete install records
- [x] 5.2 Full-run integration test on WSL: not-accepted run names correct blockers; fully-green fixture run yields accepted; confirm no writes outside the chosen output dir and no writable DB opens *(59 tests green on WSL, incl. end-to-end runs with the real `collect_evidence` over a fixture data dir; existing hermes/inventory/hardening suites re-run with no regressions)*
- [x] 5.3 Read-only review: verify by test and inspection that the verifier performs no Hermes invocations and no config/memory/session writes *(AST import allowlist — no subprocess-capable module; no direct writable `open()`; fixture-mtime untouched test)*

## 6. Operator documentation

- [x] 6.1 `hermes/memory/README.md`: what the verifier does/never does, usage, the seven attestations, canary/marker semantics, verdict/exit codes
- [x] 6.2 Update root `README.md` (repo layout, current status, next step) and `hermes/README.md` cross-reference for the new module

## 7. On-device acceptance (after the operator's procedure)

- [ ] 7.1 Operator confirms approval gating is enabled in the Hermes config (fixing it manually first if off — outside repo code) *(observed 2026-07-12: BOTH keys absent on the device → gating is OFF; set `memory.write_approval: on` and `skills.write_approval: on`, restart Hermes)*
- [ ] 7.2 Operator performs the scripted procedure in live Hermes sessions, recording any deviations
- [ ] 7.3 Run the verifier on the Pi with the earned `--attest` flags; if observed v0.18.2 shapes diverge from the pinned facts, update checks/fixtures and rerun
- [ ] 7.4 Record the verdict, run id, and ATLAS-MEM-006 evidence summary in `docs/decisions.md` (this is the evidence base for PRD §21 Q19); archive the change
