# Proposal

## Why

Activity is read from the one repository a subnet names on chain. Some
subnets develop in several repositories, so the board calls them cold
when they are not. Seen 2026-11-04: SN64 Chutes tracks `chutesai/chutes`
(last push 2026-07-23) while the same organisation pushed `chutes-miner`
on 2026-10-10 and `sek8s` on 2026-10-15. The public site repeats the
error.

## What Changes

- A subnet's activity is read from every eligible repository of the
  GitHub organisation that owns its on-chain repository, not the on-chain
  repository alone.
- Organisation-wide reading is off for an organisation that several
  current subnets name on chain (today: macrocosm-os SN1/9/13, entrius,
  taostat, datura-ai, qbittensor-labs, barbariandev). Those subnets keep
  single-repository activity. Detected from chain identity, not a hand
  list (operator decision 2026-11-04).
- Personal (User) accounts are never read organisation-wide.
- Forks, archived repositories and repositories with no push in 90 days
  are not read. The operator can exclude any repository, or turn any
  organisation back to single-repository, in config.
- Extra repositories are fetched as commit history only: no files, no
  checkout, no scan, no index. Disk and size ceilings apply.
- Commits are combined per subnet, each counted once, bot authors
  excluded as today.
- Shadow first: the combined figures are recorded beside the current
  ones and listed per subnet with the repositories counted. The board,
  "cold", scores and signals switch only when the operator sets
  `activity.multi_repo` to `on`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `fleet-rotation-metrics`: activity may combine an organisation's
  repositories under eligibility rules, shadow then on.
- `subnet-repo-fleet`: history-only fetches of extra repositories, under
  the existing disk ceiling, never checked out.

## Impact

- `fleet/atlas_fleet_metrics.py` (activity), new
  `fleet/atlas_fleet_orgrepos.py` (listing and history fetch),
  `fleet/config.json`, `fleet/tests/`, fleet README, schema (new tables,
  new columns).
- New network call: GitHub REST `GET /orgs/{org}/repos`, unauthenticated,
  about 100 organisations a day, spread under the 60-per-hour limit.
- Disk: commit-only bare repositories; Chutes has 7 eligible.
- When switched on, c7/c30/a30/days-since move for multi-repo subnets,
  which moves attention scores, tiers, "cold" and the WP8 signal inputs.
- Pi deploy needed (pull, timer stop/start, operator approval).
- Depends on nothing in WP6; WP6's "in the tracked repository" wording
  is dropped once this is on.
- Out of scope: org-only on-chain identities (SN105, SN118 name
  `github.com/orgs/...` and are marked unreachable).
