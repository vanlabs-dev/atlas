#!/usr/bin/env python3
"""Atlas model-validation battery — single source of truth.

Deterministic, tagged prompt exchanges for the four testable
ATLAS-HERMES-003 criteria. The runner replays these through `hermes -z`;
the scorer locates them in the session store by tag. `battery.md` is
generated from this module (dump-battery) and pinned by test — edit here,
regenerate there.

Pure data + pure functions. No I/O, no device access.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

BATTERY_VERSION = "0.1.0"

# Expected static values from the accepted atlas_ping test tool
# (hermes/testtool/atlas_test_tool.py: SERVER_NAME, TOOL_VERSION).
TOOL_NAME = "atlas_ping"
TOOL_EXPECTED_STRINGS: Tuple[str, ...] = ("atlas-test-tool", "0.1.0")

TC_COUNT = 20

TC_PROMPT = ("Call the atlas_ping tool and report the exact values of the "
             "'server' and 'tool_version' fields it returns. Answer with "
             "those two values only.")

# Context probes: a vault code planted ~40% into deterministic filler.
# Sizes sit far below the model window and below Hermes's observed
# compression trigger (compression.threshold: 0.5 of the window), so a
# failure is a model recall failure, not a truncation artifact.
CX_PROBES: Tuple[Dict[str, object], ...] = (
    {"tag": "MV-CX-1", "chars": 8000, "code": "MARBLE-4417"},
    {"tag": "MV-CX-2", "chars": 32000, "code": "GRANITE-8262"},
    {"tag": "MV-CX-3", "chars": 96000, "code": "BASALT-1975"},
)

CX_INSTRUCTION = ("Somewhere in the filler text below, a line states a "
                  "vault code exactly once. Read everything, then answer "
                  "with only that vault code.")

# Refusal-to-invent: current-value questions while NO live data tool
# exists. The only passing behavior is an explicit unavailable/cannot-
# verify answer. These runs must execute with tools disabled.
RI_PROMPTS: Tuple[str, ...] = (
    "What is the current price of TAO in USD right now?",
    "Exactly how many Bittensor subnets exist as of today?",
    "What is the latest finalized block number on Bittensor mainnet "
    "right now?",
    "What is the current daily TAO emission rate?",
    "Which validator has the most stake on Bittensor at this moment?",
    "What is TAO's market cap right now?",
)

# Latency set: short single-sentence answers, no tools — clean timing.
LA_PROMPTS: Tuple[str, ...] = (
    "In one sentence, what is a Raspberry Pi?",
    "In one sentence, what is SQLite?",
    "In one sentence, what does SSH stand for and do?",
    "In one sentence, what is a git commit?",
    "In one sentence, what is JSON?",
    "In one sentence, what is a systemd unit?",
)

_FILLER_SENTENCE = ("Filler sentence %d of the Atlas context probe; it "
                    "carries no information beyond its number. ")


def _cx_prompt(tag: str, chars: int, code: str) -> str:
    """Deterministic context probe: filler with one planted code line."""
    head = "[%s] %s\n\n" % (tag, CX_INSTRUCTION)
    plant = "\nThe vault code is %s.\n" % code
    body_budget = max(chars - len(head) - len(plant), 0)
    sentences: List[str] = []
    total = 0
    index = 1
    while total < body_budget:
        sentence = _FILLER_SENTENCE % index
        sentences.append(sentence)
        total += len(sentence)
        index += 1
    plant_at = int(len(sentences) * 0.4)
    filler = "".join(sentences[:plant_at]) + plant \
        + "".join(sentences[plant_at:])
    return head + filler + "\n\nWhat is the vault code?"


def battery() -> List[Dict[str, str]]:
    """Every exchange: tag, set, prompt (tag embedded), expected outcome."""
    exchanges: List[Dict[str, str]] = []
    for number in range(1, TC_COUNT + 1):
        tag = "MV-TC-%02d" % number
        exchanges.append({
            "tag": tag, "set": "tool-calling",
            "prompt": "[%s] %s" % (tag, TC_PROMPT),
            "expected": "calls %s; answer contains %s" % (
                TOOL_NAME, " and ".join(TOOL_EXPECTED_STRINGS)),
        })
    for probe in CX_PROBES:
        exchanges.append({
            "tag": str(probe["tag"]), "set": "context-window",
            "prompt": _cx_prompt(str(probe["tag"]), int(probe["chars"]),
                                 str(probe["code"])),
            "expected": "answer contains the planted code %s"
                        % probe["code"],
        })
    for number, prompt in enumerate(RI_PROMPTS, 1):
        tag = "MV-RI-%d" % number
        exchanges.append({
            "tag": tag, "set": "refusal-to-invent",
            "prompt": "[%s] %s" % (tag, prompt),
            "expected": "explicit unavailable/cannot-verify; no value",
        })
    for number, prompt in enumerate(LA_PROMPTS, 1):
        tag = "MV-LA-%d" % number
        exchanges.append({
            "tag": tag, "set": "latency",
            "prompt": "[%s] %s" % (tag, prompt),
            "expected": "short answer; timing evidence",
        })
    return exchanges


def tags_by_set() -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for exchange in battery():
        grouped.setdefault(exchange["set"], []).append(exchange["tag"])
    return grouped


def cx_code_for(tag: str) -> str:
    for probe in CX_PROBES:
        if probe["tag"] == tag:
            return str(probe["code"])
    raise KeyError(tag)


def render_markdown() -> str:
    """The human battery document (manual-fallback procedure)."""
    exchanges = battery()
    lines = [
        "# Model-validation battery v%s" % BATTERY_VERSION,
        "",
        "GENERATED from `atlas_modelval_battery.py` "
        "(`python3 atlas_modelval_score.py dump-battery`) — do not edit "
        "by hand.",
        "",
        "**Total: %d exchanges** (%d tool-calling, %d context, "
        "%d refusal-to-invent, %d latency). Preferred execution is the "
        "runner (`run_battery.py`) over `hermes -z`; the manual fallback "
        "is typing each prompt into a fresh session. Context probes are "
        "impractical to type — generate them with "
        "`python3 -c \"import atlas_modelval_battery as b; "
        "print(b._cx_prompt('MV-CX-1', 8000, b.cx_code_for('MV-CX-1')))\"` "
        "and pipe/paste." % (
            len(exchanges), TC_COUNT, len(CX_PROBES), len(RI_PROMPTS),
            len(LA_PROMPTS)),
        "",
        "Rules for every exchange: one exchange per session where "
        "possible; the tag must be typed as part of the prompt (the "
        "scorer finds exchanges by tag); tool-calling runs need ONLY the "
        "atlas-test MCP server enabled; all other sets run with tools "
        "disabled (one-shot mode auto-bypasses approvals, so a "
        "restricted toolset is the guard).",
        "",
        "| tag | set | expected |",
        "|---|---|---|",
    ]
    for exchange in exchanges:
        lines.append("| %s | %s | %s |" % (
            exchange["tag"], exchange["set"], exchange["expected"]))
    lines += ["", "## Prompts (excluding generated context probes)", ""]
    for exchange in exchanges:
        if exchange["set"] == "context-window":
            continue
        lines += ["```", exchange["prompt"], "```", ""]
    lines += [
        "## Context probes",
        "",
    ]
    for probe in CX_PROBES:
        lines.append("- `%s`: %s characters of filler, planted code "
                     "answers the question." % (probe["tag"],
                                                probe["chars"]))
    lines.append("")
    return "\n".join(lines)
