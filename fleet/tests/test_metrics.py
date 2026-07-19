"""fleet-rotation-metrics: schema, emission-map extraction (fraction parse,
docstring dedup, opacity, caps, sha-gating), epoch-scoped activity with
fork-history separation, branch-pulse tip diffing, momentum/quadrant from the
signals price panel, the combined report, and the inline pass + status."""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_metrics as met  # noqa: E402


def _iso(days_ago=0, hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(days=days_ago, hours=hours_ago)).isoformat()


CFG = met.DEFAULT_METRICS_CFG


class MetricsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        met.ensure_schema(self.conn)
        self.clone_root = os.path.join(self.tmp, "clones")
        self.config = {"db": self.db, "clone_root": self.clone_root,
                       "metrics": {}}

    def make_slot(self, netuid, files, epoch=1, status="active",
                  repo=None):
        origin = h.make_origin(self.tmp, name="origin_%d_%d" % (netuid, epoch),
                               files=files)
        clone_dir = os.path.join(self.clone_root, str(netuid))
        state = fleet.setup_clone(clone_dir, origin)
        self.assertEqual(state["status"], "active", state)
        fleet.upsert_slot(self.conn, {
            "netuid": netuid,
            "github_repo": repo or "https://github.com/org%d/repo" % netuid,
            "epoch": epoch, "status": status,
            "default_branch": state["default_branch"],
            "local_sha": state["local_sha"]})
        self.conn.commit()
        return origin, clone_dir, state


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema(MetricsBase):
    def test_additive_and_idempotent(self):
        before = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        met.ensure_schema(self.conn)
        after = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(before, after)
        self.assertIn("slots", after)               # reconcile schema intact
        self.assertIn("metric_emission_routes", after)
        self.assertIn("metric_branch_tips", after)


# ---------------------------------------------------------------------------
# Emission extraction — pure line-based functions
# ---------------------------------------------------------------------------

class TestEmissionExtraction(unittest.TestCase):
    def test_scan_surface_predicate(self):
        self.assertTrue(met.is_econ_scan_file("validator/reward.py", CFG))
        self.assertTrue(met.is_econ_scan_file("a/scoring/weights.py", CFG))
        self.assertFalse(met.is_econ_scan_file("tests/reward.py", CFG))  # test
        self.assertFalse(met.is_econ_scan_file("validator/reward.js", CFG))  # ext
        self.assertFalse(met.is_econ_scan_file("neurons/miner.py", CFG))  # token

    def test_classify_symbol(self):
        self.assertEqual(met.classify_symbol("PARTNER_FRACTION", CFG), "partner")
        self.assertEqual(met.classify_symbol("burn_uid", CFG), "burn")
        self.assertEqual(met.classify_symbol("TREASURY_ADDR", CFG), "treasury")
        self.assertIsNone(met.classify_symbol("learning_rate", CFG))

    def test_parseable_fraction_with_evidence(self):
        lines = ["PARTNER_FRACTION = 0.35  # to partner",
                 'PARTNER_HOTKEY = "5Dw7tYMwTBxc3BgapjJ2omvP5TGFSDe3UsV414aHHc'
                 'pRKh2V"']
        routes = met.extract_routes_from_lines("validator/reward.py", lines,
                                               CFG)
        partner = [r for r in routes if r["symbol"] == "PARTNER_FRACTION"][0]
        self.assertEqual(partner["kind"], "partner")
        self.assertEqual(partner["fraction"], 0.35)
        self.assertEqual(partner["line"], 1)
        hotkey = [r for r in routes if r["symbol"] == "PARTNER_HOTKEY"][0]
        self.assertEqual(hotkey["dest_hotkey"],
                         "5Dw7tYMwTBxc3BgapjJ2omvP5TGFSDe3UsV414aHHcpRKh2V")

    def test_expression_fraction_is_null(self):
        lines = ["MINER_FRACTION = 1.0 - burn_fraction - PARTNER_FRACTION"]
        routes = met.extract_routes_from_lines("reward.py", lines, CFG)
        # 'burn_fraction' mention is not an assignment; the assigned symbol is
        # MINER_FRACTION which is not a routing family -> no route. The stray
        # 1.0 must never be captured as a fraction.
        self.assertEqual(routes, [])

    def test_expression_on_a_routing_symbol_yields_null_fraction(self):
        lines = ["BURN_FRACTION = 1.0 - PARTNER_FRACTION"]
        routes = met.extract_routes_from_lines("reward.py", lines, CFG)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["kind"], "burn")
        self.assertIsNone(routes[0]["fraction"])  # present-but-unparsed

    def test_docstring_mention_collapses_into_assignment(self):
        lines = ['    """Routes PARTNER_FRACTION (0.35) to the partner."""',
                 "PARTNER_FRACTION = 0.35"]
        routes = met.extract_routes_from_lines("reward.py", lines, CFG)
        self.assertEqual(len(routes), 1)          # one row, the assignment
        self.assertEqual(routes[0]["line"], 2)
        self.assertEqual(routes[0]["fraction"], 0.35)

    def test_comment_line_is_not_a_route(self):
        lines = ["# BURN_FRACTION = 0.5 old default"]
        self.assertEqual(met.extract_routes_from_lines("reward.py", lines, CFG),
                         [])

    def test_opacity_detection(self):
        opaque = "burn_fraction = remote_config.get('burn')\n"
        self.assertTrue(met.file_is_opaque(opaque, CFG))
        plain = "learning_rate = remote_config.get('lr')\n"  # no econ vocab
        self.assertFalse(met.file_is_opaque(plain, CFG))


