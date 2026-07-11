# Design: atlas-phase-1-memory-and-session-recall

## Context

Hermes v0.18.2 is installed and accepted on the Pi (baseline run
`20260711T091512Z-61ef71d0`): it runs as `pi`, config at `~/.hermes/config.yaml`,
data in `~/.hermes/`, session history in SQLite with FTS5 per official docs, memory
in bounded `MEMORY.md`/`USER.md` files. Unlike the baseline change, the software's
on-device shape is now observable — but its *memory behavior* is unverified beyond a
single unstructured attestation. The repo pattern is established: read-only verifiers
that import the probe/redaction/envelope/schema core from
`inventory/atlas_inventory.py` (pinned by an import-surface test), fail closed on
unknowns, write redacted 0600 reports into gitignored `var/`, and record operator
attestations for anything only a live session can show.

## Goals / Non-Goals

**Goals:**

- A `hermes/memory/` module (verifier, scripted procedure, tests, README) producing
  one fail-closed verdict covering ATLAS-MEM-001…006, suitable for the decision log.
- A repeatable, exactly-scripted operator procedure for the ATLAS-MEM-006 evaluation
  set, so the evidence is reproducible rather than ad-hoc.
- Automated read-only evidence wherever the filesystem can show it (approval config,
  memory hygiene, session-store searchability); attestation only where it cannot.

**Non-Goals:**

- Changing any Hermes configuration or memory content (if approval gating is off,
  the operator fixes it manually and re-runs the verifier).
- Deciding PRD §21 Q19 (relaxing approval gating) — this change only produces the
  evidence that decision needs.
- ATLAS-HERMES-003 model validation, Phase 2 corpus/retrieval, Telegram.
- A generic memory-testing framework (PRD §5.6): one procedure, one verifier.

## Decisions

1. **Layout nests under `hermes/`**: `hermes/memory/atlas_memory_verify.py`,
   `hermes/memory/docs/procedure.md`, `hermes/memory/tests/`, `hermes/memory/README.md`
   — mirroring how `hardening/apply/` nests under `hardening/`. The verifier imports
   the probe/redaction/envelope/schema surface from `inventory/atlas_inventory.py`
   and reuses the attestation-recording and install-record-reading helpers from
   `hermes/atlas_hermes_verify.py`, both pinned by an import-surface test.
   Alternative — a new top-level `memory/` — rejected: this verifies *Hermes*
   memory behavior, and a top-level `memory/` invites confusion with the later
   Atlas knowledge store.

2. **Reports go to `var/memory/`** (`verification-<run id>.json`,
   `summary-<run id>.md`, `audit-<run id>.json`, all 0600, schema-validated).
   Separate from `var/hermes/` so baseline and memory verification runs cannot be
   confused; the install record stays in `var/hermes/` and is consumed read-only.

3. **The install record remains the path source.** Config path, data dir, and
   service user come from `var/hermes/install-record.json` (ATLAS-HERMES-001), not
   from hardcoded paths. A missing/incomplete record yields *no verdict* (exit 4),
   exactly as in the baseline verifier.

4. **Approval-gating check reads the Hermes config for the memory/skill write
   approval setting** (ATLAS-MEM-003). The concrete key names are pinned during
   implementation from the operator's installed v0.18.2 (redacted config excerpt or
   on-device inspection), with fixtures updated to the observed shape. If no
   recognized setting is found the check reports `unknown` — a blocker, never a
   pass. Alternative — asking the operator to attest gating is on — rejected: the
   config is machine-readable, so attestation would be a weaker form of available
   evidence.

5. **The procedure plants deterministic markers; the verifier scans for them.**
   `docs/procedure.md` scripts the seven ATLAS-MEM-006 items with exact prompts and
   two documented synthetic values:
   - a **canary secret** — credential-shaped but obviously fake, carrying a fixed
     recognizable prefix — which the operator asks Hermes to remember (secret
     rejection, ATLAS-MEM-005);
   - a **recall marker phrase** dropped into one session and searched for from a
     *new* session (prior-session lookup, ATLAS-MEM-002).
   After the procedure, the verifier checks: canary **absent** from
   `MEMORY.md`/`USER.md` (finding if present), and recall marker **present** in the
   session store via read-only FTS query (evidence that cross-session search has
   substance beyond the attestation). The canary *will* legitimately appear in
   session transcripts — that is conversation content, not memory; the scan and the
   report distinguish the two explicitly so a future log scan doesn't misread it.

6. **Memory hygiene scan** (ATLAS-MEM-001/005): the redaction pattern set from the
   inventory core (plus the OAuth patterns added in the baseline) runs over
   `MEMORY.md`/`USER.md`; any credential-shaped match is a finding with a redacted
   excerpt. Domain separation is checked by heuristic (bulk Bittensor/corpus-shaped
   content in memory files) **plus** a procedure step where the operator asks a
   Bittensor question and confirms no domain dump is proposed as a memory. File
   sizes are recorded as evidence; no numeric bound is invented (PRD §5.5) — Hermes
   itself bounds these files, and egregious growth surfaces through the heuristic
   and the operator's review.

