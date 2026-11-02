# Tasks

## 1. Locked-down one-shot

- [x] 1.1 `hermes/atlas_oneshot.py`: Hermes call shape and startup toolset probe. Shipped in `ac6db9d`, replaced in section 5 (the probe missed the gateway merge).
- [x] 1.2 `next_allowed_classes` removed. The `bot_room` toolset of the first deploy is replaced by `claude_path` (section 5). Verify: `test_shipped_config_names_the_cli`.

## 2. Rewrite (C4, C5, B6, B7)

- [x] 2.1 Model returns headline and meaning only; `PROMPT_VERSION` 4; facts, body and next code-owned; original meaning in the fold. Verify: `CodeOwnedLayoutTests`, `ParseTests`.
- [x] 2.2 Check: sign and unit on numbers, ordered from/to pairs, direction subset, negation both ways, deny-list, gloss rule; trusted text excludes body lines. Verify: `MeaningTests` (audit reproduction), `AssuranceTests` (real 2026-10-26 reply, real gloss).
- [x] 2.3 Nonce fence and escaped `<`. Verify: `PromptTests`.
- [x] 2.4 Injection test fails on the assurance rule, with no new number. Verify: `test_injected_instruction_never_becomes_a_claim` asserts the detail.
- [x] 2.5 Fallback reason for an unproven tool surface; health watch counts it. Now `tools-exposed` (section 5).

## 3. Econ judge (B6, B7)

- [x] 3.1 Nonce fence, escaped `<`, file names inside the fence. Verify: `test_data_cannot_close_the_fence`, `test_file_names_sit_inside_the_fence`.
- [x] 3.2 Tool surface check; `unjudged` on failure. Now per call (section 5). Verify: `TestToolSurface`.

## 4. Close

- [x] 4.1 Read-only replay of past rewrites against the new checks (design.md).
- [x] 4.2 Every Python suite and `npm --prefix web test` pass; `python3 tools/readme_sync.py`.
- [x] 4.3 After deploy: the first rewrite session in `~/.hermes/state.db` records an empty tool list. Failed 2026-11-03 (the gateway merges the Atlas MCP servers and `x_search` into any `-t` pick); superseded by section 5. Rewrite and judge disabled in `7a9f412`.

## 5. Direct `claude -p` call (B7, second route)

- [x] 5.1 `hermes/atlas_oneshot.py`: `claude -p` argv with no tools, no MCP servers, no settings or skills, one turn, no session kept; prompt on stdin; cwd outside the repo; `parse_stream` refuses a missing or non-empty `init` surface. Verify: `hermes/tests/test_oneshot.py`; one test call on the Pi (empty surface, reply passes the check).
- [x] 5.2 Rewrite: `claude_path`, `model-error`, `tools-exposed` (no retry, not cached); health counts `tools-exposed`. Verify: `test_exposed_tool_discards_the_reply`, `test_exposed_tools_page`, `CodeOwnedLayoutTests`.
- [x] 5.3 Judge: same call; `unjudged` on an exposed surface; `sk-ant-` keys redacted; provenance `claude-oneshot`. Verify: `TestToolSurface`, `test_locked_down_invocation_has_no_tools`.
- [ ] 5.4 Deploy (operator): push, Pi pull, re-enable `rewrite.enabled` and `signals.judge.enabled`, then one real rewrite through the deployed code path shows `used` and an empty surface.
