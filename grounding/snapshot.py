"""Deterministic chain snapshots for the grounding job (change:
chain-grounding). No model.

A snapshot reads, at ONE finalized block:

- the runtime metadata: the extrinsics and the storage items (with their
  defaults) of each configured pallet;
- every plain SubtensorModule value except running state
  (`chain_exclude` in config.json);
- the configured per-subnet maps for every registered subnet.

It writes `snapshots/<spec>/{meta,pallets,chain,subnets}.json` and
`DIFF.md` against the previous snapshot. Values are decoded from the
metadata's own type registry; a type the decoder does not know is kept as
hex. Any RPC or decode failure raises SnapshotError: no partial snapshot is
written.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "livedata"))

import atlas_live as al  # noqa: E402
import scale_meta as sm  # noqa: E402

Rpc = Callable[[str, List[Any]], Dict[str, Any]]
QUERY_CHUNK = 100
FIXED_PATHS = ("FixedU128", "FixedI128", "FixedU64", "FixedI64",
               "FixedU32", "FixedI32")
FILES = ("meta.json", "pallets.json", "chain.json", "subnets.json")


class SnapshotError(Exception):
    """A read or decode failed; nothing is written."""


# -- SCALE values -----------------------------------------------------------

def _compact(data: bytes, pos: int) -> Tuple[int, int]:
    first = data[pos]
    mode = first & 3
    if mode == 0:
        return first >> 2, pos + 1
    if mode == 1:
        return int.from_bytes(data[pos:pos + 2], "little") >> 2, pos + 2
    if mode == 2:
        return int.from_bytes(data[pos:pos + 4], "little") >> 2, pos + 4
    size = (first >> 2) + 4
    return int.from_bytes(data[pos + 1:pos + 1 + size], "little"), \
        pos + 1 + size


_INT_SIZES = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "u128": 16, "u256": 32,
              "i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16, "i256": 32}


def _decode(types: Dict[int, Dict[str, Any]], tid: int, data: bytes,
            pos: int, depth: int = 0) -> Tuple[Any, int]:
    if depth > 40:
        raise ValueError("type %d nests too deeply" % tid)
    entry = types[tid]
    definition = entry["def"]
    kind = definition["kind"]
    path = entry["path"]
    if kind == "primitive":
        name = definition["name"]
        if name == "bool":
            if data[pos] not in (0, 1):
                raise ValueError("bad bool byte")
            return data[pos] == 1, pos + 1
        if name in _INT_SIZES:
            size = _INT_SIZES[name]
            if pos + size > len(data):
                raise ValueError("value truncated")
            return int.from_bytes(data[pos:pos + size], "little",
                                  signed=name.startswith("i")), pos + size
        if name in ("str", "char"):
            length, pos = _compact(data, pos)
            return data[pos:pos + length].decode("utf-8", "replace"), \
                pos + length
        raise ValueError("primitive %s" % name)
    if kind == "compact":
        return _compact(data, pos)
    if kind == "composite":
        fields = definition["fields"]
        if path and path[-1] in FIXED_PATHS and len(fields) == 1:
            bits, pos = _decode(types, fields[0]["ty"], data, pos, depth + 1)
            frac = sm._typenum(types, [ty for _, ty in entry["params"]][0])
            return format(bits / float(2 ** frac), ".12g"), pos
        values = []
        for field in fields:
            value, pos = _decode(types, field["ty"], data, pos, depth + 1)
            values.append((field["name"], value))
        if len(values) == 1:
            return values[0][1], pos
        if values and all(name for name, _ in values):
            return {name: value for name, value in values}, pos
        return [value for _, value in values], pos
    if kind == "variant":
        index = data[pos]
        pos += 1
        for variant in definition["variants"]:
            if variant["index"] == index:
                break
        else:
            raise ValueError("variant index %d" % index)
        if path[-1:] == ["Option"]:
            if not variant["fields"]:
                return None, pos
            return _decode(types, variant["fields"][0]["ty"], data, pos,
                           depth + 1)
        if not variant["fields"]:
            return variant["name"], pos
        inner = []
        for field in variant["fields"]:
            value, pos = _decode(types, field["ty"], data, pos, depth + 1)
            inner.append(value)
        return {variant["name"]: inner[0] if len(inner) == 1 else inner}, pos
    if kind in ("sequence", "array"):
        if kind == "sequence":
            length, pos = _compact(data, pos)
        else:
            length = definition["len"]
        inner = types[definition["ty"]]["def"]
        if inner.get("kind") == "primitive" and inner.get("name") == "u8":
            return "0x" + data[pos:pos + length].hex(), pos + length
        items = []
        for _ in range(length):
            value, pos = _decode(types, definition["ty"], data, pos,
                                 depth + 1)
            items.append(value)
        return items, pos
    if kind == "tuple":
        items = []
        for ty in definition["tys"]:
            value, pos = _decode(types, ty, data, pos, depth + 1)
            items.append(value)
        return items, pos
    raise ValueError("cannot decode a %s" % kind)


def decode_value(types: Dict[int, Dict[str, Any]], tid: int,
                 raw: bytes) -> Any:
    """The plain value of SCALE bytes, or {"hex": ...} when the type is
    not decodable or the bytes do not fit it exactly."""
    try:
        value, end = _decode(types, tid, raw, 0)
    except (ValueError, IndexError, KeyError):
        return {"hex": "0x" + raw.hex()}
    if end != len(raw):
        return {"hex": "0x" + raw.hex()}
    return value


# -- metadata ---------------------------------------------------------------

def pallet_inventory(meta: Dict[str, Any], pallet: str) -> Dict[str, Any]:
    """Extrinsics and storage items (with decoded defaults) of a pallet."""
    types = meta["types"]
    entry = meta["pallets"].get(pallet)
    if entry is None:
        raise SnapshotError("pallet %s is not in the metadata" % pallet)
    storage: Dict[str, Any] = {}
    for name in sorted(entry["storage"]):
        item = entry["storage"][name]
        record: Dict[str, Any] = {
            "kind": "map" if item["hashers"] else "value",
            "value": sm.type_name(types, item["value"]),
            "modifier": item["modifier"]}
        if item["hashers"]:
            record["key"] = sm.type_name(types, item["key"])
            record["hashers"] = list(item["hashers"])
        if item["modifier"] == "default":
            record["default"] = decode_value(types, item["value"],
                                             item["default"])
        storage[name] = record
    return {"calls": sm.pallet_calls(meta, pallet), "storage": storage}


# -- chain reads ------------------------------------------------------------

def prefix(pallet: str, item: str) -> str:
    """Storage prefix of any item. The livedata `storage_prefix` refuses
    items outside CHAIN_READS on purpose: those are values Atlas serves.
    A snapshot reads every item the metadata lists, and decodes it with the
    metadata's own types, so it builds the prefix itself."""
    return "0x" + al.twox128(pallet).hex() + al.twox128(item).hex()


