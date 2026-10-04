#!/usr/bin/env python3
"""Chain-read probe (change: runtime-upgrade-pipeline).

Checks every storage item in atlas_live.CHAIN_READS against live runtime
metadata at one finalized block: the item exists in its pallet, with the
declared key hashers and value type. A renamed or removed item then fails
here instead of reading silently as its default.

    check   one probe; exit 0 on pass, 1 on any failure (the merge gate)
    watch   one probe; page `probe-drift` once per new failing set (hourly)

Fails closed: a metadata fetch or decode error is a failure, never a pass.
This file and scale_meta.py are outside the upgrade job's edit scope.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(_MODULE_DIR), "telegram"))

import atlas_live as al  # noqa: E402
import scale_meta as sm  # noqa: E402

WATCH_STATE = "probe-watch.json"


def probe(config: Dict[str, Any],
          reads: Iterable[al.ChainRead] = al.CHAIN_READS,
          rpc: Optional[Any] = None) -> Dict[str, Any]:
    """Returns {ok, spec, block, block_hash, failures[, error]}."""
    rpc = rpc or (lambda method, params: al._rpc_call(config, method,
                                                      params))
    live = al.read_live_spec(config, rpc)
    if not live["ok"]:
        return {"ok": False, "error": live["error"], "failures": []}
    base = {"spec": live["spec_version"], "block": live["block_number"],
            "block_hash": live["block_hash"]}
    fetched = rpc("state_getMetadata", [live["block_hash"]])
    try:
        if not fetched.get("ok"):
            raise ValueError(fetched.get("error") or "no metadata")
        meta = sm.decode_metadata(al._payload_bytes(fetched.get("result")))
    except ValueError as exc:
        return dict(base, ok=False, failures=[],
                    error="metadata unavailable: %s" % al.redact(str(exc)))

    failures: List[Dict[str, str]] = []
    reads = list(reads)
    # Every pallet first: a missing pallet fails its items as one cause,
    # not as a list of per-item misses.
    missing = sorted({r.pallet for r in reads} - set(meta["pallets"]))
    for pallet in missing:
        failures.append({"pallet": pallet, "item": "*",
                         "reason": "pallet missing from metadata"})
    for read in reads:
        if read.pallet in missing:
            continue
        entry = meta["pallets"][read.pallet]["storage"].get(read.item)
        if entry is None:
            reason = "missing from metadata"
        elif tuple(entry["hashers"]) != tuple(read.hashers):
            reason = "hashers %s, declared %s" % (
                list(entry["hashers"]), list(read.hashers))
        else:
            try:
                actual = sm.type_name(meta["types"], entry["value"])
            except ValueError as exc:
                actual = "undecodable (%s)" % exc
            reason = ("" if actual == read.value_type else
                      "value type %s, declared %s" % (actual,
                                                      read.value_type))
        if reason:
            failures.append({"pallet": read.pallet, "item": read.item,
                             "reason": reason})
    return dict(base, ok=not failures, failures=failures)


def cmd_check(config: Dict[str, Any], rpc: Optional[Any] = None,
              reads: Iterable[al.ChainRead] = al.CHAIN_READS) -> int:
    result = probe(config, reads, rpc)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def _tg() -> Any:
    import atlas_telegram as tg
    return tg


_REASON_RE = (
    (re.compile(r"^pallet missing from metadata$"),
     lambda m: "pallet removed from the chain metadata"),
    (re.compile(r"^missing from metadata$"),
     lambda m: "removed from the chain metadata"),
    (re.compile(r"^hashers (.+), declared (.+)$"),
     lambda m: "key layout changed (chain %s, Atlas expects %s)"
     % (m.group(1), m.group(2))),
    (re.compile(r"^value type (.+), declared (.+)$"),
     lambda m: "type changed (chain %s, Atlas expects %s)"
     % (m.group(1), m.group(2))),
)


def _plain_reason(reason: str) -> str:
    for pattern, words in _REASON_RE:
        match = pattern.match(reason or "")
        if match:
            return words(match)
    return reason


def drift_message(result: Dict[str, Any]) -> Any:
    """The probe-drift page in the house layout (change:
    telegram-alert-redesign)."""
    tg = _tg()
    details = ["Runtime spec %s · block %s" % (
        result.get("spec"), tg.fmt_int(result.get("block")))]
    if result.get("error"):
        return tg.Message(
            severity=tg.severity_for("probe-drift"),
            headline="Atlas could not check its chain readers",
            meaning="The probe failed closed, so drift in the live chain "
                    "metadata is not being checked.",
            facts=[("Error", tg.rec(result["error"])[:300])],
            details=details,
            next_action="run %s on the Pi and read the error."
                        % tg.mono("python3 livedata/atlas_probe.py check"))
    failures = result["failures"]
    body = ["• %s: %s" % (tg.bold(f["item"]), tg.rec(_plain_reason(
        f["reason"]))) for f in failures[:12]]
    if len(failures) > 12:
        body.append("+%d more in the details" % (len(failures) - 12))
    details += ["%s.%s: %s" % (tg.rec(f["pallet"]), tg.rec(f["item"]),
                               tg.rec(f["reason"])) for f in failures]
    return tg.Message(
        severity=tg.severity_for("probe-drift"),
        headline="%s no longer match%s the live chain" % (
            tg.plural(len(failures), "Atlas chain reader"),
            "es" if len(failures) == 1 else ""),
        meaning="At runtime spec %s these storage reads changed shape. "
                "Figures that depend on them can be missing or wrong until "
                "fixed." % result.get("spec"),
        body=body, details=details,
        next_action="wait for the self-update report. If it says blocked, "
                    "fix the readers by hand.")


def cleared_message(result: Dict[str, Any]) -> Any:
    tg = _tg()
    return tg.Message(
        severity=tg.severity_for("probe-cleared"),
        headline="Atlas chain readers match the live chain again",
        meaning="Runtime spec %s, block %s." % (
            result.get("spec"), tg.fmt_int(result.get("block"))))


def watch_decide(result: Dict[str, Any], state: Dict[str, Any],
                 send: Callable[[Any], bool]) -> Dict[str, Any]:
    """Page once per failing set. `state["paged"]` is the signature of the
    last delivered page; a clear sends one note and resets it. A failed
    send leaves the state alone, so the next run tries again."""
    if result["ok"]:
        if state.get("paged") and send(cleared_message(result)):
            state["paged"] = None
        return state
    signature = ("error" if result.get("error") else
                 "|".join(sorted("%s.%s" % (f["pallet"], f["item"])
                                 for f in result["failures"])))
    if signature != state.get("paged") and send(drift_message(result)):
        state["paged"] = signature
    return state


def telegram_send(msg: Any) -> bool:
    """Deliver one Message through the telegram module's renderer,
    credentials, scrubber, and HTML-to-plain fallback. Returns False on
    any refusal or delivery failure."""
    tg = _tg()
    try:
        config = tg.load_config()
        token, chat_id = tg.resolve_credentials(config)
        max_chars = int(config.get("message_max_chars", 3500))
        _lexicon, glosses = tg.voice_maps(config)
        text = tg.render_plain(msg, max_chars, glosses)
        html = tg.render_html(msg, max_chars, glosses)
        tg.assert_sendable(text)
        tg.assert_sendable(html)
    except (tg.FatalTelegramError, tg.ScrubRefusal) as exc:
        print("telegram: %s" % tg.redact(str(exc)), file=sys.stderr)
        return False
    result, _note = tg.send_with_fallback(config, token, chat_id, text, html,
                                          list(msg.buttons))
    return bool(result["delivered"])


def cmd_watch(config: Dict[str, Any]) -> int:
    path = os.path.join(al.resolve(config["output_dir"]), WATCH_STATE)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        state = {}
    result = probe(config)
    state = watch_decide(result, state, telegram_send)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    al.write_private(path, json.dumps(state, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check declared chain reads against live metadata")
    parser.add_argument("command", choices=("check", "watch"))
    args = parser.parse_args(argv)
    config = al.load_config()
    if args.command == "check":
        return cmd_check(config)
    return cmd_watch(config)


if __name__ == "__main__":
    raise SystemExit(main())
