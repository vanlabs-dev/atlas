"""Organisation-wide activity (change: fleet-multi-repo-activity).

Listing and eligibility run against a stubbed HTTP opener; history fetches
run against local file:// remotes. No test reaches the network."""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import _helpers as h
import atlas_fleet as fleet
import atlas_fleet_dashboard as dash
import atlas_fleet_metrics as met
import atlas_fleet_orgrepos as org

NOW = "2026-11-04T00:00:00+00:00"
NOW_DT = datetime.datetime.fromisoformat(NOW)


def _ago(days):
    return (NOW_DT - datetime.timedelta(days=days)).isoformat()


def _git(cwd, *args, env=None):
    full = dict(os.environ)
    full.update(env or {})
    done = subprocess.run(["git", "-C", cwd] + list(args),
                          capture_output=True, text=True, env=full)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit_at(origin, days_ago, email="dev@example.org", name=None):
    """One commit dated `days_ago` before NOW, by `email`."""
    when = _ago(days_ago)
    name = name or "f_%s_%s.txt" % (days_ago, len(os.listdir(origin)))
    h.write_file(origin, name, "%s %s\n" % (when, email))
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.email=%s" % email, "-c", "user.name=Dev",
         "commit", "-q", "-m", "work",
         env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})
    return _git(origin, "rev-parse", "HEAD")


