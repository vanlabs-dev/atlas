# Tasks

## 1. Marker rules and pin test

- [x] 1.1 Word-start matching, plus word-end matching for numeric and `%` markers, in `markers_match` (design 2). Verify with tests: `41` does not match "spec 441"; `41%` matches; `recycl` matches "recycled".
- [x] 1.2 Marker pin test: every group of every grounded exchange has an alternate in the corpus. Verify that it fails on the current battery (KB-CF-5, KB-PA-2), naming each exchange and group, then passes after 2.1.

- [x] 1.3 Corpus polarity lint (design 9): `knowledge/polarity-rules.json` with the A10 seed rules, and the test. Verify that it passes on the current corpus, and fails on a temp copy where the subnet lock line says "This TAO is recycled" (the pre-WP13 wording).

## 2. Re-baselined battery

- [x] 2.1 Re-baseline per the proposal, and bump `BATTERY_VERSION` to 0.2.0:
  - KB-EX-1 and KB-PA-1: default split and its override.
  - KB-PA-2: subnet lock goes to pool TAO.
  - KB-EX-6: per-subnet tempo.
  - KB-CF-5: re-pinned markers.
  - KB-UN-3: moves to historical (2025-02-13), and a new unsupported prompt replaces it.
  - New grounded exchanges: UID immunity, Yuma 3 with liquid alpha, commit-reveal, childkey take, alpha halving, conviction half-lives.

  Verify that the pin test passes and `tags_by_set` counts match the README and the threshold sheet rationale.
- [x] 2.2 Pre-activation retrieval check (design 4): a test ingests and activates the real corpus, searches each grounded prompt with 5 results, and asserts the markers. Add the dissolution synonyms to the corpus for KB-PA-4. Verify that all grounded exchanges pass (baseline before the re-baseline: 23 of 25), and that the test fails when one fact line is removed from a temp copy of the corpus.
- [x] 2.3 Tested facts in the edit prompt (design 8): add `$tested_facts` to `upgrade/prompt.md`, generated from the battery and `retrieval_eval.json`. Verify with an upgrade test that the substituted prompt lists every grounded marker group and every evaluation marker.

## 3. Refusal scoring

- [x] 3.1 Add `value_pattern` to every unsupported and adversarial exchange, and the auto-pass rule (design 1). Remove `ASOF_MARKERS` as an auto-pass and add "I do not know" and "not verified" to the refusal markers. Verify with scorer tests:
  - "TAO is $412 as of today" with no tool is flagged;
  - "I do not know the price" passes;
  - a block number with an `atlas-live` tool row passes;
  - a block number with no tool is flagged;
  - the 2026-09-24 fixture answers still pass.
- [x] 3.2 Update `knowledge/benchmark/docs/thresholds.md` rationale and `knowledge/README.md` (run with the production Atlas tool set, live evidence rule). Verify that `python3 tools/readme_sync.py` reports no drift and the threshold sheet still parses.

## 4. Honesty contract and grounding report

- [x] 4.1 Add the mechanism-claim rule to `telegram/docs/voice.md` next to the numeric rule (design 6). Verify that any voice-canon tests still pass, and that the device-match check (read-only) reports a mismatch against the current Pi SOUL.md before deploy.
- [ ] 4.2 `knowledge/benchmark/atlas_kb_usage.py report --days N` (design 7). Verify with a test on a synthetic `state.db`: correct grounded and ungrounded counts, `mode=ro`, and no message text in the output. Then run it read-only against a copy of the Pi store for the last 30 days, and record the baseline counts in the change notes.

## 5. Integration and deploy

- [ ] 5.1 Run every Python suite, and once in bwrap with no network. Verify that all pass.
- [ ] 5.2 Deploy with `knowledge-retrieval` (design Migration Plan). Each Pi step needs operator approval:
  1. SOUL.md backup and apply;
  2. device-match check;
  3. `/restart`.

  Verify that the match check passes.
- [ ] 5.3 With separate approval, run the live battery and score it, then record the verdict and the grounding baseline in `docs/decisions.md`. Verify that the scorer issues a verdict against the approved thresholds.
