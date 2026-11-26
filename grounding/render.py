"""Render GROUNDING.md from the claims ledger (change: chain-grounding).

The output is a pure function of claims.yaml and config.json, so a test
can prove the committed GROUNDING.md was never hand-edited. It must stay
under `max_bytes`: it is read whole by WebFetch on phones.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

import ledger
import yamlsub

ABBREVIATIONS = (("pallets/subtensor/src/", "st/"),
                 ("pallets/admin-utils/src/", "au/"),
                 ("pallets/swap/src/", "sw/"))
FRONT_KEYS = ("spec_version", "subtensor_tag", "subtensor_commit",
              "newest_tag", "newest_tag_live", "last_updated",
              "content_changed", "pending_on_main")
VOLATILE = ("last_updated", "content_changed")

INTRO = """# Bittensor chain grounding

Machine-checked facts about how the Bittensor chain (subtensor) works on
mainnet now. Atlas regenerates this file from `grounding/claims.yaml`.
Every claim cites source lines at a release tag. A model drafted each
claim; a second model, shown only the claim and the cited lines, agreed
with it, and code checked that every number in it appears in those lines.

- Live means mainnet runs that spec (`state_getRuntimeVersion`). Code on
  `main` that mainnet does not run yet is listed in `pending_on_main`.
- Fresh means `last_updated` is under 7 days old and `spec_version` is
  not behind the newest `v*` tag. A newer tag with `newest_tag_live:
  false` is a release mainnet has not enacted yet; facts here are still
  the live ones.
- `UNVERIFIED (pending review)` marks a claim whose last check failed. Its
  last verified text is kept; do not rely on it.
- `live at snapshot` values are read from the chain when the spec went
  live (`snapshots/<spec>/`), not from code.
- Refs: `[tag path:lines]`. `st/` is `pallets/subtensor/src/`, `au/` is
  `pallets/admin-utils/src/`, `sw/` is `pallets/swap/src/`.
"""


def short_path(path: str) -> str:
    for long, short in ABBREVIATIONS:
        if path.startswith(long):
            return short + path[len(long):]
    return path


def ref(claim: Dict[str, Any]) -> str:
    """`[v497 st/a.rs:1-9,20-30; st/b.rs:5-8]`: the tag once per run of
    evidence at that tag, and each file once with its ranges."""
    groups: List[List[Any]] = []
    for ev in claim.get("evidence") or []:
        key = (ev["ref"], short_path(ev["path"]))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(ev["lines"])
        else:
            groups.append([key, [ev["lines"]]])
    parts, last_tag = [], None
    for (tag, path), lines in groups:
        text = "%s:%s" % (path, ",".join(lines))
        parts.append(text if tag == last_tag else "%s %s" % (tag, text))
        last_tag = tag
    return "[%s]" % "; ".join(parts) if parts else "[no citation]"


def spec_dates(meta: Dict[str, Any]) -> Dict[int, str]:
    """{spec: date it went live} from the ledger's observed upgrades."""
    return {e["spec"]: e["date"] for e in meta.get("spec_dates") or []}


def _date(spec: Any, dates: Dict[int, str], floor: bool = False) -> str:
    """`spec 481, 2026-10-19`; `or before spec 430` at the oldest release
    tag, where git history cannot tell an older change apart."""
    if floor:
        return "or before spec %s" % spec
    when = dates.get(spec) if spec is not None else None
    return "spec %s, %s" % (spec, when) if when else "spec %s" % spec


def claim_line(claim: Dict[str, Any], dates: Dict[int, str]) -> str:
    review = claim.get("review")
    if review or claim.get("stale"):
        reason = (review or {}).get("reason") or "re-check queued"
        if len(reason) > 160:
            reason = reason[:157].rstrip() + "..."
        if claim.get("last_verified"):
            text = "last verified %s: %s %s" % (
                claim["last_verified"][:10], claim["statement"], ref(claim))
        else:
            proposed = (review or {}).get("proposed") or claim["statement"]
            text = "never verified, proposed: %s %s" % (proposed, ref(claim))
        return "- **%s** (%s). %s" % (ledger.UNVERIFIED, reason, text)
    line = "- %s" % claim["statement"]
    if claim.get("status") == "deprecated":
        line += " (stopped applying at %s)" % _date(
            claim.get("deprecated_since_spec"), dates,
            bool(claim.get("deprecated_since_floor")))
    elif claim.get("status") == "pending":
        line += " (pending: on main, not live)"
    if claim.get("live_value"):
        line += " (live at snapshot: %s)" % claim["live_value"]
    return line + " " + ref(claim)


def front_matter(meta: Dict[str, Any]) -> str:
    return "---\n" + yamlsub.dump({k: meta.get(k) for k in FRONT_KEYS}) \
        + "---\n"


def body(data: Dict[str, Any], config: Dict[str, Any]) -> str:
    meta = data["meta"]
    dates = spec_dates(meta)
    out: List[str] = [INTRO]
    for number, section in enumerate(config["sections"], 1):
        out.append("## %d. %s\n" % (number, section["title"]))
        lines: List[str] = []
        if section["id"] == "changelog":
            lines = ["- %s" % entry for entry in meta.get("changelog") or []]
        else:
            for claim in data["claims"]:
                in_traps = (claim.get("status") == "deprecated"
                            and section["id"] == "traps")
                own = (claim["section"] == section["id"]
                       and claim.get("status") != "deprecated")
                if in_traps or own:
                    lines.append(claim_line(claim, dates))
        out.append("\n".join(lines or ["- No verified claims yet."]) + "\n")
    return "\n".join(out)


def content_hash(data: Dict[str, Any], config: Dict[str, Any]) -> str:
    meta = dict(data["meta"])
    for key in VOLATILE:
        meta[key] = None
    text = front_matter(meta) + body(dict(data, meta=meta), config)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(data: Dict[str, Any], config: Dict[str, Any]) -> str:
    return front_matter(data["meta"]) + "\n" + body(data, config)


def section_bytes(data: Dict[str, Any], config: Dict[str, Any],
                  section: str) -> int:
    dates = spec_dates(data["meta"])
    return sum(len(claim_line(c, dates).encode("utf-8")) + 1
               for c in data["claims"] if c["section"] == section)
