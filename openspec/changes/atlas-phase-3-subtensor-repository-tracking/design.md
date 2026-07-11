# Design: atlas-phase-3-subtensor-repository-tracking

## Context

Phase 2 left a proven kit to reuse: stdlib-only modules with fail-closed
verdicts and 0600 outputs in gitignored `var/`, one SQLite/FTS5 store per
concern, a stdio MCP server shape Hermes v0.18.2 demonstrably calls (17/17
tool-call rate in the KB benchmark), and off-device tests on WSL with the Pi
run as acceptance. The Pi has git (the `~/atlas` checkout is the transfer
mechanism), 256 GB NVMe at 3%, outbound HTTPS open (nftables restricts
inbound only). The tracked repository claim is
`https://github.com/RaoFoundation/subtensor` (operator, 2026-07-12) — a
claim, not yet the ATLAS-REPO-001 validation, and notable because the
historical canonical owner was `opentensor`. One standing conflict waits on
this phase: the conviction-activation claim (operator-reported
~2026-07-10/11, no GitHub release in the window). PRD §21 Q20 (polling
interval) and Q23 (anonymous vs token) are open; Q21/22 (notifications,
priority paths) belong to later phases.

## Goals / Non-Goals

**Goals:**

- A verified, non-shallow subtensor clone on the Pi whose identity was
  validated (and recorded) before the first byte was fetched.
- A manual update command that can only leave the clone in a good state:
  verified remote, fast-forward or deterministic reset, never a merge,
  last good state preserved on any failure, everything logged.
- Change records and an incremental file index that give Hermes read-only,
  commit-and-path-cited answers and honest freshness reporting.
- Repo-side evidence (or a recorded "repo-inconclusive") for the
  conviction-activation conflict.

**Non-Goals:**

- Activating scheduled updates (interval is Q20; the mechanism ships
  interval-configurable, activation is a recorded operator step).
- Commit notifications (Phase 5), live chain data (Phase 4).
- Building, testing, or running subtensor (ATLAS-REPO-009: manual-only,
  separately approved).
- Any write path to the tracked repository, from any component.
- Editing knowledge-base content (the conviction unit updates through the
  existing corpus re-sync flow once evidence is recorded).

## Decisions

1. **Layout**: top-level `repotrack/` — `atlas_repo.py` (CLI:
   `validate-identity`, `setup`, `update`, `index`, `status`),
   `atlas_repo_server.py` (stdio MCP), `schema/`, `tests/`, `README.md`.
   Same conventions as `knowledge/`: stdlib only, schema-versioned JSON
   records, fail-closed verdicts, everything device-side under
   `var/repotrack/` (gitignored, 0600/0700).

2. **Identity validation is a command with a recorded outcome, not a
   ritual** (ATLAS-REPO-001): `validate-identity` queries the GitHub REST
   API anonymously (`/repos/<owner>/<name>`) and reports: canonical
   `full_name` (a redirect exposes moves/renames — exactly the
   RaoFoundation-vs-opentensor question), `archived` flag, `default_branch`,
   clone URL. The command only *reports*; the operator confirms owner/name,
   canonical URL, default branch, and which branch represents mainnet, and
   the confirmation goes into `docs/decisions.md`. `setup` refuses to run
   without that recorded confirmation (pinned into `repotrack/config.json`:
   owner, name, URL, branch). Any mismatch or API uncertainty blocks setup.

3. **Clone lives at `var/repotrack/subtensor/`**, created by `setup` as a
   full (non-shallow) clone over anonymous HTTPS — Q23 resolves to
   anonymous-read by default (public repo, no secret to manage; a token can
   be added later via standard git credential config without code changes;
   recorded at apply time). `setup` verifies `--is-shallow-repository` is
   false and the pinned branch exists, then **disables the push URL**
   (`git remote set-url --push origin DISABLED`) as defense in depth under
   ATLAS-REPO-003 — no component of Atlas ever gets a working push path.

