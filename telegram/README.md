# telegram — Phase 5 controlled Telegram channel

Two halves with different owners:

- **Inbound conversation** — the native NousResearch Hermes Telegram
  gateway, configured by the operator (`hermes gateway setup`). Atlas writes
  no gateway code; see [docs/operator-setup.md](docs/operator-setup.md).
- **Outbound operational notifier** — [`atlas_telegram.py`](atlas_telegram.py),
  the only code in this module. It turns events already produced by earlier
  phases into de-duplicated, secret-scrubbed alerts and records every
  delivery.

Governing spec: PRD §12.11 (ATLAS-TG-001…006) and the accepted
`telegram-integration` capability.

## Outbound notifier

Fail-closed, stdlib-only, read-only toward the device except its own 0600
`var/telegram/` store.

**Event classes** (each reads an existing store read-only, past a persisted
per-source watermark, and never mutates or invents):

| Class | Source | Trigger |
|---|---|---|
| `repository-update` | `var/repotrack/repotrack.db` (`last_remote_sha`) | subtensor head advanced (Phase 3 timer) |
| `schema-drift` | `var/livedata/livedata.db` (`integration_health`) | a live provider response stopped validating (Phase 4) |
| `knowledge-ingestion` | `var/knowledge/knowledge.db` (`intake_runs`) | a new ingest run staged units for review (Phase 2) |

**Guarantees**

- **Scrub, don't truncate** (ATLAS-TG-004): every message passes
  `assert_sendable`, which refuses — never masks-and-sends — if it matches
  the pinned inventory redaction oracle or contains the registered bot
  token.
- **Delivery ledger** (ATLAS-TG-005): the `events` table carries
  `event_id`, `created_at`, `attempted_at`, `status`, `retry_count`,
  `final_failure`. De-duplication is by stable `event_id` within
  `coalesce_window_seconds`, so a flapping source cannot flood the operator.
- **Isolation**: a Telegram outage, bad token, or API rejection is caught at
  the per-event boundary, recorded as `failed` after bounded retries, and
  never propagated — Hermes conversation, the repo timer, and live-data
  tools are unaffected.
- **Secrets**: the token is resolved from the operator's env files (the
  wizard-written `~/.hermes/.env` is reused, not duplicated) and registered
  for redaction; it never appears in a message, error, or ledger record.

**Extensibility**: the scan loop and ledger are class-agnostic — adding
`service-failure` later (once Hermes has a service unit) is a new adapter
entry only.

## Commands

```bash
python telegram/atlas_telegram.py scan                       # deliver new events
python telegram/atlas_telegram.py test --class schema-drift  # one test alert
python telegram/atlas_telegram.py status                     # ledger + watermarks
```

Config: [config.json](config.json). Setup: [docs/operator-setup.md](docs/operator-setup.md).
Tests: `python -m pytest telegram/tests -q`.
