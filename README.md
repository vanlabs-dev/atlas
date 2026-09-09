# Atlas

Self-hosted, single-user Bittensor knowledge and live-data agent built on Hermes,
running on a Raspberry Pi. Built methodically in gated phases via OpenSpec.

**This README is the orientation map. Authoritative sources it points to:**
[prd.md](prd.md) (full product requirements), [docs/decisions.md](docs/decisions.md)
(resolved/open decisions), `openspec/specs/` (accepted capability specs), and
`openspec/changes/archive/` (completed changes with their proposal/design/tasks).

## Current status (2026-09-09, chain at spec 455, corpus at spec 452)

**Phases 0–5 are complete and accepted on the device.** Hermes Agent
v0.20.0 runs on the Pi (Grok via X OAuth, validated), answering Bittensor
questions from the validated local knowledge base (`atlas-kb`), the
tracked subtensor repository clone (`atlas-repo`), and live provider
data (`atlas-live`: TaoSwap/TaoStats/CoinGecko) — source-bound, dated,
commit-cited, provenance-enveloped, fail-closed. A controlled Telegram
channel (`telegram/`) adds inbound conversation (native Hermes gateway)
and an outbound operational notifier, scrubbed and de-duplicated.

**Beyond the accepted phases:** the `subnet-repo-fleet` (`fleet/`) is
deployed and archived — 104 subnet code repositories cloned blobless and
chain-reconciled on the Pi, timer installed, discovery gate ratified. Three
downstream changes build on it: **fleet-search** (code-search index +
`atlas-fleet` MCP server) and **fleet-signals** (narrative / econ-code
alerts + effectiveness ledger), both deployed and archived; and
**fleet-rotation-metrics** (emission-redirect map, epoch-scoped activity +
branch pulse, momentum / quadrant, and a ranked LAN-only "attention board"
dashboard) — deployed + archived; the board is live on the LAN at
`http://192.168.0.150:8480/`. **gate-crossing-signal** (2026-07-28,
deployed + archived): the spec-440 emission gate made the bar
(`EmissionGateBar`) a per-subnet economic cliff, so livedata now polls
the live gate state (theta/N/q/h via keyless finney RPC on pinned keys)
each hour, tracks every subnet's side of the bar with hysteresis, and a
fifth Telegram class pages confirmed crossings. **network-drift-443**
(2026-08-06, deployed + archived): mainnet ran spec 441/442/443 and two chain changes
landed that the corpus did not know. Spec 441 made the gate bar
**rank-pinned** (`EmissionBarRank` pins theta to the Nth-largest positive
demand share; the code default is 32, so the live `EmissionBarQuantile` of
0.75 is inert), and **Root Reborn** went live with basket curation gated
OFF. livedata now reads the rank, records each observation's bar mode,
watches all four root-settable knobs for transitions, re-seeds sides
silently on a bar re-pricing instead of paging |M - N| crossings, and
cross-checks its own share pipeline against the rank invariant; a sixth
Telegram class pages knob transitions. **mining-triage** (2026-08-12,
deployed + archived): a read-only screen ranking subnets by what a new
independent miner could earn, with a cut ladder, `file:line` feasibility
evidence, a second LAN board at `http://192.168.0.150:8480/mining.html`,
and three `atlas-fleet` tools; every input is keyless. **agent-voice**
(2026-08-13, accepted + archived): one measured voice for chat and alerts.
**network-drift-452** (2026-08-31, deployed + archived): Finney ran spec 444 to 452
between 2026-08-07 and 2026-08-29. Three releases falsified corpus claims:
spec 447 made the subnet takeover gate a single hotkey above 18% of
eligible alpha (the aggregate 10% rule is gone), spec 449 switched Root
Reborn curation ON with a 1/16 `RootWeightsCap`, and spec 450 moved beta
pricing on-chain (baseline, basket index, display units). The corpus is
re-synced to 452, the battery gained three cases that tempt the stale
answers, `RootWeightsCap` joined the chain-parameter watch, and the rank
cross-check tolerance is 1 (the exact invariant holds only at the chain's
theta recalculation block; the 105 silent divergence events were that
boundary); benchmark `20260831T165224Z-722feb65` accepted on the Pi.
**pulse-briefing** (2026-08-31, deployed, not archived): the alert stream
became a pulse. Every Telegram class carries a delivery tier, a daily/weekly
briefing is composed from stores only (editions delivering since 2026-09-01),
livedata persists an hourly per-subnet panel snapshot and daily network
vitals, the gate learns hovering and zero-price rules, and the econ judge got
an anchored significance scale. Three acceptance tasks remain open (6.3 to
6.5). Task 6.4 ("flip the six classes to briefing in one commit") predates
`rotation-signal-gate` and is unresolved against its evidence rule: it would
demote classes the later change deliberately left instant, on no ledger
read. Needs an operator decision before either change is archived.
**rotation-signal-gate** (2026-09-09, deployed, not archived): alerts must now
earn the right to page. The effectiveness ledger measures every netuid-scoped
class by source triple, whatever its tier; a new `shadow` tier records and
measures but sends nothing and is the default for a new class; a class the
tier registry does not name delivers nothing. On its own ledger read
`econ-code` was demoted to `briefing` (no edge at 1 day, worse than baseline
at 7, n=185 to 212) and `subnet-registry` too (all six alerts in 30 days were
renames). livedata now reads every per-validator **root weight vector** at the
gate poll's block and aggregates them, stake-weighted, into a destination map;
a material shift records a `root-rotation` event, which ships at `shadow`. A
gate crossing pages only after a 48h durability window with no reversal.
Expected volume falls from about 6.6 pages a day to 1 or 2; the one-week
confirmation is due 2026-09-16.

