# Tasks

## 1. Transport: 429 body, message_id, ledger text

- [ ] 1.1 `_do_post` returns `(code, body)` on `HTTPError`; `send_message` parses `retry_after` and `message_id`, never retries a 429 inline. Verify: test drives `_do_post` with a stubbed `urlopen` raising a 429 `HTTPError` and asserts `retry_after` reaches the result.
- [ ] 1.2 Ledger gains additive `text` and `message_id` columns, filled on delivery (redacted, capped). Verify: test delivers one event and reads both columns; an old store opens and migrates.

## 2. Durable retry queue

- [ ] 2.1 `pending_send` table; `deliver_event` queues on transient failure (network, 5xx, 429) with status `queued`; 400/401/403/404 final; digests not queued. Verify: tests for each status class.
- [ ] 2.2 `flush_pending_sends`: id order, stop on 429 and set `next_attempt_at`, drop after 24 h as `failed`, "Detected <time>" prefix on late sends; called at the start of `scan`. Verify: tests for flush success, 429 stop, expiry, prefix in plain and HTML.

## 3. Scrubber and withheld notice

- [ ] 3.1 Narrow the CLI-flag rule in `inventory/atlas_inventory.py` with `(?<![\w-])`. Verify: redaction test for "subnet-token mechanism" passes and `--token X` / `-token X` still redact; every Python suite passes.
- [ ] 3.2 On a scrub refusal `deliver_event` sends one fixed withheld notice keyed `withheld:<event_id>`. Verify: test with a planted secret asserts one notice, no content, no retry.

## 4. One send path for probe and upgrade

- [ ] 4.1 `tg.send_alert(msg, event_id, event_class)`; `atlas_probe.telegram_send` and `Job.send` use it with stable event ids. Verify: probe and upgrade tests assert ledger rows and that a queued send counts as handed over.
- [ ] 4.2 Upgrade `fail()` uses `GATE_PHRASES`; raw detail only in state and stderr. Verify: test with an OAuth error detail asserts the report passes `assert_sendable` and holds no raw text.
- [ ] 4.3 `_run_locked` exits 0 after a handled `StepFailed` and after live spec unavailable. Verify: upgrade tests for both exits; README/docs exit-code note updated in `docs/runtime-upgrade.md`.

## 5. Fail-closed start time (G7)

- [ ] 5.1 Count only `category = 'provider-failure'` rows. Verify: test with earlier invariant-divergence rows asserts the key and start time.

## 6. Scan on its own timer

- [ ] 6.1 Add `telegram/systemd/atlas-alerts.{service,timer}` (poll-gate with `-`, then scan); remove both `ExecStartPost` lines from repotrack; scan writes `meta.last_scan_completed`. Verify: unit files reviewed; heartbeat test; `python3 tools/readme_sync.py` then `--check` passes.

## 7. Health watch

- [ ] 7.1 `telegram/atlas_health.py` with `health_state` table, threshold logic, recovery notes, template-only pages. Verify: unit tests for page once, recovery, re-page.
- [ ] 7.2 Gateway check (ActiveState, MainPID, NRestarts delta, state-file fields and age) with a pinned fixture of the current shape. Verify: tests for restart-no-page, down-two-ticks, malformed file.
- [ ] 7.3 Scan heartbeat check and LLM check (Hermes log tail plus rewrite fallbacks). Verify: tests with fixture log lines for expired login, single fallback, recovery.
- [ ] 7.4 `atlas_telegram.py health` command flushes the queue then runs the checks; `atlas-health.{service,timer}` every 5 min. Verify: CLI test with injected readers; readme_sync passes.

## 8. Unit failure notifier

- [ ] 8.1 `atlas_telegram.py unit-failed <unit> [--system]` with `unit_failures` streak table; health run ends a streak when `Result=success`. Verify: tests for three failures one page, fail-succeed-fail two pages.
- [ ] 8.2 `atlas-notify-failure@.service` (user) and `atlas-notify-failure-sys@.service` (system, `User=pi`); `OnFailure=` on every Atlas user unit and a sudo drop-in for the dashboard. Verify: units reviewed; readme_sync passes.

## 9. Docs and close

- [ ] 9.1 Update `telegram/README.md` and `docs/decisions.md` (operator decisions 2026-11-03: dashboard included, no paid smoke test, upgrade exit 0 on handled outcomes). Verify: docs read back; no em dashes.
- [ ] 9.2 Full Python suite loop and `npm --prefix web test` pass; `openspec validate alert-delivery-reliability` passes.
