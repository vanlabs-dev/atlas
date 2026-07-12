# Telegram — operator setup

Phase 5 has two halves. **You** do the inbound half (native Hermes gateway,
a few minutes). **Atlas** builds the outbound notifier. Neither opens any
inbound port — Telegram is outbound-only, so the nftables posture is
untouched.

## 1. Inbound conversation (native Hermes — you)

Done via the wizard, no manual `.env` editing:

```bash
hermes gateway setup     # create/point the bot, allowlist your user id
hermes gateway           # start it (restart after any config change)
```

- Create the bot with **@BotFather**, copy the token when prompted.
- Get your numeric id from **@userinfobot** and allowlist it
  (`TELEGRAM_ALLOWED_USERS`). Unknown ids get nothing (ATLAS-TG-002).
- Keep non-admin commands limited via `user_allowed_commands`; no
  destructive/admin/wallet command is exposed (ATLAS-TG-006).

The wizard writes `TELEGRAM_BOT_TOKEN` into `~/.hermes/.env`. Keep the token
secret — anyone holding it controls the bot.

**Verify:** message the bot from your phone; Hermes should reply.

## 2. Outbound notifier (Atlas — one value from you)

The notifier reuses the wizard's token (no duplication) and needs one thing:
where to send alerts. Set your numeric id as the alert target:

```bash
# in the Pi's 0600 ~/.hermes/.env (same file the wizard uses)
TELEGRAM_ALERT_CHAT_ID=<your-numeric-telegram-id>
```

Resolution order is `telegram/config.json` → `credential_env_files`
(`~/.hermes/.env` first, then the repo `.env`). The notifier fails closed
with a clear message if either the token or the chat id is missing.

**Test one alert of each class (delivers once, ledger-recorded):**

```bash
python telegram/atlas_telegram.py test --class repository-update
python telegram/atlas_telegram.py test --class schema-drift
python telegram/atlas_telegram.py test --class knowledge-ingestion
python telegram/atlas_telegram.py status     # ledger + watermark summary
```

**Seed watermarks once, before enabling scheduled scans:**

```bash
python telegram/atlas_telegram.py init      # no sends; marks "start from now"
```

Without this, the first `scan` would treat the entire existing backlog (the
current repo head, every past schema-drift row, every past ingest run) as
new and alert on all of it. `init` advances each class's watermark to the
current maximum silently, so only events that happen *after* deploy fire.

**Run a scan** (delivers only genuinely new events since the last run):

```bash
python telegram/atlas_telegram.py scan
```

**Schedule (decided 2026-07-12): piggyback the hourly repo timer.** The
`atlas-repotrack-update.service` unit runs `scan` as a best-effort
`ExecStartPost` after each successful subtensor update — the leading `-`
means a notifier/Telegram failure never marks the repo unit failed
(isolation). Activate the updated unit (needs sudo):

```bash
sudo cp ~/atlas/repotrack/systemd/atlas-repotrack-update.service /etc/systemd/system/
sudo systemctl daemon-reload
```

The timer itself is unchanged (still hourly). The notifier is idempotent —
de-duplication by event identity means a re-run never re-floods you.

## What is deliberately not here

- **Service-failure alerts** — deferred until Hermes has a systemd service
  unit; adding the class is a new adapter only.
- **Investment/portfolio alerts** — PRD Phase 7.
