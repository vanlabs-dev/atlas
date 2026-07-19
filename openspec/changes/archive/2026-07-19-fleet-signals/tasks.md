## 1. Ledger store and config

- [x] 1.1 Create `fleet/atlas_fleet_signals.py` skeleton with additive schema (`signal_terms`, `signal_adoptions`, `signal_events`, `signal_state`) auto-created on open, reconcile-store schema untouched (D4); `status` subcommand reporting watermark, ledger counts, queued events, failed/truncated ranges
- [x] 1.2 Enable WAL journal mode + busy_timeout on the fleet store open path (cross-unit reader/writer, D4/D8); verify fleet-search read-only server unaffected
- [x] 1.3 Add `signals` block to `fleet/config.json`: scan-surface patterns and exclusions (manifests, lockfile/vendor/test excludes), model-id regex families + `model_ids` kill-switch, giant-range caps, term-length and terms-per-range caps, novelty ceiling, cluster `(k, T)` strawmen, starter watchlist, econ-code path patterns, `econ_cooldown_hours`
- [x] 1.4 Tests: schema creation is additive and idempotent against an existing fleet.db; status renders on empty store; WAL/busy_timeout active; concurrent read-during-write does not error

## 2. Extraction

- [x] 2.1 Watermark-driven range walker: select `change_ranges` past `signal_state` watermark, filter recorded `files_json` to scan surface, advance watermark past no-op ranges without any git call — free path taken only when the record is complete and fast-forward
- [x] 2.2 Truncated/NFF fallback: rebuild the changed-path list with a capped `git diff --name-only prev..new` when the record is truncated or non-fast-forward; over-cap degrades visibly (manifests-only + digest note), never a silent skip
- [x] 2.3 Manifest diff extractor: `git diff prev_sha..new_sha -- <paths>` per matching range, parse added dependency lines per format (requirements/pyproject/package.json/Cargo/setup), normalize terms; unparseable file skipped, failed diff marks range `extract_failed` without blocking the pass
- [x] 2.4 Model-id extractor over added lines of allowed text files with path exclusions; honors kill-switch
- [x] 2.5 Giant-range cap: over-cap ranges extract manifests-only, skip model-id pass, record truncation and queue one digest line; enforce term-length and terms-per-range caps with digest note on overflow
- [x] 2.6 Adoption recording: first adoption per `(term, netuid, epoch)` with time/SHA/source file; duplicates ignored; epoch isolation on re-point
- [x] 2.7 Epoch-open seeding: on first successful clone or re-point, parse current manifest blobs (bounded fetch) and record adoptions dated at epoch open, eligible for detection (D3b)
- [x] 2.8 Tests: per-format parsing, normalization, lockfile exclusion, cap degradation and overflow caps, truncated/NFF fallback, fail-closed range, epoch isolation, epoch-open seeding, watermark advance semantics

## 3. Detection and event queue

- [x] 3.1 Novelty gate + cluster detector: qualify under novelty ceiling, emit exactly one instant cluster event at k-th distinct adopter within T days (members, first mover, window, prevalence snapshot); episode never re-fires; post-cluster adopters queue digest lines referencing the episode
- [x] 3.2 Watchlist matcher over normalized terms (plain + `re:` patterns, validated at load — invalid pattern skipped and surfaced in status), one instant event per `(term, netuid, epoch)`
- [x] 3.3 Econ-code detector over `files_json` paths only, one instant event per matching range keyed by range id, with per-netuid cooldown: matches within `econ_cooldown_hours` of an instant alert queue digest lines instead (recording never suppressed)
- [x] 3.4 Append-only event queue writes with class/tier/payload; extraction invokable standalone via `extract` subcommand
- [x] 3.5 Wire inline extraction into the reconcile pass after ranges are recorded (extraction failure never a reconcile process error)
- [x] 3.6 Tests: cluster episode once-only, common-term suppression, watchlist dedup and bad-regex handling, econ per-range dedup + cooldown dampening, inline hook failure isolation

## 4. Backfill, seeding, and calibration

