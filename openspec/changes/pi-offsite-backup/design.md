# Design

## Context

Discovery on 2026-11-04 (read-only, Pi):

- Backup set about 1.8 GB raw: `fleet.db` 1.10 GB, Hermes kept part
  about 470 MB (`state.db` 319 MB), other stores 146 MB, small files and
  secrets about 60 MB.
- Excluded, about 14 GB: clones 4.5 GB, subtensor 510 MB, upgrade source
  154 MB, Hermes runtimes and caches 5.5 GB, `~/.cache` 2.8 GB, old
  `.bak` stores 2.2 GB.
- gzip -1 gives 38 to 41% on samples, so the first snapshot is about
  0.8 GB.
- `fleet.db` grows 10 to 16 MB a day.
- Disk has 81 GB free. Python sqlite is 3.46.1. No `sqlite3` CLI.
- The operator's Drive has 10 GB free.

The project is standard-library Python only. Units are user-level, as
`pi`, installed by copying from the repo.

## Goals / Non-Goals

**Goals:**
- At most one day of data lost after a device loss.
- No plaintext leaves the Pi.
- A run never blocks or corrupts a live store.

**Non-Goals:**
- Long history. The operator chose 3 days.
- Bare-metal rebuild of the Pi (OS, packages). The repo and the clones
  are rebuilt from GitHub.
- A staleness page for a disabled timer. The health watch does not
  cover it today; this can follow as a separate `ops-health-watch`
  change if wanted.

## Decisions

1. **restic over rclone to Drive, not `rclone sync` of a tarball.**
   restic encrypts on the Pi, deduplicates nightly copies and gives
   `forget`/`prune` and `restore`. A plain tarball would upload 0.8 GB a
   night and need its own encryption. Debian ships restic 0.18 and
   rclone 1.60; the restic `rclone:` backend uses the rclone binary.

2. **SQLite online backup API in Python, staged on the NVMe.**
   `sqlite3.Connection.backup` gives a consistent copy while writers
   continue (all large stores use WAL). Staging under
   `~/atlas/var/backup/staging/` costs about 1.6 GB of disk for the
   length of the run and is cleared after upload. Alternative,
   `restic --stdin` per DB, gives one snapshot per DB and complicates
   restore.

3. **Discover databases by header, not by a hard-coded list.**
   Walk the include roots, and treat any regular file starting with
   `SQLite format 3\0` as a database to stage. This picks up new Hermes
   or Atlas stores without a config change. The config keeps a list of
   required stores; a missing required store fails the run.

4. **One restic snapshot per run** over the staging dir plus the
   non-database include paths, with an exclude list for the raw
   databases, `-wal`, `-shm`, `.bak-*` and the rebuildable trees. The
   include and exclude lists live in `backup/config.json`.

5. **Retention `forget --keep-daily 3 --prune` every run.** The
   repository is small, so a nightly prune is cheap. `restic check`
   (metadata only) runs after prune.

6. **Drive remote: `scope=drive.file`, `use_trash=false`.** `drive.file`
   limits the token to files rclone created. Without `use_trash=false`,
   pruned packs sit in Drive trash for 30 days and count against quota,
   which would exceed 10 GB at nightly prunes.

7. **Secrets in files under `~/.config/atlas-backup/`.** The restic
   password is generated on the Pi straight into a mode-600 file and
   never printed. The operator copies it to a password manager. The
   copy inside the backup (through `~/.config`) is not a recovery copy.
   The unit sets `RESTIC_PASSWORD_FILE` and `RESTIC_REPOSITORY`; the
   rclone config stays at its default path.

8. **Schedule 03:40 local, `Persistent=true`, `RandomizedDelaySec=10m`.**
   The fleet pass starts between 00:20 and 00:35 and runs about 9
   minutes; the next starts at 06:20. Local time, like the other timers.
   `Nice=10`, `IOSchedulingClass=idle`. `OnFailure=` uses the existing
   `atlas-notify-failure@%n.service`.

9. **Status file `~/atlas/var/backup/last.json`**, written atomically,
   only on success: snapshot ID, finish time (UTC), staged bytes,
   snapshot added bytes, repository raw size. Errors go to the journal
   with fixed text and no command lines that could carry secrets.

## Risks / Trade-offs

- [Nightly delta is larger than file growth because SQLite rewrites
  pages across the file] → Measure `restic stats --mode raw-data` after
  the second run and before archive. If 3 days does not fit comfortably
  in 10 GB, report and revisit.
- [Drive API rate limits or token expiry] → The run fails and pages.
  The rclone default client does not expire like a testing-mode client.
- [Staging needs 1.6 GB of disk] → The run checks free space first and
  fails before staging if under 5 GB.
- [Restic password lost] → The backup is unreadable. The operator keeps
  a copy in a password manager; the decisions entry says so.
- [A corrupt store passes into all 3 snapshots before anyone notices]
  → Accepted by the operator: a crash is noticed within a day.

## Migration Plan

1. Operator installs `restic` and `rclone` (done or pending).
2. Operator creates the rclone remote with an authorize step guided in
   session; nothing printed.
3. Generate the restic password file on the Pi; `restic init`.
4. Push, Pi `git pull` (operator approval), install units, run once by
   hand, then enable the timer.
5. Restore check, record it, measure size after the second run.
6. Cleanup of old `.bak` stores and the 2026-09-09 copy, with operator
   approval, once a restore check has passed.

Rollback: disable the timer. Nothing else on the Pi depends on it.