**shinogi-renderer** (2026-09-09, built, not deployed): `https://shinogi.dev`
serves a shell whose as-of line still reads `awaiting first Atlas publish`.
A new top-level `shinogi/` composes the public edition from the livedata and
fleet stores read-only, to the page contract frozen in that repo, and
publishes it into a second checkout when a fact on the page has moved. It is
a second reader over those stores, not a wrapper around the briefing, whose
section builders return operator lines. Blocked on one operator decision:
the Pi has no write credential for `vanlabs-dev/shinogi`, so `publish` ships
`false`.

**Known gap: the corpus is three chain releases behind.** Finney ran 453
(2026-09-03), 454 (2026-09-04) and 455 (2026-09-07); detection recorded and
paged all three. Nothing the corpus states became false, but `claim_root`
admission, the basket-escrow transfer rejection and the registration queue are
now incomplete, and proxy call filters and the crowdloan pallet have no
coverage at all. See `knowledge/corpus/SOURCES.md`. Closing it is
`network-drift-455`, proposed but not drafted. Investment/rotation tooling is
Phase 7 territory.

| Capability (accepted spec) | State |
|---|---|
| `device-inventory` | Done — read-only Pi inventory tool + clean baseline captured |
| `hardening-assessment` | Done — read-only posture assessor (11 ATLAS-ENV-003 areas) |
| `hardening-apply` | Done — 6 approved items applied + verified on the Pi |
| `hermes-baseline` | Done — manual install verified; acceptance run `20260711T091512Z-61ef71d0` |
| `memory-session-recall` | Done — ATLAS-MEM-001…006 verified on the Pi; acceptance run `20260711T171200Z-33321220` (approval gating on, all seven ATLAS-MEM-006 items attested) |
| `model-validation` | Done — ATLAS-HERMES-003 validated on the Pi; run `20260711T182926Z-b1eef1c6` (tool calls 20/20, context to 96k chars, 3.19s median latency; one documented refusal exception; retrieval criterion closed by the Phase 2 benchmark) |
| `knowledge-base` | Done — 23 units active (all `confirmed`; the **2026-08-31 re-sync** (change `network-drift-452`, ingested and activated on the Pi as run `20260831T081437Z-62048f75`) brought the corpus from spec 443 to 452: single-hotkey 18% takeover gate, Root Reborn curation live under the 1/16 cap, on-chain beta pricing, spec 448 staking additions; the 2026-08-06 re-sync had brought the rank-pinned bar), `atlas-kb` tools live in Hermes; benchmark `20260831T165224Z-722feb65` accepted over the 33-exchange battery (correct-with-evidence 0.9545, refusals 1.0, 0 fabrications — MV-RI-4 held), including the adversarial case that must refuse a live-sounding quantile; the single grounded miss is a marker string artifact ("Jun" vs "june 2026"), not a knowledge gap |
| `subtensor-repo-tracking` | Done — identity-validated full clone of `RaoFoundation/subtensor` on the Pi (non-shallow, push disabled, @ `14bc6f9f964b`), safe journaled updates (hourly timer), 581-file FTS index, `atlas-repo` tools live in Hermes (commit-and-file-cited answers; honest stale/no-evidence) |
| `live-data` | Done — contract-validated TaoSwap (keyless, first) + TaoStats (2/min self-cap, 10k/month ledger) + CoinGecko adapters; pinned schemas, freshness envelopes, `atlas-live` tools live in Hermes; outage battery proved honest unavailability (MV-RI-4 class closed); chain head watch: live spec **455** (conviction ownership ENACTED at spec 432, 2026-07-16). **gate-crossing-signal (2026-07-28):** hourly `poll-gate` reads the emission-gate state via keyless finney RPC on pinned keys at one finalized block (null-storage semantics, `assumed-default` provenance), computes demand shares from the TaoSwap panel over the chain's full bar universe, and records hysteresis-guarded crossing events. **network-drift-443 (2026-08-06):** the poll additionally reads `EmissionBarRank` (SCALE `u16`, its own codec) and records each observation's derived bar mode — rank-pinned since spec 441, which makes the explicit q of 0.75 inert; crossings carry the previous theta so a bar that moved onto a subnet is never reported as demand that rose; a bar-parameter change re-seeds all sides silently instead of emitting \|M - N\| crossings; and rank mode is cross-checked by persisting `above_count` against the effective N. A **chain-parameter watch** tracks the root-settable knobs (bar values handed over by the gate poll; `RootWeightSettingEnabled` read independently, `true` since 2026-08-27; **`RootWeightsCap`** at the root entry through a derived, self-tested Blake2_128Concat key since `network-drift-452`, 4096/65535), recording durable transitions; it survives the gate kill-switch. The rank cross-check tolerates a divergence of one: theta is fixed between 360-block recalculations while the panel EMA moves, so the Nth subnet sits on the bar. **pulse-briefing (2026-08-31):** each gate pass persists a per-subnet `panel_snapshot` (computed share + the panel fields the briefing reads, bounded retention) and one daily `network_vitals` row from two keyless calls; a zero moving price is a panel gap for side tracking (no crossing to zero, counts toward absence); subnets crossing more than `hover_crossings` times in `hover_window_days` are flagged hovering and their crossings annotated. **rotation-signal-gate (2026-09-09):** the same pass reads every per-validator **root weight vector** (`Weights[ROOT]`, one `state_getKeys` then one `state_queryStorageAt` at the gate poll's finalized block; `state_getPairs` is refused by the endpoint with code 4003) and aggregates them into a destination map that is **stake-weighted** by each validator's root stake (resolved through `Keys[ROOT][uid]` then `TotalHotkeyAlpha[hotkey][ROOT]`, two further derived batched reads, no enumeration) and carries its weighting basis as a stored field; a material shift records a `rotation_events` row, the first map seeds silently and a curation-knob transition re-seeds instead of storming. Fail-closed on a short batch, an undecodable vector, an unexpected key tail, or an enumeration over the cap. The read is independently disableable and is NOT gated by the gate kill-switch. Gate crossings now carry a persisted **eligibility**: a crossing pages only after a 48h durability window passes without an opposing crossing, and a reversal inside it marks both permanently ineligible |
| `telegram-integration` | Done — inbound conversation via the native Hermes gateway (operator wizard, numeric-id allowlist); outbound notifier (`telegram/`) for eleven classes (chain-runtime-upgrade / chain-parameter-change / gate-crossing / fleet-signal / repository-update / schema-drift / knowledge-ingestion / subnet-registry / fail-closed / root-rotation, plus the pulse briefing), each carrying a registered delivery tier, scrub-or-refuse + six-field delivery ledger + event-id de-dup, isolated on failure. **gate-crossing (2026-07-28):** confirmed emission-gate bar crossings page instantly (per-netuid 24h cooldown, suppressed-recorded-never-dropped, both figures sourced: panel share vs chain-read bar). **Signal-tiering (2026-07-13):** repo alerts tiered significant-vs-churn (deny-by-default; churn digested, never dropped), both-clocks repo-vs-live-chain marking, a high-priority live `chain-runtime-upgrade` class, and structured Telegram HTML (no em dashes, 400→plain-text fallback). Schedule: an hourly chain-head poll, then the emission-gate poll, then `scan`, all best-effort `ExecStartPost=-…` on the repo-update service; 112-test suite; live alerts delivered on the Pi. Voice is governed by `agent-voice` below. **pulse-briefing (2026-08-31):** every class carries a delivery tier (`instant` pages, `briefing` records as `briefed` and rides the daily pulse briefing); new instant classes `subnet-registry` (netuid set / on-chain name changes) and `fail-closed` (one page per persistent outage); the runtime-upgrade message joins the matching repo range for its release subject; hovering crossings record without paging; `atlas_briefing.py` composes the daily/weekly editions from stores only. **rotation-signal-gate (2026-09-09):** every class carries a registered `tier` and a class the registry does not name delivers nothing, so drift fails closed; a new `shadow` tier records and measures but sends nothing and is the default for a new netuid-scoped class; the tier is resolved per event, so the three classes the fleet-signal queue emits are demotable independently; the delivery ledger records the governing tier. `econ-code` and `subnet-registry` are demoted to `briefing` on their own effectiveness reads (see `docs/decisions.md`), and a new `root-rotation` class ships at `shadow`. Service-failure alerts deferred (needs a Hermes service unit); investment alerts are Phase 7 |
| `agent-voice` | Done: accepted + archived (2026-08-13, change `telegram-voice-overhaul`). One voice for both paths: chat (`SOUL.md` canon, 2684 B) and alerts (lexicon + gloss maps in `telegram/config.json`), specified in `telegram/docs/voice.md`. Accepted on 26 exchanges on the Pi: honesty 6/6 (dated corpus facts or explicit refusals, zero invented live values) and four voice probes at 5 replicates each, 5/5 apiece including the next-action omission arm. The next-action rule is enforced by position, not emphasis: three rounds of tightening measured 20%, the original one-liner plus a read-back check placed after the honesty contract measured 100% (n=15). Same pass fixed a live defect (`platform_hints` nested under `agent:` where hermes never read it; the Telegram hint is live since 2026-08-13) and updated Hermes 0.18.2 → 0.20.0 (model left on `grok-4.5`; a swap invalidates the knowledge-base benchmark). Not yet measured: the Telegram gateway path itself (acceptance ran through the CLI path), and a lexicon leak (`threshold`/`flip`) in one paragraph no probe covers |
| `subnet-repo-fleet` | Done — deployed + archived (2026-07-19) — a chain-driven reconciliation layer over the singleton tracker (`fleet/`): clones every subnet's on-chain `github_repo` (TaoStats `subnet/identity`, whole 129-subnet map in one call at `limit=200`) into a **blobless, never-executed** fleet under `var/fleet/`, keyed by netuid. On-device: **104 active clones** (~2.7 GB), 10 unreachable (escalating backoff — placeholder/private/dead repos), 1 invalid-url, 14 no-repo. Mass-discard guard (a degraded identity fetch is non-destructive), fingerprint re-point with epoch-segmented change history, per-repo size/file caps→quarantine, disk ceiling, optional `GITHUB_TOKEN` (public-read-only, never persisted to a clone). Reuses repotrack's `collect_range`; `status` + `reconcile [--identity-file]` CLI + a 6h timer. Timer installed, discovery gate ratified, tracking-policy confirmed. Downstream builds below: `fleet-search`, `fleet-signals`, `fleet-rotation-metrics` |
| `fleet-search` | Done — deployed + archived (2026-07-19) — a shared `(netuid,epoch)`-scoped FTS index over the fleet clones, kept in step by reconcile (incremental on clean fast-forward, full walk otherwise; discard/re-point purge in the slot transaction), plus the read-only `atlas-fleet` MCP server in Hermes (`fleet_search` / `fleet_file` / `fleet_status`). Never builds or executes subnet code; store opens `mode=ro`, fails closed as `fleet-search-unavailable` |
| `fleet-signals` | Done — deployed + archived (2026-07-19) — narrative radar + econ-code alerts over the fleet's change ranges: a `(netuid,epoch)`-scoped term ledger (manifest deps + model-id strings), novelty-gated cluster / watchlist / econ-code detection queued for tiered Telegram delivery, and an effectiveness ledger (alpha-price entry snapshots via keyless TaoSwap + horizon outcomes vs a fleet-median baseline). Read-only, per-range fail-closed, never executes subnet code; ranks/recommends nothing |
| `fleet-rotation-metrics` | Done — deployed + archived (2026-07-26) — turns the fleet into a rotation cockpit (`fleet/atlas_fleet_metrics.py` + `atlas_fleet_dashboard.py`): per-`(netuid,epoch)` **emission-redirect map** with `file:line` evidence + opacity flag (proportion/fraction/hotkey-gated so incidental family-word vars aren't mistaken for splits), epoch-scoped activity + **branch pulse** (`ls-remote` tip diff, no fetch), momentum reused from `signal_prices` (→ `n/a` until history accrues), percentile quadrant, and a ranked **LAN-only "attention board"** static dashboard (explicit score; fresh events top, opacity deduped). Read-only, additive tables, per-slot fail-closed, never executes subnet code; runs inline after signals + `atlas-dashboard.service`. Full fleet suite **214 green** off-device; delta specs synced. On the Pi: metrics inline each pass over the active clones (43 emission routes; SN54 = 35% partner); board live at `http://192.168.0.150:8480/` after a LAN-scoped nftables accept for 8480 (2026-07-26); traversal containment verified from another LAN device |
| `mining-triage` | Done: deployed + archived (2026-08-12). `fleet/atlas_fleet_mining.py`, inline and fail-isolated after metrics in the 6h fleet pass. Ranks subnets by what a **new independent miner** could earn: emission-gate cut, `identity-placeholder` cut (owner-written `SubnetIdentitiesV3` names such as `deprecated`/`Parked`, or no entry), owner-capture cut (`MinerBurned` ≥ 99%), `winner-take-all` cut (top-1 incentive share ≥ 95%), then sha-gated `file:line` feasibility over the fleet FTS index (`min_compute.yml` VRAM floor, miner entrypoint, GPU and closed-API tells). Headline is an entrant figure under a stated parity model (pool shared among earners + 1). Chain reads are keyless batched `state_queryStorageAt` at one finalized block via livedata (`twox128`, `read_subnet_maps`; hasher derived from the observed key tail and verified, never assumed); zero TaoStats quota. Output: `var/fleet/www/mining.html` at `http://192.168.0.150:8480/mining.html` and read-only `mining_board` / `mining_subnet` / `mining_history` on `atlas-fleet`. `CollateralLockShare` (dormant chain-wide) joined the chain-parameter watch. On the Pi at block 8823306: 128 observed / 36 ranked / 92 cut. `mining.budget_band` is still null (rent unknown, hardware rung inert); see Next step |
| `shinogi-publish` | Built off-device, not deployed (change `shinogi-renderer`). `shinogi/atlas_shinogi.py` composes the public shinogi.dev edition from `livedata` and `fleet` rows, all opened read-only, to the page contract frozen in `vanlabs-dev/shinogi`: five landmarks, gaps named never estimated, stale bounds per input (26h for the emission-gate bar; vitals dated, not stale for age; movers over the window since the previous publish). Attention rows reuse `build_board` ordering and `score_subnet`'s `why`, drop `pure_opaque`, cap at ten, and carry netuid, the name joined from `panel_snapshot.name`, and one public phrase: no score, no cue glyph, no thesis. Deltas compare against the last shinogi publish, held in its own `var/shinogi/shinogi.db`, never the Telegram watermark. Before any write the document is scanned for operator material and the self-contained rules, failing the pass closed. The publish gate hashes the facts with the as-of line normalised out, so a moving compose time alone never commits. Its own six-hour oneshot unit and timer at `00/6:55`. 38 tests green off-device. **Blocked:** no write credential for `vanlabs-dev/shinogi` on the Pi, so `publish` is `false` |
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
  `~/.hermes/hermes-agent`, model Grok (`grok-4.5`) via X OAuth — validated
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
  a live chain-head poll and the emission-gate poll) and sends scrubbed,
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
livedata/                  # Phase 4 live data: discovery, adapters, quota, MCP tools
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

Phases 0–5 are complete: Atlas answers from validated knowledge, cites
subtensor source by commit, reports current data with provider and
timestamp provenance (or refuses honestly), and reaches the operator over
a controlled Telegram channel — inbound conversation via the native Hermes
gateway (numeric-ID allowlist) and an outbound notifier (chain-runtime-upgrade,
gate-crossing, repository-update, schema-drift, knowledge-ingestion; repo
alerts tiered by significance) that scrubs secrets, records every delivery,
de-duplicates, and stays isolated on failure.

**No change is active** (2026-08-31). `mining-triage` shipped 2026-08-12 and
`telegram-voice-overhaul` 2026-08-13; both are archived. Three dated
follow-ups recorded in [docs/decisions.md](docs/decisions.md) "Still open"
are past due and come before any new proposal:

1. **`mining.budget_band`, due 2026-08-21.** Still `null` in
   `fleet/config.json`. The recorded rule: pick a hardware and capital band,
   or conclude mining is not being pursued and set the `mining` block's
   `enabled` to `false` rather than maintain the screen.
2. **Voice calibration read, due 2026-08-20.** One week of real Telegram
   traffic judged against `telegram/docs/voice.md`. The Telegram gateway
   path has never been measured directly.
3. **Gate calibration read, due ~2026-08-11.** Recorded-vs-paged crossings,
   tune `hysteresis_pct` / `cooldown_hours` from evidence (exclude the four
   spec-441 migration artefacts; only events from 2026-08-06 carry bar
   mode). Also re-check the rank invariant `above_count == 32`.

**Phase 6** (monitoring frontend) follows. Its §21 blocking questions stay
open: Q36 access location, Q37 auth, Q38 LAN HTTPS/certs, Q39 first-screen
health fields, Q40 retention.

Standing pre-production debts from [docs/decisions.md](docs/decisions.md):
backup restore test, dedicated service account, service unit for boot
persistence (also gates **service-failure** Telegram alerts, deferred), and
the PRD §21 Q19 gating decision (evidence recorded; default stays
approval-gated).
