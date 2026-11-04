# backup

Nightly encrypted backup of the Pi's Atlas stores, Hermes state and
device secrets to Google Drive (change `pi-offsite-backup`, audit F1).

## What a run does

1. Copies every SQLite database under the include roots with the SQLite
   online backup API into `var/backup/staging/`, switches each copy to
   rollback-journal mode (one file per copy) and runs `PRAGMA
   quick_check` on it. A missing required store or a failed check stops
   the run before anything is uploaded.
2. `restic backup` of the include roots. The live database files are
   excluded, so the snapshot holds only the checked copies, under
   `atlas/var/backup/staging/<home-relative path>`.
3. `restic forget --keep-daily 3 --prune`, then `restic check`.
4. Writes `var/backup/last.json` (snapshot ID, finish time, sizes). Only a
   successful run writes it.
5. Clears the staging dir, also after a failure.

A failed run exits 1 and pages through `atlas-notify-failure@`. restic
exit 3 (a file vanished or was unreadable mid-run, such as a rotated
log) keeps the snapshot and sets `incomplete: true` in `last.json`.

## What is backed up

Include roots, relative to `~`: `atlas/var`, `atlas/.env`, `.hermes`,
`.ssh`, `.claude`, `.config`.

Excluded, because it is rebuilt from GitHub or by the tools:

| Path or pattern | Why |
|---|---|
| `atlas/var/fleet/clones` | Subnet clones, re-cloned by the fleet pass |
| `atlas/var/repotrack/subtensor` | Subtensor clone |
| `atlas/var/upgrade/source-*` | Upgrade source trees |
| `atlas/var/backup/restore-check` | Restore scratch |
| `.hermes/hermes-agent` | Hermes code, a clean git checkout |
| `.hermes/tools`, `.hermes/installs`, `.hermes/node`, `.hermes/lsp`, `.hermes/bin` | Runtimes and tool installs |
| `.hermes/cache` | Cache |
| `*.db.bak-*` | Old manual store copies |
| `*-wal`, `*-shm`, `*-journal` | Live database side files (the copies are complete) |

`~/.cache`, `~/tmp` and the repo checkout are outside the include roots.

## Secrets

- `~/.config/atlas-backup/restic-password`, mode 600, generated on the
  Pi. Keep a second copy in a password manager. The copy inside the
  backup (through `~/.config`) cannot open the backup.
- `~/.config/rclone/rclone.conf`, remote `gdrive`, scope `drive.file`
  (only files rclone created), `use_trash = false` (pruned data must not
  sit in Drive trash and use quota).
- The unit sets `RESTIC_REPOSITORY=rclone:gdrive:atlas-backup` and
  `RESTIC_PASSWORD_FILE`. Nothing prints either value.

## Commands

```
python3 backup/atlas_backup.py run            # what the timer runs
python3 backup/atlas_backup.py stage          # copies and checks only
python3 backup/atlas_backup.py restore-check  # restore latest copies, check
```

`restore-check` needs the same two environment variables as the unit:

```
export RESTIC_REPOSITORY=rclone:gdrive:atlas-backup
export RESTIC_PASSWORD_FILE=~/.config/atlas-backup/restic-password
python3 ~/atlas/backup/atlas_backup.py restore-check
```

## Restore a store

```
export RESTIC_REPOSITORY=rclone:gdrive:atlas-backup
export RESTIC_PASSWORD_FILE=~/.config/atlas-backup/restic-password
restic snapshots
restic restore latest --target /tmp/restore \
  --include /home/pi/atlas/var/backup/staging/atlas/var/fleet/fleet.db
```

Stop the timers that write the store, put the copy in place, start them
again. The copy is in rollback-journal mode, which every store can open.
`fleet.db` switches itself back to WAL on first open.

## Install (user-level, as pi)

See the header of `systemd/atlas-backup.service`.

## Tests

```
python3 -m unittest discover -s backup/tests
```
