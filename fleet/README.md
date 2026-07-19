# fleet — subnet repository fleet tracking

OpenSpec change `subnet-repo-fleet`: a chain-driven reconciliation layer
over the singleton `repotrack` tracker. The chain is the desired state
(for each netuid, the on-chain `SubnetIdentity.github_repo`); a local
registry + a fleet of clones under gitignored `var/fleet/` are the actual
state. Each pass clones what is new, updates what exists, re-points what
churned, and discards what deregistered — reusing repotrack's journaled
update primitives and never building, testing, or executing subnet code.

The self-healing, change-tracked fleet is the substrate; three downstream
changes build on it (all below): **fleet-search** (a read-only code-search
surface + `atlas-fleet` MCP server), **fleet-signals** (narrative / watchlist /
econ-code alerts + an effectiveness ledger), and **fleet-rotation-metrics**
(emission-redirect map, epoch-scoped activity + branch pulse, momentum /
quadrant, and a ranked LAN-only "attention board" dashboard).

## Identity source (the "on chain detail") — discovery-gated

The desired map comes from the live-data TaoStats subnet-identity
operation (`GET /api/subnet/identity/v1`, paginated) →
`netuid → { github_repo, subnet_name }`. The endpoint does **not** carry
the subnet owner ss58, so the fleet fingerprint keys on the normalized
repo URL (a re-registration is a different project with a different repo).
Provenance is **TaoStats-reported chain identity**, not chain-verified.

The automatic source is built and working: a bare `reconcile` pages the
identity map to completion (the whole ~129-subnet map is one call at
`limit=200`) and reconciles. `reconcile --identity-file` still drives a
manual/seed pass from a bare list of
`{netuid, github_repo, owner_ss58, subnet_name}` or a full live-result
envelope.

Per the live-data "discovery gates adapter construction" rule, the
endpoint contract is recorded in `docs/decisions.md`. That entry is
currently **PROPOSED**; the operator ratifies it via the on-device
`discover_taostats.py` run (identity probes included) and records the
once-off fleet tracking-policy confirmation.

## Invariants

- **Blobless clones** (`--filter=blob:none --no-checkout`): the file-count
  cap gates the tree *before* any blob is fetched; blobs for the working
  tree and for change-record diffs are fetched on demand. Full commit
  graph, not shallow.
- **Never executed**: no build, test, install, hook, or submodule fetch
  (`--no-recurse-submodules`); the push URL is disabled.
- **Per-repo caps → quarantine**: size (git object bytes) and tracked-file
  count; a breach removes the clone and marks the slot `quarantined`.
- **Per-slot fail-closed**: an unreachable, invalid-URL, oversized, or
  disk-limited repo is recorded and skipped, never blocking other slots.
  A repo that will not clone (placeholder URL, private repo the
  public-read-only token cannot see, deleted/moved) is retried with an
  escalating **backoff** (`unreachable_backoff_hours`) so it stops burning
  a clone slot every pass; a fix (new repo URL → new fingerprint) re-points
  immediately, bypassing the backoff. Per-slot failures are recorded by
  status, never counted as process errors, so the scheduled unit stays
  healthy while dead repos exist.
- **Mass-discard guard**: `discard` and `repoint` run only when the
  identity fetch is validated, fresh, and paginated to completion; a
  degraded fetch makes no destructive change and only advances known-good
  slots.
- **Identity fingerprint + epochs**: `fingerprint = hash(owner ‖
  normalized_repo)` excludes the subnet name (a rename never re-points).
  A fingerprint change re-points the slot (discard + reclone) and opens a
  new epoch; change ranges are keyed by `(netuid, epoch)` so two projects'
  history never mixes on one recycled slot.
- **Disk ceiling**: below `min_free_bytes` free, new clones are held as
  `disk-limited` and retried when space frees.

## Store — `var/fleet/fleet.db` (gitignored, device-local)

- `slots` — netuid → identity, fingerprint, epoch, status
  (`active` / `pending` / `no-repo` / `invalid-url` / `quarantined` /
  `unreachable` / `disk-limited`), branch, local SHA, size, timestamps.
- `epochs` — per-netuid identity epochs (opened/closed, block).
- `change_ranges` — repotrack's recorded range shape (commits, per-file
  ±, tags), scoped to `(netuid, epoch)`.
- `audit` — one redacted row per reconcile action.
- `fleet_files` + `fleet_files_fts` + `index_state` — the shared FTS index
  (change: fleet-search), scoped by `(netuid, epoch)`; owned by
  `atlas_fleet_index.py`, created on first index run (the reconcile store's
  own schema is untouched).
