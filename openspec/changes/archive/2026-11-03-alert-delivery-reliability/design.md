# Design

## Context

Facts on the Pi, verified 2026-11-03:

- `send_message` gives up after about 4 s. `urlopen` raises `HTTPError`
  on a 429, and the except branch drops the body, so `retry_after` is
  never read. `notify_scan` advances watermarks whatever the send result
  was.
- `poll-gate` and `scan` are `ExecStartPost` lines on
  `atlas-repotrack-update.service`, and they are skipped when `update`
  fails.
- The journal is volatile: a vendor drop-in sets `Storage=volatile`. The
  system journal holds this boot's user-unit lines, and `pi` can read it
  through the `adm` group.
- atlas-upgrade exited 1 ten times this boot: five scrub refusals of raw
  error text and five live-spec RPC blips. No unit has `OnFailure=`.
- The `hermes-gateway.service` unit has `Restart=always` and
  `StartLimitIntervalSec=0`, so it never reaches `failed`.
  `~/.hermes/gateway_state.json` is rewritten about every minute. It holds
  `pid`, `gateway_state`, `platforms.telegram.{state,needs_attention}` and
  `updated_at`.
- The Hermes `agent.log` records each model call as `API call #N: model=`
  and an auth failure as `Failed to authenticate`. The logs rotate to
  `agent.log.N`.
- The rewrite failure reasons are `hermes-error`, `timeout`, `unparseable`,
  `check-failed`, `budget` and `disabled`.
- The inventory redaction rule
  `(?i)(--?(?:password|...|token|...|auth)) +(\S+)` matches the `-token`
  in "subnet-token". The same module also serves inventory, livedata,
  fleet, knowledge and hermes verify.

## Goals / Non-Goals

**Goals:**
- Atlas cannot go silent without a page: the gateway, the alert scan, the
  LLM and the units are each watched by something that does not depend on
  them.
- No alert is lost to a transient Telegram failure or a scrub false
  positive.
- One ledger records every message Atlas sends.

**Non-Goals:**
- The `atlas-repo` force-kill on a gateway restart. It is cosmetic and is
  moved to WP14 with the `readers.py` wrapper (F3).
- A paid daily LLM smoke test (operator decision, 2026-11-03).
- Restarting Hermes automatically. The operator restarts it with
  `/restart` (decision 2026-11-02).
- Rewriting the briefing (it stays off). G7's second part, the briefing
  partial resend, is out of scope while the briefing is off. It is
  recorded in the tracker.

## Decisions

1. **The health watch is its own module, `telegram/atlas_health.py`, and
   runs as `atlas_telegram.py health`.**
   - Each check is a pure function over injected readers: systemctl
     properties, the state file, the ledger and log lines. Tests need no
     systemd.
   - Outage state lives in a `health_state` table in `telegram.db`:
     `check`, `failing_since`, `consecutive`, `paged_at`.
   - A check pages when `consecutive >= threshold` and `paged_at` is
     null. It sends a recovery note when it passes and `paged_at` is set.
     Then it clears the row.
   - The gateway threshold is 2. The scan heartbeat and the LLM check
     have threshold 1, because they already measure a window.
   - Alternative rejected: putting the check in the scan. The scan cannot
     report that it is not running.
2. **Gateway signals.** The watch reads
   `systemctl --user show hermes-gateway -p ActiveState,MainPID,NRestarts`
   and the state file.
   - `NRestarts` is compared with the value stored on the last run, so a
     crash loop between ticks is caught.
   - A clean `/restart` raises `NRestarts` once and then passes on the
     next tick, so it never reaches threshold 2.
   - A missing or malformed file is a failing check, never an exception.
3. **Scan heartbeat.** At the end of `notify_scan`, the scan writes
   `meta.last_scan_completed`. The health watch compares it with
   `heartbeat_hours` (3).
4. **LLM signal.** The watch reads only the last 256 KB of `agent.log`
   and `errors.log`, looking for the newest `Failed to authenticate` line
   and the newest `API call #` line.
   - The LLM is down when the auth failure is newer than the last success
     and inside the window. It is also down when the last 2 or more
     rewrite rows in the window are all `fallback:hermes-error` or
     `fallback:timeout`.
   - It never runs `claude auth status`.
5. **The scan moves to its own unit.**
   - `telegram/systemd/atlas-alerts.service` is a oneshot with
     `ExecStart=-…atlas_live.py poll-gate` and then
     `ExecStart=…atlas_telegram.py scan`. The leading `-` keeps the scan
     running when the poll fails.
   - `atlas-alerts.timer` runs `OnCalendar=*:15` with
     `RandomizedDelaySec=5m`, after the repotrack timer's 10-minute
     window. Repotrack changes are still picked up the next hour or
     sooner.
   - Both `ExecStartPost` lines leave repotrack in the same commit.
6. **Retry queue.** The `pending_send` table holds `event_id`,
   `event_class`, `created_at`, `first_attempt_at`, `next_attempt_at`,
   `attempts`, `text`, `html`, `buttons` (JSON) and `tier`.
   - `deliver_event` queues on a transient failure: a network error,
     5xx, or 429. 400, 401, 403 and 404 are final.
   - The ledger status of a queued event becomes `queued`, which is not
     terminal.
   - `flush_pending_sends` runs first in each scan and each health run.
     It sends in id order, stops at the first 429, and sets
     `next_attempt_at` from `retry_after` (default 60 s). It drops rows
     older than 24 h as `failed`.
   - A late send prefixes the plain and HTML body with a fixed "Detected
     <time>" line, using a `tg-time` entity in HTML.
   - Digest events are not queued: `pending_churn` and `pending_signal`
     already hold their content durably and are cleared only on delivery.
     Briefing parts are not queued either: the edition watermark already
     re-sends a failed edition.
   - A 429 sets `meta.rate_limited_until`. Every sender that shares the
     store queues without sending until that time, so a 429 seen by one
     process holds the scan and the health run alike.
