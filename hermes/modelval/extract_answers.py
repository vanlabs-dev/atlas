"""Read the recorded answers for a battery out of the session store.

Read-only: opens the store with mode=ro and writes nothing. The scorer
(atlas_modelval_score.py) is bound to the modelval battery and cannot
score voice probes, so acceptance for those reads answers through here
and applies the battery's own mechanical checks.

Run on the device from the repo root:
    python3 hermes/modelval/extract_answers.py \
        --battery hermes/modelval/atlas_voice_battery.py
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _MODULE_DIR)

import atlas_modelval_score as scorer  # noqa: E402

amv = scorer.amv  # scorer already resolves hermes/memory onto sys.path


def _load(path):
    spec = importlib.util.spec_from_file_location("battery_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _final_answer(rows):
    """Last assistant row carrying content. The scorer's own extractor
    returns the last assistant row even when it is empty."""
    for role, _tool, content, _ts in reversed(rows):
        if role == "assistant" and content:
            return content
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--battery", required=True)
    parser.add_argument("--store", default=os.path.expanduser(
        "~/.hermes/" + amv.SESSION_DB_NAME))
    parser.add_argument("--quiet", action="store_true",
                        help="verdict lines only, no answer text")
    args = parser.parse_args()

    battery_mod = _load(args.battery)
    exchanges = battery_mod.battery()
    found = scorer.extract_exchanges(args.store, exchanges)["exchanges"]

    checks = {}
    tallies = {}
    for exchange in exchanges:
        tag = str(exchange["tag"])
        hit = found.get(tag)
        if not hit:
            print("%-12s NOT FOUND" % tag)
            continue
        answer = _final_answer(hit["rows"])
        verdict = ""
        if hasattr(battery_mod, "base_tag"):
            base = battery_mod.base_tag(tag)
            expected = str(exchange["expected"])
            if "next-action presence" in expected:
                ok = battery_mod.closes_with_next_action(answer)
            elif "next-action absence" in expected:
                ok = battery_mod.omits_next_action(answer)
            else:
                ok = None
            if ok is not None:
                checks[tag] = ok
                passed, total = tallies.get(base, (0, 0))
                tallies[base] = (passed + int(ok), total + 1)
                verdict = " | next-action: %s" % ("pass" if ok else "FAIL")
        print("=" * 72)
        print("%s%s" % (tag, verdict))
        if not args.quiet:
            print(answer)

    if tallies:
        print("=" * 72)
        threshold = getattr(battery_mod, "PASS_K", None)
        for base in sorted(tallies):
            passed, total = tallies[base]
            mark = ""
            if threshold is not None:
                mark = "  %s" % ("PASS" if passed >= threshold else "FAIL")
            print("%-12s %d/%d%s" % (base, passed, total, mark))
        print("\nMechanical checks only. Honesty (dated corpus facts or "
              "explicit refusals, zero invented live values) and the "
              "lexicon remain operator-judged from the answers above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
