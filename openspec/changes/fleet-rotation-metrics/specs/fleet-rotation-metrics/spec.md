# fleet-rotation-metrics Specification

## ADDED Requirements

### Requirement: Emission-redirect map is extracted from current code, evidence-linked, and never executed

The metrics module SHALL derive, per `(netuid, epoch)`, an emission-redirect
map from the slot's checked-out clone by scanning only files on the configured
economic scan surface (reward/weight/scoring/emission code paths, tests, vendor,
docs, and examples excluded). It SHALL match configured route families
(burn, partner, treasury/dev-fund, owner-take, royalty/commission). A matched
symbol SHALL be recorded as a route ONLY when it also reads as a proportion (its
name carries a configured proportion token such as fraction/share/pct/take/cut),
or it carries a parseable fraction literal, or it carries a destination hotkey —
so incidental family-word variables (e.g. `is_burn`, `burn_uid`, `burned_epochs`)
are not mistaken for emission splits. Each recorded route SHALL carry one row per
`(kind, symbol, file)` with its `file:line` evidence, its fraction when a lone
`0..1` literal is parseable on the assignment line (NULL otherwise), and a
destination hotkey when an SS58 literal is present. Extraction SHALL fetch only
already-local blobs, SHALL never build, import, install, or execute clone code,
and SHALL cap routes per subnet with truncation recorded. A slot SHALL be
rescanned only when its `local_sha` differs from the last scanned sha.

#### Scenario: Live route with a parseable fraction is recorded with evidence

- **WHEN** a slot's reward-path file assigns a redirect constant to a literal
  fraction (e.g. `PARTNER_FRACTION = 0.35`)
- **THEN** a route row is recorded for that `(netuid, epoch, sha)` with kind,
  symbol, fraction `0.35`, the file and line, and (if present on/near the line)
  the destination hotkey

#### Scenario: Present-but-unparsed fraction is not fabricated

- **WHEN** a redirect constant is assigned from an expression rather than a
  literal (no parseable `0..1` on the line)
- **THEN** the route is still recorded with `fraction` NULL, rendered as "?",
  and never defaulted to zero or a guessed value

#### Scenario: Docstring mentions collapse into the assignment

- **WHEN** the same redirect symbol appears in docstrings/comments as well as
  its assignment line
- **THEN** only one route row per `(kind, symbol, file)` is produced, anchored
  to the assignment line

#### Scenario: Untrusted code is scanned but never run

- **WHEN** the emission map is (re)computed for any slot
- **THEN** only file reads occur; no build, import, install, hook, or execution
  of clone code is invoked

#### Scenario: Unchanged sha is not rescanned

- **WHEN** a metrics pass runs and a slot's `local_sha` equals its last scanned
  sha
- **THEN** its emission map is reused unchanged and no scan is performed

#### Scenario: Incidental family-word variable is not a route

- **WHEN** a scan-surface line assigns a symbol that merely contains a family
  word but is neither proportion-named nor carries a fraction or a hotkey (e.g.
  `is_burn = True`, `burned_epochs = []`)
- **THEN** no route is recorded for it, so the map surfaces emission splits
  rather than every mention of a routing concept

### Requirement: Runtime-configured economics are flagged opaque rather than guessed

When a slot's economic scan surface shows that burn/weight/emission values are
loaded from a remote source at runtime (configured remote-config vocabulary
co-occurring with economic vocabulary in the same file), the module SHALL set an
`economics_opaque` flag on that subnet's metric state and SHALL NOT infer or
fabricate the redirect values. Any statically parseable routes SHALL still be
recorded alongside the flag.

#### Scenario: Remote-config subnet is marked opaque

- **WHEN** a slot loads burn or weight configuration from a remote URL at
  runtime
- **THEN** its metric state carries `economics_opaque = true`, its dashboard row
  is labelled opaque, and no numeric split is invented for the remote-driven
  portion

### Requirement: Repo-activity is epoch-scoped and excludes fork history from ranking

The module SHALL record, per `(netuid, epoch)` per pass, default-branch commit
counts and distinct-author counts over trailing 7/30/90-day windows,
days-since-last-commit, and all-time totals. Ranking inputs SHALL use only the
windowed epoch-scoped figures; all-time totals SHALL be retained for context but
excluded from activity ranking so upstream fork history does not inflate a
subnet's apparent team or velocity.

#### Scenario: Windowed activity drives ranking, all-time is context only

- **WHEN** a slot's clone carries a large inherited upstream history but little
  recent own work
- **THEN** its ranked activity reflects the trailing-window commits/authors, and
  its inflated all-time author count does not raise its activity rank

#### Scenario: Activity is recorded per epoch

- **WHEN** activity is computed for a slot that has re-pointed
- **THEN** the recorded activity is tagged to the current epoch and does not
  blend the prior project's history

### Requirement: Branch pulse approximates off-default-branch activity without fetching

The module SHALL derive a branch-pulse metric from the per-slot branch-tips
snapshots recorded by the reconcile pass: `changed_tips` is the count of refs
added, removed, or moved versus the previous snapshot for that slot. It SHALL
NOT fetch branch contents or attempt to date branch commits. A slot whose
default branch is stale but whose tips change SHALL be classified as active on a
non-default branch, not as abandoned.

#### Scenario: Cold default branch with churning tips is not called dead

