// One-off fixture export from the live Atlas stores on the Pi.
//
//   node scripts/export-fixtures.ts [ssh-target]
//
// Read-only: the remote program opens every SQLite store with mode=ro, so
// any write fails, and it only prints JSON to stdout. No file is copied.
// Records are built here from the field allowlist, rounded, and cut off
// AGE_DAYS before now. Run `npm test` before committing the output.

import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { pick, type Kind } from "./allowlist.ts";

const TARGET = process.argv[2] ?? "pi@192.168.0.150";
const KEY = join(process.env.HOME ?? "", ".ssh/id_ed25519_pi5");
const AGE_DAYS = 7;
const DAYS = 90;
const OUT = join(import.meta.dirname, "../src/data/fixtures");

const REMOTE = String.raw`
import datetime, json, os, sqlite3, sys
sys.path.insert(0, "fleet")
import atlas_fleet as fleet, atlas_fleet_dashboard as dash
import atlas_fleet_metrics as metrics

AGE_DAYS = ${AGE_DAYS}
DAYS = ${DAYS}
cutoff = (datetime.datetime.now(datetime.timezone.utc)
          - datetime.timedelta(days=AGE_DAYS)).isoformat()

def ro(path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.row_factory = sqlite3.Row
    return c

def rows(c, sql, *args):
    return [dict(r) for r in c.execute(sql, args)]

cfg = fleet.load_config(fleet.CONFIG_FILE)
f = ro(cfg["db"])
live = ro("var/livedata/livedata.db")

ts = f.execute("SELECT max(ts) FROM mine_econ WHERE ts <= ?", (cutoff,)).fetchone()[0]
econ = rows(f, "SELECT * FROM mine_econ WHERE ts = ?", ts)
feas = {r["netuid"]: r for r in rows(f,
    "SELECT netuid, verdict, gpu_floor, vram_gb FROM mine_feasibility "
    "WHERE scanned_at <= ?", cutoff)}
names = {r["netuid"]: r["subnet_name"] for r in econ}
mining = [dict(r, **{k: v for k, v in feas.get(r["netuid"], {}).items()
                     if k != "netuid"}) for r in econ]

board = dash.build_board(f, cfg)
fleet_rows = []
for tier in ("head", "mid", "quiet"):
    for item in board[tier]:
        row = dict(item["row"])
        row.update({k: v for k, v in item["sc"].items()
                    if not isinstance(v, (dict, list))})
        row.update(tier=tier, name=names.get(row["netuid"]),
                   cold=bool(row.get("cold")),
                   emission_opaque=bool(row.get("emission_opaque")))
        fleet_rows.append(row)
# Daily commits for 90 days per subnet, from the same git log the activity
# metric reads, binned back from that subnet's latest activity pass. The sums
# of the last 7 and 30 bins then match the board's c7 and c30.
clone_root = cfg.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
passes = dict(f.execute("SELECT netuid, MAX(pass_ts) FROM metric_activity "
                        "GROUP BY netuid").fetchall())
activity = []
for nid in range(1, 129):
    daily = None
    if nid in passes:
        code, out, _ = fleet._run_git(os.path.join(clone_root, str(nid)),
                                      ["log", "--no-merges", "--format=%cI"])
        if code == 0:
            anchor = metrics._parse_iso(passes[nid])
            daily = [0] * DAYS
            for line in out.split():
                age = (anchor - metrics._parse_iso(line)).total_seconds() / 86400
                if 0 <= age < DAYS:
                    daily[DAYS - 1 - int(age)] += 1
    activity.append({"netuid": nid, "daily": daily})

signals = rows(f, "SELECT class, tier, netuid, created_at FROM signal_events "
               "WHERE created_at <= ? ORDER BY id DESC LIMIT 40", cutoff)

vitals = rows(live, "SELECT * FROM network_vitals WHERE date <= ? ORDER BY date",
              cutoff[:10])
gate = rows(live, "SELECT * FROM gate_state WHERE observed_at <= ? "
            "ORDER BY id DESC LIMIT 1", cutoff)
for g in gate:
    g["gate_active"] = bool(g["gate_active"])
rotations = rows(live, "SELECT * FROM rotation_events WHERE observed_at <= ? "
                 "ORDER BY id DESC LIMIT 30", cutoff)
params = rows(live, "SELECT * FROM chain_param_events WHERE observed_at <= ? "
              "ORDER BY id DESC LIMIT 30", cutoff)
upgrades = rows(live, "SELECT * FROM spec_upgrades WHERE observed_at <= ? "
                "ORDER BY id", cutoff)
with open("var/upgrade/state.json") as handle:
    job = json.load(handle)

print(json.dumps({
    "cutoff": cutoff, "mining_at": ts, "fleet_at": board["generated_at"],
    "mining": mining, "fleet": fleet_rows, "counts": board["counts"], "activity": activity,
    "signals": signals, "vitals": vitals, "gate": gate[0] if gate else None,
    "rotations": rotations, "params": params, "upgrades": upgrades, "job": job,
}))
`;

type Source = Record<string, unknown>;

const raw = execFileSync(
  "ssh",
  ["-i", KEY, "-o", "BatchMode=yes", TARGET, "cd ~/atlas && python3 -"],
  { input: REMOTE, maxBuffer: 64 * 1024 * 1024, encoding: "utf8" },
);
const src = JSON.parse(raw);
const all = (kind: Kind, list: Source[]) => list.map((r) => pick(kind, r));
const board = (generatedAt: string, data: unknown) => ({ generatedAt, data });

const fixtures = {
  mining: board(src.mining_at, all("mining", src.mining)),
  fleet: board(src.fleet_at, {
    rows: all("fleet", src.fleet),
    counts: pick("fleetCounts", src.counts),
    signals: all("signal", src.signals),
    activity: all("activity", src.activity),
  }),
  network: board(src.cutoff, {
    vitals: all("vitals", src.vitals),
    gate: src.gate ? pick("gate", src.gate) : null,
    rotations: all("rotation", src.rotations),
    params: all("param", src.params),
  }),
  upgrades: board(src.cutoff, {
    events: all("upgrade", src.upgrades),
    job: pick("upgradeJob", src.job),
  }),
};

// Day series stay on one line each; everything else is indented as usual.
const flat = (text: string) => text.replace(/\[\s+([\d,\s]+?)\s+\]/g, (_, xs: string) => `[${xs.split(/,\s*/).join(", ")}]`);

for (const [name, value] of Object.entries(fixtures)) {
  writeFileSync(join(OUT, `${name}.json`), flat(JSON.stringify(value, null, 2)) + "\n");
  console.log(`wrote fixtures/${name}.json`);
}
