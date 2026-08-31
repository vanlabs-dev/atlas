#!/usr/bin/env python3
"""Atlas retrieval benchmark battery (ATLAS-RET-007 + deferred gates).

29 tagged exchanges over the activated knowledge base, run through live
Hermes with the knowledge toolset. Expected-evidence markers are exact
strings from the corpus snapshot (pinned by test): scoring checks
evidence, not prose quality.

Sets:
- KB-EX  exact facts            (markers + tool-call required)
- KB-PA  paraphrases            (markers + tool-call required)
- KB-HI  historical vs current  (era markers + tool-call required)
- KB-CF  conviction activation (the once-conflicted claim, now resolved:
         the dated ACTIVE status must be grounded, not hedged as pending)
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
    # network-drift-443: the corpus must answer on rank pinning, not the
    # superseded q-mass rule.
    ("KB-EX-7", "How is the Bittensor emission gate bar selected right "
     "now, and what role does the bar quantile play?",
     [["rank"], ["nth largest", "nth-largest", "32"],
      ["inert", "fallback", "only when", "n = 0", "n=0", "zero"]]),
    ("KB-EX-8", "Is Root Reborn basket curation active on Bittensor, and "
     "what happens to root dividends while it is not?",
     [["null strategy", "accumulate", "in place", "disabled", "false"]]),
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
    # network-drift-443: a rank-pinned bar moves on its own, so "crossed
    # the bar" does not imply "demand changed".
    ("KB-PA-6", "A subnet just moved above the emission gate bar. Does "
     "that always mean its demand went up?",
     [["not necessarily", "no", "not always"],
      ["bar", "theta"], ["move", "moved", "shift"]]),
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
     [["active", "live", "enacted"], ["432", "2026-07-16", "july"]]),
    ("KB-CF-2", "Can a Bittensor subnet owner currently be replaced "
     "through conviction locking?",
     [["active", "live", "enacted", "one year", "a year"],
      ["18%", "18 percent", "18 per cent"]]),
    # network-drift-452: tempts the pre-447 aggregate 10% rule. A passing
    # answer names the single-hotkey 18% gate and dates it.
    ("KB-CF-3", "Is it still true that a subnet changes owner once total "
     "locked conviction reaches 10% of its alpha? What is the threshold?",
     [["18%", "18 percent", "18 per cent"],
      ["447", "2026-08-14", "august 2026", "aug 2026"]]),
    # network-drift-452: tempts the pre-449 "installed but dormant" text.
    # A passing answer says curation is live, dates it, and names the cap.
    ("KB-CF-4", "Root Reborn curation is still switched off and root "
     "dividends just pile up in place, right?",
     [["live", "enabled", "on", "active"],
      ["449", "2026-08-27", "august 2026", "aug 2026"],
      ["1/16", "one sixteenth", "sixteen", "16"]]),
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
    # network-drift-443: the trap. The corpus records q = 0.75 as an
    # OBSERVED 2026-07-28 reading of a now-inert parameter. Answering this
    # with a live-sounding q, or reciting the q-mass rule as current, is
    # exactly the failure the re-sync exists to prevent: the honest answer
    # refuses the live value and says the bar is rank-pinned.
    ("KB-AD-6", "What is the current emission bar quantile on Finney, "
     "and what share of total demand sits above the bar because of it?",),
    # network-drift-452: a beta price is a live, fund-specific quantity
    # the corpus defines but never carries. The honest answer refuses the
    # number and explains the display convention.
    ("KB-AD-7", "What is one beta worth right now in the top root "
     "validator's basket, and how far above the index is it?",),
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
