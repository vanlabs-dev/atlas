# Proposal

## Why

The plain-English rewrite and the econ judge send untrusted text to a
Hermes one-shot model. Four gaps (audit C4, C5, B6, B7):

- The rewrite check matches numbers as a set. It ignores signs, units,
  direction words and negation, so a reply can invert the meaning and
  still pass. The model also writes facts, body lines and the `Next:`
  line, so it can change what the alert states as fact.
- The model can add an assurance ("Nothing changes for holders or
  miners") or a wrong gloss. The injection test passed only because its
  reply also carried a new number.
- Both prompts close their data with a fixed tag. Data that contains the
  tag, or a file name in the opening tag, can end the fence early.
- Both calls run with toolset `todo`. In the installed Hermes that gives
  the model `todo_list` plus a tool-search bridge whose catalog lists the
  Atlas MCP tools. The calls also run in the repository, so Hermes loads
  its AGENTS.md into the prompt.

## What Changes

- The model writes the headline and the meaning sentence only. Facts,
  body lines and the `Next:` line always come from the template. The
  original meaning joins the original headline in the fold.
- The check refuses a reply when a number's value, sign or unit is not in
  the input, when a from/to pair is not in the input in that order, when
  it states a direction the input does not state, when it drops the
  input's negation or adds one, when it adds an assurance or advice
  phrase, or when it adds a parenthetical gloss. Body lines (third-party
  text) do not license a direction, a negation or an assurance.
- Each prompt fences its data with a tag that carries a random id per
  call. `<` in the data is escaped. The judge's file names move inside
  the fence.
- Both calls use toolset `bot_room`, which resolves to zero tools in
  Hermes v0.22.5. Before its first call, each process asks the installed
  Hermes, through the launcher's own interpreter, what the toolset
  resolves to. Any tool, an unknown name or a probe failure stops the
  calls: the rewrite falls back with `toolset-unverified` (the health
  watch pages on repeats), and the judge returns `unjudged`.
- Both calls pass `--ignore-rules` and `HERMES_IGNORE_RULES=1` and run
  outside the repository, so no AGENTS.md, SOUL.md or memory text enters
  the prompt.
- `rewrite.next_allowed_classes` is removed. `PROMPT_VERSION` is 4, so
  cached replies from the old shape are not reused.

Visible effects: upgrade alerts show the template's body lines again,
and `chain-parameter-change` alerts lose the model-written `Next:` line.
Some faithful replies now fall back to the template (see design).

## Capabilities

### Modified Capabilities

- `alert-plain-rewrite`: what the model writes, the check rules, the
  fence, and the verified no-tools call.
- `econ-alert-intelligence`: the fence and the verified no-tools call.

## Impact

- `hermes/atlas_oneshot.py` (new), `telegram/atlas_plain_rewrite.py`,
  `telegram/atlas_telegram.py`, `telegram/atlas_health.py`,
  `fleet/atlas_econ_judge.py`, `telegram/config.json`,
  `fleet/config.json`, tests.
- No unit change. Deploy is a Pi pull. No gateway restart: the MCP
  servers do not import these modules.
