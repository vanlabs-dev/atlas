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
  the model `todo_list` and, through a tool-search bridge, every Atlas
  MCP tool and `x_search`. The calls also run in the repository, so Hermes loads
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
- Both calls stop using Hermes and run `claude -p` directly, with the
  login the runtime upgrade job uses: `--restricted`, `--tools ""`,
  `--strict-mcp-config` with no MCP config, `--setting-sources ""`,
  `--disable-slash-commands`, `--max-turns 1`, `--no-session-persistence`,
  the prompt on stdin, and `/tmp` as the working directory. Every CLI
  `hermes -z` call runs through the Hermes gateway, which merges every
  enabled MCP server and `x_search` into an explicit `-t` pick, so no
  Hermes flag gives an empty surface (found after the first deploy, see
  design).
- Code reads each call's `stream-json` `init` event and uses the reply
  only when it lists no tools and no MCP servers. Otherwise the rewrite
  falls back with `tools-exposed` (the health watch pages on repeats) and
  the judge records `unjudged`. The rewrite's `hermes-error` reason
  becomes `model-error`.
- No model id enters Atlas: the CLI's default model is used. Config keys
  `hermes_path` and `toolset` become `claude_path`.
- `rewrite.next_allowed_classes` is removed. `PROMPT_VERSION` is 4, so
  cached replies from the old shape are not reused.

Visible effects: upgrade alerts show the template's body lines again,
and `chain-parameter-change` alerts lose the model-written `Next:` line.
Some faithful replies now fall back to the template (see design).

## Capabilities

### Modified Capabilities

- `alert-plain-rewrite`: what the model writes, the check rules, the
  fence, the per-call no-tools proof, the model CLI and its reason codes.
- `econ-alert-intelligence`: the fence, the per-call no-tools proof and
  the model CLI.

## Impact

- `hermes/atlas_oneshot.py` (new), `telegram/atlas_plain_rewrite.py`,
  `telegram/atlas_telegram.py`, `telegram/atlas_health.py`,
  `fleet/atlas_econ_judge.py`, `fleet/atlas_fleet_signals.py`,
  `telegram/config.json`, `fleet/config.json`, `telegram/README.md`,
  tests.
- No unit change. Deploy is a Pi pull. No gateway restart: the MCP
  servers do not import these modules. The Telegram agent, the gateway
  and the model battery stay on Hermes.
- The two calls no longer follow Hermes's model setting.