- `signal_*` tables — the fleet-signals ledger (change: fleet-signals);
  owned by `atlas_fleet_signals.py`, additive, created on first signals
  run. The store runs WAL + busy-timeout so the Telegram notifier (a
  different scheduled unit) can read `signal_events` read-only while a
  reconcile writes; write access stays with fleet-side processes only.
- `metric_*` tables — the fleet-rotation-metrics store (change:
  fleet-rotation-metrics); owned by `atlas_fleet_metrics.py`, additive,
  created on first metrics run: `metric_emission_routes` +
  `metric_emission_scan` (the per-`(netuid,epoch,sha)` emission-redirect
  map, sha-gated), `metric_activity` (windowed epoch-scoped commit/author
  counts), `metric_branch_tips` (per-pass `ls-remote` tip snapshots for the
  branch-pulse metric), `metric_state`.

## Commands

```
python3 fleet/atlas_fleet.py status                       # registry summary
python3 fleet/atlas_fleet.py reconcile --identity-file F   # manual / seed pass
python3 fleet/atlas_fleet.py reconcile --max-new N         # override per-pass bound
python3 fleet/atlas_fleet.py reconcile                     # auto source (live TaoStats subnet/identity)
python3 fleet/atlas_fleet.py index                         # backfill/repair the search index (all active slots)
python3 fleet/atlas_fleet.py index --netuid N              # (re)index one subnet
python3 fleet/atlas_fleet.py index --rebuild               # purge + full re-walk
```

`GITHUB_TOKEN` (optional) is read from the 0600 `.env`, injected per git
invocation via `GIT_CONFIG_*` (never argv, never the clone's on-disk
config), and registered for redaction. Absent, the fleet clones
anonymously with a smaller per-pass budget.

## Search index + MCP server (change: fleet-search)

Reconcile keeps a shared `(netuid, epoch)`-scoped FTS index in step with the
clones — a new clone / re-point fully indexes the tree, a clean fast-forward
update indexes incrementally (a truncated range, a history-rewrite reset, or a
record-failed advance fall back to a full walk), and discard / re-point purge in
the slot transaction so no search ever returns a hit for a gone slot. Indexing
is per-slot fail-closed and transactionally isolated: an index error rolls back
only the index, never the recorded clone/update. The index reuses repotrack's
pure `_indexable` / `_walk_tree` / `local_sha` helpers — it does not fork
`run_index`, and it never builds, tests, or executes subnet code.

`atlas_fleet_server.py` — stdio JSON-RPC, three read-only tools for Hermes:

- `fleet_search(query, netuid?, max_results?)` — FTS across all subnets (or one
  netuid), citing netuid + repository + path + indexed SHA + snippet; zero hits
  return `no-fleet-evidence`. The query is reduced to allowlisted tokens
  (FTS-operator-safe).
- `fleet_file(netuid, path, start_line?, end_line?)` — bounded read from a
  subnet's clone, served only while the slot is active, tree-clean, and its
  indexed SHA equals the clone's live local SHA (else a staleness refusal).
- `fleet_status(netuid?)` — fleet + index coverage (indexed / stale slot counts,
  total indexed files); per-netuid detail with honest staleness.

The store opens `mode=ro`; missing store or an unbuilt index fails closed as
`fleet-search-unavailable`. The only write is the size-capped redacted
`var/fleet/tool-audit.jsonl`. Register alongside `atlas-repo`:

```yaml
# hermes config.yaml (mcp servers section)
atlas-fleet:
  command: python3
  args: ["/home/pi/atlas/fleet/atlas_fleet_server.py"]
```

Before it is useful the index must exist: run `python3 fleet/atlas_fleet.py
index` once to backfill the already-cloned slots, verify coverage with
`fleet_status`, then register the server.

## Signals — narrative radar + econ-code alerts (change: fleet-signals)

Every reconcile pass ends with an inline, fail-isolated signals pass
(`atlas_fleet_signals.run_pass`): epoch-open seeding → diff-scoped term
extraction → detection → price/outcome measurement. A signals failure is
audited (`signals-failed`) and never counts as a reconcile process error.

- **Term ledger.** Change ranges past a durable watermark are diffed on a
  narrow scan surface: structured manifests (`requirements*.txt`,
  `pyproject.toml`, `package.json`, `Cargo.toml`, `setup.py/.cfg`;
  lockfiles and vendor/test paths excluded) for dependency terms, plus
  model-id regex families over added lines of code/config text files
  (config kill-switch: `signals.model_ids`). First adoption per
  `(term, netuid, epoch)` — a re-pointed slot never inherits its
  predecessor's adoptions. A complete fast-forward range with no
  scan-surface files costs zero git calls; a truncated/non-fast-forward
  record NEVER takes that free path (the path list is rebuilt with a
  capped `--name-only` diff). Over-cap giant ranges degrade to
  manifests-only, visibly (digest note). Terms are adversarial input:
  length-capped, per-range count-capped, rendered as data.
