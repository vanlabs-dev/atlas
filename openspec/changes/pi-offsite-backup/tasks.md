# Tasks

## 1. Staging and backup set

- [x] 1.1 Add `backup/config.json`: include roots, exclude patterns, required stores, retention (3 daily), minimum free space (5 GB). Verify: config test loads it and rejects a missing key.
- [x] 1.2 Add `backup/atlas_backup.py stage`: walk include roots, detect SQLite by header, skip excluded paths and `-wal`/`-shm`/`.bak-*`, copy each database with `Connection.backup` into `var/backup/staging/` under its home-relative path, run `PRAGMA quick_check` on each copy, fail on a missing required store or a failed check, fail before staging when free space is under the minimum. Verify: unit tests with temp WAL databases written during the copy, a corrupt copy, a missing required store and an excluded `.bak` file.
- [x] 1.3 Add `backup/README.md` (what is backed up, what is not and why, where secrets live, install). Verify: file exists and names every exclude.

## 2. Upload, retention and status

- [x] 2.1 Add `run`: stage, then `restic backup` of staging plus non-database includes with the exclude list, then `restic forget --keep-daily 3 --prune`, then `restic check`, then write `var/backup/last.json` atomically on success, then clear staging (also on failure). Commands built as argument lists, environment from `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE`, no secret in any log line. Verify: tests with a fake `restic` on `PATH` cover the call order, the exact include and exclude arguments, a failed upload leaving `last.json` unchanged, staging cleared after failure, and no secret in captured output.
- [x] 2.2 Add `restore-check`: restore the latest snapshot into a scratch dir under `var/backup/`, `quick_check` every restored database, report counts, remove the scratch dir. Verify: test with the fake `restic` writing a good and a corrupt database.

## 3. Units and README tables

- [x] 3.1 Add `backup/systemd/atlas-backup.{service,timer}`: oneshot, 03:40 local, `RandomizedDelaySec=10m`, `Persistent=true`, `Nice=10`, idle IO, `OnFailure=atlas-notify-failure@%n.service`, the two restic environment variables, install comment in the header. Verify: `systemd-analyze verify` on the workstation passes.
- [x] 3.2 Add `backup` to `COMPONENTS` in `tools/readme_sync.py` and run `python3 tools/readme_sync.py`. Verify: `python3 tools/readme_sync.py --check` and `tools/tests` pass; every Python suite passes.

## 4. Pi setup (operator approval for each step)

- [x] 4.1 Operator installs `restic` and `rclone`. Verify: `restic version`, `rclone version` on the Pi.
- [x] 4.2 Create rclone remote `gdrive` with `scope=drive.file`, `use_trash=false` through a guided authorize step; nothing printed. Verify: `rclone lsd gdrive:` succeeds; `rclone config show gdrive` checked for scope and trash without printing the token.
- [x] 4.3 Generate `~/.config/atlas-backup/restic-password` (mode 600) on the Pi without printing it; operator copies it to a password manager; `restic init` at `rclone:gdrive:atlas-backup`. Verify: `restic cat config` succeeds.
- [ ] 4.4 Push, Pi `git pull` (state the commits pulled), install the units, run `atlas-backup.service` once by hand, enable the timer. Verify: unit exit 0, `last.json` present, `systemctl --user list-timers` shows the next run.

## 5. Proof and record

- [ ] 5.1 Run `restore-check` on the Pi. Verify: every restored database passes `quick_check`.
- [ ] 5.2 After the second nightly run, measure `restic stats --mode raw-data` and the Drive usage. Verify: numbers recorded; 3 days fits in 10 GB with headroom, else report to the operator.
- [ ] 5.3 Add a `docs/decisions.md` entry: backup set, 3-day retention (operator choice), Drive with `drive.file` and trash off, restore check result, measured sizes, password location and that the in-backup copy is not a recovery copy. Verify: entry committed.
- [ ] 5.4 With operator approval, delete the old `.bak` stores and the 2026-09-09 copy on the Pi. Verify: `du` shows about 2.8 GB freed.
