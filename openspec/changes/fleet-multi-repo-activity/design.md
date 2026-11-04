# Design

## Context

See proposal.md. Checked 2026-11-04 (Pi read-only, GitHub API
unauthenticated):

- 102 owners across 128 slots. 6 owners are named by several current
  subnets: macrocosm-os (1, 9, 13), entrius (7, 74), taostat (19, 28),
  datura-ai (22, 51), qbittensor-labs (48, 63), barbariandev (123, 125).
  `orgs` (105, 118) is a parse artefact of `github.com/orgs/...` URLs.
- chutesai: 54 public repositories, 7 not forked, not archived and pushed
  since 2026-08-06.
- SN1 apex is cold correctly: its recent commits are all from a CI bot.
- Single-subnet organisations can also host unrelated products. latent-to
  (SN14 `cacheon`) also holds `developer-docs`, `aio-substrate-interface`,
  `TAOApp-specs`, `vtao`, `cyscale`. Organisation-wide reading would credit
  that work to SN14. The shadow report exists to catch this before it is
  switched on.

## Goals / Non-Goals

**Goals:** correct cold and activity for multi-repo subnets; no commit
credited to the wrong subnet without the operator seeing it first.

**Non-Goals:** scanning, indexing or mining-feasibility reads of extra
repositories; an authenticated GitHub token; org-only identities.

## Decisions

1. **Eligibility from chain identity.** Shared owners are computed each
   pass from the current slots, so a new shared organisation is caught
   without a config edit. Config adds `activity.multi_repo`
   (`off|shadow|on`, default `shadow`), `activity.exclude_repos`
   (`owner/name` list), `activity.single_repo_owners`, `activity.max_repos`
   (default 20 most recently pushed), `activity.max_repo_bytes`.
2. **Listing.** stdlib `urllib` GET `/orgs/{owner}/repos?per_page=100&
   sort=pushed`, one page; owner type from `/users/{owner}` cached with it.
   Table `org_repos(owner, fetched_at, ok, repos_json)`. At most
   `ceil(owners / 4)` calls per pass (4 passes a day), oldest first, so
   every owner refreshes daily at about 26 calls a pass, under 60 per
   hour. Alternative: the GitHub events API. Rejected: 90-day reach is
   not guaranteed and it pages heavily.
3. **History-only bare repository.** `git clone --bare --filter=tree:0
   --no-tags --single-branch` under `<clone_root>/activity/<owner>/<name>.git`,
   then `git fetch` per pass, with the WP7 disk check before each and
   `count-objects -v` against `max_repo_bytes` after. `--filter=tree:0`
   keeps commits only; `git log --format=%H%x09%cI%x09%ae` needs no trees.
   No file path is ever opened, so file containment is not involved.
4. **Union.** `compute_activity` gains a commit-id key: commits from all
   counted repositories are merged and deduplicated by `%H` before the
   bot filter and windows. Stored as new columns on `metric_activity`
   (`c7_all`, `c30_all`, `c90_all`, `a30_all`, `days_since_all`,
   `repos_counted`) plus `metric_activity_repos(netuid, epoch, pass_ts,
   repo, c30, last_commit_at)` for the report.
5. **Switch.** One function chooses the figure set from
   `activity.multi_repo`; the board, `_classify_activity`, the dashboard,
   the export and the signals read through it. In `shadow` the output is
   byte-identical to today (test).

## Implementation notes (apply, 2026-11-04)

- `git log` in a `tree:0` repository fetches the missing trees from the
  remote on demand (seen with git 2.43). History is read with
  `git rev-list --no-merges --no-commit-header --format=...` instead; a
  test asserts the bare repository holds only commit objects after the
  clone, a fetch and a read.
- A bare clone records no fetch refspec, so a plain `fetch` would not move
  the branch. The clone sets `remote.origin.fetch` to the default branch.
- `metric_activity` also gets `last_commit_at_all` and `single_why`. The
  spec requires the report to say why a subnet kept one repository
  (shared owner, personal account, operator, no or stale listing, no
  history); the decision 4 columns had no place for it.
- `org_repos` also keeps `owner_type`, `attempted_at` and `last_error`, so
  a failed refresh keeps the last good listing and records the error.
  `org_repos_state` holds the rate-limit hold (403 with
  `X-RateLimit-Remaining: 0`, or 429).
- Budget: `ceil(owners / 4)` calls a pass, capped at `max_calls_per_pass`
  (50). While any owner has no listing yet, the pass may use the full cap,
  because a first listing costs two calls (owner type, then repositories).
  Shared, placeholder and operator single-repository owners are never
  listed.
- `max_new_histories_per_pass` (40) bounds first clones, like
  `max_new_clones_per_pass`. A history over `max_repo_bytes` (256 MiB,
  measured on disk) is removed and not retried for 7 days.
- The code default for `multi_repo` is `off`, so a store or test without
  the block never calls GitHub. `fleet/config.json` sets `shadow`. Fleet
  tests replace the default opener with one that raises.
- Signals do not read activity directly; they reach it only through
  `report()`. subnt's `SUM(c7 > 0)` reads the single column directly; its
  publisher timer is masked, so it is left as is.
- Readers tolerate an unmigrated store (read-only MCP or export before the
  first new pass): the combined columns read as null.

## Risks / Trade-offs

- [Unrelated repositories in a single-subnet organisation] → shadow
  report per subnet; operator exclusions before `on`.
- [Rate limit shared with other unauthenticated GitHub calls from the Pi]
  → budget per pass, back off on 403/429, keep last listing.
- [Scores and WP8 signal inputs move on switch] → recorded as a dated
  decision; the switch is a config change the operator makes.
- [Disk] → commit-only history, size cap, disk ceiling.

## Migration Plan

Deploy in `shadow` (Pi pull with timers stopped, approval). After a few
passes, review the report with the operator, set exclusions, then set
`on` in a separate approved commit. Rollback: `off` or `shadow`; extra
history directories can be deleted freely.

## Open Questions

- Whether SN105 and SN118 (org-only identities) should get org activity
  later. Does not change this design.
