You extend the citations of claims about the Bittensor chain (subtensor)
source code. A checker rejected each claim below because its cited lines
stop short of a link it needs. The reason says what is missing.

The source at release tag `$tag` is your working directory: `$source_dir`.
Old code exported for traps, citable by its ref: $old_refs.
Use only Read, Grep and Glob.

For each claim:

1. Find the lines that supply the missing link: the binding of a constant
   or config value, the caller, or the body of the function the claim
   relies on.
2. Return the claim with `evidence` extended by those lines: at most three
   ranges, each at most $max_lines lines, as
   `{"path": "...", "start": N, "end": M}` (add `"ref": "<ref>"` only to
   cite exported old code).
3. If the link cannot be cited, narrow the statement to what the lines do
   show. Never add a fact, a number or a name the original statement did
   not have.

Every number and backticked name in a statement must appear in its cited
lines.

Claims:

```json
$items
```

Reply with one JSON object and nothing after it:

```json
{"claims": [{"key": "r0", "statement": "...", "evidence": [{"path": "...", "start": 1, "end": 2}]}]}
```
