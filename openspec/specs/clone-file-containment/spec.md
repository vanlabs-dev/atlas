# clone-file-containment Specification

## Purpose
Defines how Atlas resolves and reads files inside the clones it does not
control, the subnet fleet clones and the subtensor clone, so that a
committed symlink can never make Atlas read, index or serve a file
through a link or outside the clone.

## Requirements

### Requirement: Clone files are read only through a containment check

Every Atlas code path that reads a file from a fleet clone or the
subtensor clone SHALL resolve the clone-relative path through one shared
containment check before it opens the file. The check SHALL refuse the
path when any part of it is a symbolic link, when the resolved real path
is not inside the clone's real path, or when the path is empty, holds a
`.` or `..` part, or starts with `.git`. A refused path SHALL be skipped
and never opened. This SHALL cover the fleet index, the subtensor index,
the rotation-metrics economics scan, the signals manifest seed, and the
`fleet_file` and `repo_file` read tools.

#### Scenario: A file link to a path outside the clone is never read

- **WHEN** a clone commits `notes.md` as a symlink to a file outside the
  clone
- **THEN** no indexer, scan or seed opens it, no index row holds its
  content, and `fleet_file` refuses the path

#### Scenario: A link inside the clone is skipped too

- **WHEN** a clone commits `CLAUDE.md` as a symlink to `AGENTS.md`
- **THEN** `AGENTS.md` is read under its own path and `CLAUDE.md` is
  skipped

#### Scenario: A folder link is not followed

- **WHEN** a clone commits a symlinked folder and a later change lists a
  path under it
- **THEN** the path is refused because one of its parts is a link, and
  any old index row for it is removed

#### Scenario: A dangling link is skipped without error

- **WHEN** a clone commits a symlink whose target does not exist
- **THEN** every reader skips it and the pass completes

### Requirement: The working-tree walk lists no links

The shared working-tree walk SHALL leave out symlinked files and SHALL
NOT descend into symlinked folders.

#### Scenario: Full index of a clone with links

- **WHEN** a clone with file and folder links is fully indexed
- **THEN** the walk returns only regular paths reached without a link
