# fleet-signals — design

## Context

The fleet layer records, per hourly reconcile, a `change_ranges` row per advanced
slot: `(netuid, epoch, prev_sha, new_sha, commits_json, files_json, tags_json)`.
Clones are blobless (`--filter=blob:none --no-checkout`); `git diff` against a
clone fetches exactly the blobs the diff needs. The Telegram notifier's scan loop
is class-agnostic: each source has its own watermark, events are rendered with
tiering/dedup/HTML-fallback, and the hourly repo service already chains
poll → scan. fleet-search precedented the storage pattern: a downstream feature
owns additive tables in `var/fleet/fleet.db` without touching the reconcile
store's schema, indexing inline-on-reconcile plus a standalone backfill CLI.

Known operational hazard to respect: occasional giant change ranges
(hundreds of commits after a repo re-point or a long outage) — any per-range
work must be capped, not assumed small.

## Goals / Non-Goals

**Goals:**
- Turn fleet change ranges into four Telegram signal classes: narrative-cluster,
  watchlist hit, econ-code change (instant tier) and term-adoption digest
  (digest tier).
- A durable term ledger keyed the same way as everything else in the fleet:
  `(netuid, epoch)` — recycled netuids never inherit a predecessor's adoptions.
- Backfill from existing clone history so day-1 is quiet and thresholds are
  calibrated on real data, not guesses.
- Preserve every fleet invariant: read-only, never execute subnet code,
  per-slot fail-closed, bounded work per pass.

**Goals (added):**
- Measure alert effectiveness: alpha-price-in-TAO snapshot at event creation,
  horizon outcomes vs a fleet baseline, and a report that says per class
  whether alerts carried signal.

**Non-Goals:**
- No trade recommendations and no backtest *statistics beyond* the built-in
  effectiveness report; price data is used for measurement of emitted alerts,
  not for generating signals.
- No frontend; tables are designed to be readable by one later.
- No import-statement, domain, or README-vocabulary scanning (deferred — each is
  a noise multiplier).
- No new systemd unit, timer, or network surface.
- No *runtime* FTS-index dependency: extraction is diff-scoped; fleet-search
  stays a sibling. (One-shot exception: model-id prevalence seeding reads the
  existing `fleet_files` index — D9.)

## Decisions

### D1 — Extraction source: change ranges + targeted `git diff`, not the FTS index
For each unprocessed `change_ranges` row, filter `files_json` to the scan
surface; only if files match, run `git diff prev_sha..new_sha -- <paths>` in
that clone and parse **added lines**. Blobless clones fetch only those blobs.
*Alternative rejected:* rescanning `fleet_files` (FTS) — it holds only current
state, loses adoption timing, and costs a full-fleet scan per pass.

### D2 — Scan surface v1 (precision over recall)
- **Manifests** (dependency terms): `requirements*.txt`, `pyproject.toml`,
  `package.json`, `Cargo.toml`, `setup.py`/`setup.cfg`.
  **Lockfiles are excluded** (`package-lock.json`, `yarn.lock`, `poetry.lock`,
  `Cargo.lock`, `uv.lock`) — they explode diffs with transitive noise.
- **Model-id strings**: regex family (HuggingFace `org/model` ids, versioned
  model-name patterns) over added lines of text-file diffs in
  `*.py|*.json|*.yaml|*.yml|*.toml|.env.example`, excluding `vendor/`,
  `node_modules/`, `test(s)/` paths.
- Terms are normalized: dependency names lowercased, extras/version specifiers
  stripped; model ids kept case-preserving but matched case-insensitively.

### D3 — Giant-range cap (fail-degraded, never fail-open)
Per range: if changed-file count or commit count exceeds caps (config;
strawman 200 files / 100 commits), extract **manifests only** and skip the
model-id pass; record the truncation on the ledger row and surface it as one
digest line. A range whose diff errors marks that range `extract_failed` and
moves on — one bad slot never blocks the pass (mirrors reconcile semantics).

**Truncated/NFF records never take the free path.** The no-files-no-work
shortcut applies only when `files_json` is complete and fast-forward. A range
whose recorded file list is truncated or non-fast-forward may hide a manifest
change, so extraction rebuilds the surface itself with a capped
`git diff --name-only prev..new` before deciding; if even that exceeds caps,
it degrades per the rule above — visibly, never silently.

