You are updating Atlas after a live Finney runtime upgrade. You only edit
files. The job that runs you checks every gate in code afterwards: scope,
the grounded spec, all test suites, and a live chain-read probe. You cannot
run commands, and you do not commit or push.

## Facts

- Live runtime spec: **$live_spec**. The corpus is grounded at spec
  **$corpus_spec**.
- Tracked subtensor clone (read-only): `$clone_dir`, at spec $clone_spec.
- Spec-bump commits in the clone:

```
$bump_log
```

- The full diff of those commits is in `$diff_file` (read-only).

## Live knobs at one finalized block

Read by the job. Cite this block. `unset` means the key is not written on
chain. A code default is not a live value.

```json
$knobs
```

## Chain-read probe against live metadata

Every storage item Atlas reads, checked against the live runtime metadata.
A failure means a reader uses an item that was renamed, removed, or
changed shape.

```json
$probe
```

## Task

Follow the re-sync rules in `knowledge/corpus/SOURCES.md`:

1. State only mechanics that are live at spec $live_spec. A path that was
   added and then dropped before the spec shipped is not live.
2. Edit `knowledge/corpus/ground-truth.md`, `fact-patterns.md`, and
   `negative-claim-rules.md` so they state current chain facts, not history.
3. Update `knowledge/corpus/SOURCES.md`: the sync and coverage dates, the
   "Grounded at" line to spec **$live_spec**, and the live facts with the
   block above.
4. Update the live-chain entry in `docs/decisions.md`.
5. Review `knowledge/supersession-markers.json`.
6. Fix `livedata/` readers and `livedata/config.json` if the upgrade
   renamed, removed, or reshaped an item they read. Keep `CHAIN_READS` in
   `livedata/atlas_live.py` equal to what the readers read. Remove a read
   that no longer exists; do not point it at a guess.

Do not edit `knowledge/corpus/hashes.json`: the job regenerates it.

You may edit only these paths:

$allowed

Any other change fails the attempt. If the fix needs another path, make no
change outside scope and say so in your final message. Finish with a short
summary of what changed and why.
