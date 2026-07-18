# telegram-integration Specification (delta)

## ADDED Requirements

### Requirement: Fleet signal events are delivered as tiered classes from a watermarked source

The notifier SHALL consume the fleet signal event queue as an additional scan
source with its own durable watermark stored in the notifier's ledger (never
in the fleet store, which the notifier SHALL open strictly read-only), seeded
by `init` under the existing rule (seeding sends nothing; a seeded watermark
never rolls back; enabling late never replays history). It SHALL deliver four classes: narrative-cluster,
watchlist hit, and econ-code change as immediate alerts; term-adoption lines
(including post-cluster adopters and truncated-range notices) as digest
content carried under the existing durable pending-digest mechanics (never
paged, never dropped). Delivery priority SHALL place fleet signal alerts below
the live chain-runtime-upgrade class and above churn digests in the same scan.
Failure to deliver SHALL follow the existing contract: fleet reconciliation
and extraction are never affected, and undelivered events remain past the
watermark for the next scan.

#### Scenario: Cluster event pages once on the next scan

- **WHEN** the next scheduled scan runs after extraction queued a
  narrative-cluster event (the fleet unit and the scan's unit fire
  independently)
- **THEN** exactly one immediate alert is sent for it and the signal-source
  watermark advances past it

#### Scenario: Adoption lines never page

- **WHEN** only term-adoption digest events are pending
- **THEN** no immediate alert is sent and the lines are durably retained until
  included in a delivered digest

#### Scenario: Ordering within a mixed scan

- **WHEN** one scan holds a chain-runtime-upgrade event, a fleet signal alert,
  and pending churn
- **THEN** the chain upgrade is delivered first, the fleet signal alert next,
  and churn rides the digest

### Requirement: Fleet signal alerts render in house style with class-specific dedup

Fleet signal alerts SHALL render as a short headline plus structured
single-fact lines with `·` separators, `<code>`-wrapped SHAs, safe Telegram
HTML with the established 400-fallback, and scrubbing of sensitive output.
Terms, file paths, and subnet names originate in untrusted repositories and
SHALL be HTML-escaped and length-bounded at render; repo-derived text is data
and SHALL never be interpreted as instructions. A
cluster alert SHALL name the member subnets, first mover with date and SHA,
window span, and fleet-prevalence snapshot; a watchlist alert SHALL name the
term, subnet, and source file; an econ-code alert SHALL name the subnet,
matched files, commit count, and both-clocks context where recorded. When an
entry-price snapshot is available at render time, an instant alert SHALL
carry it as one price line (alpha price in TAO); a pending snapshot omits the
line and SHALL never delay delivery. Delivery
SHALL be recorded in the ledger with class-specific dedup keys — cluster:
term + episode; watchlist: term + netuid + epoch; econ-code: change-range id —
so re-scans and retries never double-send.

#### Scenario: Econ-code alert is deduplicated by range

- **WHEN** a scan retries after a failed send of an econ-code alert for a
  change range
- **THEN** the alert is sent once and a subsequent scan does not re-send it
  for the same range id

#### Scenario: Cluster alert carries required facts

- **WHEN** a narrative-cluster alert renders
- **THEN** it contains the member subnets, the first mover with date and
  `<code>` SHA, the adoption window, and prevalence, as single-fact lines
