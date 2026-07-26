# Design — fleet-rotation-metrics

## Context

The fleet store (SQLite, WAL) already holds slots/epochs/change_ranges, the
signals tables (including per-pass full-fleet alpha-price vectors in
`signal_prices`), and the FTS file index. Clones are blobless, default-branch
working trees under `var/fleet/clones/<netuid>/`, never executed. The hourly
fleet pass runs reconcile → signals extraction inline. A validated on-device
sweep (2026-07-19, memory: atlas-fleet-sweep-findings) proved the signal exists
and pinned four traps this design must respect:

1. Default-branch staleness marks live majors (chutes, computehorde) as dead —
   real work happens on branches the fleet never sees.
2. All-time commit/author counts inherit upstream fork history (netuid 80:
   137 "authors").
3. Emission-routing evidence is real and live (netuid 54 `reward.py:485`) but
   raw SS58/keyword grep drowns in fixtures — scoping and evidence links are
   what made the sweep readable.
4. Netuids 37/45 load economics from remote URLs at runtime — code cannot
   yield their numbers, only the fact of opacity.

Operator constraints: single Pi, keep-it-simple, usable data before polish,
read-only over untrusted clones, no new external APIs, off-device tests.

## Goals / Non-Goals

**Goals:**
- Standing, epoch-scoped rotation metrics computed from data already on disk.
- Every number traceable to evidence (file:line, sha, or store row).
- Usable output from the first pass (CLI/JSON), dashboard as a pure renderer.
- Degrade honestly: young price history, unreachable repos, unparseable
  fractions all render as explicit gaps, never estimates.

**Non-Goals:**
- No template-ratio / code-similarity scoring (future change).
- No recommendations or automated trading signals — ranked evidence only.
- No historical price backfill (momentum columns mature as `signal_prices`
  accrues; no TaoStats quota spend).
- No auth/TLS on the dashboard (LAN-only by binding; not exposed).
- No per-branch history fetching — branch *pulse* only (tip churn), not
  branch content.

## Decisions

### D1. One metrics module, run inline at the end of the hourly pass
`fleet/atlas_fleet_metrics.py` with subcommands (`emissions`, `activity`,
`report`, `render`, `status`), invoked inline after signals in the hourly fleet
pass and standalone. Same pattern as signals: metrics failure is recorded and
never affects reconcile or signals outcomes. *Alternative rejected:* separate
timer/unit — more moving parts for zero freshness gain (inputs update hourly
anyway).

### D2. Emission map is a per-slot state snapshot, recomputed on sha change
Emission routing is a property of the *current* code, not a change stream —
so extraction scans the checked-out working tree, gated by `local_sha`: a slot
is rescanned only when its sha differs from the last scan (cold start scans
all). Rows are keyed `(netuid, epoch, sha)`; the latest row per slot is the
map. *Alternative rejected:* diff-driven extraction like signals — wrong shape
(a route removed years ago still matters as absence; state, not events).

Extraction mechanics, tuned from the sweep:
- **File scope**: paths matching the existing `econ_paths` vocabulary plus
  reward/weight/scoring filename patterns, `*.py` first-class; excluding
  tests/vendor/docs/examples. Config-listed under `metrics` in
  `fleet/config.json`, operator-tunable without redeploy.
- **Route patterns**: regex families per kind — burn
  (`burn_(fraction|pct|rate|ratio|uid|hotkey)`), partner/royalty/commission,
  treasury/dev-fund/team-wallet, owner-take/cut/share. A match on an
  *assignment* line yields a route row; a literal float `0..1` on that line
  populates `fraction`, otherwise `fraction` is NULL (present-but-unparsed,
  rendered as "?"). An SS58 literal on or adjacent to the line populates
  `dest_hotkey`.
- **Dedup + caps**: one row per (kind, symbol-name, file) — docstring mentions
  of the same constant collapse into the assignment row. Per-subnet route cap
  (config, default 40) with truncation recorded.
- **Opacity flag**: separate regex family for runtime-remote-config economics
  (`remote_config|fetch_config|config_url|dynamic_config` co-occurring with
  burn/weight/emission vocabulary in the same file). Sets
  `economics_opaque = 1` on the subnet's metric row; routes still recorded.
- **Derived miner-take**: `1 − Σ(parsed fractions of non-burn kinds…)` is NOT
  computed as a single authoritative number — the sweep showed fractions
  compose differently per subnet (54 funds partner from burn, not miners).
  Instead the report shows the route list with fractions and lets the ranked
  view sort by `Σ(parsed redirect fractions)` labelled as an upper bound.
  *Alternative rejected:* modelling each subnet's composition logic —
  unbounded per-subnet reverse engineering, precisely the overengineering
  this change must avoid.

### D3. Activity metric: windowed, default-branch, plus branch pulse
Per slot per pass: commits and distinct authors in trailing 7d/30d/90d windows
on the default branch (`git log --since`), days-since-last-commit, all
epoch-tagged. All-time totals are recorded for context but excluded from
ranking inputs (fork-history pollution). *Alternative rejected:* merge-base
fork detection — needs upstream identification per repo; deferred with
template-ratio.

