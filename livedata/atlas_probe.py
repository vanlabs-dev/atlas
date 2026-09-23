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


def _drift_text(result: Dict[str, Any]) -> str:
    where = "spec %s block %s" % (result.get("spec"), result.get("block"))
    if result.get("error"):
        return "Atlas • probe-drift: probe failed closed (%s): %s" % (
            where, result["error"])
    lines = ["Atlas • probe-drift: %d chain read(s) fail at %s"
             % (len(result["failures"]), where)]
    lines += ["- %s.%s: %s" % (f["pallet"], f["item"], f["reason"])
              for f in result["failures"]]
    return "\n".join(lines)


def watch_decide(result: Dict[str, Any], state: Dict[str, Any],
                 send: Callable[[str], bool]) -> Dict[str, Any]:
    """Page once per failing set. `state["paged"]` is the signature of the
    last delivered page; a clear sends one note and resets it. A failed
    send leaves the state alone, so the next run tries again."""
    if result["ok"]:
        if state.get("paged") and send(
                "Atlas • probe-drift cleared at spec %s block %s"
                % (result.get("spec"), result.get("block"))):
            state["paged"] = None
        return state
    signature = ("error" if result.get("error") else
                 "|".join(sorted("%s.%s" % (f["pallet"], f["item"])
                                 for f in result["failures"])))
    if signature != state.get("paged") and send(_drift_text(result)):
        state["paged"] = signature
    return state


def telegram_send(text: str) -> bool:
    """Deliver through the telegram module's send path, credentials, and
    scrubber. Returns False on any refusal or delivery failure."""
    import atlas_telegram as tg
    try:
        config = tg.load_config()
        token, chat_id = tg.resolve_credentials(config)
        tg.assert_sendable(text)
    except (tg.FatalTelegramError, tg.ScrubRefusal) as exc:
        print("telegram: %s" % tg.redact(str(exc)), file=sys.stderr)
        return False
    return bool(tg.send_message(config, token, chat_id, text)["delivered"])


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
