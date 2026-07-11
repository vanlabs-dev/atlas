# Manual Hermes install — what the operator must capture

The Hermes install and interactive setup are performed **manually by the
operator** (decision 2026-07-11). This note lists what must happen *during*
that session, because it cannot be retrofitted cleanly afterwards. The
verifier ([../README.md](../README.md)) checks the result; it never installs
or fixes anything.

## During the install

1. **Disable all telemetry** when the setup offers it — usage analytics *and*
   crash reporting (decision Q11). If setup never asks, find the setting in
   the config afterwards and set it explicitly to off; the verifier fails
   closed on "no telemetry setting found".
2. **Prefer a dedicated unprivileged account** (ATLAS-HERMES-002). If the
   official method installs for the login user (`pi`), that is acceptable
   only with a documented reason — record it as an `exceptions` entry for
   `unprivileged-execution` in the install record (note: `pi` is in the
   `sudo` group, which the verifier flags).
3. **No secrets on command lines.** Let the OAuth flow handle authentication;
   never paste tokens into shell commands (they land in shell history).
   Credentials belong in the `.env` the installer manages — check
   `chmod 600` on it.
4. **Capture the install record as you go** — see below. Memory fades;
   `history` does not capture versions.

## The install record (ATLAS-HERMES-001)

Copy [install-record.template.json](install-record.template.json) to
`var/hermes/install-record.json` **on the Pi** (`mkdir -p var/hermes` first;
the file is device-sensitive and gitignored — never commit it) and replace
every TODO. Required fields:

| field | what to record |
|---|---|
| `install_source` | where the software came from (repo URL, installer, branch) |
| `installed_version` | version string, or the commit hash of the checked-out code |
| `install_date` | ISO date of the install (`2026-07-11`) |
| `update_method` | the exact procedure a future update will use |
| `rollback_method` | how to get back to this (or the previous) version |
| `service_user` | the account Hermes runs as |
| `data_dir` | Hermes data directory (e.g. `/home/pi/.hermes`) |
| `config_path` | main configuration file (e.g. `/home/pi/.hermes/config.yaml`) |

Optional fields:

- `diagnostics_command` — the official Hermes diagnostics/health command, if
  one exists (it must be read-only; the verifier runs it). Leave `null` and
  record an exception if this Hermes version ships none.
- `service_unit` — the systemd unit keeping Hermes running (`hermes.service`,
  or `user:hermes.service` for a `systemd --user` unit — user units are only
  inspectable when the verifier runs as that same user). Leave `null` and
  record an exception if Hermes is not under systemd (then boot persistence
  is an open operator decision).
- `exceptions` — documented deviations, each `{"check": ..., "reason": ...}`.
  An exception does not make a problem pass; it makes the deviation an
  explicit recorded decision instead of a silent one.

## Before running the verifier

1. **Restart Hermes once** after the install (service restart or reboot), so
   restart survival has evidence.
2. **Perform the three interactive checks** in a real Hermes session:
   - basic chat succeeds;
   - write a memory, then find it and the conversation again in a *new*
     session (memory + session search);
   - register the test tool (see [../README.md](../README.md)) and have
     Hermes discover and call `atlas_ping`.
3. Run the verifier with the matching `--attest` flags — see the README.

## After acceptance

Record the verdict, run id, and an install-record summary in
[docs/decisions.md](../../docs/decisions.md), then archive the OpenSpec
change.
