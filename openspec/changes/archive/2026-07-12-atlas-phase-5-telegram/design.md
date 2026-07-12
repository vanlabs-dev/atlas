# Design: atlas-phase-5-telegram

References: [proposal.md](proposal.md) (motivation, scope), the
[telegram-integration spec](specs/telegram-integration/spec.md) (normative
requirements), PRD §12.11 ATLAS-TG-001…006, and the confirmed Hermes
Telegram gateway mechanism (NousResearch, validated against current docs at
propose time and re-confirmed at apply time).

## Context

Phases 0–4 are accepted on the Pi: Hermes v0.18.2 runs as `pi` (started
manually, **no service unit yet** — a documented open baseline exception),
answering from `atlas-kb`, `atlas-repo`, and `atlas-live`. Three event
sources already exist that Phase 5 consumes without changing them: the
Phase 3 hourly repo-update timer (`repotrack/`), Phase 4 live-data health /
schema-drift signals (`livedata/`), and Phase 2 knowledge ingestion
(`knowledge/`). The device is LAN-only (Q6), nftables default-deny inbound
(SSH only); sudo needs a password and automation must never enter it.
Secrets live only in the Pi's 0600 `~/.hermes/.env`; nothing sensitive
enters the repo, logs, or chat.

Telegram has two distinct halves with different owners:

- **Inbound conversation** is a *native Hermes feature*. Atlas configures
  it (token, allowlist, command allowlist) and the operator restarts the
  gateway. Atlas writes no gateway code.
- **Outbound operational notifications** are *not* a conversation reply, so
  the Hermes gateway's reply path does not cover them. Atlas owns a small
  notifier that pushes to the Telegram Bot API when an event source fires.

## Goals / Non-Goals

**Goals:**
- A validated, allowlisted inbound Hermes conversation channel with an
  explicit command allowlist (ATLAS-TG-001/002/006).
- A fail-closed outbound notifier for repository-update, schema-drift, and
  knowledge-ingestion events, each source- and time-labelled, scrubbed of
  secrets (ATLAS-TG-003/004).
- A 0600 delivery ledger with the six ATLAS-TG-005 fields and identity-based
  de-duplication to prevent floods.
- Strict isolation: Telegram failure never disturbs core operation; token
  never leaves the 0600 `.env`. (Telegram is outbound-only — no inbound port
  and no firewall change, so there is nothing to configure there.)

**Non-Goals:**
- Investment/portfolio alerts (PRD Phase 7).
- A Hermes systemd service unit (separate hardening step) — and therefore
  full service-failure alerting; the notifier only leaves room for it.
- Destructive system administration or any wallet path over Telegram
  (Atlas holds no wallet secrets).
- Any change to the nftables posture or remote-access model.

## Decisions

### D1 — Inbound is operator-configured native Hermes; Atlas writes none of it
The operator sets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, and
`user_allowed_commands` in the Pi's `~/.hermes/` config and starts
`hermes gateway`. Atlas provides a short setup note and verifies the exit
criteria at acceptance — nothing more. *Why not a custom bot?* ATLAS-TG-001
mandates the supported mechanism; the native gateway already gives
numeric-ID gating, command allowlisting, and STT/MEDIA handling. Building
our own would duplicate it and widen the trust surface for no benefit.

### D2 — Separate Atlas-owned outbound notifier (`telegram/`)
A stdlib sender posts to the Bot API `sendMessage` using the same bot
token (read from `~/.hermes/.env` at call time; never logged). It mirrors
`livedata/`/`repotrack/` conventions: read-only toward the device except
its own 0600 `var/telegram/` store; explicit unknowns; no assumptions.
*Why separate from the gateway?* Proactive alerts are not conversation
replies; the gateway's MEDIA-tag reply path cannot originate them.

### D3 — Event adapters pull from existing sources; no source changes
One thin adapter per class translates an existing signal into a
notification event with a **stable event identifier**:
- repository-update → new-commit transition observed by the Phase 3 timer;
- schema-drift → a Phase 4 livedata health "drift" event;
- knowledge-ingestion → a Phase 2 ingestion completion / review-needed
  marker.