- [x] 4.1 `backfill` subcommand: per active clone, `git log -p -- <manifest paths>` (no `--follow`; single-pathspec limitation, renames accepted as lost) with per-repo commit cap; seed terms/adoptions with historical author dates; set watermark to newest range; emit zero events
- [x] 4.2 `seed-modelids` subcommand: one-shot read-only pass running model-id regex families over current `fleet_files` index contents; record prevalence as `seeded` adoptions counting toward novelty but never toward cluster windows (D9)
- [x] 4.3 `calibrate` subcommand: replay seeded ledger over a `(k, T, novelty)` grid, print historical clusters per candidate with dates; read-only
- [x] 4.4 Tests: backfill emits nothing and seeds correctly on a fixture history; seed-modelids marks rows `seeded` and blocks cold-start clusters; calibrate output stable and side-effect-free

## 5. Price snapshots and effectiveness

- [x] 5.1 Add `signal_prices` and `signal_outcomes` tables (D10) to the signals schema; config: `outcome_horizons_days` (default [1,7,30]), price retention cap
- [x] 5.2 Price snapshot step in the extraction hook: at most one keyless TaoSwap subnets fetch per pass via the live-data layer (never raw HTTP), only when events were emitted or outcomes are due; store the full fleet price vector; entry snapshots per instant event (clusters: per member); failed fetch leaves snapshots pending, never blocks events
- [x] 5.3 Outcomes filler in the same hook: fill due horizon rows with subnet return + fleet-median baseline over the identical window; deregistered/price-less at horizon marked unavailable; late fills marked late
- [x] 5.4 `effectiveness` subcommand: per class × horizon, alerted-subnet median return vs fleet baseline, with counts and pending/unavailable tallies; read-only, no recommendations
- [x] 5.5 Tests: one-fetch-per-pass bound, pending/late/unavailable state machine, baseline window alignment, retention cap, effectiveness output stable and side-effect-free

## 6. Telegram delivery

- [x] 6.1 Register `signal_events` as a new watermarked notifier source in `telegram/atlas_telegram.py`: fleet.db opened strictly read-only (`mode=ro`), delivery watermark stored in the notifier ledger, `init` seeds it (no sends, never rolls back); delivery priority below chain-runtime-upgrade, above churn digest
- [x] 6.2 Renderers for the three instant classes in house style (headline + single-fact `·` lines, `<code>` SHAs, safe HTML + 400 fallback, scrubbing; repo-derived strings escaped and length-bounded): cluster (members/first mover/window/prevalence), watchlist (term/subnet/source file), econ-code (subnet/files/commit count/both-clocks where recorded); one entry-price line (alpha in TAO) when the snapshot is available, omitted without delaying delivery when pending
- [x] 6.3 Digest path: adoption lines, post-cluster adopters, cooldown-dampened econ ranges, truncation notices carried under existing durable pending-digest mechanics
- [x] 6.4 Ledger dedup keys per class (cluster: term+episode; watchlist: term+netuid+epoch; econ: range id); retries never double-send
- [x] 6.5 Tests: mixed-scan ordering, cross-unit lag delivery (events queued between scans arrive exactly once next scan), dedup on retry, digest durability across failed scans, render fallback, read-only fleet.db access enforced

## 7. Documentation and deployment

- [x] 7.1 `fleet/README.md` section (signals pipeline, invariants, two-unit scheduling and accepted ≤1-cycle lag, CLI) + `telegram/README.md` class table update; document threshold calibration and starter-watchlist editing
- [x] 7.2 Full local test pass (fleet + telegram suites) on the workstation
- [x] 7.3 On-device (Pi): git pull, run `backfill`, `seed-modelids`, then `calibrate`; operator sets `(k, T, novelty)` + edits watchlist; run `atlas_telegram.py init`; verify next fleet-unit run extracts and next repo-unit scan delivers (or stays silent) correctly
- [ ] 7.4 Operator sign-off: first week of live signals reviewed for noise; thresholds adjusted in config if needed
