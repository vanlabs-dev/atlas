# Design

## The no-tools toolset

Hermes has no named empty toolset. `-t` must name at least one valid
toolset, or one-shot exits 2. Findings on the Pi (Hermes v0.22.5,
2026-11-03):

- `todo` resolves to `todo_list`. With the MCP servers loaded, Hermes
  wraps the surface in `tool_search`, `tool_describe` and `tool_call`. The
  session records in `~/.hermes/state.db` show the judge and rewrite
  sessions advertised 22 to 26 deferred tools (every Atlas MCP tool plus
  `todo_list`). The bridge scopes calls to the session's toolset, so only
  `todo_list` was callable, but the model saw the catalog.
- `bot_room` and `context_engine` resolve to no tools. `context_engine`
  gains tools from an active context engine, so it is not used.
  `bot_room` is a group-chat feature toolset; nothing adds tools to it
  today.

Because `bot_room` is empty by accident, not by contract, the startup
check is the guarantee. `hermes/atlas_oneshot.py` follows the launcher
chain (`~/.local/bin/hermes` to the Python launcher) to the interpreter
and Hermes root that one-shot really uses, then runs
`toolsets.validate_toolset` and `model_tools.get_tool_definitions` there.
It fails closed on any tool, an unknown name, a non-zero exit, a timeout
or unreadable output. The result is cached per process.

The shipped probe does not start MCP servers, and the `todo` leak came
through MCP: the `tool_search` catalog listed every Atlas MCP tool although
tool selection excluded them. The probe cannot see that path. A one-off
run on the Pi with `discover_mcp_tools()` first showed `bot_room` still
yields no tools and no bridge with all four Atlas servers loaded. After
deploy, and after each Hermes update, the session record of the first
real call confirms the surface is empty.

`--ignore-rules` is a session policy field on the `-z` path (Hermes
`gateway_chat._POLICY`); the agent factory maps it to
`skip_context_files` and `skip_memory`. Hermes's own parser accepts the
exact argv. The first real call's session record (`cwd` `/tmp`, lower
`input_tokens` than earlier rewrites) is the end-to-end evidence.

Rejected: a user-defined empty toolset in `~/.hermes/config.yaml`. It is
a Pi config change, and Hermes validates `-t` against built-in, plugin
and MCP names only.

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
