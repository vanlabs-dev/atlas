"""Push scope of the grounding job (change: chain-grounding).

The job commits generated data only: GROUNDING.md, the claims ledger and
the snapshot directories. The gate checks every changed path in the
grounding worktree against these lists, in code. Additions are allowed
(a new spec adds a snapshot directory); a deletion or rename is not.
Nothing here is imported by the job or by a long-lived service.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

ALLOWED = (
    re.compile(r"^GROUNDING\.md$"),
    re.compile(r"^grounding/claims\.yaml$"),
    re.compile(r"^snapshots/\d+/(meta|pallets|chain|subnets)\.json$"),
    re.compile(r"^snapshots/\d+/DIFF\.md$"),
)
# Porcelain v1 XY codes for a modification or an addition.
OK_CODES = (" M", "M ", "MM", "??", "A ", "AM")


def is_allowed(path: str) -> bool:
    return any(r.match(path) for r in ALLOWED)


def scope_violations(entries: Iterable[Tuple[str, str]]) -> List[str]:
    found = set()
    for code, path in entries:
        if not is_allowed(path):
            found.add("%s (outside the grounding scope)" % path)
        elif code not in OK_CODES:
            found.add("%s (%s: only additions and modifications are "
                      "allowed)" % (path, code.strip() or code))
    return sorted(found)