7. **The 429 body.** `_do_post` catches `HTTPError` and returns
   `(exc.code, body)`. `send_message` then parses
   `parameters.retry_after` and returns it. A 429 is never retried inside
   `send_message`. It is retried later from the queue.
8. **The ledger stores text and `message_id`.** These are additive
   columns, `text` (the plain text, redacted, capped at 4000) and
   `message_id`. `send_message` parses `result.message_id` from a 200
   reply.
9. **One send path for other senders.** A new `tg.send_alert(msg,
   event_id, event_class)` loads the config and credentials, opens the
   store, renders the message, and calls `deliver_event`.
   - It returns True for `delivered`, `queued` or `suppressed`, and for
     `scrub-refused` after the withheld notice has been sent.
   - `atlas_probe.telegram_send` and `Job.send` call it.
   - The upgrade job's single pending slot remains as a fallback for when
     the store cannot be opened. In normal runs the queue owns retry, so
     there is no double send.
   - Event ids default to `<class>:<sha256 of the rendered text>[:16]`,
     so an identical message inside the coalescing window is not resent.
     The probe uses `probe-drift` and `probe-cleared`, and the upgrade job
     uses `upgrade-report`. The health watch passes explicit ids:
     `health:<check>:<since>` and `unit-failure:<unit>:<since>`.
10. **Scrubber.**
    - The rule becomes
      `(?i)(?<![\w-])(--?(?:password|…|auth)) +(\S+)`. A redaction test
      keeps `--token X` and `-p` behaviour and adds the hyphenated-word
      case.
    - On a refusal, `deliver_event` sends `withheld_message(event_class,
      event_id)` once, keyed `withheld:<event_id>`.
    - The withheld text is a fixed template. It holds no event content and
      cannot itself be refused.
11. **Upgrade wording and exit codes.**
    - A `GATE_PHRASES` map covers prepare, edit, goal, scope, test, probe,
      ingest, push, activate and interrupted, with a generic fallback.
    - `fail()` builds details from the phrase plus the attempt line. Raw
      text stays in `state.last_error` and stderr.
    - `_run_locked` returns 0 after a handled `StepFailed` and after
      "live spec unavailable". `main` lets an unexpected exception
      propagate, so the exit is non-zero.
12. **Unit failure notifier.**
    - `telegram/systemd/atlas-notify-failure@.service` runs
      `atlas_telegram.py unit-failed %i`.
    - The command records the failure in a `unit_failures` table: unit,
      streak start, paged.
    - It pages once per streak with fixed text and
      `journalctl -b --user-unit=%i -n 50`, or `-u` for the system
      variant.
    - The streak ends when the health watch sees the unit's `Result` as
      `success` on a later run. The check reads
      `systemctl show -p Result,ExecMainExitTimestamp`.
    - `OnFailure=atlas-notify-failure@%n.service` goes on fleet, probe,
      poll-chain-head, repotrack-update, upgrade, alerts and health.
    - The dashboard gets a system unit, `atlas-notify-failure-sys@.service`,
      run with `User=pi`, which calls the same command with `--system`.
      The operator installs it with sudo.
13. **G7.** The `fail_closed_events` first-failure query adds
    `AND category = 'provider-failure'`.

14. **Dashboard in the health watch.** `Restart=on-failure` with
    `RestartSec=10` keeps the dashboard out of `failed`, so `OnFailure=`
    fires only at the start limit. The watch checks its `ActiveState` and
    `NRestarts` like the gateway, with threshold 2.
15. **Busy store.** The scan commits the adapter inserts before it sends or
    rewrites, so a model call never holds the lock. `send_alert` returns
    False on `sqlite3.Error`. The health tick skips. `unit-failed` retries.

## Risks / Trade-offs

- **Narrowing the shared redaction rule** changes five modules. It is
  mitigated by running every suite. It still redacts `--token X` and
  `-token X` at the start of a word.
- **The Hermes log format can change on an update.** The LLM check
  degrades to the rewrite-ledger signal. A pinned fixture test catches a
  format change in CI only if the fixture is refreshed. This is recorded
  in the tracker as a manual check after Hermes updates.
- **`gateway_state.json` is a Hermes internal.** An unknown shape pages
  "cannot read gateway state" once. This fails loud, not silent.
- **Two writers on `telegram.db`.** Health every 5 min and the hourly
  scan both write. The store already opens with `timeout=10`, and the
  writes are short. WAL is not enabled, to keep backup semantics simple.
- **Health timer cost.** A run every 5 minutes is a few ms of Python and
  two `systemctl show` calls. Its `Nice=10` is acceptable on the Pi.
- **Notifier loop.** The notifier unit has no `OnFailure=`, and the health
  unit's failure is paged by the notifier. If Telegram is down, both
  queue.

## Deploy (operator)

1. `git pull --ff-only` in `~/atlas`.
2. Copy the unit files for alerts, health, notify-failure, and the
   changed repotrack, fleet, probe, poll-chain-head and upgrade units to
   `~/.config/systemd/user/`.
3. Run `systemctl --user daemon-reload`.
4. Run `systemctl --user enable --now atlas-alerts.timer atlas-health.timer`.
5. Sudo: install the dashboard notifier and the journald drop-in.

No gateway restart is needed.
