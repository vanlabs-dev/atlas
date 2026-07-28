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
python telegram/atlas_telegram.py test --class chain-runtime-upgrade
python telegram/atlas_telegram.py test --class gate-crossing
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

**Upgrading an existing deployment (signal tiering):** re-run `init` once —
it only seeds classes with no watermark yet (here: the new
`chain-runtime-upgrade`), never touches seeded ones. The old SHA-valued
repository watermark migrates itself on the first scan (translated to its
`change_ranges` row id, or reseeded to the current maximum — history is
never replayed).

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

The same unit also polls the live chain head (`atlas_live.py
poll-chain-head`, one non-interactive TaoStats call per hour, well inside
the 2/min self-cap) *before* the scan — that is what detects a live
runtime upgrade promptly instead of waiting for someone to ask Hermes.

## How repository alerts are tiered

Repo alerts are no longer one-per-head pings. Each tracked commit range is
classified from recorded facts (changed paths + the recorded
`spec_version` delta):

- **Significant** — a runtime `spec_version` bump, any touch of
  `pallets/ runtime/ precompiles/ common/`, any top-level directory *not*
  in the churn allowlist, or a range whose file list is incomplete
  (truncated / non-fast-forward). These page immediately with a breakdown
  (commit count, top areas, key subjects, tags, spec delta) in an
  expandable quote.
- **Churn** — ranges touching *only* the allowlist
  (`.github/ docs/ website/ vendor/ sdk/`) with no spec change. Never
  paged, never dropped: held durably and carried as a one-line digest on
  the next significant alert, or flushed as a standalone low-priority
  digest after `digest_backstop_hours` (default 24).

Both directory sets and the backstop cadence live in
`telegram/config.json` under `repository_update` — retune without code.

**Repo vs live chain, always explicit.** Every repo alert is badged as a
source-code event and states both clocks: `repo spec N · live Finney spec
M · Δ · not enacted`. A repo alert never means the network changed. The
moment the *live* chain's runtime `spec_version` actually changes, the
separate high-priority `chain-runtime-upgrade` class fires (crossing the
spec ≥ 425 conviction threshold is called out in that message).

Messages render as Telegram HTML (escaped, size-bounded); if Telegram
rejects the formatting (HTTP 400), the same alert is re-sent once as plain
text and the fallback is recorded — a rendering fault never costs you an
alert.

## What is deliberately not here

- **Service-failure alerts** — deferred until Hermes has a systemd service
  unit; adding the class is a new adapter only.
- **Investment/portfolio alerts** — PRD Phase 7.
