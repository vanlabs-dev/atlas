# Tasks: atlas-phase-3-subtensor-repository-tracking

Off-device work (WSL, fixture git repos) first; the Pi run is acceptance.
Operator gates are explicit tasks — nothing is assumed before it is recorded
in [docs/decisions.md](../../../docs/decisions.md).

## 1. Module scaffold and identity validation

- [x] 1.1 Create `repotrack/` scaffold: `atlas_repo.py` CLI skeleton
      (`validate-identity`, `setup`, `update`, `index`, `status`
      subcommands, non-interactive, exit codes), `schema/` with versioned
      JSON schemas for run/change records, `tests/`, `README.md` following
      `knowledge/` conventions (stdlib only, fail-closed, `var/repotrack/`
      outputs 0600/0700)
- [x] 1.2 Implement `validate-identity`: anonymous GitHub API metadata
      report (canonical full name / redirect detection, archived flag,
      default branch, clone URL) with fail-closed handling; report only,
      no state created
- [x] 1.3 Implement pinned-identity config (`repotrack/config.json`:
      owner, name, URL, branch, `update_interval_hours`, stale policy,
      index filters) and the setup guard that refuses to run without a
      recorded operator confirmation
- [x] 1.4 **Operator gate (ATLAS-REPO-001)**: run `validate-identity`
      against `RaoFoundation/subtensor`, resolve the
      RaoFoundation-vs-opentensor question, confirm owner/name, canonical
      URL, default branch, mainnet-representing branch, and Q23 access
      method (default: anonymous read); record the decision in
      `docs/decisions.md` and pin the config

## 2. Clone and safe update pipeline

- [x] 2.1 Implement `setup`: full clone to `var/repotrack/subtensor/`,
      non-shallow verification, pinned-branch check, push-URL disable,
      recorded setup report
- [x] 2.2 Implement the journaled `update` pipeline per design D4:
      remote-identity check → clean-tree check → fetch with tags →
      SHA recording → fast-forward or deterministic reset (non-FF
      recorded, never merge) → run record with start/finish/status/error
- [x] 2.3 Implement the SQLite store (`var/repotrack/repotrack.db`):
      `update_runs`, `change_ranges`, `files`/`files_fts`, `audit`;
      change records with all ATLAS-REPO-005 fields and the fixed
      machine-summary label
- [x] 2.4 Off-device tests with throwaway fixture repos covering: normal
      fast-forward, no-change run, upstream force-push → deterministic
      reset recorded, dirty-tree abort, remote-URL-mismatch abort, fetch
      failure preserving last good state

## 3. Indexing

- [x] 3.1 Implement the indexer: extension allowlist + null-byte sniff +
      size cap, full walk at tracked SHA on first run, FTS rows with path
      + indexed SHA, index outcome written into the change record
- [x] 3.2 Implement incremental re-index from change-range paths
      (including deletions) and the schema-version-bump full-rebuild path
- [x] 3.3 Off-device tests: changed-subset re-index, file removal, rebuild
      on schema bump, filter/caps behavior, indexed-SHA bookkeeping

## 4. MCP server (atlas-repo)

- [x] 4.1 Implement `atlas_repo_server.py` (stdio JSON-RPC, `atlas-kb`
      shape): `repo_search`, `repo_file` (tree-clean + index-SHA guard,
      bounded reads), `repo_changes`, `repo_status` (all ATLAS-REPO-007
      fields, stale-per-policy); DB read-only, structured errors,
      no-evidence and staleness-refusal results, append-only redacted
      call audit with size-capped rotation
- [x] 4.2 Off-device tool contract tests over a fixture store: provenance
      in every content result, no-match → structured no-evidence, dirty/
      mismatched state → staleness refusal, missing store → fail closed
      (`repository-tracking-unavailable`), read-only tool surface
      (no mutating git invocation anywhere in the server)

## 5. On-device acceptance (Pi)

- [x] 5.1 `git pull` on the Pi; run `setup` with the pinned identity;
      verify non-shallow, pinned branch, disabled push URL; run the
      initial index and record duration/size (bounds check)
- [x] 5.2 Run a real `update` cycle (normal case) and verify the run
      record, change record, and incremental index outcome; verify
      `status` answers every ATLAS-REPO-007 field and reports honest
      staleness with the network deliberately unavailable (ATLAS-REPO-008
      check)
- [x] 5.3 **Operator action**: register `atlas-repo` in the Hermes config
      (alongside `atlas-kb`), pin the toolset identifier, restart Hermes
- [x] 5.4 Exit-criteria check through live Hermes: a repository evidence
      question answered with commit SHA and file reference from tool
      results; unsupported repo question yields the structured no-evidence
      behavior
- [x] 5.5 Conviction-activation evidence check (design D9): search the
      validated history v3.4.0-411 → July 2026, judge
      confirmed / refuted / repo-inconclusive, record the finding in
      `docs/decisions.md` (corpus unit update goes through the existing
      re-sync flow separately)

## 6. Documentation and close-out

- [x] 6.1 Write `repotrack/README.md`: identity-validation procedure,
      setup/update/status usage, re-sync of pinned identity, the systemd
      timer template with the explicit Q20 activation gate (not installed
      in this change)
- [x] 6.2 Update `README.md` / `docs/decisions.md` phase status; record
      the acceptance entry (runs, SHAs, exit criteria) and any deviations;
      confirm Q20 remains open with the scheduling gate documented
