You check claims about the Bittensor chain (subtensor) source code. Each
claim below comes with the exact source lines cited for it, from release
tag `$tag`. Lines whose `where` starts with `spec-<N>` are old code, from
the last release before a change; a deprecated claim may cite them to
show what used to apply. A claim may also carry `code_checked_facts`:
facts code proved from the git history, such as a string being absent
from every release since spec N. Treat them as shown. You see nothing
else, and you have no tools.

For each claim, decide:

- `agree` only when the cited lines alone show the whole statement is
  true: every value, name, condition and direction of effect. A claim of
  kind `deprecated` says something no longer applies and what applies
  now; agree when the cited lines show what applies now and that it rules
  out the old behaviour.
- `disagree` when any part is wrong, overstated, missing from the cited
  lines, or depends on code you cannot see. When unsure, disagree.

Give a one-sentence reason for every verdict. For every `disagree`, give
`kind`:

- `missing_context`: the statement may be right, but the cited lines stop
  short of a link it needs (a binding of a constant or config value, a
  caller, the body of a function it relies on). More lines could settle it.
- `wrong`: the cited lines show the statement is false, overstated or
  missing a condition that changes its meaning. More lines would not save
  it.

Judge substance strictly; `kind` only says why you disagree.

Claims:

```json
$items
```

Reply with one JSON object and nothing after it:

```json
{"verdicts": [{"key": "c0", "verdict": "agree|disagree", "kind": "missing_context|wrong", "reason": "..."}]}
```
