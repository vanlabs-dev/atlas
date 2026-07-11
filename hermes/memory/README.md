# Atlas memory and session recall verification (Phase 1)

Read-only verification that Hermes personal memory and session recall meet
**ATLAS-MEM-001…006**, via OpenSpec change
`atlas-phase-1-memory-and-session-recall`. Produces the evidence base for
the PRD §21 Q19 decision (keep memory writes approval-gated, or relax
later).

## What it does — and does not do

- **Verifies, never configures**: if approval gating is off, the operator
  fixes `config.yaml` manually and re-runs; the verifier changes nothing.
- **Read-only, always**: no Hermes invocation, no config/memory/session
  writes; the session store is opened via a SQLite `mode=ro` URI (writes
  through it are impossible by construction). The only writes are redacted
  0600 reports in gitignored `var/memory/`.
- **Fails closed**: a missing/incomplete install record or invalid
  exceptions file yields *no verdict*; any finding, unresolved unknown
  (`unknown`, `permission-denied`, `unsupported-on-device`), or missing
  attestation yields **not-accepted** with every blocker named.
- Reuses the inventory probe/redaction/schema core and the baseline
  verifier's record/check/verdict machinery (both pinned by
  `tests/test_import_surface.py`) — still one implementation of
  "read-only verification" in this repo.

## Pinned Hermes v0.18.2 facts

Source-verified on the accepted install (2026-07-12) and pinned by test;
a change in any of these is a deliberate re-pin, not drift:

| fact | value |
|---|---|
| approval gating | `memory.write_approval` **and** `skills.write_approval` in `config.yaml` — two separate settings (answers the design open question), both must be on |
| gate default | **OFF when the key is absent** — so absence is a *finding*, not an unknown |
| enabled spellings | `on`, `true`, `yes`, `1`, `approve`, `enabled` |
| memory files | `<data_dir>/memories/MEMORY.md` and `USER.md` (USER.md created on first use) |
| session store | `<data_dir>/state.db`, FTS5 virtual table `messages_fts(content)` |

## The checks

| check | what it verifies |
|---|---|
| `install-record` | the ATLAS-HERMES-001 record is complete (paths come from it) |
| `approval-gating` | both write-approval gates explicitly on (ATLAS-MEM-003) |
| `memory-hygiene` | `MEMORY.md`/`USER.md` are secret-free and canary-free (ATLAS-MEM-005), hold no bulk domain content (ATLAS-MEM-001); sizes recorded |
| `session-store` | store present, FTS surface present, recall marker findable read-only (ATLAS-MEM-002) |

**The seven ATLAS-MEM-006 items are attested, not automated.** The
operator performs [docs/procedure.md](docs/procedure.md) in live Hermes
sessions — preference retention, correction replacement, stale removal,
duplicate prevention, prior-session lookup, secret rejection, domain
separation — then passes `--attest` per completed item. The report records
who attested what, when. An unattested item blocks acceptance.

Two synthetic values give the attestations physical corroboration (both
defined in the procedure): a **canary secret** (`ATLAS-CANARY-…`,
credential-shaped, expected in session transcripts, *forbidden* in memory
files) and a **recall marker phrase** (planted in one session; the
verifier confirms it is FTS-findable).

## Usage

```sh
# on the Pi, from the repo root, after performing docs/procedure.md:
python3 hermes/memory/atlas_memory_verify.py verify \
    --attest preference-retention --attest correction-replacement \
    --attest stale-removal --attest duplicate-prevention \
    --attest prior-session-lookup --attest secret-rejection \
    --attest domain-separation
```

Run after ending the interactive Hermes session (a live session can hold
the store locked; the verifier then reports an explicit unknown).

Exit codes: `0` accepted · `3` not-accepted (blockers listed) · `4` no
verdict (install record or exceptions file missing/invalid) · `1` fatal.

Outputs per run into `var/memory/`: `verification-<run id>.json`
(schema-validated), `summary-<run id>.md` (for the decision log),
`audit-<run id>.json`.

## Documented exceptions

Memory-check exceptions live in optional, gitignored
`var/memory/exceptions.json` — **not** in the install record (the baseline
verifier validates that file's exceptions against *its* check names and
would reject ours):

```json
[{"check": "session-store", "reason": "why this deviation is accepted"}]
```

An exception never rewrites a check's status; it makes the deviation an
explicit recorded decision, reproduced in the report. Attestations cannot
be excepted — an unperformed procedure step always blocks.

## Tests

```sh
cd hermes/memory/tests && python3 -m unittest discover -v
```

Off-device only (WSL/dev machine), including an end-to-end run against a
fixture data dir; the Pi run after the operator's procedure is the
acceptance run.
