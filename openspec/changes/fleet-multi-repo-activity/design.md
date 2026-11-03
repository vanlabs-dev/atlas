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
