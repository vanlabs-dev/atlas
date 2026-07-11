# Tasks: atlas-phase-2-knowledge-base

## 1. Corpus snapshot and module scaffolding

- [x] 1.1 Create `knowledge/` layout (`corpus/`, `atlas_kb.py` stub, `atlas_kb_server.py` stub, `benchmark/`, `schema/`, `tests/`, `README.md`)
- [x] 1.2 Snapshot the three grounding files verbatim from `IntoOps\intoops-routines\references` into `knowledge/corpus/` with `SOURCES.md` (origin, sync date, SHA-256 per file) and a documented re-sync procedure
- [x] 1.3 Pin reused surfaces (redaction/schema/verdict machinery) with `test_import_surface.py`

## 2. Intake, store, and validation report

- [x] 2.1 SQLite store schema: `intake_runs` (ATLAS-KB-001 fields), `sources`, `units` (provenance, temporal scope, evidence state, conflict links, active flag), `units_fts` (FTS5), `audit`
- [x] 2.2 Heading-level unit splitter with stable locators (heading path + line range) and per-unit temporal-scope extraction for dated statements
- [x] 2.3 Hash-verified ingest producing staged units + validation report (structure analysis, secret scan, duplicate detection, counts by evidence state)
- [x] 2.4 Known-supersession marking: conviction activation units ingested `conflicting` with the decision-log note (data-driven markers file, not hardcoded)
- [x] 2.5 Explicit `activate` step gated on operator action, recorded in `audit`; tools fail closed when nothing is activated

## 3. Knowledge MCP server

- [x] 3.1 Stdio JSON-RPC server (test-tool handshake shape) exposing `knowledge_search`, `knowledge_get_evidence`, `knowledge_status`; store opened `mode=ro`
- [x] 3.2 Source-bound results with evidence state + conflict flags; structured insufficient-evidence result on zero hits; ATLAS-TOOL-002 structured errors (category, retry-safety, correlation id)
- [x] 3.3 Redacted per-call audit line (size-capped JSONL in `var/knowledge/`) as the server's only write; no SQL/shell/file/HTTP surface

## 4. Retrieval benchmark

- [x] 4.1 Generalize the modelval machinery with backward-compatible parameters — `extract_exchanges(battery=...)`, `load_exceptions(path, valid_checks=...)`, `run_battery.py --battery-module` — keeping all 46 modelval tests green and pinning the widened signatures
- [x] 4.2 Tagged battery module (KB-EX exact, KB-PA paraphrase, KB-HI historical-vs-current emission eras, KB-CF conviction conflict, KB-UN unsupported, KB-AD adversarial current-data / MV-RI-4 re-test; small sets) with expected-evidence markers pinned against the corpus snapshot by test
- [x] 4.3 Read-only scorer importing the generalized machinery: expected-evidence + tool-called metrics (ATLAS-RET-001 evidence), bounded classification flow for KB-UN/KB-AD (auto-pass on refusal/as-of markers without live-claim phrasing; flag the rest), threshold-sheet gate, exceptions file, fail-closed verdict, 0600 reports (exit 0/3/4/1)
- [x] 4.4 `docs/thresholds.md` with proposed values (correct-with-evidence ≥ 0.9, fabrications == 0, tool-call rate ≥ 0.9) behind approval markers

## 5. Off-device verification (WSL)

- [x] 5.1 Unit tests: splitter/locators/temporal scopes against the real corpus snapshot; ingest record + hash mismatch abort; conflicting-unit marking; activation gating
- [x] 5.2 Server tests over pipes: handshake, all three tools, source-bound results, insufficient-evidence, structured errors, not-activated fail-closed, read-only surface (import allowlist, `mode=ro`)
- [x] 5.3 Benchmark scorer tests with fixture session stores (green run, missing tool call, fabricated value, unsupported handled); full suites regression (all repo test dirs)

## 6. On-device acceptance

- [x] 6.1 Ingest + review the validation report on the Pi; operator activates (delegation per keep-it-simple decision unless he objects)
- [x] 6.2 Replace `atlas-test` with the knowledge server in the Hermes config; verify discovery + a live `knowledge_search` call in a real session; pin the `-t` toolset identifier
- [x] 6.3 Approve thresholds; run the benchmark battery; score, classify flagged answers; fix evidence gaps and re-run as needed (if tool-call rate is low, apply the minimal ATLAS-RET-001 mitigation — tool descriptions, then one rules-file line — and record it)
- [x] 6.4 Record in `docs/decisions.md`: benchmark verdict + run id, closure of the deferred ATLAS-HERMES-003 retrieval criterion, MV-RI-4 re-test outcome, and the §22 scope-consolidation deviation; update root `README.md`; archive the change
