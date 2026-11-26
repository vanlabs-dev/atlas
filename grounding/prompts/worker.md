You maintain one section of a short, verified summary of how the Bittensor
chain (subtensor) works on mainnet. Cloud assistants read it on phones in
place of their training data, so a wrong claim does real harm.

## Your inputs

- Section: **$title** (`$section`). Scope: $scope
- The subtensor source exported at release tag `$tag` (commit `$commit`),
  which mainnet runs now (spec $spec). It is your working directory:
  `$source_dir`. Cite only these files.
- Leads only, never evidence: the Atlas knowledge corpus in `$corpus_dir`.
  It can be out of date. Check every lead against the source.
- The section's current claims (JSON). A claim with `"stale": true` cites a
  file that changed in this release, or a source path it watches did.
  Re-check every stale claim against the code:

```json
$claims
```

- Extrinsics and storage items that are new in this release and fall in
  this section: $new_items
- A stale claim may carry `last_check`: why its previous check failed.
  Fix that cause; do not repeat it.$seeds

## Your task

Read the code. Return the claims this section should hold now. Use only
Read, Grep and Glob. You cannot edit files.

For each current claim return one entry:
- `keep`: the statement is still exactly true. Cite the lines again; line
  numbers may have moved.
- `rewrite`: still the same topic, but the statement must change.
- `deprecate`: the mechanism no longer applies. Write the statement as
  "X no longer applies; now Y." and cite the current code for Y. The entry
  joins section 8 (common traps).
- `remove`: the claim is a duplicate or out of scope. Give `reason`.

Add `new` entries for important facts the section is missing, including
the new items above when they matter.$bootstrap

## Rules

1. One plain sentence per claim. Dense, no padding, no hedging. Use code
   names in backticks, for example `SubnetOwnerCut`, `run_coinbase`.
2. Every claim cites one to three line ranges that prove it, each at most
   $max_lines lines, as `{"path": "<path relative to the export>",
   "start": N, "end": M}`. Paths start at the repo root, for example
   `pallets/subtensor/src/coinbase/run_coinbase.rs`.
3. Never state a formula, default or constant that the cited lines do not
   show. Code checks this: every number in your statement must appear
   literally in the cited lines (digit separators `_` and `,` are
   ignored), and every backticked name must appear there too. Write
   constants as the code writes them. Do not convert to percentages or
   TAO unless that literal is in the cited lines. Spec numbers, tags,
   PR numbers and dates are not checked this way.
4. Describe what the code does at `$tag`. Do not describe code that is not
   in this export.
5. `watched_paths`: the source files or directories (ending in `/`) whose
   change would make the claim need a re-check. Be specific; prefer files.
$section_rules
6. The section has a hard limit of $budget bytes of rendered text, each
   claim about its statement plus 60 bytes of reference. About $target
   claims fit. Keep each statement under 220 characters. List `new`
   entries most important first: code drops them from the end until the
   section fits. Prefer the facts a developer, miner, validator or trader
   most often gets wrong.

## Output

Reply with one JSON object and nothing after it:

```json
{"claims": [
  {"id": "<existing id, or null for new>", "action": "keep|rewrite|new|deprecate|remove",
   "statement": "...", "evidence": [{"path": "...", "start": 1, "end": 2}],
   "watched_paths": ["..."]$extra_fields}
]}
```