7. **Session store opened strictly read-only** (SQLite URI `mode=ro`): confirm the
   database exists at the recorded data dir, the FTS5 surface is present, and the
   recall marker is findable. Alternative — copying the DB before querying —
   rejected: a copy doubles device writes for no integrity gain when `mode=ro`
   already refuses writes. Since Hermes has no service unit and is started manually,
   the procedure instructs running the verifier after ending the interactive
   session, so lock contention is not expected.

8. **Attestations are per-run CLI inputs**, one per ATLAS-MEM-006 item:
   `--attest preference-retention`, `--attest correction-replacement`,
   `--attest stale-removal`, `--attest duplicate-prevention`,
   `--attest prior-session-lookup`, `--attest secret-rejection`,
   `--attest domain-separation`. Recorded with operator and timestamp; an
   unattested item blocks acceptance. Same rationale as the baseline: these are
   facts about what the operator just did, and the report is the durable record.

9. **Memory-check exceptions live in `var/memory/exceptions.json`, not the
   install record.** Discovered during implementation: the baseline verifier
   validates the install record's `exceptions[].check` against *its own*
   check names and rejects unknown ones — memory-check exceptions in that
   file would break baseline re-runs. So this module reads an optional
   gitignored JSON list of `{check, reason}`; an invalid file is an
   input-contract problem (no verdict), and every entry is reproduced in the
   report. Attestations cannot be excepted.

10. **Verdict and exit codes mirror the baseline verifier**: `0` accepted, `3`
   not-accepted (every blocker named), `4` no verdict (install record
   missing/incomplete), `1` fatal. Acceptance requires every automated check `ok`
   (or covered by a documented exception, which the report reproduces) and all
   seven attestations present.

## Risks / Trade-offs

- [Hermes v0.18.2 memory internals (config keys, DB schema, FTS table names) not
  yet pinned in the repo] → Pinned during implementation from the accepted
  on-device install; until then checks report `unknown`/`unsupported-on-device`
  rather than guessing. Fixtures encode the observed shapes.
- [Model may not cooperate with the procedure (e.g. Grok never proposes a memory
  for a step)] → The procedure marks the step not-completable as scripted; that is
  a recorded deviation for the decision log (and ATLAS-HERMES-003 evidence), never
  a silent pass. The verifier simply lacks the attestation and blocks.
- [Canary in session transcripts could look like a leaked secret later] → The
  canary's documented fixed prefix identifies it; the report states where the
  canary is expected (sessions) versus forbidden (memory files). The baseline's
  log scan patterns are left untouched — if it ever flags the canary, the
  procedure doc is the documented explanation.
- [Attestations are honor-based] → Deliberate, same as baseline: pretending to
  automate live-session behavior would be a false guarantee. Markers (decision 5)
  give the attestations physical corroboration where possible.
- [Session DB locked or WAL-inconsistent while Hermes runs] → Procedure sequences
  the verifier after the interactive session ends; a locked/unreadable store is
  reported as an explicit unknown with retry guidance, not guessed around.
- [Memory files legitimately contain machine facts that resemble "domain" content]
  → ATLAS-MEM-001 allows machine environment facts; the heuristic targets bulk
  corpus-shaped content (size, structure), and the operator's domain-separation
  attestation is the deciding evidence. Findings carry redacted excerpts for review.

## Open Questions

- ~~Exact v0.18.2 config key(s) for memory/skill write approval, and the session
  DB path/FTS table names~~ — **resolved 2026-07-12** by read-only inspection of
  the accepted install (keys only, no values): gating is `memory.write_approval`
  and `skills.write_approval` in config.yaml (read by `tools/write_approval.py`;
  enabled spellings `on/true/yes/1/approve/enabled`; **defaults OFF when
  absent** — so an absent key is a determinable *finding*, not an `unknown`;
  `unknown` remains for unreadable/unparseable config). Memory files are
  `<data_dir>/memories/MEMORY.md` + `USER.md` (USER.md created on first use);
  session store is `<data_dir>/state.db` with FTS5 table `messages_fts(content)`.
  All pinned by `tests/test_import_surface.py`. Note: neither approval key is
  currently set on the device — gating is OFF and the operator must enable both
  before the procedure (task 7.1).
- ~~Whether skill-write approval is configured distinctly from memory-write
  approval~~ — **resolved: two separate settings**; the check requires both on.
- Whether the stale-memory-removal step leaves a tombstone or truly deletes in
  v0.18.2 — either satisfies ATLAS-MEM-004 if no contradictory active memory
  remains; the procedure records which behavior was observed.
