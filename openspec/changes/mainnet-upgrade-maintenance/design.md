# Design

A deterministic Python controller holds the chain cursor, durable ledger,
publication credential and rollout authority. Models receive evidence and
sanitized tracked text, not shell access, credentials or production databases.
Structured edits and independent reviews are untrusted until validated.

## Discovery and evidence

Read finalized headers across the unscanned range. Detect runtime-update
digests, including same-spec replacements. Confirm parent/current runtime
state at pinned hashes. Persist only contiguous accepted scans. Resolve source
provenance using a matching release artifact; tag/spec correspondence alone
is insufficient. Save the complete changed-file manifest and untruncated diff.
A provenance failure is a blocked upgrade, not permission to guess.

## Isolation and publication

Use a separate checkout. Tests run through bubblewrap with a read-only source
mount, isolated network/PID namespaces, temporary HOME and no host credentials.
The service supplies CPU/memory/process/time bounds. The trusted publisher
checks changed paths, reviews, tree identity, test receipts and remote baseline.
Normal fast-forward pushes only; verify the exact remote ref afterward.

## Activation

System-owned producers must first migrate to equivalent user units through an
operator-performed privilege step. A private lock alone cannot coordinate
producers that do not acquire it. Pause timers, wait for active jobs to finish,
then update the clean live checkout. Back up SQLite with its backup API.
Stage/validate knowledge before activation. Preserve prior code and active run
for rollback. Explicitly gate long-lived process reloads. A remote publish and
a local activation are separate ledger transitions.

The current public renderer is `subnt/atlas_subnt.py`, with producer units
`atlas-subnt.service` and `atlas-subnt.timer`. Maintenance uses these renamed
units, preserving their command and schedule when removing system identity
directives for user installation. It does not recreate retired publisher units
or repeat the operator-completed checkout/state migration. The renderer stays
outside automatic candidate edits; `subnt/tests` remains a mandatory isolated
suite, and an active subnt producer blocks migration/activation.

## Failure behavior

No silent skips, default-success reviews, missing mandatory suites, fabricated
migration flags, forced pushes, agent-chosen commands, or assumed MCP reloads.
Retain evidence and surface the blocker. Do not rewrite dated audit records.
