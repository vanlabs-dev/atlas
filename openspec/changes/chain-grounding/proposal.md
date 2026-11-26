# Proposal: chain-grounding

## Why

Cloud Claude sessions (phone, work laptop) cannot reach the Pi. They need a
short, current, machine-checked summary of how the Bittensor chain works.
The corpus in `knowledge/corpus/` is 220 KB, is served only through Hermes,
and is too large for one WebFetch on a phone.

The sessions will fetch
`https://raw.githubusercontent.com/vanlabs-dev/atlas/main/GROUNDING.md`
and treat it as stale when `last_updated` is more than 7 days old or
`spec_version` is behind the newest `v*` tag of opentensor/subtensor.

## What Changes

- New component `grounding/`, run hourly on the Pi by `atlas-grounding.timer`.
- **Detection** with no model: `git ls-remote` on opentensor/subtensor
  (`v*` tags, `main`) and `state_getRuntimeVersion` through the existing
  keyless finney RPC readers. A spec is live only when mainnet runs it.
  Code on `main` past the live tag is listed as pending.
- **Snapshots** `snapshots/<spec>/` on each new live spec: chain-wide and
  per-subnet parameters at one finalized block, the extrinsics and storage
  items (with defaults) of `SubtensorModule` and `AdminUtils`, and a facts-only
  `DIFF.md` against the previous snapshot. `livedata/scale_meta.py` gains
  call decoding.
- **Claims ledger** `grounding/claims.yaml`. Each claim cites a path and
  line range at a tag and lists the paths that would affect it. A new live
  tag marks every claim stale whose watched paths the tag diff touches.
- **Verification**: one worker `claude -p` per section with stale claims,
  reading only the source exported at the live tag. Code checks every
  citation and every number in the statement against the cited lines. A
  separate critic run, with no tools and no sight of the worker's output
  beyond the claims, checks each claim against its cited lines. Agreement
  updates the claim. Anything else shows as `UNVERIFIED (pending review)`
  next to the last verified text.
- **GROUNDING.md** at the repo root, generated from the ledger, at most
  25 KB, with YAML front matter (`spec_version`, `subtensor_tag`,
  `subtensor_commit`, `last_updated`, `content_changed`, `pending_on_main`,
  plus `newest_tag` and `newest_tag_live`).
- **Push** through the same gates as the upgrade job: worktree from
  `origin/main`, scope check against `grounding/allowed_paths.py`, test
  suites in the bubblewrap sandbox, author vaNlabs, the Atlas deploy key,
  read-back, `pull --ff-only`. The grounding job holds the upgrade job's
  lock, so the two never run at once.
- **Heartbeat**: with no content change, a `last_updated` commit at most
  once every 3 days.
- **gitleaks** in `tools/git-hooks/pre-commit` on the Pi, and in a local
  pre-commit hook on the workstation.

## Non-goals

- No change to the upgrade job's scope or the corpus.
- No historical chain state: public finney is not an archive node, so the
  first snapshot has no previous snapshot to diff against.
- No model-written code. The worker and the critic return JSON; code
  applies it.

## Impact

- New: `grounding/**`, `GROUNDING.md`, `snapshots/**`,
  `atlas-grounding.{service,timer}`.
- Changed: `livedata/scale_meta.py` (calls), `tools/git-hooks/pre-commit`,
  `tools/readme_sync.py`, `README.md`, `docs/decisions.md`.
- The Atlas deploy key gains a second caller (operator decision 1A,
  2026-11-27).
