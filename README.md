# Atlas

Self-hosted, single-user Bittensor knowledge and live-data agent built on Hermes,
running on a Raspberry Pi. Built methodically in gated phases via OpenSpec.

**This README is the orientation map. Authoritative sources it points to:**
[prd.md](prd.md) (full product requirements), [docs/decisions.md](docs/decisions.md)
(resolved/open decisions), `openspec/specs/` (accepted capability specs), and
`openspec/changes/archive/` (completed changes with their proposal/design/tasks).

## Runtime upgrades (2026-09-24)

`upgrade/atlas_upgrade.py` runs on the Pi every 30 minutes. When the live
runtime spec moves past the corpus spec, one headless `claude -p` session
edits the corpus and chain readers in a separate worktree. Code then gates
the result (goal, edit scope, every test suite, a live chain-read probe)
before it pushes to `main` and activates the corpus. An hourly probe
(`livedata/atlas_probe.py`) pages when any storage item Atlas reads drifts
from live runtime metadata. See [docs/runtime-upgrade.md](docs/runtime-upgrade.md).
It replaced the Hermes cron job "Atlas runtime upgrade", removed
2026-09-24.

## Current status (2026-09-23, Finney spec 469)

**Phases 0–5 are complete and accepted on the device.** Hermes Agent
v0.20.0 runs on the Pi (Grok `grok-4.6` via X OAuth), answering Bittensor
questions from the local knowledge base (`atlas-kb`), the tracked
subtensor clone (`atlas-repo`), and live provider data (`atlas-live`:
TaoSwap/TaoStats/CoinGecko). Fail-closed. Telegram handles inbound chat
and outbound alerts.

**Live chain (verified 2026-09-23, finalized block 9125891):** spec **469**.
Emission bar is rank-pinned (`EmissionBarRank` unset, default 32; q 0.75
explicit and inert; h unset, default 3). `SubnetEmissionEnabled` is live:
128 keys, **29 / 35 / 36 / 108 off**, SN1 on (map read at block 9125893).
Spec 469 retired `set_root_weights`: `Weights[ROOT]` is cleared and the
curation switch is gone, so root dividends accumulate in place.
`BasketTradingEnabled` is **true** (explicit). It gates `swap_basket`, the
only way a fund's composition changes. `BasketConcentrationCap` is **4096**
(explicit, 1/16 of fund NAV, read at finalized block 9133918).
Corpus and this README are grounded at 469.

**On the device:** fleet clones + LAN boards at
`http://192.168.0.150:8480/` and `/mining.html`; hourly gate poll and
chain-parameter watch; Telegram pulse + subnt.dev public edition.
The 455 switch
watch is deployed (`063d206`).

Investment/rotation tooling is Phase 7 territory. Archived change history
lives in `openspec/changes/archive/` and `docs/decisions.md`. Do not treat
those dated live reads as current.

