# Proposal: atlas-phase-5-telegram

Governing documents: [prd.md](../../../prd.md) (§12.11 ATLAS-TG-001…006,
§16 Phase 5, and the Phase 7 deferral of investment alerts) and
[docs/decisions.md](../../../docs/decisions.md) (Q6 LAN-only/Telegram is
outbound-only; Q20 hourly repo timer already pushes toward notification).
Blocking Phase 5 questions Q32–Q35 resolved: **conversation *and*
notifications** (PRD Phase 5 exit criteria require both "approved account
can query Hermes" and "test alerts deliver once"); **allowed identifiers**
are operator-supplied numeric Telegram user IDs at apply time (device
config, never in the repo); **initial alert classes** = repository update,
API schema-drift, and knowledge-ingestion (operator-selected 2026-07-12 —
**service-failure deferred** until Hermes has a systemd service unit, which
is a separate open baseline exception); **quiet-hours/severity** kept
minimal for a single user — identity-based de-duplication with a short
coalescing window, no time-of-day muting initially.

## Why

Atlas answers Bittensor questions on the Pi over SSH only. It cannot reach
the operator when something changes (subtensor advances, a live provider's
schema drifts, knowledge is ingested), and the operator cannot ask it a
question without opening a terminal. Phase 5 adds a controlled Telegram
channel — outbound-only at the network layer, so it fits the LAN-only
posture (Q6) without opening any inbound port — giving the operator
conversation with Hermes and honest, de-duplicated operational alerts from
any device, while never exposing a secret or a wallet path.

## What Changes

- **Inbound conversation — operator setup, not Atlas code.** The operator
  creates the bot with BotFather and enables the native NousResearch Hermes
  Telegram gateway on the Pi: bot token in the 0600 `~/.hermes/.env`
  (`TELEGRAM_BOT_TOKEN`), access restricted to allowlisted numeric user IDs
  (`TELEGRAM_ALLOWED_USERS`), non-admin commands limited to an explicit
  `user_allowed_commands` allowlist. Atlas writes no gateway code; this
  change only provides a short setup note and **verifies the phase exit
  criteria at acceptance** — unauthorized account rejected, approved account
  can query Hermes, no destructive/wallet command reachable (ATLAS-TG-001/
  002/006). Telegram is outbound-only, so nothing needs opening in the
  firewall — the LAN-only/nftables posture (Q6) is untouched.
- **Outbound operational notifier (the actual build — new `telegram/`).** A
  small fail-closed sender that posts alerts to the Telegram Bot API for
  three event classes — repository update (Phase 3 hourly timer), API
  schema-drift (Phase 4 livedata health), knowledge-ingestion
  completion/review-needed (Phase 2) — each carrying source and time
  metadata, with a **sensitive-output scrubber** that refuses to send any
  message containing a key, a secret path with a value, an environment
  dump, or an over-exposure diagnostic (ATLAS-TG-004).
- **Delivery record with de-duplication (ATLAS-TG-005).** A 0600 append
  ledger in `var/telegram/` recording per event: identifier, creation time,
  attempted delivery time, delivery status, retry count, and final failure
  — with identity-based de-duplication so a flapping source cannot flood the
  operator.
- **Isolation guarantee.** Telegram unavailability (network, token, API
  outage) is caught and recorded; it MUST NOT affect Hermes conversation,
  the repo timer, or live-data tools (PRD Phase 5 exit criterion).

## Capabilities

### New Capabilities

- `telegram-integration`: Controlled Telegram channel for single-operator
  Atlas — validated Hermes inbound conversation gateway with numeric-ID
  access control and command allowlisting, plus an Atlas-owned outbound
  operational notifier (repository-update, schema-drift, knowledge-ingestion
  classes) with sensitive-output scrubbing, a delivery ledger, identity-based
  de-duplication, and core-operation isolation on Telegram failure.

### Modified Capabilities

<!-- None. Phase 5 introduces a new capability; it consumes existing
     event sources (subtensor-repo-tracking timer, live-data health,
     knowledge-base ingestion) without changing their accepted specs. -->

## Impact

- **New code:** `telegram/` (outbound notifier, scrubber, delivery ledger,
  event-source adapters, tests, docs) mirroring `livedata/`/`repotrack/`
  conventions — read-only toward the device except its own 0600 `var/`
  store.
- **New state (gitignored, on the Pi):** `var/telegram/` — delivery ledger,
  de-dup index, audit.
- **Config/secrets:** `TELEGRAM_BOT_TOKEN` and allowed user IDs added to the
  Pi's 0600 `~/.hermes/.env` and gateway config by the operator;
  `env.example` documents the keys with placeholder values only.
- **Hermes:** the native Telegram gateway is enabled and restarted by the
  operator; Atlas adds no gateway code and no service unit here.
- **Dependencies:** Telegram Bot API over HTTPS (outbound only). No new
  inbound ports; nftables posture unchanged — nothing to configure there.
- **Docs:** README status table, `docs/decisions.md` (Q32–Q35 resolutions),
  and a new `telegram/README.md`.
