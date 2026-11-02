# Design

## The call path

Both calls run `claude -p` directly (`hermes/atlas_oneshot.py`):

```
claude -p --restricted --strict-mcp-config --tools "" --setting-sources ""
  --disable-slash-commands --max-turns 1 --no-session-persistence
  --output-format stream-json --verbose --system-prompt <short>
```

The prompt goes on stdin, so untrusted text never sits in argv, and the
working directory is `/tmp`, so no AGENTS.md or CLAUDE.md is found. No
`--mcp-config` is passed, so `--strict-mcp-config` loads no server. No
`--model` is passed: the CLI's default model is used, and no model id
enters Atlas. Auth is the CLI's existing login on the Pi, the one the
runtime upgrade job uses. `--bare` is not used because it never reads
OAuth.

Each call proves its own surface. The `stream-json` `init` event lists
the tools and MCP servers of that call. `parse_stream` accepts the reply
only when the event is present and both lists are empty; otherwise the
reply is discarded without a retry (`tools-exposed`, or `unjudged` for
the judge). This replaces the startup toolset probe of the first deploy.

Test call on the Pi (Claude Code 2.1.280, 2026-11-03), the audit's
"fell below the cutoff" input with the version 4 prompt: `tools: []`,
`mcp_servers: []`, `slash_commands: []`, `cwd: /tmp`, about 1,200 prompt
tokens (5,000 through Hermes), 5.1 s, and a reply that passes the check.
The event also lists built-in plugins (`agents-md`, `telemetry`) and
subagent names; with no tools there is no tool to start a subagent, and
`/tmp` holds no AGENTS.md.

Trade-off: the two calls no longer follow Hermes's model setting. A model
change in Hermes does not reach them.

## Why not Hermes

Hermes has no named empty toolset. `-t` must name at least one valid
toolset, or one-shot exits 2. Findings on the Pi (Hermes v0.22.5,
2026-11-03):

- Every CLI `-z` call runs through the Hermes gateway. The gateway writes
  an explicit `-t` pick into the `cli` platform toolsets and resolves them
  with the default merge, which adds every enabled MCP server and, when
  xAI credentials exist, `x_search`. With `-t bot_room` the session's
  enabled toolsets were `bot_room`, the four Atlas MCP servers and
  `x_search`; Hermes put the 26 tools behind its `tool_search`,
  `tool_describe` and `tool_call` bridge, and the bridge scopes calls to
  that set, so all were callable. `-t todo` (before this change) was the
  same plus `todo_list`.
- `-t bot_room,no_mcp` drops the MCP servers, but no per-call flag drops
  `x_search`. Only the global `agent.disabled_toolsets` does, and the
  Telegram agent lists `x_search`.
- `--safe-mode` disables plugins, and the Claude provider is a plugin.
- The direct `hermes_cli.oneshot.run_oneshot` path builds an empty
  surface, but the CLI no longer uses it, so an update can remove it.
- The first deploy shipped a startup probe that resolved the bare toolset
  name. It passed because the merge happens later, in the gateway. The
  post-deploy test call's session record showed the bridge.

A read-only check of all 510 `oneshot` sessions in `~/.hermes/state.db`
found tool calls only in the 2026-09-24 knowledge battery, which uses the
KB tools on purpose. No rewrite (121) or judge (350) session called a
tool. Both calls were disabled (`7a9f412`) until this route shipped.

`--ignore-rules` and the `/tmp` cwd worked on the Hermes path (test
session: no AGENTS.md text, about 5,000 prompt tokens against 10,000 to
17,000 before); the direct call keeps both properties by construction.

## Check rules

Number tokens carry sign, value and unit (`%`, TAO, rao, days, blocks,
hours, minutes, weeks, epochs, `x`). A reply token must match an input
token on value and unit. A signed reply token must match a sign the input
uses. An unsigned reply token for a value the input only shows signed
needs a direction word of that sign in the same sentence. The 0 to 10
free pass is gone.

Directions come from word lists, signed numbers and from/to pairs (`0%
→ 95%` is up). A reply's directions must be a subset of the trusted
input's. Negation: if the input's headline or meaning is negated, the
reply must be; a negated reply needs a negation or a stop word ("off",
"stopped") in the trusted input. "not only" does not count.

Trusted input is the headline, meaning, facts, details and next action.
Body lines carry commit subjects and signal lines, so they license no
direction, negation or assurance.

## Replay (read-only, 2026-11-03)

31 `used` rewrites exist (2026-10-22 to 2026-11-02). The inputs are not
stored, so they were rebuilt from snapshots of the Pi stores with the
code as of 2026-10-22, and matched to cached replies by cache key.

- 13 matched exactly. The new checks reject 2: a model-added "not from
  the cutoff moving" (the input names the cause without a negation), and
  a false reject where "was never interrupted" became "kept being paid
  out the whole time".
- 6 rebuilt with later source data (approximate). 1 rejected: the
  2026-10-26 "Nothing changes for holders or miners".
- 12 cannot be rebuilt: 8 signal digests (rows deleted after send) and 4
  operator test sends.

Every reject falls back to the template, so a false reject costs wording,
not an alert. These replies came from the version 3 prompt; the version 4
prompt asks the model to keep direction and negation, so the live reject
rate may differ. Signal digests are no longer paged (every digest source
is shadow since alert-tier-trim), so the 8 unrebuilt digests do not recur.