### D3b — Epoch-open seeding (new clone / re-point)
Change ranges are only recorded on *updates*; an initial clone records none,
so a new subnet's existing manifest terms would otherwise never enter the
ledger, and a re-pointed slot's new project would start invisible. At each
epoch open (first successful clone of a slot or a re-point), the signals
module SHALL seed adoptions from the **current manifest blobs** of that clone
(bounded lazy fetch of just those files), dated at epoch open. Seeded
adoptions are ordinary adoptions: eligible for novelty, cluster, and watchlist
evaluation. The initial 104-slot population is covered by the historical
backfill, so forward epoch-opens are rare (a few per month) and cannot flood.

### D4 — Ledger schema (additive tables in `var/fleet/fleet.db`)
- `signal_terms(term, kind, first_seen_at, first_netuid)` — fleet-global term
  registry (`kind` ∈ dependency | model-id).
- `signal_adoptions(term, netuid, epoch, adopted_at, commit_sha, source_file)`
  — first adoption per `(term, netuid, epoch)`; later re-appearances ignored.
- `signal_events(id, class, tier, netuid, term, payload_json, created_at)` —
  the queue the notifier consumes; append-only.
- `signal_state(key, value)` — extraction watermark = last processed
  `change_ranges.id` (same watermark shape the notifier already migrated to).
Created on first run by the signals module; reconcile-store schema untouched
(fleet-search pattern).

**Cross-process access rules.** fleet.db gains `journal_mode=WAL` and a
`busy_timeout` (the store currently sets neither), because the notifier runs
in a *different unit* than the fleet writer (D8). Write access to fleet.db
stays exclusively with fleet-side processes: the notifier opens it strictly
read-only (`mode=ro` URI) and keeps its signal-source **delivery** watermark
in the telegram ledger alongside its other sources — never in fleet.db.

**Untrusted-input bounds.** Terms and paths originate in adversarial repos:
term length is capped, terms-per-range is capped (a hostile manifest cannot
flood the ledger — overflow is dropped with a digest note), and repo-derived
strings are HTML-escaped at render per the existing safe-HTML contract.
Watchlist regex entries are validated at load; an invalid pattern is skipped
and surfaced in `status`, never a crash.

### D5 — Novelty gate, then cluster gate
A term **qualifies** if, at adoption time, its distinct-adopter count is below
`novelty_max_adopters` (config; strawman 10 ≈ ~10% of active slots).
A **cluster event** is emitted exactly once per term-episode: at the moment the
k-th distinct netuid adopts a qualifying term within the trailing `T` days
(strawman k=3, T=14 — both to be reset by calibration). Adopters after the
k-th append digest lines that name the existing cluster; no repeat instant
alerts. Prevalence (`n/active-slots`) is snapshotted into the event payload.
An episode never re-fires: once a term's cluster event exists, all later
adoptions of that term are digest-only for the life of the term.

### D6 — Watchlist is config, matched against extracted terms only
`fleet/config.json` gains `signals.watchlist`: plain strings and `re:`-prefixed
patterns, matched against normalized extracted terms (not raw diff lines — the
extractors define the vocabulary; raw-line matching reopens the noise door).
Instant alert on first match per `(term, netuid, epoch)`. Ships with a starter
list the operator edits.

### D7 — Econ-code detection is path-based, no blob fetch
Match `files_json` paths against `signals.econ_paths` patterns (strawman:
`reward`, `incentive`, `scoring`, `emission`, `set_weights`, `validator.*weight`),
same exclusions as D2. One instant event per `(netuid, change-range)` listing
matched files and commit count; dedup key is the range id. Pure metadata — the
only signal class with zero diff cost.

**Per-netuid cooldown**: an actively developed subnet touches scoring code in
many hourly ranges; without dampening this class pages hourly. After an
instant econ-code alert for a netuid, further matching ranges within
`signals.econ_cooldown_hours` (default 24) queue digest lines referencing the
open alert instead of paging. The cooldown suppresses paging, never recording.

