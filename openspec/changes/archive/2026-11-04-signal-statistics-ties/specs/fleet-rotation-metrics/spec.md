## MODIFIED Requirements

### Requirement: Repo-activity is epoch-scoped and excludes fork history from ranking

The module SHALL record, per `(netuid, epoch)` per pass, default-branch commit
counts and distinct-author counts over trailing 7/30/90-day windows,
days-since-last-commit, and all-time totals. Ranking inputs SHALL use only the
windowed epoch-scoped figures; all-time totals SHALL be retained for context but
excluded from activity ranking so upstream fork history does not inflate a
subnet's apparent team or velocity. Windowed counts SHALL exclude commits whose
author address matches a configured list of bot and CI patterns, so automation
does not count as development activity.

#### Scenario: Windowed activity drives ranking, all-time is context only

- **WHEN** a slot's clone carries a large inherited upstream history but little
  recent own work
- **THEN** its ranked activity reflects the trailing-window commits/authors, and
  its inflated all-time author count does not raise its activity rank

#### Scenario: Activity is recorded per epoch

- **WHEN** activity is computed for a slot that has re-pointed
- **THEN** the recorded activity is tagged to the current epoch and does not
  blend the prior project's history

#### Scenario: Bot commits are not activity

- **WHEN** a slot's last 30 days hold 190 commits by an author address ending
  `[bot]@users.noreply.github.com` and 10 by a person
- **THEN** its 30-day commit count is 10 and its 30-day author count is 1

### Requirement: Alpha-price momentum reuses stored price vectors and degrades to n/a

Price momentum per subnet SHALL be computed from the existing `signal_prices`
vectors as the percent change between the oldest in-window and the latest
available vector over trailing 7/30-day windows, together with the fleet-median
momentum over the identical window. The module SHALL make no new price API call
and SHALL NOT backfill history. A window lacking sufficient stored history, or
whose vectors carry different registration blocks for the netuid, SHALL render
`n/a`, never an estimated value, and that netuid SHALL be left out of the
fleet median for the window.

#### Scenario: Momentum computed from available history

- **WHEN** at least two `signal_prices` vectors exist within a window for a
  subnet
- **THEN** its momentum and the fleet-median momentum over that window are
  reported

#### Scenario: Insufficient history renders n/a

- **WHEN** a window lacks enough stored price history for a subnet
- **THEN** that momentum cell renders `n/a` and no value is fabricated or
  backfilled

#### Scenario: Re-registration inside the window renders n/a

- **WHEN** a netuid was registered to a new subnet inside the 7-day window
- **THEN** its 7-day momentum renders `n/a` and the fleet median excludes it

### Requirement: The dashboard is a self-contained static page served LAN-only from an isolated directory

The render step SHALL write a single self-contained HTML file (inline styles and
scripts, no external asset fetches, no secrets) atomically into a dedicated
output directory that contains only rendered artifacts and never the store,
clones, or journals. It SHALL be served by a minimal static file server bound to
the local network only. The page SHALL present the ranked subnet table, the
activity and momentum percentiles, the emission map with evidence links,
team-concentration groups, and an invisible-fleet tier that lists no-repo /
unreachable / placeholder-URL slots explicitly as opaque, with per-source
data-as-of timestamps. The page SHALL NOT show a direction cue, a
promising/dangerous label or filter, or a sentence that says which way price
should move.

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

#### Scenario: Divergence is a neutral fact

- **WHEN** a subnet's activity percentile is 90 and its momentum percentile is
  20
- **THEN** the page states that the two are 70 points apart and shows no ▲ or
  ▼ cue, no promising or dangerous label, and no claim that the market has
  not priced the activity

## ADDED Requirements

### Requirement: Tied values share the average percentile rank

Percentile ranks SHALL give every member of a tie group the average of the
ranks the group occupies, so a subnet's rank never depends on its netuid or on
input order.

#### Scenario: Tie group shares one rank

- **WHEN** 24 of 113 subnets have an activity value of zero
- **THEN** all 24 receive the same activity percentile, 12/113

#### Scenario: Order does not change ranks

- **WHEN** the same values are ranked with their netuids in a different order
- **THEN** every netuid receives the same percentile as before

## REMOVED Requirements

### Requirement: Quadrant classifies by percentile rank, not a fitted score

**Reason**: The accumulate / ride / ignore / fade regions are trading cues
that were never measured against outcomes (audit D8). Operator decision
2026-11-03: drop the cue instead of shadow-measuring it.

**Migration**: The report keeps `activity_pct`, `momentum_pct` and the signed
divergence. The `quadrant` field is removed from the report rows. No stored
row holds it.
