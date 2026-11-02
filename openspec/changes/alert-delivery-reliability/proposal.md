# Proposal

## Why

Atlas can go silent without anyone noticing. A failed send is never
retried. A failed repo update skips the alert scan, and in September that
left Atlas dark for about 19 hours. Unit failures, Hermes outages and LLM
outages page nobody. The scrubber also refuses harmless alerts, and a
refused alert disappears with no notice. Audit items C3, C6, C7, C8, C9,
C14, C15 and G7 (WP9, 2026-11-02). Operator decision 2026-11-02: the
first fix is a gateway health check that runs outside Hermes.

## What Changes

- New `atlas_telegram.py health` command on a 5-minute user timer. It
  runs outside Hermes. It checks:
  - the `hermes-gateway` unit, its restart count, and
    `~/.hermes/gateway_state.json`;
  - when the last alert scan completed;
  - LLM outage signals: rewrite fallbacks in the ledger and auth errors in
    the Hermes logs.

  It sends one page per outage and one recovery note. It also flushes
  the retry queue. These pages come from templates and never go through
  the LLM rewrite.
- `poll-gate` and `scan` move off the repotrack `ExecStartPost` onto a
  new `atlas-alerts.service` and `atlas-alerts.timer`. A failed repo
  update no longer silences alerts. **BREAKING** for the Pi: the unit
  files must be installed again.
- Durable retry. An undelivered message goes into a `pending_send` table
  with its rendered text, HTML and buttons. Each health run and each
  scan retries it. A Telegram 429 is honoured from `retry_after`, and
  sending stops for that run. Entries expire after 24 hours. A late send
  shows when the event was detected.
- The probe, the upgrade job and the failure notifier send through the
  ledger and the retry queue. The ledger stores the sent text and the
  Telegram `message_id`.
- Scrubber: the CLI-flag rule no longer matches a hyphenated word such as
  "subnet-token". A refused alert sends a fixed "withheld" notice that
  names only the class and the event id. A refusal is final and is not
  retried.
- Upgrade job:
  - Failure reports use fixed phrases per gate. The raw error stays in
    local state and stderr, never in Telegram text.
  - When the live spec is unavailable (an RPC blip) and the run has
    already reported its outcome, the job exits 0.
  - A non-zero exit means an unexpected error.
- New `atlas-notify-failure@.service` template, wired by `OnFailure=` into
  every Atlas user unit. It sends one page per unit per failure streak,
  with fixed text and an inspect command. A system-side variant covers
  `atlas-dashboard.service`. The operator installs it with sudo.
- Fail-closed outage start time: only `provider-failure` health rows
  count.
- Operator step, not code: a persistent journald drop-in (sudo).

## Capabilities

### New Capabilities
- `ops-health-watch`: an out-of-band health check for the Hermes gateway,
  the alert scan heartbeat, LLM availability and systemd unit failures,
  with one page per outage and a recovery note.

### Modified Capabilities
- `telegram-integration`:
  - Delivery retries durably and honours 429.
  - A scrub refusal sends a withheld notice.
  - The ledger stores the text and `message_id`.
  - All Atlas senders go through the ledger.
  - The alert scan runs on its own timer.
  - The fail-closed start time counts only provider failures.
- `runtime-upgrade`: failure reports use fixed wording, and the exit
  status reflects only unexpected errors.

## Impact

- Code: `telegram/atlas_telegram.py`, a new `telegram/atlas_health.py`,
  `livedata/atlas_probe.py`, `upgrade/atlas_upgrade.py`,
  `inventory/atlas_inventory.py` (the shared redaction rule, used by five
  modules), `telegram/config.json`.
- Units: new `telegram/systemd/atlas-alerts.{service,timer}`,
  `atlas-health.{service,timer}`, `atlas-notify-failure@.service`, and a
  system variant for the dashboard. `OnFailure=` is added to every Atlas
  unit, and `ExecStartPost` is removed from repotrack.
- Store: `telegram.db` gains a `pending_send` table and `message_id` and
  `text` columns. The change is additive.
- `tools/readme_sync.py`: new timers.
- Pi deploy: pull, copy the units, `daemon-reload`, enable the new timers.
  No gateway restart is needed, because no MCP server imports `telegram/`.
- Not in scope: the `atlas-repo` force-kill on a gateway restart. It is
  cosmetic: no orphaned servers, only stale child records in the
  out-of-repo `readers.py` wrapper. It moves to WP14 with the F3
  leftover.
