# Tasks: atlas-phase-5-telegram

Ordered by dependency. Off-device code first (read-only toward the device),
then operator-run on-device configuration and the acceptance battery.
Mirrors `livedata/`/`repotrack/` conventions: stdlib, fail-closed, secrets
never in repo/logs/chat, outputs 0600 into gitignored `var/`.

## 1. Scaffold and conventions

- [x] 1.1 Create `telegram/` layout — single `atlas_telegram.py` (scrubber, ledger, adapters, transport, CLI folded in, to keep it simple), `config.json`, `tests/`, `docs/`, `README.md`, mirroring `livedata/` conventions
- [x] 1.2 `var/telegram/` covered by the existing `var/` gitignore rule; confirmed `var/telegram/telegram.db` is ignored
- [x] 1.3 Document Telegram keys in `env.example` with placeholders only — `TELEGRAM_ALERT_CHAT_ID` (the one operator value) + `TELEGRAM_BOT_TOKEN` (normally wizard-written to `~/.hermes/.env`, not duplicated)

## 2. Outbound notifier core (Atlas-owned)

- [x] 2.1 Implement the Bot API `sendMessage` client (stdlib HTTPS); token resolved from the operator env files at call time and registered for redaction, never logged or echoed
- [x] 2.2 Implement bounded, observable retry (backoff, hard cap, never on 4xx); every path ends in a recorded terminal status (D6)
- [x] 2.3 Implement the notifier boundary (`deliver_event` / `notify_scan`) so any failure is caught and cannot propagate to Hermes, the repo timer, or live-data tools (isolation guarantee)

## 3. Sensitive-output scrubber (ATLAS-TG-004)

- [x] 3.1 Implement the fail-closed scrubber (`assert_sendable`): refuse (not truncate) on any pinned inventory redaction pattern (auth headers, bearer/JWT, named secrets, api-key shapes, url creds, PEM, mnemonic/seed) or a registered secret — one policy, reused from `inventory`
- [x] 3.2 Wire the scrubber as a mandatory pre-send gate in `deliver_event` with no bypass route; a refusal records a `scrub-refused` event and sends nothing
- [x] 3.3 Negative-test battery: seeded secret-bearing messages are all refused; a clean source/time-labelled message passes

## 4. Delivery ledger and de-duplication (ATLAS-TG-005)

- [x] 4.1 Implement the 0600 `var/telegram/` ledger `events` table with the six fields (`event_id`, `created_at`, `attempted_at`, `status`, `retry_count`, `final_failure`)
- [x] 4.2 Implement identity-based de-dup keyed on `event_id` with a configurable coalescing window; suppressed repeats are recorded (`suppressed`)
- [x] 4.3 Tests: full delivery lifecycle recorded; duplicate within the window is suppressed; not suppressed outside the window (all asserted against the ledger)

## 5. Event-source adapters (no source changes)

- [x] 5.1 Repository-update adapter: emit `repository-update:<sha>` on a new `last_remote_sha` from `var/repotrack/repotrack.db`
- [x] 5.2 Schema-drift adapter: emit `schema-drift:<id>` on new `integration_health` rows with category `schema-drift` in `var/livedata/livedata.db`
- [x] 5.3 Knowledge-ingestion adapter: emit `knowledge-ingestion:<run_id>` on new `intake_runs` (staged units = review-needed) in `var/knowledge/knowledge.db`
- [x] 5.4 Adapters open sources read-only (`mode=ro`), change no accepted spec, and treat a missing source as empty; the class-agnostic scan loop leaves a documented seam so service-failure is a future adapter only

## 6. Inbound gateway — operator setup note (no Atlas gateway code)

- [x] 6.1 Wrote `telegram/docs/operator-setup.md` (BotFather → numeric id → `~/.hermes/` → `hermes gateway`); keys confirmed against current official NousResearch Hermes Telegram docs (ATLAS-TG-001)
- [x] 6.2 Operator performs the setup on the Pi (bot created via `hermes gateway setup` wizard, gateway enabled — token + allowlist written by the wizard, no manual `.env` edit)

## 7. Acceptance battery on the Pi (operator-attested)

- [ ] 7.1 Unauthorized account (non-allowlisted ID) receives no operational data
- [ ] 7.2 Approved account queries Hermes and gets a reply through the gateway
- [x] 7.3 One test alert of each enabled class (repository-update, schema-drift, knowledge-ingestion) delivers exactly once — verified against the ledger (Pi run 2026-07-12: all three `delivered`, ledger count 1 each)
- [ ] 7.4 A seeded secret-bearing outbound message is refused and recorded as a scrub failure
- [ ] 7.5 A forced send failure is isolated (core operation continues) and ends in a recorded `final_failure` after bounded retries
- [ ] 7.6 Confirm no secret appears in logs, chat, ledger, or repo

## 8. Documentation and close-out

- [x] 8.1 `telegram/README.md`: architecture, the two halves, event classes, isolation guarantee, and the deferred service-failure/investment scope
- [ ] 8.2 Record acceptance and the Q32–Q35 resolutions in `docs/decisions.md`
- [ ] 8.3 Update README status table with a `telegram-integration` row
- [ ] 8.4 Run `openspec validate atlas-phase-5-telegram` and archive via `/opsx:archive` after operator acceptance
