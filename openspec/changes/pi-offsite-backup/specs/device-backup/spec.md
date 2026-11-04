# Spec Delta

## Purpose

Keeps a recent, encrypted, off-device copy of every Atlas store, the
Hermes agent state and the device secrets, so that a lost or corrupted
Pi can be rebuilt with at most one day of data lost.

## ADDED Requirements

### Requirement: Nightly backup on its own user timer

The backup SHALL run once a night as its own user timer, at a time that
does not overlap the fleet reconcile pass. A run missed while the Pi was
off SHALL run at the next boot.

#### Scenario: Pi off at the scheduled time
- **WHEN** the Pi is powered off at the scheduled time and boots later
- **THEN** the missed backup runs once after boot

### Requirement: Consistent copies of live SQLite stores

Every SQLite database in the backup set SHALL be copied with the SQLite
online backup API, never by copying the file. Each copy SHALL pass an
integrity check before upload. The live database files and their `-wal`
and `-shm` files SHALL NOT be uploaded.

#### Scenario: Database written during the run
- **WHEN** a store is written while the backup copies it
- **THEN** the uploaded copy is a consistent snapshot that passes
  `PRAGMA quick_check`

#### Scenario: Copy fails its check
- **WHEN** a staged copy fails `PRAGMA quick_check`
- **THEN** the run uploads nothing, exits non-zero and names the database

### Requirement: Defined backup set

The backup SHALL include the Atlas stores and small state under
`~/atlas/var`, `~/atlas/.env`, the Hermes state under `~/.hermes`, `~/.ssh`,
`~/.claude` and `~/.config`. It SHALL exclude data that can be rebuilt:
subnet clones, the subtensor clone, upgrade source trees, Hermes runtimes,
tool installs and caches, `~/.cache`, and `.bak` copies of stores.

#### Scenario: Clones not uploaded
- **WHEN** a run completes
- **THEN** the snapshot contains no file under `var/fleet/clones/` or
  `var/repotrack/subtensor/`

#### Scenario: Store copies present
- **WHEN** a run completes
- **THEN** the snapshot contains a checked copy of `fleet.db`,
  `livedata.db`, `repotrack.db`, `knowledge.db`, `telegram.db` and the
  Hermes `state.db`

### Requirement: Encrypted off-device repository

Snapshots SHALL be stored in an encrypted restic repository on Google
Drive. Encryption SHALL happen on the Pi. The repository password and
the Drive token SHALL live only in mode-600 files outside the repo and
SHALL never be printed, logged or committed. The Drive token SHALL be
limited to files the backup itself created.

#### Scenario: Status output
- **WHEN** a run writes its log and status file
- **THEN** neither contains the repository password or the Drive token

### Requirement: Three-day retention

After each successful upload the backup SHALL keep the newest snapshot
of each of the last 3 days and remove the rest from the repository.
Removed data SHALL NOT stay in Drive trash.

#### Scenario: Fourth night
- **WHEN** the fourth nightly run succeeds
- **THEN** the repository holds 3 snapshots and the oldest is gone

### Requirement: Failure is reported

A failed run SHALL exit non-zero, which pages through the existing unit
failure notifier. Each successful run SHALL write a status file with the
snapshot ID, the finish time and the uploaded and repository sizes.

#### Scenario: Drive unreachable
- **WHEN** the upload fails because Drive cannot be reached
- **THEN** the unit fails, one failure page is sent, and the status file
  still shows the last successful snapshot

### Requirement: Restore is proven

The backup SHALL provide a restore check that restores the latest
snapshot into a scratch directory and runs `PRAGMA quick_check` on each
restored database. One restore check SHALL be recorded in
`docs/decisions.md` before the change is archived.

#### Scenario: Restore check passes
- **WHEN** the operator runs the restore check
- **THEN** every restored database passes `quick_check` and the scratch
  directory is removed afterwards
