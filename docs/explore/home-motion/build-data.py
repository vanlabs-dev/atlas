#!/usr/bin/env python3
"""Write data.js for the home-motion comps from the scrubbed web fixtures.

Only allowlisted, operator-free fields leave the fixtures. Run from the repo root:
python3 docs/explore/home-motion/build-data.py
"""
import json
from pathlib import Path

FIX = Path("web/src/data/fixtures")
OUT = Path(__file__).with_name("data.js")


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


fleet, mining, network, upgrades = (load(n) for n in ("fleet", "mining", "network", "upgrades"))
rows = {r["netuid"]: r for r in fleet["data"]["rows"]}
daily = {a["netuid"]: a["daily"] for a in fleet["data"]["activity"]}
names = {m["netuid"]: m["name"] for m in mining["data"]}

slots = []
for netuid in range(1, 129):
    r = rows.get(netuid, {})
    slots.append({
        "n": netuid,
        "name": r.get("name") or names.get(netuid),
        "tier": r.get("tier"),
        "why": r.get("why"),
        "score": r.get("score"),
        "m30": r.get("momentum30d"),
        "cold": r.get("cold"),
        "c7": r.get("commits7"),
        "a30": r.get("authors30"),
        "dsc": r.get("daysSinceCommit"),
        "m7": r.get("momentum7d"),
        "opaque": r.get("emissionOpaque"),
        "daily": daily.get(netuid),
    })

seen = [e for e in network["data"]["params"] + upgrades["data"]["events"] if e.get("block")]
anchor = max(seen, key=lambda e: e["observedAt"])
vitals = network["data"]["vitals"][-1]
specs = upgrades["data"]["events"]

data = {
    "generatedAt": fleet["generatedAt"],
    "anchor": {"block": anchor["block"], "at": anchor["observedAt"]},
    "counts": fleet["data"]["counts"],
    "scored": len(fleet["data"]["rows"]),
    "slots": slots,
    "facts": {
        "cpu": sum(1 for m in mining["data"] if m.get("verdict") == "possible"),
        "miningTotal": len(mining["data"]),
        "subnetsSharePct": vitals["subnetsSharePct"],
        "vitalDays": len(network["data"]["vitals"]),
        "specs": len(specs),
        "latestSpec": specs[-1]["newSpec"],
        "latestSpecAt": specs[-1]["observedAt"][:10],
    },
    "specs": [{"spec": e["newSpec"], "at": e["observedAt"][:10]} for e in specs[-8:]],
}
OUT.write_text("window.ATLAS = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
