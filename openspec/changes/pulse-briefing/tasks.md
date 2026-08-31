## 1. Livedata: snapshot, vitals, gate rules

- [ ] 1.1 Add `panel_snapshot` (block, netuid, share, and the listed panel
  fields; nulls for absent fields) written in the gate poll's pass, with a
  configured retention prune
- [ ] 1.2 Add `network_vitals` and a once-per-day fetch of `network_stats`
  and `price_daily` through the existing adapters; health event on failure
- [ ] 1.3 Treat a zero or missing moving price as a missing observation for
  side tracking (no crossing, counts toward absence) while keeping the
  subnet in the normalization universe
- [ ] 1.4 Add the hovering flag to `gate_sides` (rolling crossing count,
  configured threshold and window) and a `hovering` column on
  `gate_events`; clear the flag after a stable window
- [ ] 1.5 Tests: snapshot row per subnet with share, null fields, prune,
  one vitals row per day, zero-price gap, hovering flag set, annotated, and
  cleared
- [ ] 1.6 Livedata suite green off-device

## 2. Judge anchors and routing

- [ ] 2.1 Add the four level definitions and the payout-path rule to the
  judge config block and inject them verbatim into the prompt
- [ ] 2.2 Route `high` and `med` as econ-code events carrying the verdict,
  `low` as digest lines, `none` dropped but persisted; keep the high-stakes
  floor
- [ ] 2.3 Tests: prompt contains anchors, routing per level, floor holds
- [ ] 2.4 Fleet suite green off-device

## 3. Notifier: tiers, merge, new instant classes

- [ ] 3.1 Add `tier` to every class in `telegram/config.json` (ship with
  current behaviour: all instant) and route in `scan`; add ledger status
  `briefed`
- [ ] 3.2 Runtime upgrade message joins the matching repository range for
  the release subject and top areas; states when none is recorded
- [ ] 3.3 Add the `subnet-registry` class over consecutive snapshots (netuid
  set and name changes; first snapshot seeds silently)
- [ ] 3.4 Add the fail-closed page over `integration_health` with a
  configured window, keyed by outage start
- [ ] 3.5 Tests: briefing-tier event recorded not paged, tier flip restores
  paging, hovering crossing suppressed at instant tier, runtime merge with
  and without a range, registry seed and change, fail-closed once per outage

## 4. Notifier: briefing builder

- [ ] 4.1 Edition watermarks (`daily:<date>`, `weekly:<iso-week>`), hour
  and weekday config, catch-up on the next scan, weekly replaces daily
- [ ] 4.2 Figure set per edition persisted as JSON for deltas; first edition
  renders without deltas and says so
- [ ] 4.3 Network section: spec plus release subject, parameter
  transitions, theta and change, rank, above-bar count, side changes,
  vitals with dates
- [ ] 4.4 Subnets section: price movers over threshold, share movers, net
  flow leaders, dereg watch, contested and takeover-eligible, hoverer count
- [ ] 4.5 Code and narrative sections: pushed count, `high` verdicts with
  one-line verdict and commit, `med` count, re-points, model-id adoptions
  and clusters only
- [ ] 4.6 Mining section: head, ranked and cut counts, top-ten entries and
  exits, budget band unset notice
- [ ] 4.7 Atlas section: provider failures and drift by provider, above-bar
  count distribution, quota, last ingest, stalled watermarks
- [ ] 4.8 Priority truncation (whole lines, network never cut, omission
  count), message bound, closing line rule (next action or board link),
  lexicon and gloss pass
- [ ] 4.9 Tests: no provider or model call during composition, stale input
  named, section order, deltas, first edition, one edition per day, catch-up,
  weekly replaces daily, truncation order, closing line
- [ ] 4.10 Telegram suite green off-device

## 5. Documentation

- [ ] 5.1 `telegram/README.md`: tiers, briefing sections and schedule, new
  classes, ledger status `briefed`
- [ ] 5.2 `livedata/README.md`: snapshot, vitals, zero-price and hovering
  rules
- [ ] 5.3 `README.md` telegram and live-data rows; decision log entry for
  the alert audit figures (333 alerts, class shares, hovering and zero-share
  counts, judge distribution)

## 6. Deployment and acceptance

- [ ] 6.1 Push; `git pull` on the Pi; suites green under system Python
- [ ] 6.2 Confirm the first snapshot and vitals rows, the registry seed, and
  snapshot size after 24 hours
- [ ] 6.3 Read the first two daily editions (first without deltas); confirm
  no provider or judge calls were made during composition from the audit
  tables
- [ ] 6.4 Flip the six classes to `briefing` in one commit; confirm the
  ledger records `briefed` and nothing pages except instant classes
- [ ] 6.5 After the first weekly edition: record instant count for the week,
  the verdict distribution, and the hoverer list in the decision log; close
  the gate calibration read
