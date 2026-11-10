"""Public subnt.dev boards from the Atlas stores (change: supabase-data-layer).

    python3 sitedata/atlas_sitedata.py compose   # print the four boards

Each record is built from the shared field allowlist alone
(sitedata/allowlist.json), so a field the stores add later cannot reach the
site. Numbers are rounded to four significant digits, the way JavaScript's
toPrecision(4) rounds, so the boards match the fixture export exactly.
"""

import json
import math
import os
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOARDS = ("mining", "fleet", "network", "upgrades")

with open(os.path.join(HERE, "allowlist.json"), encoding="utf-8") as _handle:
    CONTRACT = json.load(_handle)
ALLOWLIST: Dict[str, Dict[str, str]] = CONTRACT["kinds"]
SERIES: Dict[str, int] = CONTRACT["series"]

with open(os.path.join(HERE, "scrub.json"), encoding="utf-8") as _handle:
    _SCRUB = json.load(_handle)
_RULES = [(r["kind"], re.compile(r["pattern"], re.I if "i" in r["flags"] else 0))
          for r in _SCRUB["rules"]]
_SS58 = re.compile(_SCRUB["ss58"])
PUBLIC_ADDRESSES = frozenset(_SCRUB["public_addresses"])

Value = Union[str, int, float, bool, None, List[int]]


def round4(value: Union[int, float]) -> Union[int, float]:
    """Four significant digits, ties away from zero, as Number(v.toPrecision(4))."""
    if isinstance(value, int) or (math.isfinite(value) and value.is_integer()):
        return int(value)
    if not math.isfinite(value):
        raise ValueError("non-finite value %r" % value)
    exact = Decimal(value)
    shift = exact.adjusted() - 3
    rounded = exact.scaleb(-shift).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    out = float(rounded.scaleb(shift))
    return int(out) if out.is_integer() else out


def _clean(value: Any) -> Value:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round4(value)
    if isinstance(value, str):
        # House style bans em dashes, and source prose carries some.
        return value.replace("—", "-")
    raise ValueError("non-scalar value %s" % json.dumps(value))


def _series(field: str, value: Any) -> Optional[List[int]]:
    if value is None:
        return None
    ok = (isinstance(value, list) and len(value) == SERIES[field]
          and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                  for v in value))
    if not ok:
        raise ValueError("%s must be %d non-negative integers"
                         % (field, SERIES[field]))
    return value


def pick(kind: str, source: Dict[str, Any]) -> Dict[str, Value]:
    """A record from the allowlist alone. Unlisted source fields drop."""
    return {field: (_series(field, source.get(src)) if field in SERIES
                    else _clean(source.get(src)))
            for field, src in ALLOWLIST[kind].items()}


def pick_all(kind: str, records: List[Dict[str, Any]]) -> List[Dict[str, Value]]:
    return [pick(kind, r) for r in records]


def bin_daily(ages: List[float], days: int = 90) -> List[int]:
    """Commits per day, oldest first, from commit ages in days.

    The activity metric counts a commit in the w-day window when its age is
    at most w days, so a bin k days from the end holds ages in (k-1, k] and
    the newest bin also holds ages of zero or less. Ages above `days` drop.
    """
    out = [0] * days
    for age in ages:
        if not isinstance(age, (int, float)) or not math.isfinite(age) \
                or age > days:
            continue
        k = max(1, math.ceil(age))
        out[days - k] += 1
    return out


def boards(src: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The four public boards from compose.raw() output."""
    activity = [{"netuid": a["netuid"],
                 "daily": None if a["ages"] is None
                 else bin_daily(a["ages"], SERIES["daily"])}
                for a in src["activity"]]
    return {
        "mining": {"generatedAt": src["mining_at"],
                   "data": pick_all("mining", src["mining"])},
        "fleet": {"generatedAt": src["fleet_at"], "data": {
            "rows": pick_all("fleet", src["fleet"]),
            "counts": pick("fleetCounts", src["counts"]),
            "signals": pick_all("signal", src["signals"]),
            "activity": pick_all("activity", activity),
        }},
        "network": {"generatedAt": src["network_at"], "data": {
            "vitals": pick_all("vitals", src["vitals"]),
            "gate": pick("gate", src["gate"]) if src["gate"] else None,
            "crossings": pick_all("crossing", src["crossings"]),
            "emission": pick_all("emission", src["emission"]),
            "emissionSince": src["emission_since"],
            "params": pick_all("param", src["params"]),
        }},
        "upgrades": {"generatedAt": src["now"], "data": {
            "events": pick_all("upgrade", src["upgrades"]),
            "releases": pick_all("release", src["releases"]),
            "job": pick("upgradeJob", src["job"]),
        }},
    }


def find_leaks(text: str) -> List[str]:
    """Anything in `text` shaped like a secret, a private address, an
    internal host detail, a dropped or rent-bounding field, or an em dash.
    The same rules as the web fixture test (sitedata/scrub.json)."""
    found = ["%s: %s" % (kind, m.group(0))
             for kind, rule in _RULES for m in rule.finditer(text)]
    found += ["address: %s" % m.group(0) for m in _SS58.finditer(text)
              if m.group(0) not in PUBLIC_ADDRESSES]
    return found


def board_text(board: Dict[str, Any]) -> str:
    """The text the scrub reads: the board as JSON, non-ASCII kept as is."""
    return json.dumps(board, ensure_ascii=False, sort_keys=True)


def scrub(built: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """Leaks per board. A board with any leak must not be published."""
    leaks = {name: find_leaks(board_text(board)) for name, board in built.items()}
    return {name: found for name, found in leaks.items() if found}


def main(argv: List[str]) -> int:
    if argv[1:] == ["compose"]:
        os.chdir(ROOT)
        sys.path.insert(0, HERE)
        import compose
        print(json.dumps(boards(compose.raw())))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