# ---------------------------------------------------------------------------
# Emission scan over a clone — sha gating, caps, opacity, replace-on-rescan
# ---------------------------------------------------------------------------

class TestEmissionScan(MetricsBase):
    def test_scan_records_routes_and_gates_on_sha(self):
        files = {"validator/reward.py":
                 "PARTNER_FRACTION = 0.35\nBURN_FRACTION = 0.30\n"}
        self.make_slot(7, files)
        out = met.run_emissions(self.conn, self.config)
        self.assertEqual(out["scanned"], 1)
        rows = self.conn.execute(
            "SELECT kind, fraction FROM metric_emission_routes WHERE "
            "netuid = 7 ORDER BY kind").fetchall()
        self.assertEqual(rows, [("burn", 0.30), ("partner", 0.35)])
        # Second pass, sha unchanged -> skipped, not rescanned.
        out2 = met.run_emissions(self.conn, self.config)
        self.assertEqual(out2["unchanged"], 1)
        self.assertEqual(out2["scanned"], 0)

    def test_rescan_replaces_stale_routes(self):
        _o, clone_dir, _s = self.make_slot(
            8, {"validator/reward.py": "PARTNER_FRACTION = 0.35\n"})
        met.run_emissions(self.conn, self.config)
        # Simulate an advance that removes the redirect: rewrite + new sha in
        # the slot row so the sha gate reopens.
        h.write_file(clone_dir, "validator/reward.py", "MINER_ONLY = True\n")
        self.conn.execute("UPDATE slots SET local_sha = ? WHERE netuid = 8",
                          ("deadbeef" * 5,))
        self.conn.commit()
        met.run_emissions(self.conn, self.config)
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM metric_emission_routes WHERE netuid = 8"
        ).fetchone()[0]
        self.assertEqual(rows, 0)  # stale route gone

    def test_opaque_flag_set(self):
        files = {"validator/weights.py":
                 "burn = remote_config.fetch('burn_fraction')\n"}
        self.make_slot(9, files)
        met.run_emissions(self.conn, self.config)
        scan = self.conn.execute(
            "SELECT opaque, outcome FROM metric_emission_scan WHERE netuid = 9"
        ).fetchone()
        self.assertEqual(scan[0], 1)

    def test_route_cap_truncates(self):
        body = "".join("BURN_%d = 0.01\n" % i for i in range(60))
        self.make_slot(10, {"scoring/reward.py": body})
        self.config["metrics"] = {"route_cap_per_subnet": 5}
        met.run_emissions(self.conn, self.config)
        rows = self.conn.execute(
            "SELECT COUNT(*), MAX(truncated) FROM metric_emission_scan "
            "WHERE netuid = 10").fetchone()
        n = self.conn.execute("SELECT COUNT(*) FROM metric_emission_routes "
                              "WHERE netuid = 10").fetchone()[0]
        self.assertEqual(n, 5)
        self.assertEqual(rows[1], 1)  # truncated recorded

    def test_scan_failure_is_recorded_not_raised(self):
        self.make_slot(11, {"reward.py": "BURN_FRACTION = 0.5\n"})
        # Remove the clone so ls-tree fails; the slot must be recorded failed.
        fleet._rmtree(os.path.join(self.clone_root, "11"))
        out = met.run_emissions(self.conn, self.config)
        self.assertEqual(out["failed"], 1)
        scan = self.conn.execute(
            "SELECT outcome FROM metric_emission_scan WHERE netuid = 11"
        ).fetchone()
        self.assertEqual(scan[0], met.OUT_FAILED)


