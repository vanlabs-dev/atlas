# Proposal: upgrade-sandbox-scope

## Why

Audit WP5 (B2, A4, A17, C17) found the runtime upgrade job broader and less isolated than its task needs, and grounding the corpus on code that had not shipped:

- Its edit scope included chain reader code and config, which the job and the MCP servers later import. The scope should hold data only.
- The test and probe gates ran with the job's full user environment. They should run isolated, with no credentials.
- The edit session's file reads were not limited to its inputs.
- The scope check ran once, before the later gates.
- The spec diff and the source the model read ran to the clone HEAD (now spec 487, live 486). The spec-482 run stated unshipped 483 mechanics as live.
- The probe did not compare storage defaults, while Atlas hard-codes several.
- The upgrade job and the repotrack timer both run `atlas_repo.py update` with no lock. Both fired at 13:01:20 on 2026-11-03. Step timeouts sum to about 102 min against a 45 min unit timeout.

None of the 12 upgrade commits (spec 470 to 486) touched `livedata/` or added a file. Narrowing scope costs nothing observed.

## What Changes

- **BREAKING (operator workflow):** The edit scope becomes the knowledge corpus, `knowledge/supersession-markers.json` and `docs/decisions.md` only. `livedata/` leaves the allowed list.
  - A reader rename or reshape is no longer fixed by the job.
  - A failing chain-read probe on the base tree becomes a preflight `waiting` reason ("chain readers need an operator fix"). It uses no attempt and no model session.
  - This reverses the WP2 handover note that the job can fix a rename.
- The scope gate rejects any added file, a rename and a copy. It reads porcelain status codes.
- The scope gate runs again on the exact tree immediately before the commit in `step_push`.
- The test and probe gates run in a bubblewrap sandbox:
  - It gets system dirs only, a read-only worktree, and a private `/tmp` and HOME.
  - There is no `/run`, no D-Bus, no docker socket and no `~/.ssh`, `~/.hermes` or `~/.claude`.
  - It runs with a cleared environment and a PID namespace. Tests get no network.
  - The probe gets network but no secrets.
  - Before the gates, a canary runs in the same sandbox. The attempt fails closed if the canary sees any secret path, socket or sudo, or if it can write the worktree.
- The edit session's Read, Grep and Glob are scoped to the worktree, the live-spec source export and `var/upgrade`. Explicit denies cover `~/.ssh`, `~/.hermes`, `~/.claude` and `**/.env*`.
- The spec diff ends at the release tag `v<live>`.
  - Fallback: the commit that introduced `spec_version: <live>,`.
  - The spec at the anchor must equal live. If no anchor qualifies, the run waits ("no release anchor"), uses no attempt and never falls back to HEAD.
  - The diff start uses the same rule for the corpus spec.
  - The model reads a `git archive` export of the anchor, not the clone.
- A citation gate checks the corpus lines the edit adds:
  - A cited finalized block must be one this run read, or one the base corpus already cites.
  - No added line may name a spec above live as shipped or live.
- The probe also compares storage defaults. One declared table, `EXPECTED_DEFAULTS`, holds the default Atlas assumes for each item it hard-codes:
  - `SubnetOwnerCut`
  - the gate's `assumed_defaults`
  - the `chain_params` watch defaults
  - `SUBNET_PARAM_DEFAULTS`
  - The probe compares exact SCALE bytes with the metadata default. A test keeps the code and config defaults equal to the table.
- `atlas_repo.py update` takes an exclusive lock and waits a bounded time for it. The upgrade job holds the same lock while it reads the clone spec, builds the diff and exports the anchor.
- One overall run deadline:
  - Each pre-push step's timeout is capped at the time remaining.
  - The push sequence does not start unless its reserve remains.
  - `TimeoutStartSec` rises from 45 to 60 min, and a test keeps the deadline inside it.
- Out of scope: the KB battery gate before activation is deferred to WP13, after A6 makes its refusal scoring able to fail. The evidence markers are already checked against the edited corpus by `knowledge/tests` in the test gate.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `runtime-upgrade`: changes these requirements:
  - allowed scope (corpus only, no added files, re-check before the commit)
  - preflight (probe failure and a missing release anchor become waits)
  - gates (sandbox and canary, citation gate)
  - edit-session read scope
  - spec diff anchor
  - run deadline
- `chain-read-probe`: the probe checks storage defaults against declared expected defaults, and the default table is declared once.
- `subtensor-repo-tracking`: `update` is serialized by an exclusive lock that other callers share.

## Impact

- **Code:**
  - `upgrade/allowed_paths.py`
  - `upgrade/atlas_upgrade.py`
  - `upgrade/prompt.md`
  - new `upgrade/sandbox.py`
  - `livedata/atlas_probe.py`
  - `livedata/scale_meta.py` (keeps modifier and default bytes)
  - `livedata/atlas_live.py` (`EXPECTED_DEFAULTS`; constants derive from it)
  - `repotrack/atlas_repo.py` (update lock)
  - tests in `upgrade/tests`, `livedata/tests` and `repotrack/tests`
- **Units:** `upgrade/systemd/atlas-upgrade.service` (`TimeoutStartSec=60min`). The Pi needs a unit copy and `daemon-reload`.
- **Pi:** uses `/usr/bin/bwrap`, which is already installed. The hourly `atlas-probe` gains a default check. Run it from the workstation against live Finney before deploy, so the first hourly run does not page.
- **Docs:**
  - `docs/runtime-upgrade.md`
  - `upgrade/README.md`
  - AGENTS.md scope text (the job may not edit it, but the operator may)
  - `docs/decisions.md` entry for the scope narrowing
  - `tools/readme_sync.py`
- **Hermes:** MCP servers import `atlas_live`. After the pull, the operator runs `/restart` so they load the same module.
