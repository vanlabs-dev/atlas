# Design

## Context

Fleet clones are blobless and come from repositories Atlas does not
control. The subtensor clone is pinned but still third-party. Files are
read by six code paths. Two of them (the MCP file tools) check the real
path; none of them refuse links.

## Decisions

### One containment helper in repotrack

`repotrack/atlas_repo.py` gains `contained_file(root, rel) -> str | None`.
It rejects an empty path, `.` and `..` parts and `.git` as the first part.
It walks the path one part at a time from `realpath(root)` and returns
None when any part is a symlink (`os.path.islink`). It also returns None
when the final real path is not under `realpath(root) + os.sep`. The
fleet already imports repotrack, so all readers share it.

Checking every part, not only the leaf, matters for incremental indexing.
Changed paths come from git. When a folder becomes a link, an old path
under it would otherwise resolve through the link.

Alternative: `O_NOFOLLOW` on open. Rejected as the only check: it guards
the last part only.

### Links are skipped, not followed even inside the clone

The goal is a simple rule an operator can audit: Atlas never reads a
file through a link. In-clone links only duplicate content that is
indexed under its real path anyway.

### Size the tree with `git ls-tree -r -l`

In a blobless clone this fetches the blobs it sizes. For a new clone the
blobs land compressed in `.git`, and a breach removes the clone before
the worktree is written. For an update it fetches only the changed
blobs, which the advance would fetch anyway. So the check bounds the
worktree, not the download. The disk ceiling bounds the download: it is
checked before the clone, before each fetch and before each checkout or
advance.

Gitlinks print `-` in the size column and count as zero.

Alternative: a git runner that kills git when the clone passes the cap.
Not chosen: more process handling for a bound the disk ceiling already
gives.

### Update breach: quarantine, keep the last good head

A breach after fetch does not advance the tree. The slot moves to
`quarantined` (terminal, as for a new clone) and keeps its clone, index
rows and `local_sha` at the last good head. A later identity change still
re-points it.

### Disk-limited updates keep state

Reconcile calls the disk check before `update`. On failure it records an
audit line and the `disk-limited` count, updates only `last_reconciled`,
and leaves the slot `active`. The subtensor tracker records the run as
`disk-limited` and exits 1, so the unit's `OnFailure=` notifier pages.

### No indexer schema bump

A bump would re-index every slot and purge the six existing link rows
without the operator seeing them first. The operator chose a targeted
purge after deploy instead.

## Risks

- A repository that relies on symlinked docs loses those paths from
  search. Accepted.
- Measuring HEAD-tree bytes instead of object bytes changes what the cap
  means. Measured on the Pi before deploy: largest 248 MB.