4. **Update is a strictly ordered, journaled pipeline** (ATLAS-REPO-004),
   each run a JSON record (start, finish, status, error, SHAs):
   1. verify the remote URL still matches the pinned identity (abort on
      mismatch);
   2. verify the working tree is clean (`git status --porcelain`); dirty →
      abort with `local-modifications` finding, tree untouched;
   3. `git fetch origin <branch> --tags` (fetch failure leaves local refs
      unchanged by git's own semantics — last good state preserved);
   4. record previous local SHA and new remote SHA; unchanged → record
      `no-change` and stop;
   5. advance the working tree: fast-forward if ancestor, otherwise a
      **deterministic reset** to the fetched remote SHA with the
      non-fast-forward fact recorded (upstream rewrite is visible, never
      merged over); never any merge commit;
   6. write the change record, then run incremental indexing.
   The update interval is a config value (`update_interval_hours`) used
   only by the staleness policy until Q20 activates scheduling.

5. **One SQLite store** (`var/repotrack/repotrack.db`): `update_runs`
   (the ATLAS-REPO-004 journal), `change_ranges` (prev/new SHA, commit
   list, changed paths with additions/deletions from `git diff --numstat`,
   tags/releases encountered in the range, retrieval timestamp, indexing
   outcome, machine summary), `files` + `files_fts` (FTS5 over indexed
   content), `audit` (tool calls). The machine summary is generated from
   commit subjects and path statistics and stored with the fixed prefix
   `"[machine summary — not verified effect]"` so no downstream consumer
   can mistake it for analysis (ATLAS-REPO-005).

6. **Indexing is path-filtered, size-capped, and incremental**
   (ATLAS-REPO-006): text files at the tracked SHA (extension allowlist —
   Rust/TOML/Markdown/Python/YAML/scripts — plus a null-byte sniff, per-file
   size cap), one FTS row per file with path + indexed-at SHA. First run
   indexes the full tree at the pinned branch head; every later run
   re-indexes only the changed paths from the change range (delete rows for
   removed files). A bumped indexer schema version forces a recorded full
   rebuild. Index outcome (ok/failed, file counts) lands in the change
   record; the indexed SHA is stored so status can answer
   "index matches local SHA" truthfully (ATLAS-REPO-007).

7. **MCP server `atlas-repo` follows the `atlas-kb` shape** (stdlib
   JSON-RPC over stdio, structured errors with category/retry_safe/
   correlation id, append-only redacted JSONL call audit with the same
   size-capped rotation, no SQL/shell/HTTP surface — ATLAS-TOOL-002/003/004)
   with exactly four read-only tools:
   - `repo_search(query, max_results?)` → matching files with path,
     indexed SHA, and snippets; zero hits returns a structured
     `no-repository-evidence` result, never prose;
   - `repo_file(path, start_line?, end_line?)` → bounded file content read
     from the clone working tree **only after verifying tree-clean and
     index-SHA == local SHA**, with the SHA in the response; otherwise a
     structured staleness refusal;
   - `repo_changes(limit?)` → recent change ranges (SHAs, commits, paths,
     tags, labelled summary);
   - `repo_status()` → every ATLAS-REPO-007 field: local SHA, last-fetch
     remote SHA, last attempt, last success, last detected update, tree
     clean, index-matches-SHA, stale-per-policy (now − last success >
     configured interval × a stale multiplier), plus clone size.
   The DB opens read-only; the server never invokes a mutating git command
   (ATLAS-REPO-003 — enforced by construction and by the disabled push URL).
   If the store or clone is missing/unreadable it fails closed with
   `repository-tracking-unavailable`; it never claims currency it cannot
   prove (ATLAS-REPO-008).

8. **Scheduling stays gated, mechanism ready**: the CLI is cron/systemd
   friendly (non-interactive, exit codes, journaled), and the README carries
   a systemd timer template — but nothing is installed or enabled in this
   change. Activation = operator records Q20 in `docs/decisions.md`, sets
   `update_interval_hours`, and installs the timer (a natural bundle with
   the deferred Hermes service unit work). This matches §16 ("scheduled
   update after interval decision") without inventing the decision.

9. **Conviction evidence check is a documented one-off procedure, not a
   subsystem**: at acceptance, use `git log`/`git tag --contains`/
   `repo_search` over the validated clone to look for conviction-related
   code and parameter changes from v3.4.0-411 through July 2026, judge
   whether the repo alone confirms or refutes the ~2026-07-10/11 activation
   (an on-chain parameter flip may be invisible here), and record the
   finding — confirmed / refuted / repo-inconclusive-needs-chain-evidence —
   in `docs/decisions.md`. The knowledge unit itself is updated by the
   existing re-sync flow only after the finding is recorded.

10. **Testing mirrors Phase 2**: off-device pytest builds throwaway local
    git repos (origin + clone in tmp) to exercise every update path —
    normal fast-forward, upstream force-push → deterministic reset recorded,
    dirty tree abort, remote-URL mismatch abort, fetch failure preserving
    state, no-change run, incremental vs full index, schema-bump rebuild —
    plus MCP tool contract tests over a fixture store. The Pi run is
    acceptance: identity validation, real clone, real update, Hermes
    answering a repository question with commit + file reference.

## Risks / Trade-offs

- [The RaoFoundation claim may not survive validation (historical owner:
  opentensor)] → that is ATLAS-REPO-001 working as intended: setup blocks,
  the API redirect evidence goes to the operator, the confirmed canonical
  repo is recorded before any clone.
- [Upstream force-push/history rewrite] → deterministic reset path handles
  it; the change record marks the range non-fast-forward and the commit
  list as potentially incomplete rather than fabricating continuity.
- [Initial full index too heavy for the Pi] → extension allowlist + size
  caps bound it (subtensor's text content is tens of MB at most); measured
  at acceptance; incremental thereafter.
- [Anonymous GitHub rate limits or outage] → fetch is git-protocol (not
  API-limited); the API is used only for one-off identity validation; any
  failure fails closed and `repo_status` reports stale/unavailable — never
  falsely current (ATLAS-REPO-008).
- [Clone grows unbounded over years] → `repo_status` reports clone size;
  disk posture already governed by the 80/90 thresholds decision.
- [Working tree drifts from index between update and query] →
  `repo_file`/`repo_status` verify tree-clean + index-SHA match on every
  call and refuse with staleness info instead of serving mixed states.
- [Machine summaries read as analysis] → fixed warning prefix stored in the
  record itself, required by spec and pinned by tests.

## Open Questions

- Q20 (update interval) — operator decision; activates the scheduling
  mechanism, not this change's exit criteria.
- Q23 (anonymous vs token) — defaulting to anonymous read; recorded at
  apply time, reversible later without code changes.
- Which branch/release represents mainnet — an ATLAS-REPO-001 output,
  resolved and recorded during identity validation (expected:
  `main` + release tags, but not assumed).
- Hermes toolset identifier for the new server (expected `atlas-repo`,
  pinned during on-device acceptance like `atlas-kb` was).
