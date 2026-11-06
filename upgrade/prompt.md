You are updating Atlas after a live Finney runtime upgrade. You only edit
files. The job that runs you checks every gate in code afterwards: scope,
the grounded spec, all test suites, and a live chain-read probe. You cannot
run commands, and you do not commit or push.

## Facts

- Live runtime spec: **$live_spec**. The corpus is grounded at spec
  **$corpus_spec**.
- Subtensor source as shipped at spec $live_spec (read-only):
  `$source_dir`, exported at $anchor_kind `$anchor`. This is the live
  release. Code past it has not shipped; you are not given it.
- Commits from the spec $corpus_spec release to the spec $live_spec
  release:

```
$bump_log
```

- The full diff between the two releases is in `$diff_file` (read-only).

## Live knobs at one finalized block

Read by the job. Cite this block. `unset` means the key is not written on
chain. A code default is not a live value.

```json
$knobs
```

## Chain-read probe against live metadata

Every storage item Atlas reads, checked against the live runtime metadata
(names, shapes and defaults). It passed: the job does not start you when
it fails. Cite its block.

```json
$probe
```

## Task

Follow the re-sync rules in `knowledge/corpus/SOURCES.md`:

1. State only mechanics that are live at spec $live_spec, as shown by the
   source and diff above. A path that was added and then dropped before
   the spec shipped is not live. Never name a spec number above
   $live_spec.
2. Edit `knowledge/corpus/ground-truth.md`, `fact-patterns.md`, and
   `negative-claim-rules.md` so they state current chain facts, not history.
3. Update `knowledge/corpus/SOURCES.md`: the sync and coverage dates, the
   "Grounded at" line to spec **$live_spec**, and the live facts with the
   block above.
4. Update the live-chain entry in `docs/decisions.md`.
5. Review `knowledge/supersession-markers.json`.
6. Cite only the two finalized blocks above (knobs and probe) for new
   live facts. Any other new block number fails the attempt.
7. Chain readers (`livedata/`) are out of scope. If the diff changes an
   item Atlas reads in a way the probe cannot see, say so in your final
   message for the operator.

## Facts the test suite checks

The knowledge suite runs before the push and fails if any of these is no
longer true of the corpus. Keep each one retrievable. Change one only when
the spec $live_spec source changes the fact itself; then say which, and
why, in your final message, because the operator must update the test.

```
$tested_facts
```

Keep each paragraph and each list item under 1,500 characters. The
search index cannot split a longer one, and the test suite fails it.
Do not edit `knowledge/corpus/hashes.json`: the job regenerates it.
Do not create, rename or delete files: only edit existing ones.

You may edit only these paths:

$allowed

Any other change fails the attempt. If the fix needs another path, make no
change outside scope and say so in your final message. Finish with a short
summary of what changed and why.
