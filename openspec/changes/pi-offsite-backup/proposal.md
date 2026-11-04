# Proposal

## Why

The Pi holds the only copy of every Atlas store, the Hermes state and the
device keys. The one backup is a two-month-old copy of three databases on
the same NVMe, taken while the databases were live, and no restore has
ever been tested (audit F1, open since 2026-07-11). A disk failure or a
bad write loses months of fleet history, the Telegram ledger and the
Hermes memory with no way back.

## What Changes

- New component `backup/` with a standard-library script,
  `backup/atlas_backup.py`, and a nightly user timer,
  `atlas-backup.timer`.
- Each run takes a consistent copy of every SQLite store with the SQLite
  online backup API, checks each copy, then sends the copies plus the
  non-database files to an encrypted restic repository on Google Drive
  through rclone.
- The run keeps 3 daily snapshots and prunes the rest. The operator wants
  recent recovery, not history.
- Rebuildable data stays out: subnet clones, the subtensor clone, the
  upgrade source tree, Hermes runtimes and caches, old `.bak` copies.
- A failed run pages through the existing `atlas-notify-failure@` unit.
- Each run writes a small status file with the snapshot ID, sizes and
  the time it finished.
- One restore test is run and recorded in `docs/decisions.md`.
- New Pi packages `restic` and `rclone` (Debian), installed by the
  operator.

## Capabilities

### New Capabilities

- `device-backup`: what the Pi backs up, how it makes consistent copies,
  where they go, how long they are kept, how a failure is reported and
  how a restore is proven.

### Modified Capabilities

None. The failure page uses the existing notifier contract in
`ops-health-watch` unchanged.

## Impact

- New: `backup/atlas_backup.py`, `backup/config.json`,
  `backup/systemd/atlas-backup.{service,timer}`, `backup/tests/`,
  `backup/README.md`.
- `tools/readme_sync.py`: add `backup` to `COMPONENTS`; README tables
  regenerated.
- Pi: packages `restic` and `rclone`; an rclone remote limited to the
  `drive.file` scope with trash off; a restic password file under
  `~/.config/atlas-backup/` (mode 600). None of these are in the repo.
- Google Drive: about 1 GB for the repository at 3 daily snapshots (to be
  measured after the second run).
- Secrets leave the device, encrypted by restic before upload. Google
  never sees plaintext.
