# Tasks — fleet-rotation-metrics

Ordered so usable data lands first: emission map + activity CLI reports ship
value before any dashboard exists; branch pulse and the served page follow.

## 1. Store + config foundation

- [x] 1.1 Add additive tables to the fleet store schema (idempotent
  `CREATE TABLE IF NOT EXISTS`): `metric_emission_routes`, `metric_activity`,
  `metric_branch_tips`, `metric_state`; confirm no existing table is altered.
- [x] 1.2 Add a `metrics` block to `fleet/config.json` (enabled flag, scan
  surface + exclusions, route-family regexes, opacity regexes, per-subnet route
  cap, activity windows, `ls_remote_ref_cap`, momentum windows, placeholder-org
  list, dashboard port, www dir) with a `_comment` documenting each key.
- [x] 1.3 Create `fleet/atlas_fleet_metrics.py` skeleton (read-only store open,
  config load, subcommand argparse: `emissions`, `activity`, `report`,
  `render`, `status`) following the signals-module conventions.

## 2. Emission-redirect map (first-class metric)

- [x] 2.1 Implement scan-surface file selection over a clone (config paths +
  filename patterns, tests/vendor/docs/examples excluded), reading only local
  files, never executing.
- [x] 2.2 Implement route extraction: per-family regex over assignment lines,
  fraction parse (literal `0..1` → value, else NULL), SS58 dest-hotkey capture,
  dedup to one row per `(kind, symbol, file)`, per-subnet cap with truncation
  recorded; write `(netuid, epoch, sha)` rows.
- [x] 2.3 Implement opacity detection (remote-config vocabulary co-occurring
  with economic vocabulary) setting `economics_opaque` in `metric_state`.
- [x] 2.4 Gate rescans on `local_sha` change (cold start scans all; unchanged
  sha reuses prior rows).
- [x] 2.5 `emissions` CLI report (text + `--json`): per subnet routes with
  file:line evidence, fraction (or "?"), dest hotkey, opacity flag, and
  Σ(parsed redirect fractions) as a labelled upper bound.
- [x] 2.6 Off-device unit tests with fixture repos: parseable fraction,
  expression fraction (NULL), docstring-dedup, opaque remote-config, cap
  truncation, sha-unchanged skip.

## 3. Repo-activity metric

- [x] 3.1 Implement epoch-scoped windowed activity from `git log --since`
  (commits + distinct authors over 7/30/90d, days-since-last-commit) plus
  all-time totals recorded as context-only; write `metric_activity` rows.
- [x] 3.2 Ensure ranking inputs exclude all-time totals (fork-history guard);
  verify against a fixture repo carrying large inherited history.
- [x] 3.3 `activity` CLI report (text + `--json`) with the windowed columns and
  a staleness classification placeholder (finalized once branch pulse lands).
- [x] 3.4 Off-device tests: windowed vs all-time separation, epoch tagging,
  empty/idle repo.

## 4. Branch pulse (fleet delta + metric)

- [x] 4.1 In the reconcile pass, record a bounded `git ls-remote --heads`
  tip snapshot per active slot (`ref → sha`, capped), fail-closed and
  non-blocking per slot; write `metric_branch_tips` rows scoped to
  `(netuid, epoch, pass)`.
- [x] 4.2 Derive `changed_tips` vs the slot's previous snapshot (added/removed/
  moved refs); no fetch, no dating.
- [x] 4.3 Finalize activity classification: cold default branch + churning tips
  → "active (non-default)"; cold + unchanged tips → fade-eligible.
- [x] 4.4 Off-device tests: tip added/removed/moved counts, first-snapshot
  (no prior) case, ls-remote failure records nothing, epoch-scoped comparison.

## 5. Momentum + quadrant

- [x] 5.1 Compute per-subnet and fleet-median momentum (7/30d) from
  `signal_prices`; insufficient history → `n/a`, no backfill, no new API call.
- [x] 5.2 Compute activity and momentum percentiles and quadrant region per
  qualifying subnet; subnets with `n/a` momentum kept off the momentum axis.
- [x] 5.3 Combined `report` subcommand (text + `--json`): ranked per-subnet view
  joining activity, branch pulse, momentum, redirect summary, org.
- [x] 5.4 Off-device tests: momentum n/a path, percentile edges, quadrant
  placement, subnet excluded from axis.

## 6. Static dashboard render

- [x] 6.1 Implement `render`: build one self-contained `index.html` (inline
  CSS/JS, inline SVG quadrant, sortable table, no external assets, no secrets)
  and write atomically (tmp + rename) into `var/fleet/www/`.
- [x] 6.2 Page sections: ranked table, quadrant SVG, emission-map detail with
  evidence links, team-concentration groups, invisible-fleet tier
  (no-repo/unreachable/placeholder-URL as opaque), per-source data-as-of footer.
- [x] 6.3 Off-device tests: page renders with zero external requests, half-empty
  price history shows `n/a`, invisible-fleet slots present, atomic write leaves
  no partial file.

## 7. Pass integration + serve unit

- [x] 7.1 Hook the metrics step (emissions + activity + render) inline at the
  end of the hourly fleet pass, after signals; per-subnet fail-closed, metrics
  failures never counted as reconcile/signals errors; honor `metrics.enabled`.
- [x] 7.2 `status` subcommand: watermarks, per-metric row counts, last computed
  time, failed/truncated slot counts.
- [x] 7.3 Add `atlas-dashboard.service` systemd unit (`python3 -m http.server`
  serving `var/fleet/www/` only, bound to LAN, port from config) with README
  install notes; verify the store/clones are outside the served root.

## 8. On-device bring-up (Pi)

- [x] 8.1 Deploy via git pull; auto-create tables; run `emissions` cold-start
  scan over the ~104 active slots (respect `rg --no-ignore` + explicit-path and
  no-`sqlite3` constraints) and eyeball the map against the 2026-07-19 findings
  (netuid 54 = 35% partner, burn-mechanics breadth).
- [x] 8.2 Run `activity` backfill from local `git log`; confirm chutes/
  computehorde are not fade-flagged once branch pulse has ≥2 passes.
- [x] 8.3 Install + start `atlas-dashboard.service`; confirm LAN reachability
  from another device and that only `www/` is served.
- [x] 8.4 Let the hourly pass run one cycle; verify metrics + render fire inline
  without affecting reconcile/signals, and `status` reports healthy coverage.

## 9. Sync + archive

- [x] 9.1 Run `openspec validate fleet-rotation-metrics`; sync delta specs into
  the live specs (`fleet-rotation-metrics` new spec + `subnet-repo-fleet` branch
  -tips requirement).
- [x] 9.2 Update memory (atlas-fleet-sweep-findings → shipped; note dashboard
  URL/port and any config knobs tuned on-device) and archive the change.
