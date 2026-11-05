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
import datetime, json, re, sqlite3, sys
sys.path.insert(0, "fleet")
sys.path.insert(0, "telegram")
import atlas_fleet as fleet, atlas_fleet_dashboard as dash
import atlas_fleet_metrics as metrics, atlas_fleet_mining as mining
import atlas_telegram as tg

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
crossings = rows(live, "SELECT * FROM gate_events ORDER BY id DESC LIMIT 12")

# Emission share per subnet: the latest panel pass against the last pass at
# least 30 days before it. Panel rows are hourly; one pass shares a timestamp.
emission_now = live.execute("SELECT max(observed_at) FROM panel_snapshot").fetchone()[0]
emission_since = None
emission = []
if emission_now:
    target = (datetime.datetime.fromisoformat(emission_now) - datetime.timedelta(days=30)).isoformat()
    panel_passes = [r[0] for r in live.execute("SELECT DISTINCT observed_at FROM panel_snapshot")]
    emission_since = max((p for p in panel_passes if p <= target), default=None)
    then = {r["netuid"]: r["emission_percent"] for r in rows(
        live, "SELECT netuid, emission_percent FROM panel_snapshot WHERE observed_at = ?",
        emission_since)} if emission_since else {}
    emission = [{"netuid": r["netuid"], "emission_pct": r["emission_percent"],
                 "emission_pct_then": then.get(r["netuid"])}
                for r in rows(live, "SELECT netuid, emission_percent FROM panel_snapshot "
                              "WHERE observed_at = ? ORDER BY netuid", emission_now)]
params = rows(live, "SELECT * FROM chain_param_events ORDER BY id DESC LIMIT 30")
upgrades = rows(live, "SELECT * FROM spec_upgrades ORDER BY id")

# Releases: what each chain upgrade shipped, from the subtensor repo ranges.
# A range that bumps the spec ships in the first chain upgrade at or past
# that spec. A range at an unchanged spec landed after that spec's release,
# so it ships in the first chain upgrade after it was read. Ranges no chain
# upgrade covers yet are merged and waiting. Files are counted once per
# release, grouped into the areas the site's heat map shows.
AREAS = {
    "runtime": "runtime", "pallets": "pallets",
    "precompiles": "evm", "chain-extensions": "evm", "ink-contract": "evm",
    "node": "node", "primitives": "node", "common": "node", "support": "node",
    "chainspecs": "node", "sdk": "sdk", "docs": "docs", "website": "docs",
}
AREA_COLS = ("runtime", "pallets", "evm", "node", "sdk", "docs", "tooling")
RELEASE_TITLE = re.compile(r"^(?:release|v)[ -]?\d+\s*[-:–—]\s*(.+)$", re.I)
NOISE = re.compile(r"^(?:(?:spec )?bump\b|release[ -]?\d+$|v?\d+ release\b|publish runtime)|\bCI\b|\bclippy\b", re.I)
PR_REF = re.compile(r"\s*\(#\d+\)$")

def headlines(commits):
    subjects = [PR_REF.sub("", s) for s in tg._filter_commits(commits)]
    titles = [m.group(1) for m in (RELEASE_TITLE.match(s) for s in subjects) if m]
    rest = [t for t in (tg._tidy_subject(s) for s in subjects if not RELEASE_TITLE.match(s))
            if not NOISE.search(t)]
    return (titles + rest)[:3]

repo = ro("var/repotrack/repotrack.db")
chain = sorted(upgrades, key=lambda u: u["observed_at"])
groups = {}
for r in rows(repo, "SELECT retrieved_at, prev_spec, new_spec, commits_json, "
                    "files_json FROM change_ranges ORDER BY id"):
    if r["new_spec"] is None:
        continue
    bump = r["prev_spec"] is not None and r["prev_spec"] != r["new_spec"]
    target = next((u for u in chain if u["new_spec"] >= r["new_spec"]
                   and (bump or u["observed_at"] > r["retrieved_at"])), None)
    groups.setdefault(target["new_spec"] if target else None, []).append((r, bump))

releases = []
for shipped, ranges in groups.items():
    paths, adds, dels, commits, partial, bumps = {}, 0, 0, [], False, []
    for r, bump in ranges:
        cj, fj = json.loads(r["commits_json"]), json.loads(r["files_json"])
        partial = partial or bool(cj["truncated"] or fj["truncated"])
        commits += cj["commits"]
        for e in fj["files"]:
            paths[e["path"]] = True
            adds += e.get("additions") or 0
            dels += e.get("deletions") or 0
        if bump:
            bumps.append(r["new_spec"])
    spec = shipped if shipped is not None else max(r["new_spec"] for r, _ in ranges)
    area = dict.fromkeys(AREA_COLS, 0)
    for p in paths:
        area[AREAS.get(p.split("/", 1)[0] if "/" in p else "", "tooling")] += 1
    heads = headlines(commits) + [None, None, None]
    rel = {"spec": spec, "pending": shipped is None, "since": ranges[0][0]["retrieved_at"],
           "bundled": ", ".join(str(b) for b in sorted(set(bumps)) if b < spec) or None,
           "commits": len(commits), "files": len(paths), "adds": adds, "dels": dels,
           "partial": partial, "headline": heads[0], "headline2": heads[1],
           "headline3": heads[2]}
    rel.update({"files_" + c: n for c, n in area.items()})
    releases.append(rel)
releases.sort(key=lambda x: x["spec"])
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
    "gate": gate[0] if gate else None, "crossings": crossings,
    "emission": emission, "emission_since": emission_since,
    "params": params, "upgrades": upgrades, "releases": releases, "job": job,
}))
`;