- **WHEN** a slot's default branch has not advanced within the staleness window
  but its `ls-remote` tip set changed since the previous pass
- **THEN** the slot is classified "active (non-default)" and is not placed on
  the fade list on staleness alone

#### Scenario: Truly idle repo reads as idle

- **WHEN** a slot's default branch is stale and its tip set is unchanged across
  passes
- **THEN** `changed_tips` is zero and the slot is eligible for fade
  classification

### Requirement: Alpha-price momentum reuses stored price vectors and degrades to n/a

Price momentum per subnet SHALL be computed from the existing `signal_prices`
vectors as the percent change between the oldest in-window and the latest
available vector over trailing 7/30-day windows, together with the fleet-median
momentum over the identical window. The module SHALL make no new price API call
and SHALL NOT backfill history. A window lacking sufficient stored history SHALL
render `n/a`, never an estimated value.

#### Scenario: Momentum computed from available history

- **WHEN** at least two `signal_prices` vectors exist within a window for a
  subnet
- **THEN** its momentum and the fleet-median momentum over that window are
  reported

#### Scenario: Insufficient history renders n/a

- **WHEN** a window lacks enough stored price history for a subnet
- **THEN** that momentum cell renders `n/a` and no value is fabricated or
  backfilled

### Requirement: Quadrant classifies by percentile rank, not a fitted score

The module SHALL compute a rotation quadrant placing each qualifying subnet by
price-momentum percentile (X, 7-day relative) and activity percentile (Y, 30-day
commits and `changed_tips`). The quadrant SHALL be presented as a lens over the
underlying columns, which remain visible; it SHALL NOT emit a recommendation or
a calibrated composite score.

#### Scenario: Subnet is placed by its percentile ranks

- **WHEN** the quadrant is rendered and a subnet has both an activity percentile
  and a momentum percentile
- **THEN** it is plotted in the corresponding region (accumulate / ride /
  ignore / fade) with its raw columns still shown in the table

#### Scenario: Subnet without momentum is not forced into a quadrant

- **WHEN** a subnet's momentum is `n/a` (insufficient price history)
- **THEN** it is listed with its activity metrics but not placed on the
  momentum axis, and no verdict is asserted for it

### Requirement: Metrics are available as CLI/JSON reports independent of the dashboard

The module SHALL expose CLI subcommands producing human-readable and JSON
reports for the emission map, activity, and combined ranked view, usable before
and independent of any dashboard render. A status subcommand SHALL report scan
watermarks, per-metric row counts, last computed time, and counts of slots that
failed or were truncated.

#### Scenario: Combined report before any dashboard exists

- **WHEN** the operator runs the ranked report subcommand after a metrics pass
- **THEN** it prints the per-subnet ranked metrics (and a `--json` form) without
  requiring the dashboard to be rendered or served

#### Scenario: Status surfaces coverage and failures

- **WHEN** the status subcommand runs
- **THEN** it reports watermark positions, row counts per metric, last computed
  time, and how many slots failed extraction or were truncated

### Requirement: Metrics are per-subnet fail-closed and never disrupt the fleet pass

Metric computation SHALL run inline after signals extraction in the hourly pass
and SHALL also be invokable standalone. A slot whose extraction, git query, or
scoring fails SHALL be recorded as failed for that pass and skipped without
blocking other slots, and metrics failures SHALL never count as reconcile or
signals process errors. The module SHALL write only additive metric tables in
the fleet store and SHALL be disableable via config without redeploy.

#### Scenario: One bad slot does not stop the metrics pass

- **WHEN** a slot's git log or scan fails during a metrics pass
- **THEN** that slot is recorded failed for the pass, remaining slots compute
  normally, and the reconcile/signals outcomes are unaffected

#### Scenario: Kill-switch disables metrics cleanly

- **WHEN** `metrics.enabled` is false in config
- **THEN** the hourly pass runs reconcile and signals with no metric
  computation or render, and no error is raised

### Requirement: The dashboard is a self-contained static page served LAN-only from an isolated directory

The render step SHALL write a single self-contained HTML file (inline styles and
scripts, no external asset fetches, no secrets) atomically into a dedicated
output directory that contains only rendered artifacts and never the store,
clones, or journals. It SHALL be served by a minimal static file server bound to
the local network only. The page SHALL present the ranked subnet table, the
quadrant, the emission map with evidence links, team-concentration groups, and
an invisible-fleet tier that lists no-repo / unreachable / placeholder-URL slots
explicitly as opaque, with per-source data-as-of timestamps.

#### Scenario: Only rendered output is under the served root

- **WHEN** the dashboard service serves its directory
- **THEN** the fleet store, clones, and journal files are not within the served
  root and cannot be retrieved through it

#### Scenario: Page renders without network access

- **WHEN** the rendered page is opened
- **THEN** it displays fully using only inline assets, with no request to any
  external host

#### Scenario: Invisible-fleet slots are shown, not dropped

- **WHEN** the fleet contains no-repo, unreachable, or placeholder-URL slots
- **THEN** the page lists them in an invisible-fleet tier marked opaque rather
  than omitting them

#### Scenario: Atomic render never serves a half-written page

- **WHEN** a render occurs while the page may be requested
- **THEN** the new file is written to a temporary path and renamed into place so
  a reader sees either the previous or the complete new page, never a partial
  one
