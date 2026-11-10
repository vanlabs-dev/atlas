"""Public subnt.dev boards from the Atlas stores (change: supabase-data-layer).

    python3 sitedata/atlas_sitedata.py compose   # print the four boards
    python3 sitedata/atlas_sitedata.py publish   # upload changed boards

`publish` reads SUPABASE_URL and SUPABASE_SECRET_KEY from ~/.hermes/.env
(or the process environment), uploads each board that passes the scrub
and differs from the stored copy, and exits non-zero on any failure, so
the unit's OnFailure alert fires. It never deletes or blanks a board.

Each record is built from the shared field allowlist alone
(sitedata/allowlist.json), so a field the stores add later cannot reach the
site. Numbers are rounded to four significant digits, the way JavaScript's
toPrecision(4) rounds, so the boards match the fixture export exactly.
"""

import datetime
import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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


# -- publish ---------------------------------------------------------------

ENV_FILE = os.path.expanduser("~/.hermes/.env")
TABLE = "boards"
HTTP_TIMEOUT = 30

# (method, url, headers, body) -> (status, response body)
Transport = Callable[[str, str, Dict[str, str], Optional[bytes]],
                     Tuple[int, bytes]]


class PublishError(Exception):
    """A publish step failed. The message never holds the secret key."""


def read_env_file(path: str) -> Dict[str, str]:
    """KEY=VALUE lines; blank lines, comments and `export ` prefixes ok."""
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def credentials(env_file: str = ENV_FILE,
                environ: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """(url, secret key) from the env file, else the process environment."""
    found = read_env_file(env_file)
    environ = os.environ if environ is None else environ
    url = (found.get("SUPABASE_URL") or environ.get("SUPABASE_URL") or "").strip()
    key = (found.get("SUPABASE_SECRET_KEY")
           or environ.get("SUPABASE_SECRET_KEY") or "").strip()
    if not url or not key:
        raise PublishError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set "
                           "in %s or the environment" % env_file)
    return url.rstrip("/"), key


def content_hash(data: Any) -> str:
    """SHA-256 over the canonical JSON of a board's data."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _same_time(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return (datetime.datetime.fromisoformat(a)
                == datetime.datetime.fromisoformat(b))
    except ValueError:
        return a == b


def urllib_transport(method: str, url: str, headers: Dict[str, str],
                     body: Optional[bytes]) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method,
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def publish(built: Dict[str, Dict[str, Any]], url: str, key: str,
            transport: Transport = urllib_transport,
            now: Optional[str] = None) -> Dict[str, str]:
    """Upload each board that differs from the stored copy.

    Returns name -> "uploaded" or "unchanged". Raises PublishError on any
    HTTP failure; a board already stored is then left as it was."""
    headers = {"apikey": key, "Accept": "application/json"}

    def call(method: str, path: str, body: Optional[bytes] = None,
             extra: Optional[Dict[str, str]] = None) -> bytes:
        merged = dict(headers, **(extra or {}))
        try:
            status, payload = transport(method, url + path, merged, body)
        except (urllib.error.URLError, OSError) as exc:
            raise PublishError(redact("%s %s failed: %s" % (method, path, exc),
                                      key)) from None
        if not 200 <= status < 300:
            raise PublishError(redact("%s %s returned HTTP %d: %s" % (
                method, path, status,
                payload[:300].decode("utf-8", "replace")), key))
        return payload

    stored = {row["name"]: row for row in json.loads(call(
        "GET", "/rest/v1/%s?select=name,content_hash,generated_at" % TABLE)
        or b"[]")}
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat()
    result: Dict[str, str] = {}
    upload = []
    for name, board in built.items():
        if not board.get("generatedAt"):
            raise PublishError("%s board has no generated time" % name)
        digest = content_hash(board["data"])
        old = stored.get(name)
        if old and old.get("content_hash") == digest and _same_time(
                old.get("generated_at"), board["generatedAt"]):
            result[name] = "unchanged"
            continue
        upload.append({"name": name, "generated_at": board["generatedAt"],
                       "data": board["data"], "content_hash": digest,
                       "published_at": now})
        result[name] = "uploaded"
    if upload:
        call("POST", "/rest/v1/%s?on_conflict=name" % TABLE,
             json.dumps(upload, ensure_ascii=False).encode("utf-8"),
             {"Content-Type": "application/json",
              "Prefer": "resolution=merge-duplicates,return=minimal"})
    return result


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def run_publish(env_file: str = ENV_FILE,
                compose_raw: Optional[Callable[[], Dict[str, Any]]] = None,
                transport: Transport = urllib_transport) -> int:
    """The `publish` command. 0 when every board is stored and current."""
    try:
        url, key = credentials(env_file)
    except PublishError as exc:
        print("publish: %s" % exc, file=sys.stderr)
        return 1
    if compose_raw is None:
        os.chdir(ROOT)
        sys.path.insert(0, HERE)
        import compose
        compose_raw = compose.raw
    built = boards(compose_raw())
    leaks = scrub(built)
    for name, found in sorted(leaks.items()):
        # Name the rule kinds only: the matched text may be the leak itself.
        kinds = sorted({f.split(":", 1)[0] for f in found})
        print("publish: %s board failed the scrub (%s); not uploaded"
              % (name, ", ".join(kinds)), file=sys.stderr)
    clean = {name: board for name, board in built.items() if name not in leaks}
    try:
        result = publish(clean, url, key, transport)
    except PublishError as exc:
        print("publish: %s" % redact(str(exc), key), file=sys.stderr)
        return 1
    for name in BOARDS:
        if name in result:
            print("%s: %s (data from %s)" % (name, result[name],
                                              built[name]["generatedAt"]))
    return 1 if leaks else 0


def main(argv: List[str]) -> int:
    if argv[1:] == ["compose"]:
        os.chdir(ROOT)
        sys.path.insert(0, HERE)
        import compose
        print(json.dumps(boards(compose.raw())))
        return 0
    if argv[1:] == ["publish"]:
        return run_publish()
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