# ---------------------------------------------------------------------------
# Activity — windowed vs all-time, epoch tag, idle
# ---------------------------------------------------------------------------

class TestActivity(MetricsBase):
    def test_windows_separate_from_alltime(self):
        now = datetime.datetime(2026, 7, 19, tzinfo=datetime.timezone.utc)
        commits = [
            (now - datetime.timedelta(days=1), "a@x"),
            (now - datetime.timedelta(days=5), "b@x"),
            (now - datetime.timedelta(days=40), "c@x"),
            (now - datetime.timedelta(days=400), "d@x"),  # fork-era history
        ]
        act = met.compute_activity(commits, [7, 30, 90], now)
        self.assertEqual(act["windows"][7], 2)
        self.assertEqual(act["windows"][30], 2)
        self.assertEqual(act["windows"][90], 3)
        self.assertEqual(act["a30"], 2)             # only recent authors
        self.assertEqual(act["total_commits"], 4)   # context includes old
        self.assertEqual(act["total_authors"], 4)

    def test_idle_repo(self):
        act = met.compute_activity([], [7, 30], _dt())
        self.assertEqual(act["windows"][7], 0)
        self.assertIsNone(act["last_commit_at"])
        self.assertIsNone(act["days_since"])

    def test_run_activity_records_epoch_tagged(self):
        self.make_slot(3, {"README.md": "# r\n"}, epoch=4)
        out = met.run_activity(self.conn, self.config, pass_ts=_iso())
        self.assertEqual(out["recorded"], 1)
        row = self.conn.execute(
            "SELECT epoch, total_commits FROM metric_activity WHERE netuid = 3"
        ).fetchone()
        self.assertEqual(row[0], 4)
        self.assertGreaterEqual(row[1], 1)


