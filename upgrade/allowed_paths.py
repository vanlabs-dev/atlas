"""Edit scope of the runtime upgrade job (change: runtime-upgrade-pipeline,
narrowed by upgrade-sandbox-scope).

The scope gate checks every changed path in the upgrade worktree against
these lists, in code. The same lists shape the model's Edit and Write
permissions, but the gate does not trust that: it runs on the diff.
A path must match ALLOWED and must not match DENIED, and only a
modification of a file that exists in the base commit passes: an added,
renamed, copied or deleted file fails even under an allowed path.

The scope is data only: the corpus, the supersession markers and the
decision log. No file the job or a long-lived service imports is in it, so
the job never runs model-written code. A chain reader that drifts is an
operator fix (the probe preflight waits for one).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

ALLOWED = (
    "knowledge/corpus/**",
    "knowledge/supersession-markers.json",
    "docs/decisions.md",
)

# Denied even when an ALLOWED pattern matches. Most entries are outside
# ALLOWED already; they are listed so the scope is readable in one place.
DENIED = (
    "livedata/**",
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


# Porcelain v1 XY codes that are a plain modification of a tracked file.
MODIFIED_CODES = (" M", "M ", "MM")


def scope_violations(entries: Iterable[Tuple[str, str]]) -> List[str]:
    """Readable violations for (porcelain XY code, path) entries: a path
    outside the scope, or any change that is not a modification."""
    found = set()
    for code, path in entries:
        if not is_allowed(path):
            found.add("%s (outside the allowed scope)" % path)
        elif code not in MODIFIED_CODES:
            found.add("%s (%s: only modifications of existing files are "
                      "allowed)" % (path, code.strip() or code))
    return sorted(found)


def tool_rules() -> List[str]:
    """Edit and Write permission rules for `claude --allowedTools`."""
    return ["%s(%s)" % (tool, p) for p in ALLOWED for tool in ("Edit",
                                                               "Write")]


def tool_denials() -> List[str]:
    return ["%s(%s)" % (tool, p) for p in DENIED for tool in ("Edit",
                                                              "Write")]
