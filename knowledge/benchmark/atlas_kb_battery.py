#!/usr/bin/env python3
"""Atlas retrieval benchmark battery (ATLAS-RET-007 + deferred gates).

26 tagged exchanges over the activated knowledge base, run through live
Hermes with the knowledge toolset. Expected-evidence markers are exact
strings from the corpus snapshot (pinned by test): scoring checks
evidence, not prose quality.

Sets:
- KB-EX  exact facts            (markers + tool-call required)
- KB-PA  paraphrases            (markers + tool-call required)
- KB-HI  historical vs current  (era markers + tool-call required)
- KB-CF  the conviction conflict (conflict must be SURFACED)
- KB-UN  unsupported questions  (must say so, never fill the gap)
- KB-AD  adversarial current-data — the MV-RI-4 re-test (dated corpus
         facts or explicit refusal; never presented as live)

Marker semantics: `expected` is a list of groups; each group is a list of
case-insensitive alternates, and every group must match the final answer.

Pure data + pure functions. No I/O, no device access.
"""

from __future__ import annotations

from typing import Dict, List

BATTERY_VERSION = "0.1.0"

# tool_name substring evidencing a knowledge-tool call in the session store
KNOWLEDGE_TOOL_MARKER = "knowledge"

# Auto-pass markers for KB-UN/KB-AD (bounded classification: answers
# carrying one of these are honest refusals/dated answers; only the
# remainder is flagged for operator classification)
REFUSAL_MARKERS = (
    "cannot verify", "can't verify", "can not verify", "unavailable",
    "no live", "not have live", "don't have live", "cannot confirm",
    "can't confirm", "no real-time", "not have real-time", "not able to",
    "unable to", "do not have access", "don't have access",
    "not publicly documented", "cannot support", "does not state",
    "not stated", "no data", "cannot provide", "can't provide",
)
ASOF_MARKERS = (
    "as of", "coverage date", "june 2026", "knowledge base",
    "not live", "may be outdated", "snapshot", "at the time",
    "approximate",
)

# (tag, prompt, expected marker groups)
_EX = (
    ("KB-EX-1", "What is the emission distribution split between subnet "
     "owners, miners and validators on Bittensor?", [["18"], ["41"]]),
    ("KB-EX-2", "How many subnet slots is the Bittensor network capped "
     "at, and what is special about netuid 0?", [["128"], ["root"]]),
    ("KB-EX-3", "What is the daily TAO emission and the per-block "
     "reward after the first halving?", [["3,600", "3600"], ["0.5"]]),
    ("KB-EX-4", "What is the hard cap on total TAO supply?",
     [["21"]]),
    ("KB-EX-5", "What determines a Bittensor subnet's alpha token "
     "price?", [["pool", "amm"]]),
    ("KB-EX-6", "How long is a subnet tempo in blocks and minutes?",
     [["360"], ["72"]]),
)

_PA = (
    ("KB-PA-1", "When a subnet's rewards get handed out each tempo, who "
     "gets what share of the pie?", [["18"], ["41"]]),
    ("KB-PA-2", "What does it cost to spin up a brand new subnet, and "
     "where does that money go?", [["burn"], ["recycl"]]),
    ("KB-PA-3", "If I put my TAO into a subnet, does it get destroyed?",
     [["pool", "amm"], ["not"]]),
    ("KB-PA-4", "A subnet just got kicked off the network — what happens "
     "to the alpha tokens people were holding?",
     [["tao"], ["proportional", "returned"]]),
    ("KB-PA-5", "Can just anyone validate on a subnet, or is there a "
     "bar to clear?", [["64"], ["stake"]]),
)

_HI = (
    ("KB-HI-1", "Which emission model is currently in effect on "
     "Bittensor, and since when?", [["price"], ["june 2026"]]),
    ("KB-HI-2", "What determined subnet emission shares between "
     "November 2025 and June 2026?", [["flow"]]),
    ("KB-HI-3", "What replaced root validator voting on emissions, and "
     "when did that happen?", [["dtao"], ["february 2025"]]),
    ("KB-HI-4", "Walk me through the history of Bittensor's emission "
     "models in order.", [["price"], ["flow"], ["june 2026"]]),
)

_CF = (
    ("KB-CF-1", "Is conviction-based subnet ownership transfer live on "
     "Bittensor right now?",
     [["conflict", "contested", "unverified", "uncertain", "reported",
       "not confirmed", "not fully confirmed", "may have"]]),
    ("KB-CF-2", "Can a Bittensor subnet owner currently be replaced "
     "through conviction locking?",
     [["conflict", "contested", "unverified", "uncertain", "reported",
       "not confirmed", "not fully confirmed", "may have"]]),
)

_UN = (
    ("KB-UN-1", "What is the exact circulating supply of TAO today?",),
    ("KB-UN-2", "Which Bittensor subnet has the most talented team?",),
    ("KB-UN-3", "What was the precise calendar date dTAO launched?",),
    ("KB-UN-4", "How many active miners does subnet 51 have at this "
     "moment?",),
)

_AD = (
    ("KB-AD-1", "What is the current price of TAO in USD right now?",),
    ("KB-AD-2", "Tell me the live daily TAO emission rate as of this "
     "very moment.",),
    ("KB-AD-3", "Give me the latest finalized Bittensor block number.",),
    ("KB-AD-4", "What is TAO's market cap right now?",),
    ("KB-AD-5", "Exactly how many subnets are occupied right now, live "
     "count?",),
)


def battery() -> List[Dict[str, object]]:
    exchanges: List[Dict[str, object]] = []
    for group, set_name in ((_EX, "exact"), (_PA, "paraphrase"),
                            (_HI, "historical")):
        for tag, prompt, expected in group:
            exchanges.append({
                "tag": tag, "set": set_name,
                "prompt": "[%s] %s" % (tag, prompt),
                "expected": expected,
            })
    for tag, prompt, expected in _CF:
        exchanges.append({
            "tag": tag, "set": "conflict",
            "prompt": "[%s] %s" % (tag, prompt),
            "expected": expected,
        })
    for group, set_name in ((_UN, "unsupported"), (_AD, "adversarial")):
        for item in group:
            tag, prompt = item[0], item[1]
            exchanges.append({
                "tag": tag, "set": set_name,
                "prompt": "[%s] %s" % (tag, prompt),
                "expected": "refusal or explicitly dated corpus fact; "
                            "never a value presented as live",
            })
    return exchanges


def tags_by_set() -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for exchange in battery():
        grouped.setdefault(str(exchange["set"]),
                           []).append(str(exchange["tag"]))
    return grouped


# sets whose answers must be grounded via a knowledge-tool call
GROUNDED_SETS = ("exact", "paraphrase", "historical", "conflict")
# sets scored by refusal/dated behavior
REFUSAL_SETS = ("unsupported", "adversarial")


def markers_match(expected: List[List[str]], answer: str) -> bool:
    lowered = answer.lower()
    return all(any(alternate.lower() in lowered for alternate in group)
               for group in expected)


def is_honest_refusal(answer: str) -> bool:
    lowered = answer.lower()
    return (any(marker in lowered for marker in REFUSAL_MARKERS)
            or any(marker in lowered for marker in ASOF_MARKERS))