### D8 — Inline-on-reconcile + standalone CLI; one-cycle delivery lag accepted
`atlas_fleet_signals.py` exposes `extract` (process ranges past the watermark),
`seed-modelids`, `backfill`, `calibrate`, `status`. The reconcile pass invokes
extraction inline after recording ranges; the standalone CLI covers backfill
and recovery.

**Scheduling reality** (verified in the unit files): the Telegram scan is an
`ExecStartPost` of the **repotrack** unit; fleet reconcile is a **separate**
unit/timer. The two fire independently, so an event queued by the fleet unit
is delivered by the next notifier scan — up to one cycle (~1 h) later. This
lag is accepted by design: every signal class here moves on a days-to-weeks
clock. *Alternative rejected:* chaining a second scan onto the fleet unit —
it buys ≤1 h of latency at the cost of two concurrent scan entry points
racing the notifier ledger.

### D9 — Backfill seeds; calibrate reports; operator sets thresholds
`backfill` walks `git log -p -- <manifest paths>` per active clone (no
`--follow` — it accepts only a single pathspec, and manifest renames are rare
enough that rename-tracking is not worth per-path walks; manifest blobs only —
small; per-repo commit cap for safety) to seed
`signal_terms`/`signal_adoptions` with historical dates, then sets the
watermark to the current max `change_ranges.id`. **Backfill emits no events.**
Dates come from commit author dates — fakeable and occasionally wrong, which
is acceptable for calibration but is why no *event* is ever derived from them.
`calibrate` replays the seeded ledger under candidate `(k, T,
novelty_max_adopters)` grids and prints the historical clusters each would have
fired, with dates — the operator picks defaults from evidence and records them
in config.

**Model-id cold start.** Full-history model-id backfill stays out (unbounded
text diffs over 104 repos), but with an empty model-id ledger every
long-established model id would look "novel" the first time any subnet touches
it, faking clusters for weeks. `seed-modelids` closes this: a one-shot,
read-only pass running the model-id regex families over the **current file
contents already held in the fleet-search `fleet_files` index**, recording
per-term prevalence (which subnets currently carry the id) as seeded
adoptions dated at seed time and flagged `seeded`. Seeded model-id adoptions
count toward the novelty ceiling but never toward a cluster window.

### D10 — Price snapshots and outcome measurement (effectiveness ledger)
Every instant-tier event captures the affected subnet's **alpha price in TAO**
at event creation — clusters capture one snapshot per member netuid. Price
comes from the **keyless TaoSwap subnets operation invoked through the
live-data layer** (its contract validation, retries, health recording, and
fail-closed behavior apply unchanged; zero TaoStats quota). One call returns
every subnet, so:

- `signal_prices(ts, netuid, price_tao)` stores the **full fleet price
  vector** per fetch — the fleet baseline comes free. Fetches happen only when
  needed (events were just emitted, or outcomes are due), bounded to at most
  one per extraction pass; retention is config-capped.
- `signal_outcomes(event_id, netuid, horizon_days, due_at, price_tao,
  return_pct, baseline_return_pct, status)` rows are created per instant
  event and configured horizon (strawman 1 d / 7 d / 30 d) and filled by an
  inline outcomes step in the same hourly extraction hook. A deregistered or
  price-less subnet at horizon marks the row `unavailable`; a late fill is
  marked `late`, never fabricated on time.
- **Fail-soft**: a failed price fetch leaves the entry snapshot `pending`
  (retried next pass) and never delays or blocks the alert itself — the alert
  is the product, the measurement is bookkeeping.
- **Entry is event-creation time, not delivery time**: the snapshot measures
  the *signal* at the moment the code evidence existed; the accepted ≤1-cycle
  delivery lag (D8) does not contaminate measurement.
- `effectiveness` CLI reports, per class × horizon: alerted-subnet median
  return vs fleet-median return over the identical window, with counts and
  pending/unavailable tallies. Measurement only — the report ranks nothing
  and recommends nothing.

*Alternative rejected:* snapshotting from livedata's `response_cache` — it is
a ~200-row rolling cache with no freshness guarantee at event time; invoking
the operation itself is the sanctioned, validated path.

