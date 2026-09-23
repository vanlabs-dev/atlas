"""Edit scope of the runtime upgrade job (change: runtime-upgrade-pipeline).

The scope gate checks every changed path in the upgrade worktree against
these lists, in code. The same lists shape the model's Edit and Write
permissions, but the gate does not trust that: it runs on the diff.
A path must match ALLOWED and must not match DENIED.
"""

from __future__ import annotations

import re
from typing import Iterable, List

ALLOWED = (
    "knowledge/corpus/**",
    "knowledge/supersession-markers.json",
    "docs/decisions.md",
    "livedata/*.py",
    "livedata/config.json",
)

# Denied even when an ALLOWED pattern matches. Most entries are outside
# ALLOWED already; they are listed so the scope is readable in one place.
DENIED = (
    "livedata/atlas_probe.py",
    "livedata/scale_meta.py",
    "**/tests/**",
    "upgrade/**",
    "AGENTS.md",
    "**/systemd/**",
    "**/.env*",
)


def _regex(pattern: str) -> "re.Pattern[str]":
    """Glob to regex: `**/` is zero or more directories, `**` is anything,
    `*` stays inside one path segment."""
    out = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            out += ".*"
            index += 2
        elif pattern[index] == "*":
            out += "[^/]*"
            index += 1
        else:
            out += re.escape(pattern[index])
            index += 1
    return re.compile(out + r"\Z")


_ALLOWED = [_regex(p) for p in ALLOWED]
_DENIED = [_regex(p) for p in DENIED]


def is_allowed(path: str) -> bool:
    return (any(r.match(path) for r in _ALLOWED)
            and not any(r.match(path) for r in _DENIED))


def out_of_scope(paths: Iterable[str]) -> List[str]:
    return sorted({p for p in paths if not is_allowed(p)})


def tool_rules() -> List[str]:
    """Edit and Write permission rules for `claude --allowedTools`."""
    return ["%s(%s)" % (tool, p) for p in ALLOWED for tool in ("Edit",
                                                               "Write")]


def tool_denials() -> List[str]:
    return ["%s(%s)" % (tool, p) for p in DENIED for tool in ("Edit",
                                                              "Write")]