- **Detection.** Watchlist (config `signals.watchlist`, plain or `re:`
  entries, validated at load — an invalid pattern is skipped and shown in
  `signals status`) pages on first adoption per subnet. A term still
  under the novelty ceiling clusters when the k-th distinct subnet
  adopts it within the window — ONE instant event per term episode, ever;
  later adopters become digest lines. Econ-code path matches
  (reward/incentive/scoring/emission vocabulary) page once per change
  range with a per-netuid cooldown (`econ_cooldown_hours`, default 24 —
  dampens paging, never recording). Events queue append-only in
  `signal_events` for the notifier.
- **Effectiveness ledger.** Instant events snapshot alpha price in TAO at
  event creation (clusters: per member) via the KEYLESS TaoSwap subnets
  operation through the live-data layer — at most one fetch per pass,
  only when something needs it, zero TaoStats quota; the full fleet
  price vector is stored so horizon outcomes (default 1/7/30d) compare
  against the fleet-median baseline over the identical window. States
  are honest: `pending` / `recorded` / `late` / `unavailable` — a failed
  fetch never delays an alert. `effectiveness` reports per class ×
  horizon medians vs baseline; it ranks nothing and recommends nothing.
- **Two-unit scheduling.** Extraction runs here (fleet unit); the
  Telegram scan runs in the repo unit — delivery may lag extraction by up
  to one scheduling cycle (~1h), accepted by design: every signal class
  moves on a days-to-weeks clock.

```
python3 fleet/atlas_fleet_signals.py status          # watermark/ledger/queue
python3 fleet/atlas_fleet_signals.py extract         # standalone pass (also inline on reconcile)
python3 fleet/atlas_fleet_signals.py backfill        # SILENT historical manifest seed (real commit dates)
python3 fleet/atlas_fleet_signals.py seed-modelids   # SILENT model-id prevalence seed (from the FTS index)
python3 fleet/atlas_fleet_signals.py calibrate       # replay ledger over a (k, window, novelty) grid — read-only
python3 fleet/atlas_fleet_signals.py effectiveness   # per-class × horizon report — read-only
```

**Deploy order on the Pi**: `git pull` → `backfill` → `seed-modelids` →
`calibrate` (pick `cluster.k` / `cluster.window_days` /
`novelty_max_adopters` from the evidence, edit `signals.watchlist` to
taste) → `telegram/atlas_telegram.py init` (seeds the notifier's
`fleet-signal` watermark; never rolls back) → the next hourly runs do the
rest. First run self-installs quietly even without the manual steps: the
extraction watermark seeds to the newest range and all pre-existing
epochs seed silently — no alert flood is possible from history. The
first meaningful `effectiveness` read comes after the 30-day horizon
matures.

## Rotation metrics + attention dashboard (change: fleet-rotation-metrics)

Every reconcile pass, after signals, runs an inline fail-isolated metrics
pass (`atlas_fleet_metrics.run_pass`) that turns the fleet into a rotation
cockpit — read-only over the clones and store, additive tables only, never
executing subnet code, per-slot fail-closed:

- **Emission-redirect map.** Scans each active slot's reward/weight/scoring
  code paths for routing symbols (burn / partner / treasury / owner /
  royalty), recording one route per `(kind, symbol, file)` with `file:line`
  evidence, its fraction when a lone `0..1` literal is parseable (NULL
  otherwise), and a destination hotkey when present. A matched symbol is
  only recorded when it reads as a proportion (name carries
  fraction/share/pct/take/…) or carries a fraction or a hotkey — so
  incidental family-word variables (`is_burn`, `burn_uid`) are not mistaken
  for splits. Subnets whose economics load from a remote URL at runtime are
  flagged **opaque** (values not fabricated). Rescanned only when a slot's
  `local_sha` moves.
- **Epoch-scoped activity + branch pulse.** Windowed default-branch
  commit/author counts (7/30/90d); all-time totals kept as context only,
  excluded from ranking so inherited fork history can't inflate a subnet.
  The reconcile pass records a per-slot `git ls-remote --heads` tip snapshot
  (no fetch, no dating); `changed_tips` between passes is the branch-pulse
  metric, so a live subnet working off its default branch is not mistaken
  for abandoned.
- **Momentum + quadrant.** Alpha-price momentum reused from the signals
  `signal_prices` panel (no new API call, no backfill; missing history →
  `n/a`), and a percentile-rank quadrant. Ranks evidence; recommends
  nothing.

