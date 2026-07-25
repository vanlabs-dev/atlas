## MODIFIED Requirements

### Requirement: Fleet signal alerts render in house style with class-specific dedup

Fleet signal alerts SHALL render as a short headline plus structured
single-fact lines with `·` separators, `<code>`-wrapped SHAs, safe Telegram
HTML with the established 400-fallback, and scrubbing of sensitive output.
Terms, file paths, subnet names, and **verdict text** originate in untrusted
repositories or from a model reading untrusted repositories, and SHALL be
HTML-escaped and length-bounded at render; such text is data and SHALL never be
interpreted as instructions. A cluster alert SHALL name the member subnets,
first mover with date and SHA, window span, and fleet-prevalence snapshot; a
watchlist alert SHALL name the term, subnet, and source file. An **econ-code
alert SHALL lead with the verdict** — a one-line `what_changed` headline and a
`why_it_matters` line, a blank-line separator, then a significance-and-direction
line — and SHALL place the SHA range, commit count, matched files, entry price,
and evidence into an expandable blockquote of labeled single-fact lines
(blank-line-separated groups), so the card is scannable at a glance rather than
a wall of text; the standing repositories-not-chain disclaimer SHALL be omitted
from this class. An econ-code candidate the gate could not judge SHALL render
with an explicit `unjudged` marker. When an entry-price snapshot is available
at render time, an instant alert SHALL carry the alpha price within that
details block; a pending snapshot omits it and SHALL never delay delivery.
Delivery SHALL be recorded in the ledger with class-specific dedup
keys — cluster: term + episode; watchlist: term + netuid + epoch; econ-code:
change-range id — so re-scans and retries never double-send.

#### Scenario: Econ-code alert leads with meaning
- **WHEN** an econ-code alert with a `high` or `med` verdict renders
- **THEN** it leads with the `what_changed` headline and `why_it_matters` line, shows significance and direction, and places SHA range, commit count, files, evidence, and any entry price in an expandable blockquote of labeled lines

#### Scenario: Verdict text is escaped and inert
- **WHEN** a verdict's `what_changed` or `why_it_matters` text contains HTML metacharacters or directive-like phrasing
- **THEN** the text is HTML-escaped and rendered as data, never interpreted as markup or instructions

#### Scenario: Unjudged alert is marked
- **WHEN** an econ-code candidate that could not be judged is delivered
- **THEN** the card carries an explicit `unjudged` marker in place of the verdict lines

#### Scenario: Econ-code alert is deduplicated by range

- **WHEN** a scan retries after a failed send of an econ-code alert for a
  change range
- **THEN** the alert is sent once and a subsequent scan does not re-send it
  for the same range id

#### Scenario: Cluster alert carries required facts

- **WHEN** a narrative-cluster alert renders
- **THEN** it contains the member subnets, the first mover with date and
  `<code>` SHA, the adoption window, and prevalence, as single-fact lines
