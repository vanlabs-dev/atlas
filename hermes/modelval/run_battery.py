#!/usr/bin/env python3
"""Atlas model-validation battery runner.

Replays the battery (atlas_modelval_battery.py) through the live Hermes
deployment via one-shot mode (`hermes -z`), one fresh session per
exchange. This is the ONLY file in hermes/modelval/ that invokes Hermes —
it is operator-invoked on the Pi and mutates nothing except by conversing
(sessions are written by Hermes itself, exactly as in manual use).

Because one-shot mode AUTO-BYPASSES approvals (v0.18.2 `-z` help), every
run MUST carry an explicit toolset restriction; this runner refuses to
start without one:
- tool-calling exchanges need ONLY the atlas-test MCP server
  (--toolsets-tc, e.g. "atlas-test" — verify with `hermes tools list`);
- every other set runs with tools disabled (--toolsets-plain, the
  identifier your `hermes tools list` shows for a no-tools/minimal set).

Per exchange the runner also asks Hermes for a usage report
(--usage-file) and appends a line to a run manifest (tag, exit code,
duration) — both land in the (gitignored) output directory for the
scorer's evidence trail.

Usage (on the Pi, from the repo root):
    python3 hermes/modelval/run_battery.py \
        --toolsets-tc atlas-test --toolsets-plain <no-tools-identifier> \
        [--only tool-calling|context-window|refusal-to-invent|latency]
        [--hermes ~/.local/bin/hermes] [--output-dir var/modelval]
        [--pause-seconds 2]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import atlas_modelval_battery as battery_mod  # noqa: E402

EXCHANGE_TIMEOUT_S = 600


def run_battery(hermes: str, toolsets_tc: str, toolsets_plain: str,
                output_dir: str, only: Optional[str],
                pause_seconds: float) -> int:
    usage_dir = os.path.join(output_dir, "usage")
    os.makedirs(usage_dir, exist_ok=True)
    manifest_path = os.path.join(output_dir, "run-manifest.jsonl")
    exchanges = [exchange for exchange in battery_mod.battery()
                 if only is None or exchange["set"] == only]
    print("Running %d exchange(s)%s — battery v%s"
          % (len(exchanges), " (set: %s)" % only if only else "",
             battery_mod.BATTERY_VERSION))
    failures = 0
    for index, exchange in enumerate(exchanges, 1):
        tag = exchange["tag"]
        toolsets = (toolsets_tc if exchange["set"] == "tool-calling"
                    else toolsets_plain)
        usage_file = os.path.join(usage_dir, "%s.json" % tag)
        argv = [hermes, "-z", exchange["prompt"], "-t", toolsets,
                "--usage-file", usage_file]
        started = time.time()
        print("[%d/%d] %s (toolsets: %s) ..."
              % (index, len(exchanges), tag, toolsets), flush=True)
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=EXCHANGE_TIMEOUT_S)
            exit_code: Optional[int] = completed.returncode
            error = completed.stderr.strip()[-400:] or None
        except subprocess.TimeoutExpired:
            exit_code = None
            error = "timeout after %ds" % EXCHANGE_TIMEOUT_S
        except OSError as exc:
            print("FATAL: cannot invoke hermes (%s): %s" % (hermes, exc),
                  file=sys.stderr)
            return 1
        duration = round(time.time() - started, 2)
        if exit_code != 0:
            failures += 1
            print("  FAILED (exit %s): %s" % (exit_code, error or "?"),
                  flush=True)
        with open(manifest_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "tag": tag, "set": exchange["set"],
                "exit_code": exit_code, "duration_s": duration,
                "toolsets": toolsets, "error": error,
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime()),
            }) + "\n")
        if index < len(exchanges):
            time.sleep(pause_seconds)
    print("Done: %d/%d succeeded. Manifest: %s"
          % (len(exchanges) - failures, len(exchanges), manifest_path))
    print("Next: python3 hermes/modelval/atlas_modelval_score.py score")
    return 0 if failures == 0 else 3


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_battery",
        description="Replay the model-validation battery through "
                    "`hermes -z`. Refuses to run without explicit "
                    "toolset restrictions (one-shot mode bypasses "
                    "approvals).")
    parser.add_argument("--toolsets-tc", required=True,
                        help="toolsets for tool-calling exchanges — ONLY "
                             "the atlas-test MCP server")
    parser.add_argument("--toolsets-plain", required=True,
                        help="toolsets for all other exchanges — a "
                             "no-tools/minimal identifier")
    parser.add_argument("--hermes",
                        default=os.path.expanduser("~/.local/bin/hermes"))
    parser.add_argument("--output-dir",
                        default=os.path.join("var", "modelval"))
    parser.add_argument("--only", default=None,
                        choices=sorted(battery_mod.tags_by_set()))
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    return run_battery(args.hermes, args.toolsets_tc, args.toolsets_plain,
                       args.output_dir, args.only, args.pause_seconds)


if __name__ == "__main__":
    sys.exit(main())
