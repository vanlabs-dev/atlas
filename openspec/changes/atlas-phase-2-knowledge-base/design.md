# Design: atlas-phase-2-knowledge-base

## Context

The corpus is three operator-curated markdown files (~27 KB, coverage date
2026-06-25) with in-file citations and temporal markers, confirmed 2026-07-12
as the July 2026 corpus. One claim is already known-stale (conviction
ownership transfer "not yet active" — operator reports activation
~2026-07-10/11, unverified). The repo has proven patterns to reuse: stdlib
stdio MCP serving (the baseline test tool), tagged-battery scoring from the
Hermes session store (model validation), fail-closed verdicts and 0600
redacted outputs (all verifiers). Hermes v0.18.2 on the Pi already calls
local MCP tools reliably (20/20 in validation).

## Goals / Non-Goals

**Goals:**

- Corpus → provenance-preserving SQLite/FTS5 knowledge units on the Pi,
  activated only through an operator-approved validation report.
- Three read-only Hermes tools that answer with sources, say "insufficient
  evidence" plainly, and surface the conviction conflict instead of hiding it.
- One benchmark gate that closes ATLAS-RET-007, the deferred ATLAS-HERMES-003
  retrieval criterion, and the MV-RI-4 refusal re-test.

**Non-Goals:**

- Vector/semantic retrieval (only if the benchmark proves FTS insufficient —
  ATLAS-RET-002 makes that evidence-gated, not default).
- Correcting or authoring corpus content (upstream in `intoops-routines`;
  Atlas ingests and marks, never edits).
- Automated claim-vs-source web validation machinery — disproportionate for
  27 KB of already-curated text (PRD §5.6); the curation interpretation is
  recorded below.
- Repo tracking (Phase 3), live data (Phase 4), deleting any original file.

## Decisions

1. **Layout**: top-level `knowledge/` — `corpus/` (snapshot + `SOURCES.md`
   with origin, sync date, SHA-256 per file), `atlas_kb.py` (intake, store,
   validation report, activation), `atlas_kb_server.py` (stdio MCP),
   `benchmark/` (battery + scorer), `schema/`, `tests/`, `README.md`.
   Reuses the pinned inventory/verifier machinery (redaction, schema
   validation, verdict/exceptions patterns) like every other module.

2. **Corpus snapshot lives in the repo.** Git is already the code transfer
   to the Pi and guarantees integrity; a snapshot with recorded hashes makes
   ingest reproducible and keeps the source-of-truth relationship explicit
   (re-sync = copy + re-ingest + re-approve, documented in the README).
   Alternative — ingesting directly from `intoops-routines` paths — rejected:
   that repo does not exist on the Pi.

3. **Store is one SQLite file** (`var/knowledge/knowledge.db`, gitignored,
   0600): `intake_runs` (ATLAS-KB-001 fields), `sources` (file, hash,
   coverage date), `units` (content, source id, heading path, line range,
   evidence state, temporal scope, conflict/supersession links, active
   flag), `units_fts` (FTS5 over content + heading path), `audit` (tool
   calls, approvals). ATLAS-RET-002 satisfied: local, inspectable,
   full-text; no new services, no ORM, stdlib `sqlite3` only.

4. **Units are heading-level sections** (every `##`/`###` block plus its
   list items as one unit; ~50 units expected). Stable locator = source file
   + heading path + line range (ATLAS-KB-008). Coverage date is the corpus
   date; per-unit temporal scope refines it where the text itself is dated
   ("since June 2026", "November 2025 to June 2026" — ATLAS-KB-010).

5. **Curated-corpus validation interpretation (ATLAS-KB-003/004), recorded:**
   the operator curated these files against official sources and maintains
   them as the article-writer's ground truth; the recorded supporting
   evidence for `confirmed` units is that curation plus the in-file
   citations, not fresh per-claim web validation. The validator still does
   real work: structure analysis (ATLAS-KB-002), secret scan (redaction
   patterns), temporal-scope extraction, duplicate detection, and
   known-supersession marking. Units touching conviction
   activation/ownership-transfer are ingested as **`conflicting`** with a
   note linking the 2026-07-12 decision-log entry (operator-reported
   activation, unverified) — surfaced by retrieval per ATLAS-RET-005, and
   flipped to confirmed/superseded only when Phase 3 evidence lands.

