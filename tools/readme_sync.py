#!/usr/bin/env python3
"""Keep the generated regions of README.md true to the repository.

The README is hand-written prose plus three generated regions, each
fenced by `<!-- BEGIN:name -->` and `<!-- END:name -->`:

    components    one row per top-level component directory
    capabilities  one row per accepted spec in openspec/specs/
    schedule      one row per systemd timer shipped in the repo

Everything is derived from files in the tree (directory names, spec
Purpose text, timer units). Nothing here reads the corpus, the chain or
the device, so the runtime upgrade job never makes the README stale.

    python3 tools/readme_sync.py           # rewrite the regions
    python3 tools/readme_sync.py --check   # exit 1 when the README is stale
"""

from __future__ import annotations

import argparse
import configparser
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

# One line per component. A new top-level directory that holds tests or
# systemd units must be added here, or `--check` fails: that is what
# forces a new component into the README.
COMPONENTS: Dict[str, str] = {
    "knowledge": "Validated Bittensor corpus, search store and the `atlas-kb` MCP server",
    "repotrack": "Verified clone of the subtensor repository, change records, `atlas-repo` MCP server",
    "livedata": "Fail-closed TaoSwap, TaoStats, CoinGecko and chain-RPC readers, gate and parameter watches, `atlas-live` MCP server",
    "fleet": "Clones every subnet's repository, indexes it, scores rotation and mining signals, serves the LAN board and `atlas-fleet`",
    "telegram": "Alert classes, tiers, delivery ledger, plain-English rewrite, daily briefing",
    "upgrade": "Runtime upgrade job: detects a new spec, edits the corpus in a worktree, gates and pushes",
    "subnt": "Public-edition exporter (retired, code kept)",
    "hermes": "Read-only verifiers for the Hermes agent baseline, memory and model",
    "inventory": "Read-only device inventory collector",
    "hardening": "Read-only security-posture assessor and the operator-approved apply scripts",
    "tools": "Repository tooling, including this README generator",
}

# Retired work stays in the tree but is labelled in the generated tables.
RETIRED = {"subnt-publish", "atlas-subnt"}

# Directories that never count as components.
IGNORED = {".git", ".github", "docs", "openspec", "triage", "var", "node_modules"}


def _is_component_dir(name: str) -> bool:
    path = os.path.join(ROOT, name)
    if name in IGNORED or name.startswith(".") or not os.path.isdir(path):
        return False
    return (os.path.isdir(os.path.join(path, "tests"))
            or os.path.isdir(os.path.join(path, "systemd")))


def components() -> List[str]:
    return sorted(name for name in os.listdir(ROOT) if _is_component_dir(name))


def render_components() -> str:
    missing = [n for n in components() if n not in COMPONENTS]
    stale = [n for n in COMPONENTS if not os.path.isdir(os.path.join(ROOT, n))]
    if missing or stale:
        raise SystemExit(
            "tools/readme_sync.py COMPONENTS is out of step: add %s, remove %s"
            % (missing or "nothing", stale or "nothing"))
    rows = ["| Directory | Role |", "|---|---|"]
    for name in COMPONENTS:
        link = "[`%s/`](%s/)" % (name, name)
        if os.path.isfile(os.path.join(ROOT, name, "README.md")):
            link = "[`%s/`](%s/README.md)" % (name, name)
        rows.append("| %s | %s |" % (link, COMPONENTS[name]))
    return "\n".join(rows)


def _purpose(spec_path: str) -> str:
    with open(spec_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r"^## Purpose\s*\n(.*?)(?=^## )", text, re.S | re.M)
    if not match:
        return "(no Purpose section)"
    paragraph = " ".join(match.group(1).split())
    sentence = re.split(r"(?<=[.:])\s", paragraph, maxsplit=1)[0]
    if "TBD" in sentence:
        raise SystemExit("%s has a placeholder Purpose: write one" % spec_path)
    return sentence.rstrip(":").rstrip(".") + "."


def render_capabilities() -> str:
    specs_dir = os.path.join(ROOT, "openspec", "specs")
    rows = ["| Capability | Purpose |", "|---|---|"]
    for name in sorted(os.listdir(specs_dir)):
        spec = os.path.join(specs_dir, name, "spec.md")
        if os.path.isfile(spec):
            text = _purpose(spec).replace("|", "\\|")
            if name in RETIRED:
                text = "**Retired.** " + text
            rows.append("| [`%s`](openspec/specs/%s/spec.md) | %s |"
                        % (name, name, text))
    return "\n".join(rows)


def _unit_files() -> List[Tuple[str, str]]:
    found = []
    for name in components():
        unit_dir = os.path.join(ROOT, name, "systemd")
        if os.path.isdir(unit_dir):
            for unit in sorted(os.listdir(unit_dir)):
                if unit.endswith(".timer"):
                    found.append((name, os.path.join(unit_dir, unit)))
    return found


def _humanize(when: str) -> str:
    """Plain wording for the few OnCalendar shapes the repo uses; any other
    shape is shown as written."""
    if when == "hourly":
        return "Every hour"
    match = re.fullmatch(r"\*:00/(\d+)", when)
    if match:
        return "Every %s minutes" % match.group(1)
    match = re.fullmatch(r"\*-\*-\* 00/(\d+):(\d+):00", when)
    if match:
        return "Every %s hours, at :%s" % (match.group(1), match.group(2))
    return "`%s`" % when


def render_schedule() -> str:
    rows = ["| Timer | When | Does |", "|---|---|---|"]
    for _component, path in _unit_files():
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str  # keep unit keys case-sensitive
        parser.read(path, encoding="utf-8")
        timer = parser["Timer"] if parser.has_section("Timer") else {}
        when = timer.get("OnCalendar") or (
            "every " + timer["OnUnitActiveSec"] if "OnUnitActiveSec" in timer
            else "on boot")
        desc = parser.get("Unit", "Description", fallback="")
        desc = re.sub(r"^Atlas\s+", "", desc)
        desc = re.sub(r"\s+timer(\s*\(.*\))?$", "", desc)
        unit = os.path.basename(path)[:-len(".timer")]
        desc = desc[:1].upper() + desc[1:]
        if unit in RETIRED:
            desc += " (retired, masked)"
        rows.append("| `%s` | %s | %s |" % (unit, _humanize(when), desc))
    return "\n".join(rows)


RENDERERS = {
    "components": render_components,
    "capabilities": render_capabilities,
    "schedule": render_schedule,
}


def _region(name: str) -> "re.Pattern[str]":
    return re.compile(
        r"(<!-- BEGIN:%s -->\n)(.*?)(<!-- END:%s -->)" % (name, name), re.S)


def sync(text: str) -> str:
    for name, render in RENDERERS.items():
        pattern = _region(name)
        if not pattern.search(text):
            raise SystemExit("README.md has no BEGIN:%s / END:%s region"
                             % (name, name))
        body = render() + "\n"
        text = pattern.sub(lambda m: m.group(1) + body + m.group(3), text)
    return text


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when the README is stale; write nothing")
    args = parser.parse_args(argv)
    with open(README, "r", encoding="utf-8") as handle:
        current = handle.read()
    updated = sync(current)
    if updated == current:
        print("README.md is current")
        return 0
    if args.check:
        print("README.md is stale: run python3 tools/readme_sync.py",
              file=sys.stderr)
        return 1
    with open(README, "w", encoding="utf-8") as handle:
        handle.write(updated)
    print("README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
