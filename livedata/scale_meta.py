#!/usr/bin/env python3
"""Stdlib SCALE decoder for runtime metadata V14 and V15 (change:
runtime-upgrade-pipeline).

Decodes only what the chain-read probe needs: the type registry and each
pallet's storage entries (name, key hashers, key type, value type). It stops
after the pallet list, so the extrinsic and API sections are never read.
Every malformed input raises ValueError; the probe turns that into a fail,
never a pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

MAGIC = b"meta"
SUPPORTED_VERSIONS = (14, 15)

HASHERS = ("blake2_128", "blake2_256", "blake2_128concat", "twox128",
           "twox256", "twox64concat", "identity")
PRIMITIVES = ("bool", "char", "str", "u8", "u16", "u32", "u64", "u128",
              "u256", "i8", "i16", "i32", "i64", "i128", "i256")


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError("metadata truncated at byte %d" % self.pos)
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def compact(self) -> int:
        first = self.data[self.pos] if self.pos < len(self.data) else None
        if first is None:
            raise ValueError("metadata truncated at byte %d" % self.pos)
        mode = first & 0b11
        if mode == 0:
            return self.u8() >> 2
        if mode == 1:
            return int.from_bytes(self.take(2), "little") >> 2
        if mode == 2:
            return int.from_bytes(self.take(4), "little") >> 2
        width = (self.u8() >> 2) + 4
        return int.from_bytes(self.take(width), "little")

    def text(self) -> str:
        return self.take(self.compact()).decode("utf-8")

    def option(self, read: Any) -> Any:
        flag = self.u8()
        if flag == 0:
            return None
        if flag != 1:
            raise ValueError("bad Option flag %d at byte %d"
                             % (flag, self.pos - 1))
        return read()

    def vec(self, read: Any) -> List[Any]:
        return [read() for _ in range(self.compact())]


def _field(r: _Reader) -> Dict[str, Any]:
    name = r.option(r.text)
    ty = r.compact()
    r.option(r.text)  # type_name
    r.vec(r.text)  # docs
    return {"name": name, "ty": ty}


def _type_def(r: _Reader) -> Dict[str, Any]:
    kind = r.u8()
    if kind == 0:
        return {"kind": "composite", "fields": r.vec(lambda: _field(r))}
    if kind == 1:
        def variant() -> Dict[str, Any]:
            name = r.text()
            fields = r.vec(lambda: _field(r))
            r.u8()  # index
            r.vec(r.text)  # docs
            return {"name": name, "fields": fields}
        return {"kind": "variant", "variants": r.vec(variant)}
    if kind == 2:
        return {"kind": "sequence", "ty": r.compact()}
    if kind == 3:
        length = r.u32()
        return {"kind": "array", "len": length, "ty": r.compact()}
    if kind == 4:
        return {"kind": "tuple", "tys": r.vec(r.compact)}
    if kind == 5:
        index = r.u8()
        if index >= len(PRIMITIVES):
            raise ValueError("unknown primitive %d" % index)
        return {"kind": "primitive", "name": PRIMITIVES[index]}
    if kind == 6:
        return {"kind": "compact", "ty": r.compact()}
    if kind == 7:
        return {"kind": "bitsequence", "store": r.compact(),
                "order": r.compact()}
    raise ValueError("unknown type def %d at byte %d" % (kind, r.pos - 1))


def _registry(r: _Reader) -> Dict[int, Dict[str, Any]]:
    types: Dict[int, Dict[str, Any]] = {}
    for _ in range(r.compact()):
        type_id = r.compact()
        path = r.vec(r.text)
        params = r.vec(lambda: (r.text(), r.option(r.compact)))
        definition = _type_def(r)
        r.vec(r.text)  # docs
        types[type_id] = {"path": path, "params": params, "def": definition}
    return types


def _storage_entry(r: _Reader) -> Dict[str, Any]:
    name = r.text()
    r.u8()  # modifier
    kind = r.u8()
    if kind == 0:
        hashers: List[str] = []
        key: Optional[int] = None
        value = r.compact()
    elif kind == 1:
        codes = r.vec(r.u8)
        for code in codes:
            if code >= len(HASHERS):
                raise ValueError("unknown hasher %d in %s" % (code, name))
        hashers = [HASHERS[code] for code in codes]
        key = r.compact()
        value = r.compact()
    else:
        raise ValueError("unknown storage entry type %d in %s" % (kind, name))
    r.vec(r.u8)  # default bytes
    r.vec(r.text)  # docs
    return {"name": name, "hashers": hashers, "key": key, "value": value}


def _pallet(r: _Reader, version: int) -> Dict[str, Any]:
    name = r.text()
    storage = r.option(lambda: (r.text(), r.vec(lambda: _storage_entry(r))))
    r.option(r.compact)  # calls
    r.option(r.compact)  # event
    r.vec(lambda: (r.text(), r.compact(), r.vec(r.u8), r.vec(r.text)))
    r.option(r.compact)  # error
    r.u8()  # index
    if version >= 15:
        r.vec(r.text)  # docs
    entries = {entry["name"]: entry for entry in (storage[1] if storage
                                                  else [])}
    return {"name": name, "storage": entries}


def decode_metadata(raw: bytes) -> Dict[str, Any]:
    """Decode `state_getMetadata` bytes. Returns {version, types, pallets},
    where pallets maps pallet name to {name, storage: {item: entry}}."""
    r = _Reader(raw)
    if r.take(4) != MAGIC:
        raise ValueError("not runtime metadata: bad magic")
    version = r.u8()
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("metadata V%d is not supported" % version)
    types = _registry(r)
    pallets = {p["name"]: p for p in r.vec(lambda: _pallet(r, version))}
    return {"version": version, "types": types, "pallets": pallets}


def _typenum(types: Dict[int, Dict[str, Any]], type_id: int,
             _depth: int = 0) -> int:
    """Value of a typenum type-level integer (UInt<UInt<UTerm, B1>, B0>
    is 2), so a fixed-point type reads FixedU128<U64>, not a nested chain."""
    if _depth > 256:
        raise ValueError("typenum %d nests too deeply" % type_id)
    entry = types[type_id]
    last = entry["path"][-1]
    if last in ("UTerm", "B0"):
        return 0
    if last == "B1":
        return 1
    if last == "UInt":
        high, bit = [ty for _, ty in entry["params"]]
        return (2 * _typenum(types, high, _depth + 1)
                + _typenum(types, bit, _depth + 1))
    raise ValueError("unknown typenum type %s" % last)


def type_name(types: Dict[int, Dict[str, Any]], type_id: int,
              _depth: int = 0) -> str:
    """Readable, deterministic name of a registry type: the last path
    segment with its resolved generic parameters, or the structural form of
    an unnamed type. Generic parameters are kept because they change the
    encoding: FixedU128<U64> and FixedU128<U32> share a path."""
    if _depth > 32:
        raise ValueError("type %d nests too deeply" % type_id)
    entry = types.get(type_id)
    if entry is None:
        raise ValueError("type %d is not in the registry" % type_id)

    def sub(tid: int) -> str:
        return type_name(types, tid, _depth + 1)

    definition = entry["def"]
    if entry["path"][:1] in (["typenum"], ["substrate_typenum"]):
        return "U%d" % _typenum(types, type_id)
    if entry["path"]:
        base = entry["path"][-1]
        params = [sub(ty) for _, ty in entry["params"] if ty is not None]
        return "%s<%s>" % (base, ", ".join(params)) if params else base
    kind = definition["kind"]
    if kind == "primitive":
        return definition["name"]
    if kind == "sequence":
        return "Vec<%s>" % sub(definition["ty"])
    if kind == "array":
        return "[%s; %d]" % (sub(definition["ty"]), definition["len"])
    if kind == "tuple":
        return "(%s)" % ", ".join(sub(ty) for ty in definition["tys"])
    if kind == "compact":
        return "Compact<%s>" % sub(definition["ty"])
    if kind == "composite" and len(definition["fields"]) == 1:
        return sub(definition["fields"][0]["ty"])
    raise ValueError("type %d is an unnamed %s" % (type_id, kind))