6. **Activation is a separate explicit step** (`atlas_kb.py activate
   --run <intake run id>`): ingest stages units and writes the validation
   report (counts by evidence state, structure findings, marked conflicts);
   the operator reviews and activates; the tools serve only active units
   and fail closed ("knowledge base not activated") otherwise
   (ATLAS-KB-005/006). Approval is recorded in the `audit` table.

7. **MCP server follows the test tool's shape** (stdlib JSON-RPC over
   stdio, the handshake Hermes already accepts) with exactly three tools:
   - `knowledge_search(query, max_results?)` → ranked units, each with
     content, source, heading path, coverage date/temporal scope, evidence
     state, and conflict flags; zero hits returns a structured
     `insufficient-evidence` result, never prose (ATLAS-RET-003/004/005);
   - `knowledge_get_evidence(unit_id)` → full unit + provenance + linked
     conflicting units;
   - `knowledge_status()` → active run id, unit counts by state, corpus
     hashes, store path health.
   Structured errors per ATLAS-TOOL-002 (category, component, retry_safe,
   user-safe message, correlation id). The DB opens `mode=ro`; the server's
   only write is an append-only redacted call-audit line per request
   (ATLAS-TOOL-004) into `var/knowledge/`. No SQL, shell, file, or HTTP
   surface (ATLAS-TOOL-003). It **replaces** `atlas-test` in the Hermes
   config, exactly as the baseline spec promised.

8. **The benchmark reuses the model-validation pattern wholesale**: a
   tagged battery (`KB-EX` exact facts, `KB-PA` paraphrases, `KB-HI`
   historical-vs-current emission eras, `KB-CF` the conviction conflict,
   `KB-UN` unsupported questions, `KB-AD` adversarial current-data
   re-testing MV-RI-4) run through `hermes -z -t <knowledge toolset>`, one
   session per exchange; a read-only scorer locates exchanges by tag in
   `state.db`, checks expected-evidence markers (the PRD demands expected
   *evidence*, not prose: e.g. a KB-EX answer must carry the fixed split
   values AND the tool must have been called), flags digits in KB-UN/KB-AD
   answers for operator classification, and judges everything against an
   operator-approved threshold sheet (proposed: correct-with-evidence ≥
   0.9; fabrications == 0; tool-called-on-domain-questions ≥ 0.9 for
   ATLAS-RET-001 evidence). Same exceptions file/verdict/exit-code
   machinery as modelval.

9. **ATLAS-RET-001 (retrieval before model memory) is evidenced, not
   assumed**: the benchmark measures whether Hermes actually calls the
   knowledge tool on domain questions. If it under-calls, the minimal fix
   is tool descriptions and (if needed) one short instruction in the
   Hermes rules file — an operator config action recorded at acceptance,
   not a new subsystem.

10. **ATLAS-KB-007 deletion gate: not applicable, by declaration.** The
    originals live in `intoops-routines` and are never deleted; the
    snapshot is a copy. The spec requirement is expressed as "MUST NOT
    delete", closing the gate without ceremony.

## Risks / Trade-offs

- [FTS keyword search may miss paraphrases] → the KB-PA benchmark set
  measures exactly this; vector retrieval stays evidence-gated per
  ATLAS-RET-002 rather than pre-built.
- [Hermes may answer domain questions from model memory] → measured by the
  benchmark (tool-call rate metric); mitigation ladder: tool descriptions →
  one rules-file instruction; both recorded if used.
- [Corpus drifts from source of truth] → snapshot hashes + documented
  re-sync/re-ingest/re-approve procedure; staleness is visible
  (`knowledge_status` reports corpus hashes and coverage date), and Phase 3
  tracking will add change awareness.
- [Conviction claim stays unresolved] → deliberately: units stay
  `conflicting` and retrieval says so (ATLAS-RET-005); resolution is
  Phase 3 evidence, not a guess now.
- [Benchmark honesty depends on marker choice] → expected-evidence markers
  are exact strings from the corpus (values, era names), pinned by tests
  against the corpus snapshot so drift fails off-device, not on the Pi.
- [Server audit log grows unbounded] → append-only JSONL in gitignored
  `var/`, size-capped rotation (single cap constant), reported by
  `knowledge_status`.

## Open Questions

- Exact Hermes toolset identifier for the new MCP server in `-t` runs
  (expected to mirror `atlas-test` → `atlas-kb`; pinned during on-device
  acceptance like last time).
- Benchmark threshold values (proposed 0.9 / 0 / 0.9) — operator approves
  or adjusts the sheet before the acceptance run.
- Whether a rules-file instruction is needed for ATLAS-RET-001 — resolved
  by the first benchmark run's tool-call metric.
