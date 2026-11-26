"""A fixed YAML subset for the claims ledger and the GROUNDING.md front
matter (change: chain-grounding). Atlas uses the standard library only, so
there is no YAML package.

The emitter writes block mappings and block sequences, two spaces per
level. Every string is a double-quoted JSON string (valid YAML), so a
statement can hold any character. Scalars are null, true, false, integers
and strings. An empty list is `[]` and an empty mapping is `{}`.

The parser reads exactly what the emitter writes, plus `#` comment lines
and blank lines. Anything else raises ValueError: the ledger is generated,
so an unexpected shape is a fault, never a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Tuple

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INT_RE = re.compile(r"^-?\d+$")


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError("unsupported scalar %r" % (value,))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, str))


def _emit(value: Any, indent: int, out: List[str]) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _KEY_RE.match(key):
                raise ValueError("unsupported key %r" % (key,))
            if _is_scalar(item):
                out.append("%s%s: %s" % (pad, key, _scalar(item)))
            elif isinstance(item, (list, dict)) and not item:
                out.append("%s%s: %s" % (pad, key,
                                         "[]" if isinstance(item, list)
                                         else "{}"))
            else:
                out.append("%s%s:" % (pad, key))
                _emit(item, indent + 2, out)
        return
    if isinstance(value, list):
        for item in value:
            if _is_scalar(item):
                out.append("%s- %s" % (pad, _scalar(item)))
            elif isinstance(item, dict) and item:
                inner: List[str] = []
                _emit(item, indent + 2, inner)
                out.append("%s- %s" % (pad, inner[0][indent + 2:]))
                out.extend(inner[1:])
            else:
                raise ValueError("unsupported list item %r" % (item,))
        return
    raise ValueError("unsupported value %r" % (value,))


def dump(value: dict, header: str = "") -> str:
    """The YAML text of a mapping, ending in a newline."""
    if not isinstance(value, dict):
        raise ValueError("the top level must be a mapping")
    out: List[str] = ["# " + line if line else "#"
                      for line in header.splitlines()]
    _emit(value, 0, out)
    return "\n".join(out) + "\n"


def _parse_scalar(text: str, where: int) -> Any:
    if text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if _INT_RE.match(text):
        return int(text)
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise ValueError("line %d: bad string: %s" % (where, exc))
        if isinstance(value, str):
            return value
    raise ValueError("line %d: unsupported scalar %r" % (where, text))


def _split_key(text: str, where: int) -> Tuple[str, str]:
    key, sep, rest = text.partition(":")
    if not sep or not _KEY_RE.match(key):
        raise ValueError("line %d: expected `key:`, got %r" % (where, text))
    if rest and not rest.startswith(" "):
        raise ValueError("line %d: no space after `%s:`" % (where, key))
    return key, rest.strip()


def load(text: str) -> dict:
    """Parse emitter output back into Python values."""
    lines: List[Tuple[int, int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError("line %d: tab indentation" % number)
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ValueError("line %d: odd indentation" % number)
        lines.append((number, indent, raw.rstrip()[indent:]))
    pos = [0]

    def block(indent: int) -> Any:
        if pos[0] >= len(lines):
            raise ValueError("unexpected end of document")
        if lines[pos[0]][2].startswith("- ") or lines[pos[0]][2] == "-":
            return sequence(indent)
        return mapping(indent)

    def mapping(indent: int, first: str = "", where: int = 0) -> dict:
        result: dict = {}
        if first:
            entry(result, first, where, indent)
        while pos[0] < len(lines):
            number, level, body = lines[pos[0]]
            if level < indent:
                break
            if level > indent:
                raise ValueError("line %d: unexpected indentation" % number)
            if body.startswith("- "):
                break
            pos[0] += 1
            entry(result, body, number, indent)
        return result

    def entry(result: dict, body: str, number: int, indent: int) -> None:
        key, rest = _split_key(body, number)
        if key in result:
            raise ValueError("line %d: duplicate key %s" % (number, key))
        if rest:
            result[key] = _parse_scalar(rest, number)
            return
        if pos[0] >= len(lines) or lines[pos[0]][1] <= indent:
            raise ValueError("line %d: `%s:` has no value" % (number, key))
        result[key] = block(lines[pos[0]][1])

    def sequence(indent: int) -> list:
        result: list = []
        while pos[0] < len(lines):
            number, level, body = lines[pos[0]]
            if level < indent:
                break
            if level > indent or not body.startswith("- "):
                if level == indent and not body.startswith("- "):
                    break
                raise ValueError("line %d: unexpected indentation" % number)
            pos[0] += 1
            item = body[2:]
            if item.startswith('"') or ":" not in item:
                result.append(_parse_scalar(item, number))
            else:
                result.append(mapping(indent + 2, item, number))
        return result

    if not lines:
        return {}
    value = mapping(0)
    if pos[0] != len(lines):
        raise ValueError("line %d: unexpected content" % lines[pos[0]][0])
    return value
