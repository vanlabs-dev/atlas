// The program the fixture export runs on the Pi, over ssh, from ~/atlas.
//
// Read-only: every SQLite store opens with mode=ro, git only reads logs,
// and the program only prints JSON. It reads the latest stored pass of each
// input (change: subnt-site-honesty): no age cutoff, so a newer
// feasibility scan is never erased and the mining model is the live one.
// Records are built and rounded on this side, from the field allowlist.

/** Signal classes the site names; anything else stays on the Pi. */
export const SIGNAL_CLASSES = ["econ-code", "narrative-cluster", "signal-digest"];

export const DAYS = 90;

export const REMOTE = String.raw`
import datetime, json, sqlite3, sys
sys.path.insert(0, "fleet")
import atlas_fleet as fleet, atlas_fleet_dashboard as dash
import atlas_fleet_metrics as metrics, atlas_fleet_mining as mining

DAYS = ${DAYS}
SIGNAL_CLASSES = ${JSON.stringify(SIGNAL_CLASSES)}
now = datetime.datetime.now(datetime.timezone.utc).isoformat()

def ro(path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.row_factory = sqlite3.Row
    return c

def rows(c, sql, *args):
    return [dict(r) for r in c.execute(sql, args)]

cfg = fleet.load_config(fleet.CONFIG_FILE)
f = ro(cfg["db"])
live = ro("var/livedata/livedata.db")

# Mining: the latest stored pass and the scans that are current for it.
ts = f.execute("SELECT max(ts) FROM mine_econ").fetchone()[0]
econ = rows(f, "SELECT * FROM mine_econ WHERE ts = ?", ts)
feas = mining.latest_feasibility(f)
names = {r["netuid"]: r["subnet_name"] for r in econ}
for r in econ:
    feature = feas.get(r["netuid"])
    r["verdict"] = feature["verdict"] if feature else None
    possible = r["verdict"] == "possible"
    # A template "0 GB VRAM" floor on a no-GPU-code scan is not a figure.
    r["gpu_floor"] = None if (possible or not feature) else feature["gpu_floor"]
    r["vram_gb"] = None if (possible or not feature) else feature["vram_gb"]
    r["gpu_mention_files"] = mining.gpu_mention_files(feature) if possible else None

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

# Commit ages per subnet, from the reader and bot patterns the activity
# metric uses, measured from that subnet's latest activity pass. Commits
# dated after the pass were not in the pass, so they are left out. The
# site bins the ages with the metric's window rule. The commits are the
# ones behind the board's figures: with activity.multi_repo "on", that
# includes the organisation repositories the pass counted.
mcfg = metrics.metrics_cfg(cfg)
bots = metrics.compile_bot_patterns(mcfg.get("bot_author_patterns") or [])
passes = dict(f.execute("SELECT netuid, MAX(pass_ts) FROM metric_activity "
                        "GROUP BY netuid").fetchall())
activity = []
for nid in range(1, 129):
    ages = None
    if nid in passes:
        try:
            log = metrics.activity_commit_log(f, cfg, nid, passes[nid],
                                              fleet._run_git)
        except RuntimeError:
            log = None
        if log is not None:
            anchor = metrics._parse_iso(passes[nid])
            ages = []
            for when, email in log:
                if metrics.is_bot_author(email, bots) or when > anchor:
                    continue
                age = (anchor - when).total_seconds() / 86400.0
                if age <= DAYS:
                    ages.append(round(age, 6))
    activity.append({"netuid": nid, "ages": ages})

marks = ",".join("?" * len(SIGNAL_CLASSES))
signals = rows(f, "SELECT class, tier, netuid, created_at FROM signal_events "
               "WHERE class IN (%s) AND tier != 'shadow' "
               "ORDER BY id DESC LIMIT 40" % marks, *SIGNAL_CLASSES)

vitals = rows(live, "SELECT * FROM network_vitals ORDER BY date")
gate = rows(live, "SELECT * FROM gate_state ORDER BY id DESC LIMIT 1")
for g in gate:
    g["gate_active"] = bool(g["gate_active"])
rotations = rows(live, "SELECT * FROM rotation_events ORDER BY id DESC LIMIT 30")
params = rows(live, "SELECT * FROM chain_param_events ORDER BY id DESC LIMIT 30")
upgrades = rows(live, "SELECT * FROM spec_upgrades ORDER BY id")
with open("var/upgrade/state.json") as handle:
    job = json.load(handle)

# The board is composed now, but its activity comes from the last pass:
# stamp it with that pass, so its age is never understated.
fleet_at = max(passes.values()) if passes else board["generated_at"]

print(json.dumps({
    "now": now, "mining_at": ts, "fleet_at": fleet_at,
    "network_at": gate[0]["observed_at"] if gate else now,
    "mining": econ, "fleet": fleet_rows, "counts": board["counts"],
    "activity": activity, "signals": signals, "vitals": vitals,
    "gate": gate[0] if gate else None, "rotations": rotations,
    "params": params, "upgrades": upgrades, "job": job,
}))
`;
