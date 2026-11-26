## ADDED Requirements

### Requirement: Hourly detection without a model

The job SHALL run hourly. Each run SHALL read the `v*` tags and `main` of
opentensor/subtensor with `git ls-remote`, and the live `spec_version`
with `state_getRuntimeVersion` at the finalized head through the keyless
finney RPC readers. A spec SHALL count as live only when mainnet runs it.
When the live spec, the newest tag and `main` are unchanged since the last
successful run, no claim is stale or queued, no push is pending and no
heartbeat is due, the run SHALL record the successful check and exit
without a worktree, a model call or a commit.

#### Scenario: Nothing moved
- **WHEN** a run sees the same live spec, newest tag and `main` as the
  last successful run, with no backlog and no heartbeat due
- **THEN** it records `last_success` and exits 0 without other work

#### Scenario: Detection fails
- **WHEN** ls-remote or the RPC read fails on three runs in a row
- **THEN** the job sends one Telegram report and exits 0 each time

### Requirement: Snapshots on a new live spec

On the first run that sees a live spec without `snapshots/<spec>/`, the
job SHALL write, from one finalized block: the extrinsics and storage items
(with metadata defaults) of `SubtensorModule` and `AdminUtils`, every
plain `SubtensorModule` value except declared running state, and the
configured per-subnet parameters for every registered subnet. It SHALL
write `DIFF.md` with facts only against the highest earlier snapshot, and
commit the snapshot without a model. A failed read SHALL write nothing.

#### Scenario: First snapshot
- **WHEN** no earlier snapshot exists
- **THEN** `DIFF.md` states that there is nothing to compare

#### Scenario: New extrinsic
- **WHEN** the diff finds an added extrinsic or storage item
- **THEN** the item is queued for re-check in the section its name maps to

### Requirement: Claims ledger and stale detection

`grounding/claims.yaml` SHALL hold every claim with id, section,
statement, evidence (path, line range, tag, commit, PR when known),
`live_since_spec`, status (`live`, `pending` or `deprecated`),
`last_verified` (UTC) and `watched_paths`. When the live tag changes, the
job SHALL compute `git diff <old_tag>..<new_tag> --name-only` and mark
stale every claim whose watched paths or evidence paths match a changed
file. Only stale claims and queued items SHALL be re-checked.

#### Scenario: Release touches a watched file
- **WHEN** the release diff changes a file a claim watches
- **THEN** that claim is marked stale and the others are not

### Requirement: Verification by worker, code check and critic

For each section with stale claims, up to a per-run cap and inside the run
deadline, the job SHALL run one worker `claude -p` that reads only the
source exported at the live tag (and the corpus as leads), cannot edit
files or run commands, and returns JSON. Code SHALL reject a claim whose
citation is not a line range of a file at the tag, or whose statement holds
a number or backticked name that is not in the cited lines, or whose
hyperparameter default differs from the runtime metadata default. A
separate critic `claude -p` with no tools SHALL see only each claim and the
text of its cited lines. A claim the critic agrees with SHALL be applied.
Any other outcome SHALL mark the claim `UNVERIFIED (pending review)` and
keep its last verified text. The model SHALL never write a file.

#### Scenario: Critic disagrees
- **WHEN** the critic disagrees with a rewritten claim
- **THEN** the claim keeps its last verified text and shows as UNVERIFIED
  with the proposed text and the reason

#### Scenario: Number not in the cited lines
- **WHEN** a statement states a number the cited lines do not hold
- **THEN** the claim is UNVERIFIED and the critic is not asked about it

#### Scenario: Worker keeps failing
- **WHEN** the worker for a section fails three runs in a row
- **THEN** that section's stale claims show as UNVERIFIED

### Requirement: GROUNDING.md is generated and small

`GROUNDING.md` SHALL be the render of `claims.yaml` and SHALL stay under
`max_bytes` (25,600). Its YAML front matter SHALL hold `spec_version`,
`subtensor_tag`, `subtensor_commit`, `newest_tag`, `newest_tag_live`,
`last_updated` (the run that made the commit), `content_changed` and
`pending_on_main`. It SHALL have the nine sections of the operator brief,
each claim ending in a short ref (tag and path:lines). A test SHALL fail
when the committed file is not the render of the committed ledger.

#### Scenario: Hand edit
- **WHEN** GROUNDING.md differs from the render of claims.yaml
- **THEN** the grounding test suite fails and the job will not push

### Requirement: Push through the upgrade job's gates

The job SHALL hold the upgrade job's lock for the whole run. It SHALL
commit only `GROUNDING.md`, `grounding/claims.yaml` and
`snapshots/<spec>/` files, as vaNlabs, after the gitleaks hook, the size
and render checks, the sandbox canary and every test suite in the
sandbox. It SHALL push with the Atlas deploy key, never forced, read the
remote back, and never pull the live tree. A failed push SHALL keep the
commits and retry them, rebased onto `origin/main`, on the next run.

#### Scenario: Push rejected
- **WHEN** `main` moved and the push is rejected
- **THEN** the next run rebases the kept commits and pushes them

### Requirement: Heartbeat

With no content change, the job SHALL commit a `last_updated` refresh at
most once every 3 days, so a healthy system never looks stale to a reader
that treats 7 days as stale.

#### Scenario: Quiet week
- **WHEN** nothing changes for 3 days
- **THEN** one heartbeat commit updates `last_updated` only

### Requirement: Citation retry for missing links

The critic SHALL label each rejection `missing_context` or `wrong`. A claim
rejected only as `missing_context`, or by the code check only for a
backticked name absent from its cited lines, SHALL get one worker run that
extends its citations (narrowing the statement, never widening it) and a
second critic pass. A `wrong` rejection SHALL get no retry.

#### Scenario: Missing binding
- **WHEN** the critic rejects a claim because a constant's binding is not
  cited, and the retry cites it
- **THEN** the second critic pass decides the claim

#### Scenario: Substance
- **WHEN** the critic rejects a claim as `wrong`
- **THEN** it stays UNVERIFIED with no retry

### Requirement: Seeded traps and dating by release

`claims.yaml` SHALL hold an operator seed list of historical mechanisms.
Each seed SHALL get exactly one claim in section 8, verified like any
other; a seed without one SHALL show as UNVERIFIED. Old code for a seed
SHALL come from an export at the last release that held the seed's removed
string, citable as `spec-<N>`. Releases SHALL be dated from mainline
release bumps, and a trap's stop release from where its marker string
changed state in every later release.

#### Scenario: Removed mechanism without a Deprecated error
- **WHEN** the `tao-flow` seed is re-checked at v497
- **THEN** section 8 holds a tao-flow claim dated by the release since
  which `Self::get_shares_flow(` is absent
