#!/usr/bin/env python3
"""Voice acceptance battery (change: telegram-voice-overhaul).

The named chat-side verification (telegram/docs/voice.md section 7): the
MV-RI-4 adversarial re-test (the KB-AD set of the retrieval benchmark,
imported so the trap prompts stay single-sourced) plus three voice probes
against the re-voiced live chat:

- MV-VP-1  answer-first structure: a yes/no question; the first line
           must open with the answer, no opener or restatement.
- MV-VP-2  banned-synonym absence: the emission-gate bar explained;
           prose must say "bar" and never theta/threshold/limit/cutoff,
           with jargon glossed at first use.
- MV-VP-3  next-action presence: a question with a real follow-up; the
           answer must end with a single imperative next-action line.

All exchanges run with the knowledge toolset so dated corpus facts are
reachable. Acceptance: dated corpus facts or explicit refusals, zero
invented live values, and the three voice probes pass. Judging is
operator-recorded (docs/decisions.md) over the answers the scorer's
extract_exchanges() pulls by tag.

Run on the Pi from the repo root:
    python3 hermes/modelval/run_battery.py \
        --battery hermes/modelval/atlas_voice_battery.py \
        --toolsets-tc atlas-kb --toolsets-plain atlas-kb \
        --tool-sets adversarial,voice-probe

Pure data + pure functions. No I/O, no device access.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List

BATTERY_VERSION = "0.1.0"

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_KB_BATTERY = os.path.join(_MODULE_DIR, os.pardir, os.pardir,
                           "knowledge", "benchmark",
                           "atlas_kb_battery.py")


def _load_kb_battery() -> Any:
    spec = importlib.util.spec_from_file_location(
        "atlas_kb_battery", _KB_BATTERY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The voice probes. Each is a corpus-grounded question whose pass
# condition is a voice property, judged by the operator from the recorded
# answer. Expected text documents the pass condition.
_VP = (
    ("MV-VP-1",
     "Answer yes or no: is conviction-based subnet ownership transfer "
     "live on Bittensor right now?",
     "answer-first: the first line opens with the yes/no answer, no "
     "opener or restatement; the fact carries its date"),
    ("MV-VP-2",
     "What is the bar in Bittensor's emission gate, and how is it "
     "selected right now?",
     "banned-synonym absence: prose says 'bar', never theta / threshold "
     "/ limit / cutoff; jargon (rank-pinned, q-mass) glossed at first "
     "use; selection rule stated as dated or current per the corpus"),
    ("MV-VP-3",
     "A subnet I hold fell below the emission gate bar today. What does "
     "that mean for its emission?",
     "next-action presence: verdict first, then a single imperative "
     "next-action line closes the answer"),
)


def battery() -> List[Dict[str, object]]:
    kb = _load_kb_battery()
    exchanges: List[Dict[str, object]] = [
        exchange for exchange in kb.battery()
        if exchange["set"] == "adversarial"  # KB-AD: the MV-RI-4 re-test
    ]
    for tag, prompt, expected in _VP:
        exchanges.append({
            "tag": tag, "set": "voice-probe",
            "prompt": "[%s] %s" % (tag, prompt),
            "expected": expected,
        })
    return exchanges


def tags_by_set() -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for exchange in battery():
        grouped.setdefault(str(exchange["set"]),
                           []).append(str(exchange["tag"]))
    return grouped


if __name__ == "__main__":
    for exchange in battery():
        print("%s [%s] %s" % (exchange["tag"], exchange["set"],
                              exchange["expected"]))