def _ok(rpc: Rpc, method: str, params: List[Any]) -> Any:
    result = rpc(method, params)
    if not result.get("ok"):
        raise SnapshotError("%s failed: %s" % (method, result.get("error")))
    return result.get("result")


def _query(rpc: Rpc, keys: List[str], block_hash: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for start in range(0, len(keys), QUERY_CHUNK):
        chunk = keys[start:start + QUERY_CHUNK]
        result = _ok(rpc, "state_queryStorageAt", [chunk, block_hash])
        for change_set in result or []:
            for key, value in change_set.get("changes") or []:
                values[key] = value
    return values


def take(config: Dict[str, Any], live_config: Dict[str, Any],
         rpc: Optional[Rpc] = None) -> Dict[str, Any]:
    """Read one snapshot. Returns {meta, pallets, chain, subnets}."""
    rpc = rpc or (lambda method, params: al._rpc_call(live_config, method,
                                                      params))
    spec = al.read_live_spec(live_config, rpc)
    if not spec.get("ok"):
        raise SnapshotError("live spec: %s" % spec.get("error"))
    block_hash = spec["block_hash"]
    try:
        meta = sm.decode_metadata(al._payload_bytes(
            _ok(rpc, "state_getMetadata", [block_hash])))
    except ValueError as exc:
        raise SnapshotError("metadata: %s" % exc)
    types = meta["types"]
    pallets = {p: pallet_inventory(meta, p) for p in config["pallets"]}

    # Plain values.
    subtensor = meta["pallets"][al.SUBTENSOR_PALLET]["storage"]
    exclude = set(config["chain_exclude"])
    plain = sorted(name for name, item in subtensor.items()
                   if not item["hashers"] and name not in exclude)
    keys = {name: prefix(al.SUBTENSOR_PALLET, name)
            for name in plain}
    read = _query(rpc, list(keys.values()), block_hash)
    chain: Dict[str, Any] = {}
    for name in plain:
        raw = read.get(keys[name])
        item = subtensor[name]
        if raw is None:
            value = (decode_value(types, item["value"], item["default"])
                     if item["modifier"] == "default" else None)
            chain[name] = {"state": "unset", "value": value}
        else:
            chain[name] = {"state": "explicit", "value": decode_value(
                types, item["value"], al._payload_bytes(raw))}

    # Registered subnets, then the per-subnet maps.
    try:
        _, netuids = al._enumerate_map_keys(
            rpc, prefix(al.SUBTENSOR_PALLET, "NetworksAdded"),
            block_hash)
    except al.FatalLiveError as exc:
        raise SnapshotError("NetworksAdded: %s" % exc)
    if not netuids:
        raise SnapshotError("NetworksAdded enumerated empty")
    subnets: Dict[str, Any] = {"netuids": sorted(netuids), "items": {},
                               "missing": []}
    for pallet, name in config["subnet_items"]:
        item = meta["pallets"].get(pallet, {}).get("storage", {}).get(name)
        if item is None or len(item["hashers"]) != 1:
            subnets["missing"].append("%s.%s" % (pallet, name))
            continue
        try:
            map_keys, owners = al._enumerate_map_keys(
                rpc, prefix(pallet, name), block_hash)
        except al.FatalLiveError as exc:
            raise SnapshotError("%s.%s: %s" % (pallet, name, exc))
        raw_values = _query(rpc, map_keys, block_hash)
        values = {}
        for key, netuid in zip(map_keys, owners):
            raw = raw_values.get(key)
            if raw is not None:
                values[str(netuid)] = decode_value(
                    types, item["value"], al._payload_bytes(raw))
        record = {"values": dict(sorted(values.items(),
                                        key=lambda kv: int(kv[0])))}
        if item["modifier"] == "default":
            record["default"] = decode_value(types, item["value"],
                                             item["default"])
        subnets["items"]["%s.%s" % (pallet, name) if pallet !=
                         al.SUBTENSOR_PALLET else name] = record
    return {
        "meta": {"spec_version": spec["spec_version"],
                 "block_number": spec["block_number"],
                 "block_hash": block_hash,
                 "metadata_version": meta["version"],
                 "taken_at": datetime.datetime.now(
                     datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "pallets": pallets, "chain": chain, "subnets": subnets}


# -- files and diff ---------------------------------------------------------

def _dump(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True,
                      ensure_ascii=False) + "\n"


def write(snapshot: Dict[str, Any], directory: str) -> None:
    os.makedirs(directory, exist_ok=True)
    for name in ("meta", "pallets", "chain", "subnets"):
        with open(os.path.join(directory, name + ".json"), "w",
                  encoding="utf-8") as handle:
            handle.write(_dump(snapshot[name]))


def load(directory: str) -> Dict[str, Any]:
    out = {}
    for name in ("meta", "pallets", "chain", "subnets"):
        with open(os.path.join(directory, name + ".json"), "r",
                  encoding="utf-8") as handle:
            out[name] = json.load(handle)
    return out


def previous_spec(snapshots_dir: str, spec: int) -> Optional[int]:
    """The highest snapshot spec below `spec`, or None."""
    try:
        names = os.listdir(snapshots_dir)
    except FileNotFoundError:
        return None
    specs = [int(n) for n in names if n.isdigit() and int(n) < spec
             and os.path.isfile(os.path.join(snapshots_dir, n, "meta.json"))]
    return max(specs) if specs else None


def _show(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def _args(call: Dict[str, Any]) -> str:
    return "%s(%s)" % (call["name"], ", ".join(
        "%s: %s" % (a, t) for a, t in call["args"]))


def _effective(item: Dict[str, Any], netuid: str) -> Any:
    return item["values"].get(netuid, item.get("default"))


def diff(old: Optional[Dict[str, Any]], new: Dict[str, Any],
         dynamic: List[str]) -> Dict[str, Any]:
    """Structured differences between two snapshots. With no old
    snapshot, only `first` is set."""
    if old is None:
        return {"first": True}
    out: Dict[str, Any] = {"first": False, "calls": {}, "storage": {},
                           "chain": [], "subnet_items": [], "netuids": {}}
    for pallet, inv in new["pallets"].items():
        before = old["pallets"].get(pallet, {"calls": [], "storage": {}})
        old_calls = {c["name"]: c for c in before["calls"]}
        new_calls = {c["name"]: c for c in inv["calls"]}
        out["calls"][pallet] = {
            "added": [_args(new_calls[n]) for n in sorted(new_calls)
                      if n not in old_calls],
            "removed": [n for n in sorted(old_calls) if n not in new_calls],
            "changed": ["%s -> %s" % (_args(old_calls[n]),
                                      _args(new_calls[n]))
                        for n in sorted(new_calls) if n in old_calls
                        and old_calls[n]["args"] != new_calls[n]["args"]]}
        old_st, new_st = before["storage"], inv["storage"]
        changed = []
        for name in sorted(set(old_st) & set(new_st)):
            a, b = old_st[name], new_st[name]
            for field in ("kind", "key", "value", "modifier", "default"):
                if a.get(field) != b.get(field):
                    changed.append("%s %s: %s -> %s" % (
                        name, field, _show(a.get(field)),
                        _show(b.get(field))))
        out["storage"][pallet] = {
            "added": ["%s: %s" % (n, new_st[n]["value"])
                      for n in sorted(new_st) if n not in old_st],
            "removed": [n for n in sorted(old_st) if n not in new_st],
            "changed": changed}
    for name in sorted(set(old["chain"]) | set(new["chain"])):
        a = old["chain"].get(name)
        b = new["chain"].get(name)
        if a != b:
            out["chain"].append("%s: %s -> %s%s" % (
                name, _show(a and a["value"]) if a else "absent",
                _show(b and b["value"]) if b else "absent",
                " (dynamic)" if name in dynamic else ""))
    old_n = set(map(str, old["subnets"]["netuids"]))
    new_n = set(map(str, new["subnets"]["netuids"]))
    out["netuids"] = {"added": sorted(new_n - old_n, key=int),
                      "removed": sorted(old_n - new_n, key=int)}
    both = sorted(old_n & new_n, key=int)
    for name in sorted(new["subnets"]["items"]):
        b = new["subnets"]["items"][name]
        a = old["subnets"]["items"].get(name)
        if a is None:
            out["subnet_items"].append("%s: newly snapshotted" % name)
            continue
        if a.get("default") != b.get("default"):
            out["subnet_items"].append("%s default: %s -> %s" % (
                name, _show(a.get("default")), _show(b.get("default"))))
        moved = [n for n in both if _effective(a, n) != _effective(b, n)]
        if not moved:
            continue
        if name in dynamic:
            out["subnet_items"].append(
                "%s: changed on %d of %d subnets (dynamic)" % (
                    name, len(moved), len(both)))
        else:
            shown = ", ".join("%s: %s -> %s" % (
                n, _show(_effective(a, n)), _show(_effective(b, n)))
                for n in moved[:8])
            more = " (+%d more)" % (len(moved) - 8) if len(moved) > 8 else ""
            out["subnet_items"].append("%s changed on %d subnets: %s%s" % (
                name, len(moved), shown, more))
    return out


def new_items(d: Dict[str, Any]) -> List[str]:
    """Names of extrinsics and storage items the diff found added."""
    if d.get("first"):
        return []
    names = []
    for pallet in d["calls"]:
        names += [a.split("(", 1)[0] for a in d["calls"][pallet]["added"]]
        names += [a.split(":", 1)[0] for a in d["storage"][pallet]["added"]]
    return names


def diff_markdown(d: Dict[str, Any], new_meta: Dict[str, Any],
                  old_meta: Optional[Dict[str, Any]]) -> str:
    head = ["# Snapshot diff: spec %d" % new_meta["spec_version"], "",
            "Generated by `grounding/atlas_grounding.py`. Facts only.", "",
            "- This snapshot: spec %d, block %d, taken %s." % (
                new_meta["spec_version"], new_meta["block_number"],
                new_meta["taken_at"])]
    if d.get("first") or old_meta is None:
        return "\n".join(head + [
            "- Previous snapshot: none. This is the first snapshot, so "
            "there is nothing to compare.", ""])
    head.append("- Previous snapshot: spec %d, block %d, taken %s." % (
        old_meta["spec_version"], old_meta["block_number"],
        old_meta["taken_at"]))
    lines = head + [""]

    def block(title: str, items: List[str]) -> None:
        lines.append("## " + title)
        lines.append("")
        lines.extend(["- `%s`" % i for i in items] or ["- None."])
        lines.append("")

    for pallet in sorted(d["calls"]):
        c, s = d["calls"][pallet], d["storage"][pallet]
        block("%s extrinsics added" % pallet, c["added"])
        block("%s extrinsics removed" % pallet, c["removed"])
        block("%s extrinsic signatures changed" % pallet, c["changed"])
        block("%s storage items added" % pallet, s["added"])
        block("%s storage items removed" % pallet, s["removed"])
        block("%s storage items changed (type or default)" % pallet,
              s["changed"])
    block("Chain-wide values changed", d["chain"])
    block("Subnets registered", d["netuids"]["added"])
    block("Subnets removed", d["netuids"]["removed"])
    block("Per-subnet parameters changed", d["subnet_items"])
    return "\n".join(lines)
