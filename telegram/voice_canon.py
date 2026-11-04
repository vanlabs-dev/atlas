#!/usr/bin/env python3
"""Read-only check that the device SOUL.md matches the canon in
telegram/docs/voice.md (agent-voice: "Device matches canon").

    python3 telegram/voice_canon.py check [--soul ~/.hermes/SOUL.md]

Prints both sha256 values; exit 0 on a match, 1 on a mismatch, 2 when a
file cannot be read. Never writes anything."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from typing import Optional, List

VOICE_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "docs", "voice.md")
_SOUL_BLOCK = re.compile(
    r"### Canonical `~/\.hermes/SOUL\.md`\n\n```text\n(?P<body>.*?)\n```",
    re.S)


def canonical_soul(voice_md: str = VOICE_MD) -> str:
    """The SOUL.md text as the device holds it (block body plus a final
    newline)."""
    with open(voice_md, "r", encoding="utf-8") as handle:
        match = _SOUL_BLOCK.search(handle.read())
    if not match:
        raise ValueError("no canonical SOUL.md block in %s" % voice_md)
    return match.group("body") + "\n"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="voice_canon")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--soul", default=os.path.expanduser(
        "~/.hermes/SOUL.md"))
    args = parser.parse_args(argv)
    try:
        canon = canonical_soul()
        with open(args.soul, "r", encoding="utf-8") as handle:
            device = handle.read()
    except (OSError, ValueError) as exc:
        print("unreadable: %s" % exc, file=sys.stderr)
        return 2
    print("canon  %s %d B" % (sha256(canon), len(canon.encode("utf-8"))))
    print("device %s %d B" % (sha256(device), len(device.encode("utf-8"))))
    if device == canon:
        print("match")
        return 0
    print("MISMATCH: apply the canon per telegram/docs/voice.md section 6")
    return 1


if __name__ == "__main__":
    sys.exit(main())
