# Tasks

## 1. Locked-down one-shot

- [x] 1.1 `hermes/atlas_oneshot.py`: call shape (`-t`, `--ignore-rules`, `HERMES_IGNORE_RULES=1`, cwd outside the repo), per-call nonce, launcher-chain parser, toolset probe, `verify_no_tools` cached per process and failing closed. Verify: `hermes/tests/test_oneshot.py`; live probe on the Pi read-only (`bot_room` passes, `todo` refused with 3 tools, `none` unknown).
- [x] 1.2 `telegram/config.json` and `fleet/config.json` use `bot_room`; `next_allowed_classes` removed. Verify: config test in `fleet/tests/test_econ_judge.py`.

## 2. Rewrite (C4, C5, B6, B7)

- [x] 2.1 Model returns headline and meaning only; `PROMPT_VERSION` 4; facts, body and next code-owned; original meaning in the fold. Verify: `CodeOwnedLayoutTests`, `ParseTests`.
- [x] 2.2 Check: sign and unit on numbers, ordered from/to pairs, direction subset, negation both ways, deny-list, gloss rule; trusted text excludes body lines. Verify: `MeaningTests` (audit reproduction), `AssuranceTests` (real 2026-10-26 reply, real gloss).
- [x] 2.3 Nonce fence and escaped `<`. Verify: `PromptTests`.
- [x] 2.4 Injection test fails on the assurance rule, with no new number. Verify: `test_injected_instruction_never_becomes_a_claim` asserts the detail.
- [x] 2.5 `toolset-unverified` fallback; health watch counts it. Verify: `test_unverified_toolset_makes_no_call`, `test_unverified_toolset_pages`.

## 3. Econ judge (B6, B7)

- [x] 3.1 Nonce fence, escaped `<`, file names inside the fence. Verify: `test_data_cannot_close_the_fence`, `test_file_names_sit_inside_the_fence`.
- [x] 3.2 Toolset check before the first call; `unjudged` on failure. Verify: `TestToolsetCheck`.

## 4. Close

- [x] 4.1 Read-only replay of past rewrites against the new checks (design.md).
- [x] 4.2 Every Python suite and `npm --prefix web test` pass; `python3 tools/readme_sync.py`.
- [ ] 4.3 After deploy (operator): Pi pull; the first rewrite and judge sessions in `~/.hermes/state.db` record an empty tool list.