Adapters read state/health outputs already produced; they do not modify the
accepted specs of those capabilities. Adding service-failure later is a new
adapter only (satisfies the spec's extensibility scenario).

### D4 — Scrub-before-send, fail-closed (ATLAS-TG-004)
Every message passes a scrubber that **refuses** (never truncates-and-sends)
on secret/over-exposure patterns: API-key shapes, secret path + value,
environment dumps, wallet-secret shapes, diagnostics beyond the approved
exposure policy. A refused message is recorded as a scrub failure and never
transmitted. Reuse the redaction patterns already used by the `var/`
writers where possible for one consistent policy.

### D5 — Delivery ledger + de-dup as the single source of delivery truth
A 0600 append-only ledger in `var/telegram/` stores per event: `event_id`,
`created_at`, `attempted_at`, `status`, `retry_count`, `final_failure`.
Before sending, the notifier consults a de-dup index keyed on `event_id`
with a coalescing window (default short, configurable); repeats inside the
window are suppressed/coalesced and the suppression is recorded. This makes
"delivers once" and "no flood" both testable against the ledger.

### D6 — Bounded, observable retries; failure is isolated
Sends use a small bounded retry with backoff. Any outage/invalid-token/API
rejection ends in a recorded `final_failure` after the cap and is swallowed
by the notifier boundary so nothing propagates into Hermes, the repo timer,
or live-data tools. The notifier runs out-of-band of those paths.

### D7 — Operator owns secret-bearing and restart steps
Per the device model, Atlas prepares config and code; the operator installs
the token, sets allowed IDs, and restarts the gateway (no secret on a
command line, no passwordless sudo). `env.example` documents the keys with
placeholders only. Acceptance is an operator-attested run, consistent with
prior phases.

## Risks / Trade-offs

- **Bot token compromise grants bot control** → token only in 0600 `.env`,
  never in repo/logs/chat; access still gated by numeric-ID allowlist so a
  leaked token alone does not expose operator data to arbitrary users.
- **Scrubber false-negative leaks a secret** → fail-closed refusal + reuse
  of the existing `var/` redaction policy + a negative-test battery; a
  refused clean message (false-positive) is the safe failure direction.
- **Alert flooding from a flapping source** → identity de-dup + coalescing
  window, verified against the ledger.
- **Service-failure gap** → explicitly deferred and documented; the timer
  itself surfaces repo staleness, and the notifier is built to add the
  class once a Hermes service unit exists.
- **Telegram/API change breaks sends** → bounded retries end in a recorded
  final failure; isolation guarantee keeps core Atlas unaffected; contract
  is a single well-documented `sendMessage` call, low surface.

## Migration Plan

1. Land `telegram/` (notifier, scrubber, ledger, adapters, tests, docs) and
   `env.example` key documentation; no device change yet.
2. Operator adds `TELEGRAM_BOT_TOKEN` + allowed user ID(s) to the Pi's 0600
   `~/.hermes/.env`, sets `user_allowed_commands`, restarts `hermes gateway`.
3. Validate gateway config against current official Hermes docs; record it.
4. Acceptance battery on the Pi: unauthorized rejected; approved account
   queries Hermes; one test alert of each enabled class delivers exactly
   once (ledger-verified); a seeded secret-bearing message is refused; a
   forced send failure is isolated and recorded; firewall posture unchanged.
5. Record acceptance in `docs/decisions.md`; update README status table.

**Rollback:** stop the gateway and unset the Telegram keys in `~/.hermes/`
— Atlas returns to Phase 4 behavior; the `telegram/` code is inert without
a token. No device or firewall state was mutated.

## Open Questions

- None blocking. Chat/user IDs and the bot token are operator-supplied at
  apply time (device config, not repo). Quiet-hours/severity are minimal by
  decision for a single user and can be tuned post-acceptance without a spec
  change.
