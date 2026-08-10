# Atlas

Self-hosted, single-user Bittensor knowledge and live-data agent built on Hermes,
running on a Raspberry Pi. Built methodically in gated phases via OpenSpec.

**This README is the orientation map. Authoritative sources it points to:**
[prd.md](prd.md) (full product requirements), [docs/decisions.md](docs/decisions.md)
(resolved/open decisions), `openspec/specs/` (accepted capability specs), and
`openspec/changes/archive/` (completed changes with their proposal/design/tasks).

## Current status (2026-08-06)

**Phases 0–5 are complete and accepted on the device.** Hermes Agent
v0.18.2 runs on the Pi (Grok via X OAuth, validated), answering Bittensor
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
Telegram class pages knob transitions. Investment/rotation tooling is
Phase 7 territory.

| Capability (accepted spec) | State |
|---|---|
| `device-inventory` | Done — read-only Pi inventory tool + clean baseline captured |
| `hardening-assessment` | Done — read-only posture assessor (11 ATLAS-ENV-003 areas) |
| `hardening-apply` | Done — 6 approved items applied + verified on the Pi |
| `hermes-baseline` | Done — manual install verified; acceptance run `20260711T091512Z-61ef71d0` |
| `memory-session-recall` | Done — ATLAS-MEM-001…006 verified on the Pi; acceptance run `20260711T171200Z-33321220` (approval gating on, all seven ATLAS-MEM-006 items attested) |
| `model-validation` | Done — ATLAS-HERMES-003 validated on the Pi; run `20260711T182926Z-b1eef1c6` (tool calls 20/20, context to 96k chars, 3.19s median latency; one documented refusal exception; retrieval criterion closed by the Phase 2 benchmark) |
| `knowledge-base` | Done — 23 units active (all `confirmed`; the **2026-08-06 re-sync** brought the corpus from spec 440 to 443: the gate bar is rank-pinned and the quantile is inert, plus a Root Reborn section covering the live mechanism and its dormant curation gate), `atlas-kb` tools live in Hermes; benchmark re-run `20260806T083003Z-58ae33ea` accepted over the new corpus (correct-with-evidence 0.95, refusals 10/10, 0 fabrications — MV-RI-4 held), including the adversarial case that must refuse a live-sounding quantile; the single grounded miss is a marker string artifact ("Jun" vs "june 2026"), not a knowledge gap |
| `subtensor-repo-tracking` | Done — identity-validated full clone of `RaoFoundation/subtensor` on the Pi (non-shallow, push disabled, @ `14bc6f9f964b`), safe journaled updates (hourly timer), 581-file FTS index, `atlas-repo` tools live in Hermes (commit-and-file-cited answers; honest stale/no-evidence) |
| `live-data` | Done — contract-validated TaoSwap (keyless, first) + TaoStats (2/min self-cap, 10k/month ledger) + CoinGecko adapters; pinned schemas, freshness envelopes, `atlas-live` tools live in Hermes; outage battery proved honest unavailability (MV-RI-4 class closed); chain head watch: live spec **443** (conviction ownership ENACTED at spec 432, 2026-07-16). **gate-crossing-signal (2026-07-28):** hourly `poll-gate` reads the emission-gate state via keyless finney RPC on pinned keys at one finalized block (null-storage semantics, `assumed-default` provenance), computes demand shares from the TaoSwap panel over the chain's full bar universe, and records hysteresis-guarded crossing events. **network-drift-443 (2026-08-06):** the poll additionally reads `EmissionBarRank` (SCALE `u16`, its own codec) and records each observation's derived bar mode — rank-pinned since spec 441, which makes the explicit q of 0.75 inert; crossings carry the previous theta so a bar that moved onto a subnet is never reported as demand that rose; a bar-parameter change re-seeds all sides silently instead of emitting \|M - N\| crossings; and rank mode is cross-checked by persisting `above_count` against the effective N. A **chain-parameter watch** tracks all four root-settable knobs (bar values handed over by the gate poll, `RootWeightSettingEnabled` read independently and currently `false`), recording durable transitions; it survives the gate kill-switch |
| `telegram-integration` | Done — inbound conversation via the native Hermes gateway (operator wizard, numeric-id allowlist); outbound notifier (`telegram/`) for six classes (chain-runtime-upgrade / chain-parameter-change / gate-crossing / repository-update / schema-drift / knowledge-ingestion), scrub-or-refuse + six-field delivery ledger + event-id de-dup, isolated on failure. **gate-crossing (2026-07-28):** confirmed emission-gate bar crossings page instantly (per-netuid 24h cooldown, suppressed-recorded-never-dropped, both figures sourced: panel share vs chain-read bar). **Signal-tiering (2026-07-13):** repo alerts tiered significant-vs-churn (deny-by-default; churn digested, never dropped), both-clocks repo-vs-live-chain marking, a high-priority live `chain-runtime-upgrade` class, and structured Telegram HTML (no em dashes, 400→plain-text fallback). Schedule: an hourly chain-head poll, then the emission-gate poll, then `scan`, all best-effort `ExecStartPost=-…` on the repo-update service; 78-test suite; live alerts delivered on the Pi. Service-failure alerts deferred (needs a Hermes service unit); investment alerts are Phase 7 |
| `subnet-repo-fleet` | Done — deployed + archived (2026-07-19) — a chain-driven reconciliation layer over the singleton tracker (`fleet/`): clones every subnet's on-chain `github_repo` (TaoStats `subnet/identity`, whole 129-subnet map in one call at `limit=200`) into a **blobless, never-executed** fleet under `var/fleet/`, keyed by netuid. On-device: **104 active clones** (~2.7 GB), 10 unreachable (escalating backoff — placeholder/private/dead repos), 1 invalid-url, 14 no-repo. Mass-discard guard (a degraded identity fetch is non-destructive), fingerprint re-point with epoch-segmented change history, per-repo size/file caps→quarantine, disk ceiling, optional `GITHUB_TOKEN` (public-read-only, never persisted to a clone). Reuses repotrack's `collect_range`; `status` + `reconcile [--identity-file]` CLI + a 6h timer. Timer installed, discovery gate ratified, tracking-policy confirmed. Downstream builds below: `fleet-search`, `fleet-signals`, `fleet-rotation-metrics` |
| `fleet-search` | Done — deployed + archived (2026-07-19) — a shared `(netuid,epoch)`-scoped FTS index over the fleet clones, kept in step by reconcile (incremental on clean fast-forward, full walk otherwise; discard/re-point purge in the slot transaction), plus the read-only `atlas-fleet` MCP server in Hermes (`fleet_search` / `fleet_file` / `fleet_status`). Never builds or executes subnet code; store opens `mode=ro`, fails closed as `fleet-search-unavailable` |
| `fleet-signals` | Done — deployed + archived (2026-07-19) — narrative radar + econ-code alerts over the fleet's change ranges: a `(netuid,epoch)`-scoped term ledger (manifest deps + model-id strings), novelty-gated cluster / watchlist / econ-code detection queued for tiered Telegram delivery, and an effectiveness ledger (alpha-price entry snapshots via keyless TaoSwap + horizon outcomes vs a fleet-median baseline). Read-only, per-range fail-closed, never executes subnet code; ranks/recommends nothing |
| `fleet-rotation-metrics` | Done — deployed + archived (2026-07-26) — turns the fleet into a rotation cockpit (`fleet/atlas_fleet_metrics.py` + `atlas_fleet_dashboard.py`): per-`(netuid,epoch)` **emission-redirect map** with `file:line` evidence + opacity flag (proportion/fraction/hotkey-gated so incidental family-word vars aren't mistaken for splits), epoch-scoped activity + **branch pulse** (`ls-remote` tip diff, no fetch), momentum reused from `signal_prices` (→ `n/a` until history accrues), percentile quadrant, and a ranked **LAN-only "attention board"** static dashboard (explicit score; fresh events top, opacity deduped). Read-only, additive tables, per-slot fail-closed, never executes subnet code; runs inline after signals + `atlas-dashboard.service`. Full fleet suite **214 green** off-device; delta specs synced. On the Pi: metrics inline each pass over the active clones (43 emission routes; SN54 = 35% partner); board live at `http://192.168.0.150:8480/` after a LAN-scoped nftables accept for 8480 (2026-07-26); traversal containment verified from another LAN device |

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
  Pi's 0600 `.env`). Stores live in gitignored `var/knowledge/`,
  `var/repotrack/` (clone + index), `var/livedata/` (quota ledger,
  audit, health), and `var/telegram/` (delivery ledger + watermarks) on
  the Pi. **Telegram (Phase 5):** inbound conversation is the native Hermes
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
fleet/                     # subnet-repo-fleet: chain-driven blobless clone fleet of subnet repos (reconciler, registry, CLI, timer)
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

**Next is `mining-triage`** (2026-08-07), sequenced ahead of Phase 6 by
operator decision and recorded as a §22 amendment. A read-only screen
ranking subnets by what a new independent miner could earn: emission-gate
and owner-capture cuts, an entrant income figure under a stated parity
assumption, concentration from the chain incentive vector, `file:line`
feasibility evidence from the fleet clones, a second LAN-only board at
`http://192.168.0.150:8480/mining.html`, and three read-only tools on the
`atlas-fleet` MCP server. Every input is keyless, so it consumes zero
TaoStats quota. It runs no miner, holds no key, and submits no transaction,
so PRD §7 holds unchanged.

**Phase 6** (monitoring frontend) follows rather than precedes. Its §21
blocking questions stay open — Q36 access location, Q37 auth, Q38 LAN
HTTPS/certs, Q39 first-screen health fields, Q40 retention.
Watchpoints: the **gate-crossing calibration read (~2026-08-11)** — review
recorded-vs-paged crossings, tune `hysteresis_pct`/`cooldown_hours` from
evidence (the conviction-enactment watch closed 2026-07-28: spec 424→432
carried the enforcement, the corpus is re-synced, and the emission model is
now gated price-based at spec 440), and
the standing pre-production debts from [docs/decisions.md](docs/decisions.md):
backup restore test, dedicated service account, service unit for boot
persistence (also gates **service-failure** Telegram alerts, deferred), and
the PRD §21 Q19 gating decision (evidence recorded; default stays
approval-gated).
