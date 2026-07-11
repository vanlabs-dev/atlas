# Proposal: atlas-phase-2-knowledge-base

Governing documents: [prd.md](../../../prd.md) (§12.4 ATLAS-KB-001…010, §12.5
ATLAS-RET-001…007, §12.10 ATLAS-TOOL-001…004, §16 Phase 2) and
[docs/decisions.md](../../../docs/decisions.md): the corpus decision of
2026-07-12 (Q12–15 — the three curated grounding files from
`IntoOps\intoops-routines\references`, ~27 KB, coverage date 2026-06-25), the
deferred ATLAS-HERMES-003 retrieval benchmark, the MV-RI-4 fabrication
exception (re-test here), and the operator-reported conviction activation
(~2026-07-10/11, unverified — the corpus's "not yet active" claim is a
supersession candidate).

## Why

Phase 1 proved the platform (hardened Pi, Hermes, memory, model); Atlas still
cannot answer a single Bittensor question from validated knowledge — the
entire product purpose. The corpus exists and is confirmed; the deferred
Phase 1 gates (retrieval benchmark, refusal re-test) have nowhere to run
until retrieval exists. This change turns the confirmed corpus into a
provenance-preserving, searchable knowledge base exposed to Hermes through
read-only tools, and proves it with the benchmark.

**Scope consolidation (recorded deviation from PRD §22):** the recommended
decomposition (`corpus-intake` / `knowledge-validation` / `grounded-retrieval`
as three changes) was sized for bulk corpus dumps. The actual corpus is ~27 KB
of operator-curated markdown, so intake, validation, retrieval, and the
benchmark are one proportionate change (PRD §5.6; keep-it-simple decision
2026-07-12). The requirements themselves are not weakened — every ATLAS-KB/RET
gate below still applies.

## What Changes

- **Corpus snapshot in-repo** (`knowledge/corpus/`): the three grounding files
  copied verbatim from the source of truth with recorded origin, sync date,
  and SHA-256 hashes. Git remains the transfer to the Pi. The originals in
  `intoops-routines` are never touched or deleted — the ATLAS-KB-007 deletion
  gate is explicitly not applicable (recorded as such).
- **Intake + knowledge store** (`knowledge/atlas_kb.py`): heading-based
  knowledge units in a single SQLite file (FTS5) on the Pi, per ATLAS-RET-002
  (local, inspectable, full-text; no vector store). Every unit preserves
  provenance (source file + hash, heading path, line range, coverage date,
  evidence state, supersession links — ATLAS-KB-008/010); the intake records
  hash/size/dates/parser version/run id (ATLAS-KB-001).
- **Proportionate validation** with an operator approval gate: the corpus is
  already operator-curated against official sources, so validation here means
  structure analysis (ATLAS-KB-002), secret scan, temporal-scope assignment,
  and marking of known supersession candidates — starting with the conviction
  activation, whose corpus claim ("ownership transfer NOT yet active") is
  ingested as **conflicting/superseded-candidate**, never as current
  (ATLAS-KB-009/010). A validation report with unit counts by state gates
  activation on explicit operator approval (ATLAS-KB-005/006). The
  ATLAS-KB-003/004 interpretation for a curated corpus — operator curation +
  in-file citations are the recorded supporting evidence — is documented in
  the design, not silently assumed.
- **Read-only knowledge tools for Hermes** (`knowledge/atlas_kb_server.py`,
  stdio MCP, replacing the `atlas-test` server as the baseline promised):
  `knowledge_search`, `knowledge_get_evidence`, `knowledge_status` — returning
  content **with provenance and evidence state** (ATLAS-RET-003), explicit
  insufficient-evidence results (ATLAS-RET-004), surfaced conflicts
  (ATLAS-RET-005), structured errors (ATLAS-TOOL-002), no generic query/shell
  surface (ATLAS-TOOL-003), auditable calls (ATLAS-TOOL-004).
- **The retrieval benchmark** (ATLAS-RET-007 + the two deferred Phase 1
  gates): a tagged battery through live Hermes with the knowledge tools
  enabled — exact facts, paraphrases, historical-vs-current (the emission
  model's three eras), the conviction conflict, unsupported questions (must
  say so), and the adversarial current-data set re-testing MV-RI-4 (must
  answer from dated corpus facts or decline — never present them as live).
  Scored from the session store against operator-approved thresholds,
  reusing the proven model-validation pattern.
- Explicitly out of scope: subtensor repo tracking (Phase 3), TaoStats/TaoSwap
  live data (Phase 4), Telegram (Phase 5), vector/semantic retrieval (only if
  the benchmark proves FTS insufficient — ATLAS-RET-002), any corpus content
  authoring or correction (upstream in `intoops-routines`), deletion of any
  original file.

## Capabilities

### New Capabilities

- `knowledge-base`: Validated Bittensor knowledge on the Pi — corpus snapshot
  with recorded provenance, heading-level knowledge units in SQLite/FTS5 with
  evidence states and supersession links, an operator-approved validation
  report, read-only Hermes MCP tools returning source-bound answers with
  explicit insufficient/conflicting handling, and a benchmark gate that also
  closes the deferred ATLAS-HERMES-003 retrieval criterion and re-tests the
  MV-RI-4 refusal exception.

### Modified Capabilities

None. (`hermes-baseline` promised the test tool would be *replaced* by the
production tool interface — that replacement is this change doing exactly
what that spec anticipated; the baseline spec itself is unchanged.)

## Impact

- **Device**: new SQLite knowledge store + reports under gitignored `var/`
  on the Pi; the MCP server registration in Hermes config is an operator
  action (like `atlas-test` was). No other device mutation.
- **Repo**: new `knowledge/` module (corpus snapshot, intake/store/server,
  benchmark, tests) beside the existing verifiers; reuses the pinned
  redaction/schema/verdict machinery.
- **Hermes**: gains three read-only knowledge tools; loses the inert
  `atlas_ping` test tool (replaced, per the baseline plan).
- **Privilege/testing**: unchanged conventions — unprivileged, off-device
  tests on WSL with fixtures, the Pi run is acceptance.
- **Downstream**: closes the deferred ATLAS-HERMES-003 retrieval gate;
  gives Phase 3 (repo tracking) a store to link change records against and
  Phase 4 a grounded baseline to contrast live data with.