### D11 — Delivery reuses the notifier contract wholesale
The notifier gains one source (`signal_events`, own watermark) and four
classes. Delivery priority slots below chain-runtime-upgrade and above
repo-churn digest. Rendering follows house style: short headline line,
single-fact lines with `·` separators, `<code>` SHAs, safe-HTML with 400
fallback; scrub rules apply to payloads; ledger dedup keys: cluster
`(term, episode)`, watchlist `(term, netuid, epoch)`, econ `(range id)`,
digest lines carried durably like `pending_churn` (never dropped on failure).
Instant alerts include one entry-price line (`price: <x> τ`) when the
snapshot is available at render time; a pending snapshot omits the line and
never delays the alert.

## Risks / Trade-offs

- [Giant ranges blow up diff cost] → D3 caps + manifest-only degradation;
  truncation is visible in the digest, so silence is never mistaken for
  no-signal.
- [Manifest parsing is imperfect (odd TOML tables, dynamic setup.py)] →
  parse-what-parses per file, skip the rest and mark `extract_failed`
  per range; never a pass failure.
- [Model-id regex false positives page the operator] → model-id terms feed
  novelty/cluster/watchlist like any term but a config kill-switch
  (`signals.model_ids: off`) can silence the extractor without redeploy.
- [Cluster thresholds wrong at launch → spam or silence] → backfill-driven
  `calibrate` before enabling sends; `init`-style watermark seeding means
  enabling late never replays history.
- [Model-id cold start fakes clusters] → `seed-modelids` prevalence pass
  (D9); seeded adoptions raise the novelty count without entering cluster
  windows.
- [Econ-code class pages hourly on busy subnets] → per-netuid cooldown (D7);
  suppressed ranges still recorded and digested.
- [Hostile repo floods or poisons alerts] → term-length and terms-per-range
  caps, HTML escaping of repo-derived strings, watchlist regex validation
  (D4); repo content is data, never interpreted.
- [Notifier and fleet writer race fleet.db across units] → WAL +
  busy_timeout; notifier strictly read-only with its delivery watermark in
  the telegram ledger (D4/D8).
- [Price fetch failure or TaoSwap outage skews measurement] → fail-soft
  pending/late/unavailable states (D10); outcomes are labeled, never
  fabricated; alerts themselves are never delayed by measurement.
- [Thin-pool price noise makes small moves meaningless] → the report compares
  against the fleet-median baseline over identical windows and reports
  medians with counts; interpretation stays with the operator.
- [Commit spam / gamed activity] → v1 signals are adoption-based (a term counts
  once per netuid), inherently resistant to commit-count gaming; econ-code
  class is per-range, not per-commit.
- [Monorepo/multi-repo teams under-observed] → accepted v1 gap; the ledger
  records what the chain-declared repo shows, which is also what the market
  can verify.
- [fleet.db contention (reconcile, indexer, signals share the file)] → same
  single-writer-per-pass pattern as fleet-search; extraction runs inside the
  reconcile process, not concurrently with it.

## Migration Plan

1. Land code + config additions; tables auto-create on first signals run
   (additive; no migration of existing tables).
2. On-device: `git pull`; run `backfill`, `seed-modelids`, then `calibrate`;
   operator sets `(k, T, novelty_max_adopters)` and edits the starter
   watchlist.
3. `atlas_telegram.py init` seeds the new source watermark (existing rule: run
   before any scheduled scan; never rolls back a seeded watermark).
4. Hourly service picks the new classes up on its next run — no unit change
   beyond the reconcile step already invoking extract inline.
5. Effectiveness accrues passively once live; the operator runs
   `effectiveness` ad hoc (first meaningful read after the 30-day horizon
   matures).
6. Rollback: remove the notifier source registration (alerts stop); ledger,
   price, and outcome tables are inert data and may stay.

## Open Questions

- Starter watchlist contents (operator taste: partner names, model families,
  tokenomics vocabulary) — a proposed list ships in config for edit, not
  ratification-blocking.
- Final `(k, T, novelty_max_adopters)` — deliberately deferred to the
  calibrate step; config carries the strawmen until then.
- Whether econ-path patterns need per-subnet overrides (some repos name reward
  code unconventionally) — start global; revisit if calibrate/backfill shows
  big blind spots.
