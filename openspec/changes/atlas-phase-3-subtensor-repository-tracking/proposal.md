# Proposal: atlas-phase-3-subtensor-repository-tracking

Governing documents: [prd.md](../../../prd.md) (§12.6 ATLAS-REPO-001…009, §12.10
ATLAS-TOOL-001…004, §16 Phase 3) and
[docs/decisions.md](../../../docs/decisions.md): the repo-tracking placement
decision of 2026-07-12 (`https://github.com/RaoFoundation/subtensor`,
re-confirmed by the operator; formal ATLAS-REPO-001 identity revalidation
happens when this change starts), and the conviction-activation conflict (the
knowledge base's one `conflicting` unit — operator-reported activation
~2026-07-10/11, unverified, no GitHub release in that window — to be resolved
by Phase 3 repo/chain evidence).

## Why

Atlas can now answer from a validated but *dated* corpus (coverage 2026-06-25);
it has no view of what the protocol source has done since. Phase 3 gives Atlas
its first living evidence stream: a verified, non-shallow clone of the mainnet
subtensor repository with safe updates, recorded change ranges, an incremental
index, and read-only Hermes tools — so repository questions get commit-and-file
evidence instead of model memory, and the standing conviction-activation
conflict can finally be checked against repo evidence.

## What Changes

- **Repository identity validation gate** (ATLAS-REPO-001): before any clone,
  confirm owner/name, canonical clone URL, default branch, moved/archived
  status, and which branch/release represents mainnet. Any uncertainty blocks
  setup; the outcome is recorded in `docs/decisions.md`. (The 2026-07-12
  operator confirmation of `RaoFoundation/subtensor` is the starting claim,
  not the validation.)
- **Full clone on the Pi** (ATLAS-REPO-002): a non-shallow clone with complete
  reachable history under the Pi's gitignored `var/` area. No Bittensor node
  is hosted or run; no routine build is required or scheduled (ATLAS-REPO-009).
- **Safe update process** (`repotrack/atlas_repo.py`, ATLAS-REPO-004): manual
  `update`/`status` commands that verify remote identity, fetch changes and
  tags, record previous/new SHAs, advance the working tree only by
  fast-forward or deterministic reset to the confirmed remote branch, never
  merge, detect unexpected local modifications, and preserve the last good
  state on any failure (ATLAS-REPO-008). The update interval is configurable
  and **scheduling is not activated in this change** — PRD §21 Q20 (polling
  interval) is an open operator decision; per §16 the scheduled update comes
  only after that decision is recorded.
- **Change records** (ATLAS-REPO-005): every tracked commit range persisted
  with previous/new SHA, commit list, changed paths, additions/deletions,
  tags/releases encountered, retrieval timestamp, indexing outcome, and a
  machine-generated summary clearly labelled as a summary.
- **Incremental repository index** (ATLAS-REPO-006): text files at the tracked
  SHA indexed into a local SQLite/FTS5 store (same proven pattern as the
  knowledge base, kept separate from it); after the initial index, only
  changed files are re-indexed unless a schema/parser change forces a rebuild.
- **Read-only repository tools for Hermes** (`repotrack/atlas_repo_server.py`,
  stdio MCP, ATLAS-REPO-003): search/read/status tools that return content
  with commit SHA and file-path provenance, answer the ATLAS-REPO-007
  freshness questions (local/remote SHAs, last fetch attempt/success, tree
  clean, index-matches-SHA, stale-per-policy), and report **unavailable or
  stale — never "current"** when the remote cannot be reached
  (ATLAS-REPO-008). No push/rewrite/remote-modify capability exists anywhere
  in the tool surface; structured errors, no generic shell (ATLAS-TOOL-002/003),
  auditable calls (ATLAS-TOOL-004).
- **Conviction-activation evidence check**: a bounded, one-off investigation
  using the new tooling — search the tracked history around v3.4.0-411 and the
  June–July conviction changes for evidence bearing on the activation claim;
  record the finding (confirmed, refuted, or repo-inconclusive → chain
  evidence needed in Phase 4) in `docs/decisions.md` so the corpus re-sync
  flow can update the `conflicting` unit.
- Explicitly out of scope: scheduled/automated updates (gated on Q20),
  commit notifications (Q21, Phase 5 Telegram), TaoStats/TaoSwap live data
  (Phase 4), building or running subtensor, any write access to the tracked
  repository, and any change to the knowledge-base corpus content (the
  conviction unit is updated through the existing re-sync flow, upstream
  first).

## Capabilities

### New Capabilities

- `subtensor-repo-tracking`: A verified, non-shallow local clone of the
  mainnet subtensor repository with identity-validated setup, a safe
  fail-preserving update process with recorded change ranges, an incremental
  SQLite/FTS5 index of repository files, and read-only Hermes MCP tools that
  answer repository questions with commit and file references and report
  freshness honestly (stale/unavailable, never falsely current).

### Modified Capabilities

None. (`knowledge-base` is untouched — the repo index is a separate store and
a separate MCP server; the conviction unit's eventual update goes through the
already-specified corpus re-sync flow, not this change.)

## Impact

- **Device**: new full clone + SQLite repo index + change records under
  gitignored `var/` on the Pi (subtensor history is well within the 256 GB
  NVMe at 3% used); outbound HTTPS fetches to GitHub (anonymous read — PRD §21
  Q23 defaults to anonymous unless the operator supplies a token; recorded at
  apply time). The nftables inbound posture is unaffected.
- **Repo**: new `repotrack/` module (setup/update/status CLI, indexer, MCP
  server, tests) beside `knowledge/`, reusing its conventions (stdlib-only,
  fail-closed, schema-versioned records, off-device tests with fixtures).
- **Hermes**: gains a second stdio MCP server (`atlas-repo`) with read-only
  tools; registration is an operator action like `atlas-kb` was. Existing
  tools unchanged.
- **Decisions**: resolves ATLAS-REPO-001 identity validation and Q23 (access
  method) as recorded entries; Q20 (interval) stays open — the scheduler gate
  remains for a follow-up once decided; produces the conviction-activation
  evidence entry.
- **Downstream**: Phase 4 gets a freshness-honest repo baseline to contrast
  live chain data with; Phase 5 notifications can consume the change records.