The **dashboard** (`atlas_fleet_dashboard.py`) assembles one explicitly-
scored "attention board" — subnets ordered from look-here to safely-ignore
by a legible score (fresh econ-code/branch changes rank highest, then
divergence, emission severity, abandonment; opacity deduped into one grouped
line) — and renders a single self-contained HTML page (inline CSS/JS, no
external asset, no secret) atomically into `var/fleet/www/`. It is served
LAN-only by `atlas-dashboard.service` (`python3 -m http.server`, bound to the
Pi's LAN IP; the dedicated `www/` dir + bind address are the security
boundary — the store, clones, and journals are never under the served root).

```
python3 fleet/atlas_fleet_metrics.py status        # coverage + failure summary
python3 fleet/atlas_fleet_metrics.py pass           # branch tips + activity + emissions + render (also inline on reconcile)
python3 fleet/atlas_fleet_metrics.py emissions      # sha-gated emission-map scan
python3 fleet/atlas_fleet_metrics.py report         # combined ranked JSON view
python3 fleet/atlas_fleet_dashboard.py board        # ranked head (JSON), no render
python3 fleet/atlas_fleet_dashboard.py render       # write var/fleet/www/index.html
```

**Deploy on the Pi**: `git pull` → the hourly reconcile runs the metrics +
render inline automatically. Install the LAN server (sudo):

```
sudo cp ~/atlas/fleet/systemd/atlas-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-dashboard.service
# browse http://<pi-lan-ip>:8480/   (edit --bind in the unit if the IP differs)
```

The board is intentionally thin at the top until price history accrues:
momentum needs ≥2 `signal_prices` snapshots, so divergence (the largest
score driver) lights up over the first days; until then it ranks on
emission / freshness / abandonment alone, honestly showing `n/a` momentum.

## Scheduling — every 6h, independent of repotrack

Unit files in [systemd/](systemd/); installation needs sudo:

```
sudo cp ~/atlas/fleet/systemd/atlas-fleet.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-fleet.timer
```

Verify with `systemctl list-timers atlas-fleet.timer` and
`python3 fleet/atlas_fleet.py status`.

## Status (2026-07-19)

Deployed and seeded on the Pi: **104 active blobless clones** (~2.7 GB),
10 unreachable (backed off), 1 invalid-url, 14 no-repo = 129 subnets. The
reconcile pipeline is accepted on-device (blobless, push-disabled,
token-safe, per-slot fail-closed all verified against real data).

- **fleet-search** — shared FTS index + read-only `atlas-fleet` MCP server;
  deployed + archived.
- **fleet-signals** — narrative / watchlist / econ-code alerts + the
  effectiveness ledger; deployed + archived.
- **fleet-rotation-metrics** — metrics + the ranked LAN dashboard;
  implemented, tested (full fleet suite 214 green off-device), committed
  (`17f8e28`), delta specs synced into live specs. On the Pi the metrics
  pass has run over all 104 clones (43 emission routes, e.g. SN54 = 35%
  partner) and the board renders; `atlas-dashboard.service` is installed and
  serves the board locally. **Open:** the board is not yet reachable from the
  operator's browser (LISTEN on `192.168.0.150:8480`, SSH/ping to the Pi work
  but port 8480 does not, and the Pi has no host firewall installed —
  under diagnosis; likely a hardening-loaded kernel netfilter ruleset). The
  change is **not yet archived** pending that access confirmation.

## Before it is self-maintaining — operator steps

1. Install the timer (sudo) so passes run every 6h — see Scheduling above.
2. Ratify the **PROPOSED** `subnet/identity` discovery-gate entry in
   `docs/decisions.md` (run `discover_taostats.py` on the Pi, confirm the
   contract, flip it to approved). The automatic source already works; this
   is the recorded operator approval, not a functional unblock.
3. Record the once-off fleet **tracking-policy** confirmation in
   `docs/decisions.md` (the policy-level analogue of ATLAS-REPO-001:
   "track chain-reported subnet `github_repo`s under the fleet policy,"
   not a per-repo confirmation).

## Tests (off-device)

```
cd fleet/tests && python3 -m unittest discover -s .
```

Fixture git origins exercise the full pipeline: URL normalization and
fingerprinting, the reconcile plan + mass-discard guard + bounding, the
blobless clone policy with size/file caps and token non-persistence, the
fetch → fast-forward-or-reset update with recorded ranges, re-point epoch
segmentation, deregistration with preserved provenance, the disk ceiling,
and the status/CLI surface. The Pi run is acceptance.
