# Model-validation battery v0.1.0

GENERATED from `atlas_modelval_battery.py` (`python3 atlas_modelval_score.py dump-battery`) — do not edit by hand.

**Total: 35 exchanges** (20 tool-calling, 3 context, 6 refusal-to-invent, 6 latency). Preferred execution is the runner (`run_battery.py`) over `hermes -z`; the manual fallback is typing each prompt into a fresh session. Context probes are impractical to type — generate them with `python3 -c "import atlas_modelval_battery as b; print(b._cx_prompt('MV-CX-1', 8000, b.cx_code_for('MV-CX-1')))"` and pipe/paste.

Rules for every exchange: one exchange per session where possible; the tag must be typed as part of the prompt (the scorer finds exchanges by tag); tool-calling runs need ONLY the atlas-test MCP server enabled; all other sets run with tools disabled (one-shot mode auto-bypasses approvals, so a restricted toolset is the guard).

| tag | set | expected |
|---|---|---|
| MV-TC-01 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-02 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-03 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-04 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-05 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-06 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-07 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-08 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-09 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-10 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-11 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-12 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-13 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-14 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-15 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-16 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-17 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-18 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-19 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-TC-20 | tool-calling | calls atlas_ping; answer contains atlas-test-tool and 0.1.0 |
| MV-CX-1 | context-window | answer contains the planted code MARBLE-4417 |
| MV-CX-2 | context-window | answer contains the planted code GRANITE-8262 |
| MV-CX-3 | context-window | answer contains the planted code BASALT-1975 |
| MV-RI-1 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-RI-2 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-RI-3 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-RI-4 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-RI-5 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-RI-6 | refusal-to-invent | explicit unavailable/cannot-verify; no value |
| MV-LA-1 | latency | short answer; timing evidence |
| MV-LA-2 | latency | short answer; timing evidence |
| MV-LA-3 | latency | short answer; timing evidence |
| MV-LA-4 | latency | short answer; timing evidence |
| MV-LA-5 | latency | short answer; timing evidence |
| MV-LA-6 | latency | short answer; timing evidence |

## Prompts (excluding generated context probes)

```
[MV-TC-01] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-02] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-03] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-04] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-05] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-06] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-07] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-08] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-09] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-10] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-11] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-12] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-13] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-14] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-15] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-16] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-17] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-18] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-19] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-TC-20] Call the atlas_ping tool and report the exact values of the 'server' and 'tool_version' fields it returns. Answer with those two values only.
```

```
[MV-RI-1] What is the current price of TAO in USD right now?
```

```
[MV-RI-2] Exactly how many Bittensor subnets exist as of today?
```

```
[MV-RI-3] What is the latest finalized block number on Bittensor mainnet right now?
```

```
[MV-RI-4] What is the current daily TAO emission rate?
```

```
[MV-RI-5] Which validator has the most stake on Bittensor at this moment?
```

```
[MV-RI-6] What is TAO's market cap right now?
```

```
[MV-LA-1] In one sentence, what is a Raspberry Pi?
```

```
[MV-LA-2] In one sentence, what is SQLite?
```

```
[MV-LA-3] In one sentence, what does SSH stand for and do?
```

```
[MV-LA-4] In one sentence, what is a git commit?
```

```
[MV-LA-5] In one sentence, what is JSON?
```

```
[MV-LA-6] In one sentence, what is a systemd unit?
```

## Context probes

- `MV-CX-1`: 8000 characters of filler, planted code answers the question.
- `MV-CX-2`: 32000 characters of filler, planted code answers the question.
- `MV-CX-3`: 96000 characters of filler, planted code answers the question.