**Branch pulse** (the chutes fix): the reconcile pass records per active slot a
`git ls-remote --heads origin` snapshot — JSON map `ref → sha` (capped at 200
refs), keyed `(netuid, epoch, pass)`. The metric is `changed_tips` = refs
added/removed/moved vs the previous snapshot. No fetch, no dating, one cheap
git call per slot. A slot whose default branch is cold but whose tips churn is
rendered "active (non-default)" — never "dead". `ls-remote` failure records
nothing for the slot that pass (fail-closed, non-blocking).

### D4. Momentum reuses signal_prices; columns appear as history permits
Alpha-price momentum per subnet = percent change over trailing 7d/30d using the
oldest in-window `signal_prices` vector vs latest, plus the same computed for
the fleet median (relative momentum, consistent with the effectiveness ledger's
baseline methodology). A window with insufficient history renders `n/a` —
columns fill in as retention grows. No backfill, no new API calls.

### D5. Quadrant = percentile ranks, not a fitted score
X = price-momentum percentile (7d relative), Y = activity percentile (30d
commits + changed_tips, equal weight). Plotted as an SVG scatter in the
dashboard with the four regions labelled (accumulate / ride / ignore / fade).
Raw columns stay visible in the table; the quadrant is a lens, not a verdict.
*Alternative rejected:* calibrated composite scores — no outcome history yet
to calibrate against; revisit after the effectiveness ledger matures (~mid-Aug).

### D6. Dashboard: one self-contained HTML file in a dedicated www dir
`render` writes a single self-contained `index.html` (inline CSS/JS, vanilla
sortable table, inline SVG quadrant, no external assets) atomically
(tmp + rename) into **`var/fleet/www/`** — a directory containing *only*
rendered output. Serving is `python3 -m http.server` as
`atlas-dashboard.service`, bound to the Pi's LAN address, port from config
(default 8480). **The bind-address + dedicated-directory pair is the security
boundary**: the store, clones, and journals are never under the served root.
*Alternatives rejected:* serving `var/fleet/` directly (exposes fleet.db);
Flask/FastAPI (a dependency and a daemon for zero added capability); Grafana
(wrong shape, heavy upkeep).

Page sections: ranked table (per subnet: activity windows, branch pulse,
staleness, momentum, redirect summary + opacity flag, org), quadrant SVG,
emission-map detail (routes with file:line evidence), team-concentration
groups, invisible-fleet tier (no-repo / unreachable / placeholder-URL slots
listed explicitly as opaque), footer with data-as-of timestamps per source.

### D7. Store: additive tables only, same WAL database
`metric_emission_routes(netuid, epoch, sha, kind, symbol, fraction, dest_hotkey,
file, line, scanned_at)`, `metric_activity(netuid, epoch, pass_ts, c7, c30,
c90, a30, last_commit_at, total_commits, total_authors)`,
`metric_branch_tips(netuid, epoch, pass_ts, tips_json, tips_count,
changed_tips)`, `metric_state(key, value)` for watermarks/render bookkeeping.
Existing tables untouched; only fleet-side processes write (unchanged rule).

### D8. Team concentration is derived at render time
Org = second path segment of `github_repo`, lowercased; placeholder orgs
(`deprecated`, `orgs`, obvious junk — config list) excluded. Groups with >1
subnet render as correlated-fate clusters. No table needed — computed from
`slots` on render. *Alternative rejected:* commit-author identity graph across
repos — email normalization and privacy questions; org overlap delivers most
of the value free.

## Risks / Trade-offs

- [Regex noise in emission map] → evidence links on every row, per-subnet caps,
  config-tunable patterns, and assignment-line + symbol-dedup rules from the
  sweep; the map is ranked evidence for a human, not an oracle.
- [Unparseable fractions understate redirects] → NULL fraction renders "?" and
  the subnet sorts by count of routes too; never silently zero.
- [104 `ls-remote` calls/pass to GitHub] → plain git protocol, no API quota;
  spread already by the pass; failure per slot is recorded-and-skipped. If
  GitHub throttles unauthenticated ls-remote, existing optional GITHUB_TOKEN
  applies to git URLs.
- [Momentum columns empty for ~weeks] → rendered as `n/a` with an explicit
  "price history since" note; activity/emission value is independent and
  immediate.
- [http.server is single-threaded/simple] → acceptable for one LAN viewer;
  static file means worst case is a slow load, never data corruption.
- [Branch pulse counts CI/bot branch churn as activity] → displayed alongside
  default-branch velocity, not instead of it; tips_count trend visible so a
  branch-farm anomaly is inspectable.
- [Docstring/comment false positives that survive assignment filtering]
  → accepted residual; evidence link makes each one a 5-second manual check.

## Migration Plan

1. Ship module + tables (auto-created on first metrics run; additive only).
2. Enable inline metrics step in the hourly pass (config-gated,
   `metrics.enabled`, default on; kill-switch without redeploy).
3. First on-device run: `emissions` cold-start scan (~104 slots, local regex
   only), `activity` backfill from `git log` (local), verify CLI report.
4. Install + start `atlas-dashboard.service`; verify LAN reachability and that
   only `www/` is served.
5. Rollback: disable config gate and stop the service; tables are inert data.

## Open Questions

- Dashboard port (default 8480) and whether the Pi's address should come from
  config or bind to all interfaces behind the home router — operator call at
  deploy time.
- Whether `changed_tips` should ignore deletions (a mass branch-cleanup reads
  as a pulse spike); start counting all changes, revisit with real data.