| Capability (accepted spec) | State |
|---|---|
| `device-inventory` | Done — read-only Pi inventory tool + clean baseline captured |
| `hardening-assessment` | Done — read-only posture assessor (11 ATLAS-ENV-003 areas) |
| `hardening-apply` | Done — 6 approved items applied + verified on the Pi |
| `hermes-baseline` | Done — manual install verified; acceptance run `20260711T091512Z-61ef71d0` |
| `memory-session-recall` | Done — ATLAS-MEM-001…006 verified on the Pi; acceptance run `20260711T171200Z-33321220` (approval gating on, all seven ATLAS-MEM-006 items attested) |
| `model-validation` | Done — ATLAS-HERMES-003 validated on the Pi; run `20260711T182926Z-b1eef1c6` (tool calls 20/20, context to 96k chars, 3.19s median latency; one documented refusal exception; retrieval criterion closed by the Phase 2 benchmark) |
| `knowledge-base` | Done — corpus grounded at Finney spec **469** (2026-09-24): pool-side switch distinct from the bar (off 29/35/36/108), `set_root_weights` retired and `BasketConcentrationCap` 4096, rank-pinned bar. 36-exchange battery; last accepted run `20260919T215719Z-7b20c3a0` on `grok-4.6` (re-ingest on the Pi after this lock-in) |
| `subtensor-repo-tracking` | Done — identity-validated full clone of `RaoFoundation/subtensor` on the Pi (non-shallow, push disabled, @ `14bc6f9f964b`), safe journaled updates (hourly timer), 581-file FTS index, `atlas-repo` tools live in Hermes (commit-and-file-cited answers; honest stale/no-evidence) |
| `live-data` | Done — contract-validated TaoSwap (keyless, first) + TaoStats (2/min self-cap, 10k/month ledger) + CoinGecko adapters; pinned schemas, freshness envelopes, `atlas-live` tools live in Hermes; outage battery proved honest unavailability (MV-RI-4 class closed); chain head watch: live spec **469**. **gate-crossing-signal (2026-07-28):** hourly `poll-gate` reads the emission-gate state via keyless finney RPC on pinned keys at one finalized block (null-storage semantics, `assumed-default` provenance), computes demand shares from the TaoSwap panel over the chain's full bar universe, and records hysteresis-guarded crossing events. **network-drift-443 (2026-08-06):** the poll additionally reads `EmissionBarRank` (SCALE `u16`, its own codec) and records each observation's derived bar mode — rank-pinned since spec 441, which makes the explicit q of 0.75 inert; crossings carry the previous theta so a bar that moved onto a subnet is never reported as demand that rose; a bar-parameter change re-seeds all sides silently instead of emitting \|M - N\| crossings; and rank mode is cross-checked by persisting `above_count` against the effective N. A **chain-parameter watch** tracks the root-settable knobs (bar values handed over by the gate poll; **`BasketConcentrationCap`** read independently on a plain pinned key since `root-weight-drift` (4096 = 1/16; `RootWeightSettingEnabled` and `RootWeightsCap` were dropped without a transition when spec 469 retired them); **`SubnetEmissionEnabled`** the per-subnet pool-side TAO injection switch since `network-drift-455`, a netuid-keyed bool, first observation seeds silently, empty or short batch fails the item closed), recording durable transitions; it survives the gate kill-switch. Demand shares stay over the panel's non-root set (the chain's emit-to filter is an accepted +0.34% residual, measured at block 9041640). The rank cross-check tolerates a divergence of one: theta is fixed between 360-block recalculations while the panel EMA moves, so the Nth subnet sits on the bar. **pulse-briefing (2026-08-31):** each gate pass persists a per-subnet `panel_snapshot` (computed share + the panel fields the briefing reads, bounded retention) and one daily `network_vitals` row from two keyless calls; a zero moving price is a panel gap for side tracking (no crossing to zero, counts toward absence); subnets crossing more than `hover_crossings` times in `hover_window_days` are flagged hovering and their crossings annotated. **rotation-signal-gate (2026-09-09):** the same pass reads every per-validator **root weight vector** (`Weights[ROOT]`, one `state_getKeys` then one `state_queryStorageAt` at the gate poll's finalized block; `state_getPairs` is refused by the endpoint with code 4003) and aggregates them into a destination map that is **stake-weighted** by each validator's root stake (resolved through `Keys[ROOT][uid]` then `TotalHotkeyAlpha[hotkey][ROOT]`, two further derived batched reads, no enumeration) and carries its weighting basis as a stored field; a material shift records a `rotation_events` row, the first map seeds silently and a curation-knob transition re-seeds instead of storming. Fail-closed on a short batch, an undecodable vector, an unexpected key tail, or an enumeration over the cap. The read is independently disableable and is NOT gated by the gate kill-switch. **root-weight-drift (2026-09-24):** spec 469 retired `set_root_weights` and cleared `Weights[ROOT]`, so this read, the destination map and `rotation_events` recording are removed; stored rows stay as history. Gate crossings now carry a persisted **eligibility**: a crossing pages only after a 48h durability window passes without an opposing crossing, and a reversal inside it marks both permanently ineligible |
| `telegram-integration` | Done — inbound conversation via the native Hermes gateway (operator wizard, numeric-id allowlist); outbound notifier (`telegram/`) for ten classes (chain-runtime-upgrade / chain-parameter-change / gate-crossing / fleet-signal / repository-update / schema-drift / knowledge-ingestion / subnet-registry / fail-closed, plus the pulse briefing), each carrying a registered delivery tier, scrub-or-refuse + six-field delivery ledger + event-id de-dup, isolated on failure. **gate-crossing (2026-07-28):** confirmed emission-gate bar crossings page instantly (per-netuid 24h cooldown, suppressed-recorded-never-dropped, both figures sourced: panel share vs chain-read bar). **network-drift-455:** a same-block batch of one netuid-keyed chain-parameter item pages once (the 2026-09-09 49-subnet flip would have been one page); each collapsed row is still ledgered. The pool-side emission switch is named as a switch, not as the bar. **Signal-tiering (2026-07-13):** repo alerts tiered significant-vs-churn (deny-by-default; churn digested, never dropped), both-clocks repo-vs-live-chain marking, a high-priority live `chain-runtime-upgrade` class, and structured Telegram HTML (no em dashes, 400→plain-text fallback). Schedule: the emission-gate poll, then `scan`, both best-effort `ExecStartPost=-…` on the repo-update service; the live spec poll has its own hourly timer since 2026-09-24; 112-test suite; live alerts delivered on the Pi. Voice is governed by `agent-voice` below. **pulse-briefing (2026-08-31):** every class carries a delivery tier (`instant` pages, `briefing` records as `briefed` and rides the daily pulse briefing); new instant classes `subnet-registry` (netuid set / on-chain name changes) and `fail-closed` (one page per persistent outage); the runtime-upgrade message joins the matching repo range for its release subject; hovering crossings record without paging; `atlas_briefing.py` composes the daily/weekly editions from stores only. **rotation-signal-gate (2026-09-09):** every class carries a registered `tier` and a class the registry does not name delivers nothing, so drift fails closed; a new `shadow` tier records and measures but sends nothing and is the default for a new netuid-scoped class; the tier is resolved per event, so the three classes the fleet-signal queue emits are demotable independently; the delivery ledger records the governing tier. `econ-code` and `subnet-registry` are demoted to `briefing` on their own effectiveness reads (see `docs/decisions.md`), and a new `root-rotation` class ships at `shadow` (removed 2026-09-24 by `root-weight-drift`: spec 469 left it nothing to read). Service-failure alerts deferred (needs a Hermes service unit); investment alerts are Phase 7 |
| `pulse-briefing` | Done: deployed + archived (2026-09-11). The alert stream became a pulse. `telegram/atlas_briefing.py` composes a daily edition at `daily_hour_utc`, replaced weekly, **from stores already on disk, read-only**: no provider call, no model call, every figure traced to a stored row with its reference block or date, and a section whose inputs are missing or stale says so instead of estimating. Editions are gated by a durable watermark in the notifier ledger, so a restart cannot double-send and a missed hour catches up. Sections render in fixed order and truncation drops whole lines from the lowest-priority section upward, never the network section. Each Telegram class carries a delivery tier; livedata persists an hourly per-subnet `panel_snapshot` and a daily `network_vitals` row; the gate learned hovering and zero-price rules; the econ judge got an anchored significance scale. **Acceptance 2026-09-11:** composition adds no provider call (the two calls near each 07:0x edition are the hourly `chain_head_taostats` and `subnets_taoswap`; hour 07 carries the same 4 calls as every other non-fleet hour). Task 6.4 closed as superseded by `rotation-signal-gate` |
| `agent-voice` | Done: accepted + archived (2026-08-13, change `telegram-voice-overhaul`). One voice for both paths: chat (`SOUL.md` canon, 2684 B) and alerts (lexicon + gloss maps in `telegram/config.json`), specified in `telegram/docs/voice.md`. Accepted on 26 exchanges on the Pi: honesty 6/6 (dated corpus facts or explicit refusals, zero invented live values) and four voice probes at 5 replicates each, 5/5 apiece including the next-action omission arm. The next-action rule is enforced by position, not emphasis: three rounds of tightening measured 20%, the original one-liner plus a read-back check placed after the honesty contract measured 100% (n=15). Same pass fixed a live defect (`platform_hints` nested under `agent:` where hermes never read it; the Telegram hint is live since 2026-08-13) and updated Hermes 0.18.2 → 0.20.0. Live model is `grok-4.6`. Not yet measured: the Telegram gateway path itself (acceptance ran through the CLI path), and a lexicon leak (`threshold`/`flip`) in one paragraph no probe covers |
| `subnet-repo-fleet` | Done — deployed + archived (2026-07-19) — a chain-driven reconciliation layer over the singleton tracker (`fleet/`): clones every subnet's on-chain `github_repo` (TaoStats `subnet/identity`, whole 129-subnet map in one call at `limit=200`) into a **blobless, never-executed** fleet under `var/fleet/`, keyed by netuid. On-device: **104 active clones** (~2.7 GB), 10 unreachable (escalating backoff — placeholder/private/dead repos), 1 invalid-url, 14 no-repo. Mass-discard guard (a degraded identity fetch is non-destructive), fingerprint re-point with epoch-segmented change history, per-repo size/file caps→quarantine, disk ceiling, optional `GITHUB_TOKEN` (public-read-only, never persisted to a clone). Reuses repotrack's `collect_range`; `status` + `reconcile [--identity-file]` CLI + a 6h timer. Timer installed, discovery gate ratified, tracking-policy confirmed. Downstream builds below: `fleet-search`, `fleet-signals`, `fleet-rotation-metrics` |
| `fleet-search` | Done — deployed + archived (2026-07-19) — a shared `(netuid,epoch)`-scoped FTS index over the fleet clones, kept in step by reconcile (incremental on clean fast-forward, full walk otherwise; discard/re-point purge in the slot transaction), plus the read-only `atlas-fleet` MCP server in Hermes (`fleet_search` / `fleet_file` / `fleet_status`). Never builds or executes subnet code; store opens `mode=ro`, fails closed as `fleet-search-unavailable` |
| `fleet-signals` | Done — deployed + archived (2026-07-19) — narrative radar + econ-code alerts over the fleet's change ranges: a `(netuid,epoch)`-scoped term ledger (manifest deps + model-id strings), novelty-gated cluster / watchlist / econ-code detection queued for tiered Telegram delivery, and an effectiveness ledger (alpha-price entry snapshots via keyless TaoSwap + horizon outcomes vs a fleet-median baseline). Read-only, per-range fail-closed, never executes subnet code; ranks/recommends nothing |
| `signal-effectiveness-gate` | Done: deployed + archived (2026-09-11, change `rotation-signal-gate`). Alerts must earn the right to page. The effectiveness ledger lifted out of `fleet-signals` measures every netuid-scoped class by source triple whatever its tier, so a demoted class keeps filling and a demotion can be reversed on evidence. A new `shadow` tier records and measures but sends nothing, and is the default for a new netuid-scoped class, so nothing new can page by accident; a class the tier registry does not name delivers nothing, so drift fails closed. A class reaches a paging tier only by an operator decision recorded in `docs/decisions.md` against a filled read that beats the fleet baseline. On its own ledger read `econ-code` was demoted to `briefing` (no edge at 1 day, worse at 7, n=185 to 212) and `subnet-registry` too (all six alerts in 30 days were renames). **Measured 2026-09-11:** volume fell from about 6.6 pages a day to about 1.5 |
| `fleet-rotation-metrics` | Done — deployed + archived (2026-07-26) — turns the fleet into a rotation cockpit (`fleet/atlas_fleet_metrics.py` + `atlas_fleet_dashboard.py`): per-`(netuid,epoch)` **emission-redirect map** with `file:line` evidence + opacity flag (proportion/fraction/hotkey-gated so incidental family-word vars aren't mistaken for splits), epoch-scoped activity + **branch pulse** (`ls-remote` tip diff, no fetch), momentum reused from `signal_prices` (→ `n/a` until history accrues), percentile quadrant, and a ranked **LAN-only "attention board"** static dashboard (explicit score; fresh events top, opacity deduped). Read-only, additive tables, per-slot fail-closed, never executes subnet code; runs inline after signals + `atlas-dashboard.service`. Full fleet suite **214 green** off-device; delta specs synced. On the Pi: metrics inline each pass over the active clones (43 emission routes; SN54 = 35% partner); board live at `http://192.168.0.150:8480/` after a LAN-scoped nftables accept for 8480 (2026-07-26); traversal containment verified from another LAN device |
| `mining-triage` | Done: deployed + archived (2026-08-12). `fleet/atlas_fleet_mining.py`, inline and fail-isolated after metrics in the 6h fleet pass. Ranks subnets by what a **new independent miner** could earn: pool-side emission switch cut (`pool-side-switch-off`; not the emission-gate bar), `identity-placeholder` cut (owner-written `SubnetIdentitiesV3` names such as `deprecated`/`Parked`, or no entry), owner-capture cut (`MinerBurned` ≥ 99%), `winner-take-all` cut (top-1 incentive share ≥ 95%), then sha-gated `file:line` feasibility over the fleet FTS index (`min_compute.yml` VRAM floor, miner entrypoint, GPU and closed-API tells). Headline is an entrant figure under a stated parity model (pool shared among earners + 1). Chain reads are keyless batched `state_queryStorageAt` at one finalized block via livedata (`twox128`, `read_subnet_maps`; hasher derived from the observed key tail and verified, never assumed); zero TaoStats quota. Output: `var/fleet/www/mining.html` at `http://192.168.0.150:8480/mining.html` and read-only `mining_board` / `mining_subnet` / `mining_history` on `atlas-fleet`. `CollateralLockShare` (dormant chain-wide) joined the chain-parameter watch. Latest board: 128 observed / 46 ranked / 82 cut; first rung `pool-side-switch-off` (netuids 29, 35, 36). `mining.budget_band` is still null (rent unknown, hardware rung inert); see Next step |
| `subnt-publish` | Publisher rename deployed on 2026-09-22; device publish and timer verified (see the public-page repo `docs/subnt-rename.md`). Domain cutover is complete; https://subnt.dev serves the verified edition. Original renderer: deployed + archived (2026-09-11, change `subnt-renderer`). `subnt/atlas_subnt.py` composes the public subnt.dev edition from `livedata` and `fleet` rows, all opened read-only, to the `public-pulse` contract in `vanlabs-dev/subnt`: five landmarks, gaps named never estimated, stale bounds per input (26h for the emission-gate bar; vitals dated, not stale for age; movers over the window since the previous publish). Charts are inline SVG from recorded series and introduce no figure the page does not report. Attention reuses `build_board` ordering, drops `pure_opaque`, caps at ten, and derives each reason from `div_signed`/`cold`/`econ_fresh`/`pulse_spike` rather than the near-constant category, grouping rows that share one; no score, glyph or thesis. Deltas compare against the last subnt publish in its own `var/subnt/subnt.db`, never the Telegram watermark, and a zero delta is suppressed. Before any write the document is scanned for operator material and for any browser data fetch, failing the pass closed. The publish gate hashes the facts with the as-of line normalised out, and the checkout is fast-forwarded first (a diverged one fails closed). Own oneshot unit and timer at `00/6:55` local time, after the fleet pass. On the Pi: a write-scoped deploy key for the subnt repo alone; Atlas itself still pulls anonymously over HTTPS. 75 tests green off-device |
| `econ-alert-intelligence` | Done — deployed + archived (2026-07-26, change `econ-alert-intelligence-gate`). A language-model materiality judgment between econ-path detection and the phone: the gate reads the diff from the local blobless clone (read-only, bounded, never executing subnet code), asks the local Hermes CLI for an evidence-grounded verdict, and routes by significance — page, digest, or recorded drop — with a high-stakes path floor. Diff text is untrusted end to end; verdicts cache by content, fail soft as `unjudged`, and reuse the Hermes subscription (no new credential). Since `rotation-signal-gate` the verdict drives detection, cooldown and the ledger while the class's registered tier alone decides whether anything pages |

Latest closed-loop assessment `20260711T073125Z-d52a70e9`: **ok=7, finding=0**.
Hermes baseline carries 2 documented exceptions (runs as `pi`; no service
unit) — both to close before production acceptance.

## The device

- **Hardware/OS:** Raspberry Pi 5 Model B Rev 1.1, 16 GB RAM, 256 GB NVMe,
  Debian 13 (trixie), kernel 6.18, Python 3.13.
- **Access:** `ssh pi@192.168.0.150` — **key auth only** (password auth is
  disabled as of the hardening). A new session's key must be in the Pi's
  `~/.ssh/authorized_keys` to connect.
- **sudo needs a password** (no passwordless sudo). Automation must never enter
  it: privileged steps are run by the operator, or by tooling only when
  `sudo -n` already succeeds from a cached session. Never put a password on a
  command line.
- **Repo on the Pi:** cloned at `~/atlas`, kept current with `git pull`
  (remote: `github.com/vanlabs-dev/atlas`). This is the live working tree.
- **Applied hardening:** SSH key-only + X11Forwarding off; rpcbind and avahi
  disabled; nftables default-deny inbound (SSH allowed), enabled at boot;
  unattended security updates on (no auto-reboot).
- **Hermes on the Pi:** runs as user `pi`, started manually (no service unit
  yet). CLI `~/.local/bin/hermes`, data/config in `~/.hermes/`, code clone at
  `~/.hermes/hermes-agent`, model Grok (`grok-4.6`) via X OAuth — validated
  per ATLAS-HERMES-003. Memory and skill writes are **approval-gated**
  (`memory.write_approval` / `skills.write_approval: on`). The production
  knowledge tools are registered as stdio MCP server **`atlas-kb`**
  (`knowledge/atlas_kb_server.py`; it replaced the baseline `atlas-test`
  test tool on 2026-07-12), joined by **`atlas-repo`**
  (`repotrack/atlas_repo_server.py`) for repository evidence and
  **`atlas-live`** (`livedata/atlas_live_server.py`) for current
  provider data (all registered 2026-07-12; `TAOSTATS_API_KEY` in the
  Pi's 0600 `.env`), and **`atlas-fleet`** (`fleet/atlas_fleet_server.py`)
  for fleet search, rotation metrics and the mining screen. Stores live in
  gitignored `var/knowledge/`, `var/repotrack/` (clone + index),
  `var/livedata/` (quota ledger, audit, health), `var/telegram/` (delivery
  ledger + watermarks) and `var/fleet/` (clones, `fleet.db`, `www/`) on
  the Pi. Voice canon: `~/.hermes/SOUL.md` plus a root-level
  `platform_hints` entry in `~/.hermes/config.yaml`, both from
  `telegram/docs/voice.md`. **Telegram (Phase 5):** inbound conversation is the native Hermes
  gateway (operator-configured via `hermes gateway setup`; numeric-ID
  allowlist); the outbound notifier (`telegram/atlas_telegram.py`) runs as
  a best-effort `ExecStartPost` on the hourly repotrack service (preceded by
  the emission-gate poll; the live spec poll runs on its own hourly timer)
  and sends scrubbed,
  de-duplicated, significance-tiered alerts. Install record:
  `var/hermes/install-record.json` (on the Pi only). Full facts in the
  acceptance entries in [docs/decisions.md](docs/decisions.md).

## Repo layout

```
prd.md                     # governing product requirements (source of truth)
docs/decisions.md          # resolved + open decisions (check before re-asking)
docs/emission-metrics.md   # how to read TaoSwap emission fields, verified against live data
docs/design/               # pre-proposal design records; the archived change's design.md supersedes and links to them
triage/                    # evidence for emission-metrics.md: 2026-08-11 panel snapshot, metagraph pulls, critic passes
inventory/                 # device-inventory tool (read-only), tests, schema, docs
hardening/                 # hardening-assessment tool (read-only)
hardening/apply/           # hardening-apply scripts (the ONLY device-mutating code)
hermes/                    # Hermes baseline verifier (read-only) + MCP test tool
hermes/memory/             # memory/session-recall verifier + scripted procedure (read-only)
hermes/modelval/           # ATLAS-HERMES-003 battery, runner, and read-only scorer
knowledge/                 # Phase 2 knowledge base: corpus snapshot, store, MCP tools, benchmark
repotrack/                 # Phase 3 subtensor repo tracking: clone/update/index CLI + MCP tools
livedata/                  # Phase 4 live data: discovery, adapters, quota, MCP tools, chain-read probe
upgrade/                   # runtime upgrade job: orchestrator, model prompt, edit scope, units
telegram/                  # Phase 5 outbound notifier (scrub, ledger, dedup); inbound is native Hermes gateway
telegram/docs/voice.md     # agent-voice spec: SOUL.md canon, lexicon, platform hint
fleet/                     # subnet fleet: reconciler, search index + atlas-fleet MCP, signals, rotation metrics, mining triage, dashboard
openspec/specs/            # accepted capability specs
openspec/changes/          # active changes + archive/
var/                        # gitignored: device-sensitive inventory/assessment outputs
```

## Working conventions

- **OpenSpec workflow:** propose (`/opsx:propose`) → apply (`/opsx:apply`) →
  archive (`/opsx:archive`). One change per narrowly-scoped capability; see
  PRD §22 for the recommended sequence.
- **Read-only vs mutating:** `inventory/`, `hardening/` (except
  `hardening/apply/`), and `hermes/` never change the device. `hardening/apply/`
  is the only code that mutates, and only applies operator-approved items.
- **Fail closed / no assumptions:** tools report explicit unknowns
  (`permission-denied`, `unsupported-on-device`) rather than guessing.
- **Secrets never enter the repo, logs, or chat.** Outputs are redacted and
  written 0600 into gitignored `var/`.
- **Privileged assessment:** reading the firewall and `/etc/ssl/private` needs
  root, so full hardening acceptance runs the inventory + assessor under `sudo`
  (produces root-owned outputs). See [docs/decisions.md](docs/decisions.md)
  "Operational notes".
- **Tests run off-device;** WSL is used as a throwaway Linux environment for
  integration runs. The Pi itself is the acceptance environment.

## Next step

**No change is active.** `openspec/changes/` holds only `archive/`.
`https://subnt.dev` is the only public surface; everything else is LAN-only.

The runtime upgrade rollout finished on the Pi on 2026-09-24: corpus run
`20260924T034531Z-66329b35` active, dry run passed every gate, timers
enabled, Hermes cron job removed. Operator steps still open:

1. **Battery re-run.** Run the retrieval battery against the new corpus
   run. The last accepted run predates `KB-CF-6`.
2. **Hermes script cleanup.** After the first real upgrade, delete
   `~/.hermes/scripts/atlas_live_spec.py` (task 7.4).

Before any new proposal:

1. **`mining.budget_band`.** Still `null` in `fleet/config.json` while
   `mining.enabled` is `true`. Pick a band, or set `enabled` false.
2. **Voice calibration.** One week of real Telegram traffic against
   `telegram/docs/voice.md`. Acceptance ran through the CLI only.

**Phase 6** (operator monitoring frontend) is still blocked on PRD §21
Q36–Q40. subnt.dev is a public read, not that frontend.

Standing pre-production debts from [docs/decisions.md](docs/decisions.md):
backup restore test, dedicated service account, service unit for boot
persistence (also gates **service-failure** Telegram alerts, deferred), and
the PRD §21 Q19 gating decision (evidence recorded; default stays
approval-gated).