class StubOpener:
    """Records calls; answers from a {path: (status, headers, payload)}."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, url, timeout):
        path = url.replace(org.API_BASE, "")
        self.calls.append(path)
        status, headers, payload = self.answers.get(
            path, (404, {}, None))
        body = json.dumps(payload).encode() if payload is not None else b""
        return status, headers, body


def _slot(conn, netuid, repo, status="active"):
    fleet.upsert_slot(conn, {"netuid": netuid, "github_repo": repo,
                             "epoch": 1, "status": status})
    conn.commit()


def _repo(name, pushed_days=1, fork=False, archived=False):
    return {"name": name, "fork": fork, "archived": archived,
            "pushed_at": _ago(pushed_days), "size": 10}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        met.ensure_schema(self.conn)
        org.ensure_schema(self.conn)
        self.clone_root = os.path.join(self.tmp, "clones")
        self.config = {"db": self.db, "clone_root": self.clone_root,
                       "metrics": {},
                       "dashboard": {"www_dir": os.path.join(self.tmp,
                                                             "www")},
                       "activity": {"multi_repo": "shadow"}}

    def listing(self, owner, repos, days_old=0, owner_type="Organization"):
        self.conn.execute(
            "INSERT OR REPLACE INTO org_repos (owner, owner_type, "
            "fetched_at, ok, repos_json, attempted_at) VALUES "
            "(?, ?, ?, 1, ?, ?)",
            (owner, owner_type, _ago(days_old), json.dumps(repos),
             _ago(days_old)))
        self.conn.commit()


# ---------------------------------------------------------------------------
# 1.1 Listing
# ---------------------------------------------------------------------------


class TestOwnerParse(unittest.TestCase):
    def test_canonical_urls(self):
        self.assertEqual(org.owner_repo("https://github.com/chutesai/chutes"),
                         ("chutesai", "chutes"))
        self.assertEqual(org.owner_repo("https://github.com/A/B.git"),
                         ("a", "b"))
        self.assertIsNone(org.owner_repo("https://github.com/onlyowner"))
        self.assertIsNone(org.owner_repo(None))
        self.assertIsNone(org.owner_repo("https://github.com/../x"))

    def test_default_mode_is_off_and_bad_mode_is_off(self):
        self.assertEqual(org.mode({}), "off")
        self.assertEqual(org.mode({"activity": {"multi_repo": "yes"}}),
                         "off")
        self.assertEqual(org.mode({"activity": {"multi_repo": "on"}}), "on")


class TestListing(Base):
    def test_listing_stored_with_owner_type(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        opener = StubOpener({
            "/users/chutesai": (200, {}, {"type": "Organization"}),
            "/orgs/chutesai/repos?per_page=100&sort=pushed":
                (200, {}, [_repo("chutes-miner"), _repo("sek8s"),
                           {"name": "../evil", "pushed_at": _ago(1)}])})
        out = org.refresh_listings(self.conn, self.config,
                                   fleet.all_slots(self.conn), now=NOW,
                                   opener=opener)
        self.assertEqual(out["refreshed"], 1)
        row = org._owner_rows(self.conn)["chutesai"]
        self.assertEqual(row["owner_type"], "Organization")
        names = [r["name"] for r in json.loads(row["repos_json"])]
        self.assertEqual(names, ["chutes-miner", "sek8s"])

    def test_refresh_at_most_daily_and_type_cached(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        opener = StubOpener({
            "/users/chutesai": (200, {}, {"type": "Organization"}),
            "/orgs/chutesai/repos?per_page=100&sort=pushed":
                (200, {}, [_repo("sek8s")])})
        slots = fleet.all_slots(self.conn)
        org.refresh_listings(self.conn, self.config, slots, now=NOW,
                             opener=opener)
        later = (NOW_DT + datetime.timedelta(hours=6)).isoformat()
        org.refresh_listings(self.conn, self.config, slots, now=later,
                             opener=opener)
        self.assertEqual(len(opener.calls), 2)
        next_day = (NOW_DT + datetime.timedelta(hours=25)).isoformat()
        org.refresh_listings(self.conn, self.config, slots, now=next_day,
                             opener=opener)
        self.assertEqual(opener.calls[-1],
                         "/orgs/chutesai/repos?per_page=100&sort=pushed")
        self.assertEqual(len(opener.calls), 3)

    def test_failure_keeps_last_listing_and_records_error(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        self.listing("chutesai", [_repo("sek8s")], days_old=2)
        opener = StubOpener({
            "/orgs/chutesai/repos?per_page=100&sort=pushed": (500, {}, None)})
        out = org.refresh_listings(self.conn, self.config,
                                   fleet.all_slots(self.conn), now=NOW,
                                   opener=opener)
        self.assertEqual(out["failed"], 1)
        row = org._owner_rows(self.conn)["chutesai"]
        self.assertEqual(json.loads(row["repos_json"])[0]["name"], "sek8s")
        self.assertEqual(row["fetched_at"], _ago(2))
        self.assertEqual(row["last_error"], "http 500")
        plan = org.plan(self.conn, self.config, fleet.all_slots(self.conn),
                        now=NOW)
        self.assertEqual(plan[64]["repos"], ["chutesai/sek8s"])

    def test_rate_limit_stops_and_holds(self):
        for nid, owner in ((2, "a-org"), (3, "b-org"), (4, "c-org")):
            _slot(self.conn, nid, "https://github.com/%s/x" % owner)
        reset = int((NOW_DT + datetime.timedelta(minutes=30)).timestamp())
        opener = StubOpener({"/users/a-org": (
            403, {"x-ratelimit-remaining": "0",
                  "x-ratelimit-reset": str(reset)}, None)})
        slots = fleet.all_slots(self.conn)
        out = org.refresh_listings(self.conn, self.config, slots, now=NOW,
                                   opener=opener)
        self.assertTrue(out["rate_limited"])
        self.assertEqual(opener.calls, ["/users/a-org"])
        later = (NOW_DT + datetime.timedelta(minutes=10)).isoformat()
        out = org.refresh_listings(self.conn, self.config, slots, now=later,
                                   opener=opener)
        self.assertTrue(out["rate_limited"])
        self.assertEqual(len(opener.calls), 1)

    def test_429_is_a_rate_limit(self):
        _slot(self.conn, 2, "https://github.com/a-org/x")
        opener = StubOpener({"/users/a-org": (429, {"retry-after": "60"},
                                              None)})
        out = org.refresh_listings(self.conn, self.config,
                                   fleet.all_slots(self.conn), now=NOW,
                                   opener=opener)
        self.assertTrue(out["rate_limited"])

    def test_budget_bounds_calls(self):
        for nid in range(1, 41):
            _slot(self.conn, nid, "https://github.com/org%d/x" % nid)
        answers = {}
        for nid in range(1, 41):
            answers["/users/org%d" % nid] = (200, {}, {"type": "User"})
        opener = StubOpener(answers)
        cfg = dict(self.config, activity={"multi_repo": "shadow",
                                          "max_calls_per_pass": 10})
        out = org.refresh_listings(self.conn, cfg, fleet.all_slots(self.conn),
                                   now=NOW, opener=opener)
        self.assertLessEqual(len(opener.calls), 10)
        self.assertEqual(out["calls"], len(opener.calls))

    def test_listing_older_than_seven_days_is_not_used(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        self.listing("chutesai", [_repo("sek8s")], days_old=8)
        plan = org.plan(self.conn, self.config, fleet.all_slots(self.conn),
                        now=NOW)
        self.assertEqual(plan[64]["repos"], [])
        self.assertEqual(plan[64]["why"], org.WHY_STALE)
        self.assertIn("8d", plan[64]["detail"])


# ---------------------------------------------------------------------------
# 1.2 Eligibility
# ---------------------------------------------------------------------------


class TestEligibility(Base):
    def test_shared_owner_reads_one_repository(self):
        _slot(self.conn, 1, "https://github.com/macrocosm-os/apex")
        _slot(self.conn, 9, "https://github.com/macrocosm-os/pretraining")
        _slot(self.conn, 13, "https://github.com/macrocosm-os/data-universe",
              status="unreachable")
        self.listing("macrocosm-os", [_repo("other")])
        slots = fleet.all_slots(self.conn)
        plan = org.plan(self.conn, self.config, slots, now=NOW)
        for nid in (1, 9):
            self.assertEqual(plan[nid]["repos"], [])
            self.assertEqual(plan[nid]["why"], org.WHY_SHARED)
        self.assertEqual(org.candidate_owners(slots, org.activity_cfg(
            self.config)), [])

    def test_user_owner_is_never_read(self):
        _slot(self.conn, 5, "https://github.com/somebody/subnet")
        self.listing("somebody", [], owner_type="User")
        plan = org.plan(self.conn, self.config, fleet.all_slots(self.conn),
                        now=NOW)
        self.assertEqual(plan[5]["repos"], [])
        self.assertEqual(plan[5]["why"], org.WHY_USER)

    def test_user_owner_listing_makes_no_repo_call(self):
        _slot(self.conn, 5, "https://github.com/somebody/subnet")
        opener = StubOpener({"/users/somebody": (200, {}, {"type": "User"})})
        org.refresh_listings(self.conn, self.config,
                             fleet.all_slots(self.conn), now=NOW,
                             opener=opener)
        self.assertEqual(opener.calls, ["/users/somebody"])

    def test_filters_and_exclusion(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        self.listing("chutesai", [
            _repo("chutes", pushed_days=100),
            _repo("chutes-miner", pushed_days=20),
            _repo("sek8s", pushed_days=10),
            _repo("forked", fork=True),
            _repo("old", archived=True),
            _repo("stale", pushed_days=91),
            _repo("excluded-one", pushed_days=1)])
        cfg = dict(self.config, activity={
            "multi_repo": "shadow", "exclude_repos": ["ChutesAI/excluded-one"]})
        plan = org.plan(self.conn, cfg, fleet.all_slots(self.conn), now=NOW)
        self.assertEqual(plan[64]["repos"],
                         ["chutesai/sek8s", "chutesai/chutes-miner"])
        self.assertIsNone(plan[64]["why"])

    def test_max_repos_keeps_most_recent(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        self.listing("chutesai", [_repo("r%d" % i, pushed_days=i + 1)
                                  for i in range(10)])
        cfg = dict(self.config, activity={"multi_repo": "shadow",
                                          "max_repos": 4})
        plan = org.plan(self.conn, cfg, fleet.all_slots(self.conn), now=NOW)
        self.assertEqual(plan[64]["repos"],
                         ["chutesai/r0", "chutesai/r1", "chutesai/r2"])

    def test_operator_single_repo_owner(self):
        _slot(self.conn, 14, "https://github.com/latent-to/cacheon")
        self.listing("latent-to", [_repo("developer-docs")])
        cfg = dict(self.config, activity={"multi_repo": "shadow",
                                          "single_repo_owners": ["latent-to"]})
        slots = fleet.all_slots(self.conn)
        plan = org.plan(self.conn, cfg, slots, now=NOW)
        self.assertEqual(plan[14]["why"], org.WHY_OPERATOR)
        self.assertEqual(org.candidate_owners(slots, org.activity_cfg(cfg)),
                         [])

    def test_off_mode_plans_nothing_and_run_calls_nothing(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        self.listing("chutesai", [_repo("sek8s")])
        cfg = dict(self.config, activity={"multi_repo": "off"})
        plan = org.plan(self.conn, cfg, fleet.all_slots(self.conn), now=NOW)
        self.assertEqual(plan[64]["why"], org.WHY_OFF)
        self.assertEqual(org.run(self.conn, cfg, now=NOW), {"mode": "off"})


# ---------------------------------------------------------------------------
# 2.1 History-only fetch
# ---------------------------------------------------------------------------


def _object_types(git_dir):
    out = _git(git_dir, "cat-file", "--batch-all-objects",
               "--batch-check=%(objecttype)")
    return set(out.split())


class TestHistoryFetch(Base):
    def setUp(self):
        super().setUp()
        self.origin = h.make_origin(self.tmp, name="sek8s", files={
            "src/secret.py": "x = 1\n", "README.md": "# r\n"})
        commit_at(self.origin, 3)
        self.url = "file://" + self.origin

    def sync(self, **kw):
        return org.sync_histories(self.conn, self.config, ["chutesai/sek8s"],
                                  now=NOW, url_for=lambda r: self.url, **kw)

    def test_commits_only_no_tree_no_worktree(self):
        out = self.sync()
        self.assertEqual(out["ok"], 1)
        target = org.history_dir(self.clone_root, "chutesai/sek8s")
        self.assertTrue(target.endswith(os.path.join(
            "activity", "chutesai", "sek8s.git")))
        self.assertEqual(_git(target, "rev-parse", "--is-bare-repository"),
                         "true")
        self.assertFalse(os.path.exists(os.path.join(target, "src")))
        self.assertFalse(os.path.exists(os.path.join(target, "README.md")))
        self.assertEqual(_object_types(target), {"commit"})
        log = org.history_log(self.clone_root, "chutesai/sek8s",
                              fleet._run_git)
        self.assertEqual(len(log), 2)
        # Reading the log fetched nothing lazily.
        self.assertEqual(_object_types(target), {"commit"})
        self.assertEqual(_git(target, "remote", "get-url", "--push",
                              "origin"), fleet.PUSH_URL_DISABLED)
        hooks = os.path.join(target, "hooks")
        self.assertTrue(not os.path.isdir(hooks) or not os.listdir(hooks))
        self.assertEqual(_git(target, "tag", "-l"), "")

    def test_fetch_advances_the_branch(self):
        self.sync()
        sha = commit_at(self.origin, 1)
        out = self.sync()
        self.assertEqual(out["ok"], 1)
        log = org.history_log(self.clone_root, "chutesai/sek8s",
                              fleet._run_git)
        self.assertIn(sha, [s for s, _, _ in log])
        target = org.history_dir(self.clone_root, "chutesai/sek8s")
        self.assertEqual(_object_types(target), {"commit"})

    def test_low_disk_holds_fetch_and_keeps_history(self):
        self.sync()
        commit_at(self.origin, 1)
        self.config["min_free_bytes"] = 100
        out = self.sync(disk_free=lambda: 10)
        self.assertEqual(out[org.H_DISK], 1)
        row = org._history_rows(self.conn)["chutesai/sek8s"]
        self.assertEqual(row["status"], org.H_DISK)
        log = org.history_log(self.clone_root, "chutesai/sek8s",
                              fleet._run_git)
        self.assertEqual(len(log), 2)
        counted, _ = org.counted_repos(self.conn, self.config,
                                       ["chutesai/sek8s"])
        self.assertEqual(counted, ["chutesai/sek8s"])

    def test_low_disk_blocks_first_clone(self):
        self.config["min_free_bytes"] = 100
        out = self.sync(disk_free=lambda: 10)
        self.assertEqual(out[org.H_DISK], 1)
        self.assertFalse(os.path.exists(
            org.history_dir(self.clone_root, "chutesai/sek8s")))

    def test_oversized_history_dropped_and_recorded(self):
        self.config["activity"]["max_repo_bytes"] = 1
        out = self.sync()
        self.assertEqual(out[org.H_OVERSIZED], 1)
        self.assertFalse(os.path.exists(
            org.history_dir(self.clone_root, "chutesai/sek8s")))
        counted, dropped = org.counted_repos(self.conn, self.config,
                                             ["chutesai/sek8s"])
        self.assertEqual(counted, [])
        self.assertEqual(dropped, {"chutesai/sek8s": org.H_OVERSIZED})
        # Not retried within the retry window.
        self.assertEqual(self.sync()["skipped"], 1)

    def test_new_history_bound(self):
        self.config["activity"]["max_new_histories_per_pass"] = 0
        out = self.sync()
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(org._history_rows(self.conn)["chutesai/sek8s"]
                         ["status"], org.H_PENDING)

    def test_unreachable_remote_is_recorded(self):
        out = org.sync_histories(self.conn, self.config, ["chutesai/gone"],
                                 now=NOW,
                                 url_for=lambda r: "file:///nonexistent/x")
        self.assertEqual(out[org.H_FAILED], 1)


# ---------------------------------------------------------------------------
# 3.1 Combined activity, 3.2 switch, 3.3 report
# ---------------------------------------------------------------------------


class CombinedBase(Base):
    """SN64: on-chain repo idle 120 days; sibling `sek8s` busy."""

    def setUp(self):
        super().setUp()
        self.onchain = h.make_origin(self.tmp, name="chutes")
        _git(self.onchain, "commit", "-q", "--amend", "--no-edit",
             "--reset-author", env={"GIT_AUTHOR_DATE": _ago(130),
                                    "GIT_COMMITTER_DATE": _ago(130)})
        commit_at(self.onchain, 120)
        clone_dir = os.path.join(self.clone_root, "64")
        state = fleet.setup_clone(clone_dir, self.onchain)
        fleet.upsert_slot(self.conn, {
            "netuid": 64, "github_repo": "https://github.com/chutesai/chutes",
            "epoch": 1, "status": "active",
            "default_branch": state["default_branch"],
            "local_sha": state["local_sha"]})
        self.conn.commit()
        self.sibling = h.make_origin(self.tmp, name="sek8s")
        _git(self.sibling, "commit", "-q", "--amend", "--no-edit",
             env={"GIT_AUTHOR_DATE": _ago(200),
                  "GIT_COMMITTER_DATE": _ago(200)})
        for i in range(12):
            commit_at(self.sibling, 2 + i)
        self.bot_sha = commit_at(self.sibling, 1,
                                 email="41898282+github-actions[bot]@users."
                                       "noreply.github.com")
        self.listing("chutesai", [_repo("chutes", pushed_days=120),
                                  _repo("sek8s", pushed_days=1)])
        self.urls = {"chutesai/sek8s": "file://" + self.sibling}

    def sync(self):
        return org.sync_histories(self.conn, self.config,
                                  sorted(self.urls), now=NOW,
                                  url_for=lambda r: self.urls[r])

    def latest(self):
        return self.conn.execute(
            "SELECT c7, c30, c90, days_since, c7_all, c30_all, c90_all, "
            "days_since_all, repos_counted, single_why FROM metric_activity "
            "WHERE netuid = 64 ORDER BY pass_ts DESC LIMIT 1").fetchone()


class TestCombinedActivity(CombinedBase):
    def test_sibling_commits_count_and_bot_does_not(self):
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        (c7, c30, _c90, days, c7a, c30a, _c90a, daysa, counted,
         why) = self.latest()
        self.assertEqual((c7, c30), (0, 0))
        self.assertEqual(days, 120)
        self.assertEqual(c30a, 12)
        self.assertEqual(c7a, 6)
        self.assertEqual(daysa, 2)
        self.assertEqual(counted, 2)
        self.assertIsNone(why)
        repos = dict(self.conn.execute(
            "SELECT repo, c30 FROM metric_activity_repos WHERE netuid = 64"))
        self.assertEqual(repos, {"chutesai/chutes": 0, "chutesai/sek8s": 12})

    def test_mirrored_commit_counted_once(self):
        mirror = os.path.join(self.tmp, "mirror")
        subprocess.run(["git", "clone", "-q", self.sibling, mirror],
                       check=True)
        _git(mirror, "config", "uploadpack.allowFilter", "true")
        self.urls["chutesai/mirror"] = "file://" + mirror
        self.listing("chutesai", [_repo("sek8s"), _repo("mirror")])
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        row = self.latest()
        self.assertEqual(row[5], 12)
        self.assertEqual(row[8], 3)

    def test_union_by_commit_id(self):
        a = [("s1", NOW_DT, "x@a"), ("s2", NOW_DT, "y@a")]
        b = [("s2", NOW_DT, "y@a"), ("s3", NOW_DT, "z@a")]
        self.assertEqual(len(met.union_commits([a, b])), 3)

    def test_shared_owner_combined_equals_single(self):
        _slot(self.conn, 65, "https://github.com/chutesai/other")
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        (c7, c30, c90, days, c7a, c30a, c90a, daysa, counted,
         why) = self.latest()
        self.assertEqual((c7, c30, c90, days), (c7a, c30a, c90a, daysa))
        self.assertEqual(counted, 1)
        self.assertEqual(why, org.WHY_SHARED)

    def test_missing_history_names_the_gap(self):
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        row = self.latest()
        self.assertEqual(row[5], 0)
        self.assertEqual(row[9], "no-history")

    def test_off_records_no_combined_figures(self):
        self.sync()
        cfg = dict(self.config, activity={"multi_repo": "off"})
        met.run_activity(self.conn, cfg, pass_ts=NOW)
        row = self.latest()
        self.assertIsNone(row[5])
        self.assertIsNone(row[8])

    def test_old_store_gains_columns(self):
        path = os.path.join(self.tmp, "old.db")
        old = fleet.open_store(path)
        self.addCleanup(old.close)
        old.execute(
            "CREATE TABLE metric_activity (netuid INTEGER NOT NULL, "
            "epoch INTEGER NOT NULL, pass_ts TEXT NOT NULL, c7 INTEGER, "
            "c30 INTEGER, c90 INTEGER, a30 INTEGER, last_commit_at TEXT, "
            "days_since INTEGER, total_commits INTEGER, total_authors "
            "INTEGER, PRIMARY KEY (netuid, epoch, pass_ts))")
        old.execute("INSERT INTO metric_activity (netuid, epoch, pass_ts, "
                    "c30) VALUES (1, 1, ?, 5)", (NOW,))
        old.commit()
        met.ensure_schema(old)
        met.ensure_schema(old)
        cols = {r[1] for r in old.execute("PRAGMA table_info(metric_activity)")}
        self.assertTrue({"c30_all", "repos_counted", "single_why"} <= cols)
        self.assertEqual(old.execute("SELECT c30, c30_all FROM "
                                     "metric_activity").fetchone(), (5, None))


class TestOldStoreReader(unittest.TestCase):
    def test_report_reads_an_unmigrated_store(self):
        conn = __import__("sqlite3").connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE metric_activity (netuid INTEGER, epoch INTEGER, "
            "pass_ts TEXT, c7 INTEGER, c30 INTEGER, c90 INTEGER, a30 "
            "INTEGER, last_commit_at TEXT, days_since INTEGER, "
            "total_commits INTEGER, total_authors INTEGER)")
        conn.execute("INSERT INTO metric_activity VALUES "
                     "(1, 1, ?, 1, 2, 3, 1, NULL, 4, 9, 2)", (NOW,))
        out = met._latest_activity(conn, {"activity": {"multi_repo": "on"}})
        self.assertEqual(out[1]["c30"], 2)
        self.assertFalse(met._has_combined(conn, 1, NOW))


class TestSwitch(CombinedBase):
    def board(self, mode):
        cfg = dict(self.config, activity=dict(self.config["activity"],
                                              multi_repo=mode))
        rep = met.report(self.conn, cfg, now=NOW_DT)
        board = dash.build_board(self.conn, cfg, now=NOW)
        return rep, board, dash.render_html(board)

    def setUp(self):
        super().setUp()
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)

    def test_shadow_output_equals_off(self):
        # build_board stamps wall-clock time; pin it for the comparison.
        stamp = "2026-11-04T00:00:00+00:00"

        def pinned(mode):
            rep, board, _html = self.board(mode)
            board["generated_at"] = stamp
            return rep, board, dash.render_html(board)
        self.assertEqual(pinned("shadow"), pinned("off"))

    def test_on_moves_c30_and_cold(self):
        rep_off, board_off, _ = self.board("shadow")
        rep_on, board_on, _ = self.board("on")
        row_off = [r for r in rep_off["subnets"] if r["netuid"] == 64][0]
        row_on = [r for r in rep_on["subnets"] if r["netuid"] == 64][0]
        self.assertEqual(row_off["c30"], 0)
        self.assertEqual(row_on["c30"], 12)
        self.assertEqual(row_off["activity_class"], "fade-eligible")
        self.assertEqual(row_on["activity_class"], "active")
        self.assertEqual(set(row_off), set(row_on))
        self.assertEqual(board_off["counts"]["cold"], 1)
        self.assertEqual(board_on["counts"]["cold"], 0)

    def test_export_commits_follow_the_switch(self):
        shadow = met.activity_commit_log(self.conn, self.config, 64, NOW)
        cfg_on = dict(self.config, activity={"multi_repo": "on"})
        on = met.activity_commit_log(self.conn, cfg_on, 64, NOW)
        bots = met.compile_bot_patterns(
            met.DEFAULT_METRICS_CFG["bot_author_patterns"])

        def c30(log):
            return sum(1 for when, email in log
                       if not met.is_bot_author(email, bots)
                       and (NOW_DT - when).total_seconds() / 86400 <= 30)
        self.assertEqual(c30(shadow), 0)
        self.assertEqual(c30(on), 12)


class TestReport(CombinedBase):
    def test_activity_sources_lists_both_sets_and_repos(self):
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        out = met.activity_sources(self.conn, self.config)
        self.assertEqual(out["mode"], "shadow")
        self.assertEqual(out["changed"], 1)
        row = out["subnets"][0]
        self.assertEqual(row["netuid"], 64)
        self.assertEqual(row["single"]["c30"], 0)
        self.assertEqual(row["combined"]["c30"], 12)
        self.assertEqual(row["c30_gain"], 12)
        self.assertEqual([r["repo"] for r in row["repos"]],
                         ["chutesai/sek8s", "chutesai/chutes"])
        self.assertEqual(row["left_out"], [])

    def test_report_names_left_out_repos(self):
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        row = met.activity_sources(self.conn, self.config)["subnets"][0]
        self.assertEqual(row["single_why"], "no-history")
        self.assertEqual(row["left_out"][0]["repo"], "chutesai/sek8s")

    def test_cli(self):
        self.sync()
        met.run_activity(self.conn, self.config, pass_ts=NOW)
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w") as handle:
            json.dump(self.config, handle)
        self.conn.commit()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = met.main(["--config", path, "activity-sources"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["changed"], 1)


class TestNoNetwork(Base):
    def test_default_opener_is_blocked_in_tests(self):
        _slot(self.conn, 64, "https://github.com/chutesai/chutes")
        with self.assertRaises(h.NetworkCall):
            org.refresh_listings(self.conn, self.config,
                                 fleet.all_slots(self.conn), now=NOW)


if __name__ == "__main__":
    unittest.main()