def _dt():
    return datetime.datetime.now(tz=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Branch pulse — tip diffing + recording
# ---------------------------------------------------------------------------

class TestBranchPulse(MetricsBase):
    def test_diff_tips_counts(self):
        prev = {"main": "a", "dev": "b"}
        cur = {"main": "a2", "dev": "b", "feat": "c"}  # moved + added
        self.assertEqual(met.diff_tips(prev, cur), 2)
        self.assertEqual(met.diff_tips({"main": "a"}, {}), 1)  # removed
        self.assertEqual(met.diff_tips({"main": "a"}, {"main": "a"}), 0)

    def test_first_snapshot_has_null_changed(self):
        self.make_slot(5, {"README.md": "# r\n"})
        out = met.record_branch_tips(self.conn, self.config, pass_ts=_iso())
        self.assertEqual(out["recorded"], 1)
        row = self.conn.execute(
            "SELECT changed_tips, tips_count FROM metric_branch_tips "
            "WHERE netuid = 5").fetchone()
        self.assertIsNone(row[0])          # no prior snapshot
        self.assertGreaterEqual(row[1], 1)

    def test_churn_detected_across_passes(self):
        origin, _clone, _s = self.make_slot(6, {"README.md": "# r\n"})
        met.record_branch_tips(self.conn, self.config, pass_ts=_iso(hours_ago=2))
        # New branch on the origin -> a changed tip next pass.
        h.git(origin, "branch", "v2-rewrite")
        out = met.record_branch_tips(self.conn, self.config, pass_ts=_iso())
        self.assertEqual(out["churned"], 1)
        latest = self.conn.execute(
            "SELECT changed_tips FROM metric_branch_tips WHERE netuid = 6 "
            "ORDER BY pass_ts DESC LIMIT 1").fetchone()
        self.assertEqual(latest[0], 1)

    def test_ls_remote_failure_records_nothing(self):
        self.make_slot(7, {"README.md": "# r\n"})
        fleet._rmtree(os.path.join(self.clone_root, "7"))
        out = met.record_branch_tips(self.conn, self.config, pass_ts=_iso())
        self.assertEqual(out["failed"], 1)
        self.assertEqual(out["recorded"], 0)
        n = self.conn.execute("SELECT COUNT(*) FROM metric_branch_tips "
                              "WHERE netuid = 7").fetchone()[0]
        self.assertEqual(n, 0)


# ---------------------------------------------------------------------------
# Momentum + quadrant
# ---------------------------------------------------------------------------

class TestMomentum(MetricsBase):
    def _price(self, ts, netuid, price):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS signal_prices (ts TEXT NOT NULL, "
            "netuid INTEGER NOT NULL, price_tao REAL, PRIMARY KEY (ts, netuid))")
        self.conn.execute("INSERT OR REPLACE INTO signal_prices VALUES "
                          "(?, ?, ?)", (ts, netuid, price))
        self.conn.commit()

    def test_insufficient_history_is_none(self):
        now = _dt()
        self._price(now.isoformat(), 1, 10.0)  # single point
        mom = met.compute_momentum(self.conn, CFG, now=now)
        self.assertIsNone(mom["per_subnet"][1][7])

    def test_window_return_and_baseline(self):
        now = _dt()
        old = (now - datetime.timedelta(days=3)).isoformat()
        self._price(old, 1, 10.0)
        self._price(now.isoformat(), 1, 12.0)   # +20%
        self._price(old, 2, 10.0)
        self._price(now.isoformat(), 2, 10.0)   # 0%
        mom = met.compute_momentum(self.conn, CFG, now=now)
        self.assertAlmostEqual(mom["per_subnet"][1][7], 20.0, places=3)
        self.assertAlmostEqual(mom["baseline"][7], 10.0, places=3)  # median

    def test_percentile_and_quadrant(self):
        ranks = met._percentile_ranks({1: 5.0, 2: 1.0, 3: 9.0})
        self.assertLess(ranks[2], ranks[1])
        self.assertLess(ranks[1], ranks[3])
        self.assertEqual(met._quadrant_region(0.9, 0.9), "ride")
        self.assertEqual(met._quadrant_region(0.9, 0.1), "accumulate")
        self.assertEqual(met._quadrant_region(0.1, 0.9), "fade")
        self.assertEqual(met._quadrant_region(0.1, 0.1), "ignore")
        self.assertIsNone(met._quadrant_region(0.5, None))


# ---------------------------------------------------------------------------
# Report — structure, invisible fleet, team concentration
# ---------------------------------------------------------------------------

class TestReport(MetricsBase):
    def test_report_shape_and_tiers(self):
        self.make_slot(1, {"validator/reward.py": "PARTNER_FRACTION = 0.35\n"},
                       repo="https://github.com/macrocosm-os/a")
        self.make_slot(2, {"README.md": "# r\n"},
                       repo="https://github.com/macrocosm-os/b")
        # An invisible slot (unreachable placeholder URL).
        fleet.upsert_slot(self.conn, {
            "netuid": 30, "github_repo": "https://github.com/username/repo",
            "status": "unreachable"})
        self.conn.commit()
        met.run_pass(self.conn, self.config, now=_iso())
        rep = met.report(self.conn, self.config)
        nids = {r["netuid"] for r in rep["subnets"]}
        self.assertEqual(nids, {1, 2})              # only active in the table
        self.assertIn(30, {s["netuid"] for s in rep["invisible_fleet"]})
        # Both active slots share org macrocosm-os -> a concentration group.
        orgs = {g["org"]: g["count"] for g in rep["team_concentration"]}
        self.assertEqual(orgs.get("macrocosm-os"), 2)
        # No price history yet -> momentum absent, quadrant None.
        self.assertFalse(rep["price_history_present"])
        row1 = [r for r in rep["subnets"] if r["netuid"] == 1][0]
        self.assertIsNone(row1["momentum_7d"])
        self.assertEqual(row1["emission_routes"], 1)

    def test_placeholder_org_excluded_from_concentration(self):
        self.make_slot(1, {"README.md": "# r\n"},
                       repo="https://github.com/deprecated/deprecated")
        self.make_slot(2, {"README.md": "# r\n"},
                       repo="https://github.com/deprecated/other")
        met.run_activity(self.conn, self.config, pass_ts=_iso())
        rep = met.report(self.conn, self.config)
        self.assertEqual(rep["team_concentration"], [])


# ---------------------------------------------------------------------------
# Pass integration + status
# ---------------------------------------------------------------------------

class TestPassAndStatus(MetricsBase):
    def test_kill_switch(self):
        self.config["metrics"] = {"enabled": False}
        out = met.run_pass(self.conn, self.config, now=_iso())
        self.assertEqual(out, {"disabled": True})

    def test_pass_runs_all_three_steps(self):
        self.make_slot(1, {"validator/reward.py": "BURN_FRACTION = 0.5\n"})
        out = met.run_pass(self.conn, self.config, now=_iso())
        self.assertEqual(out["branch_tips"]["recorded"], 1)
        self.assertEqual(out["activity"]["recorded"], 1)
        self.assertEqual(out["emissions"]["scanned"], 1)

    def test_status_summary(self):
        self.make_slot(1, {"scoring/reward.py": "PARTNER_FRACTION = 0.35\n"})
        met.run_pass(self.conn, self.config, now=_iso())
        st = met.metrics_status(self.conn)
        self.assertEqual(st["activity_slots"], 1)
        self.assertEqual(st["branch_pulse_slots"], 1)
        self.assertEqual(st["emission_routes"], 1)
        self.assertIsNotNone(st["last_activity_pass"])


class TestReconcileHook(MetricsBase):
    def test_metrics_run_inline_on_reconcile(self):
        # A minimal identity map with one github repo -> reconcile clones it,
        # then signals + metrics run inline. Assert the metrics tables filled.
        origin = h.make_origin(self.tmp, name="hook_origin",
                               files={"validator/reward.py":
                                      "PARTNER_FRACTION = 0.35\n"})
        identity = {"status": "ok", "freshness_status": "fresh",
                    "block_reference": 1,
                    "values": {"complete": True, "count": 1, "subnets": [
                        {"netuid": 1,
                         "github_repo": "https://github.com/org/repo",
                         "owner_ss58": None, "subnet_name": "x"}]}}

        # The normalizer accepts the github.com URL (plan = CLONE); the
        # injected setup clones from the local fixture origin instead of the
        # network, so the inline signals+metrics steps run on a real clone.
        def setup(clone_dir, url, token=None, caps=None):
            return fleet.setup_clone(clone_dir, origin, caps=caps)

        summary = fleet.reconcile(self.conn, identity, self.config,
                                  setup=setup)
        self.assertIn("metrics", summary)
        self.assertNotIn("error", summary["metrics"])
        routes = self.conn.execute(
            "SELECT COUNT(*) FROM metric_emission_routes").fetchone()[0]
        self.assertGreaterEqual(routes, 1)


if __name__ == "__main__":
    unittest.main()
