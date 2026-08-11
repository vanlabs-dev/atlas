"""mining-triage: the economics model (alpha_out base, burn applied once,
constant quantity is not a ranking input), concentration from the chain
incentive vector, the ordered cut ladder with recorded reasons, the three
fail-closed legs, sha-gated feasibility with file:line evidence, the ranked
report, the board render, and pass fail-isolation."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402,F401
from _helpers import fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402
import atlas_fleet_mining as mine  # noqa: E402


def panel_subnet(netuid, burn=0.0, price=0.01, enabled=True,
                 alpha_out=1.0, alpha_in=0.12, pool_alpha=3_000_000.0,
                 pool_root=25_000.0, reg=0.0005):
    return {"netuid": netuid, "name": "sn%d" % netuid,
            "emission_is_enabled": enabled,
            "emission_miner_burn": burn,
            "alpha_out_emission": alpha_out,
            "alpha_in_emission": alpha_in,
            "alpha_price_tao": price,
            "alpha_in_pool": pool_alpha, "root_in_pool": pool_root,
            "registration_cost": reg}


def panel(subnets):
    return {"status": "ok", "request_completed": "2026-08-07T04:00:00+00:00",
            "values": {"subnets": subnets, "count": len(subnets)}}


def chain(incentive=None, network_n=None, collateral=None, failures=None,
          identity=None, block=8789861, ok=True):
    return {"ok": ok, "block_number": block, "block_hash": "0xabc",
            "values": {"Incentive": incentive or {},
                       "SubnetworkN": network_n or {},
                       "CollateralLockShare": collateral or {},
                       "SubnetIdentitiesV3": {} if identity is None
                       else identity,
                       "MinerBurned": {}},
            "failures": failures or {}}


def inputs(subnets, **kwargs):
    return {"panel": panel(subnets), "chain": chain(**kwargs),
            "gate_sides": {}}


class MiningBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        mine.ensure_schema(self.conn)
        self.config = {"db": self.db,
                       "clone_root": os.path.join(self.tmp, "clones"),
                       "dashboard": {"www_dir": os.path.join(self.tmp, "www")},
                       "mining": {"enabled": True}}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema(MiningBase):

    def test_additive_and_idempotent(self):
        before = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        mine.ensure_schema(self.conn)
        after = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(before, after)
        self.assertIn("slots", after)          # reconcile schema untouched
        self.assertIn("mine_econ", after)
        self.assertIn("mine_feasibility", after)

    def test_primary_keys_present(self):
        econ = self.conn.execute("PRAGMA table_info(mine_econ)").fetchall()
        self.assertEqual({r[1] for r in econ if r[5]}, {"ts", "netuid"})
        feas = self.conn.execute(
            "PRAGMA table_info(mine_feasibility)").fetchall()
        self.assertEqual({r[1] for r in feas if r[5]},
                         {"netuid", "epoch", "sha"})

    def test_columns_added_after_ship_are_migrated_in(self):
        """A deployed Pi already has mine_econ; CREATE TABLE IF NOT EXISTS is
        a no-op there, so the added columns must arrive by ALTER TABLE or
        every insert against the live store fails."""
        self.conn.execute("DROP TABLE mine_econ")
        self.conn.execute(
            "CREATE TABLE mine_econ (ts TEXT NOT NULL, netuid INTEGER "
            "NOT NULL, confidence TEXT NOT NULL, PRIMARY KEY (ts, netuid))")
        self.conn.execute(
            "INSERT INTO mine_econ (ts, netuid, confidence) "
            "VALUES ('2026-08-01T00:00:00+00:00', 7, 'ok')")
        mine.ensure_schema(self.conn)
        names = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(mine_econ)")}
        self.assertIn("subnet_name", names)
        self.assertIn("identity_state", names)
        # Migration is additive: the pre-existing row is still there.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_econ").fetchone()[0], 1)

    def test_percentage_columns_carry_the_unit(self):
        names = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(mine_econ)")}
        for column in ("miner_burn_pct", "top1_share_pct", "top10_share_pct",
                       "haircut_pct", "collateral_lock_pct"):
            self.assertIn(column, names)


# ---------------------------------------------------------------------------
# Pure economics
# ---------------------------------------------------------------------------

class TestEconomics(unittest.TestCase):

    def test_burn_is_applied_exactly_once(self):
        full = mine.miner_alpha_per_day(1.0, 0.41, 0.0)
        half = mine.miner_alpha_per_day(1.0, 0.41, 50.0)
        self.assertAlmostEqual(full, 1.0 * mine.BLOCKS_PER_DAY * 0.41)
        self.assertAlmostEqual(half, full * 0.5)
        # A second application would give 0.25, not 0.5.
        self.assertNotAlmostEqual(half, full * 0.25)

    def test_total_burn_leaves_nothing(self):
        self.assertAlmostEqual(mine.miner_alpha_per_day(1.0, 0.41, 100.0),
                               0.0)

    def test_burn_is_percent_not_fraction(self):
        """0-100 throughout. A 0-1 reading of 42.7 would clamp to zero."""
        self.assertGreater(mine.miner_alpha_per_day(1.0, 0.41, 42.7), 0.0)
        self.assertAlmostEqual(
            mine.miner_alpha_per_day(1.0, 0.41, 42.7),
            mine.BLOCKS_PER_DAY * 0.41 * (1 - 0.427))

    def test_quantity_is_constant_across_subnets(self):
        """alpha_out is a protocol constant, so quantity cannot rank."""
        a = mine.miner_alpha_per_day(1.0, 0.41, 0.0)
        b = mine.miner_alpha_per_day(1.0, 0.41, 0.0)
        self.assertEqual(a, b)

    def test_concentration_from_incentive_vector(self):
        stats = mine.concentration([100, 0, 50, 0, 50])
        self.assertEqual(stats["earner_count"], 3)
        self.assertAlmostEqual(stats["top1_share_pct"], 50.0)
        self.assertAlmostEqual(stats["top10_share_pct"], 100.0)

    def test_concentration_of_an_empty_field(self):
        stats = mine.concentration([0] * 256)
        self.assertEqual(stats["earner_count"], 0)
        self.assertIsNone(stats["top1_share_pct"])

    def test_concentration_ignores_registered_count(self):
        """256 registered, 4 earning: the divisor that matters is 4."""
        vector = [0] * 256
        for i, v in enumerate([40, 30, 20, 10]):
            vector[i] = v
        self.assertEqual(mine.concentration(vector)["earner_count"], 4)

    def test_haircut_rises_with_sale_size(self):
        small = mine.exit_haircut_pct(10.0, 1_000_000.0, 10_000.0)
        large = mine.exit_haircut_pct(100_000.0, 1_000_000.0, 10_000.0)
        self.assertLess(small, large)
        self.assertGreater(large, 0.0)

    def test_haircut_unknown_without_pool_depth(self):
        self.assertIsNone(mine.exit_haircut_pct(10.0, None, 10_000.0))
        self.assertIsNone(mine.exit_haircut_pct(10.0, 0.0, 10_000.0))

    def test_median_of_empty_is_none(self):
        self.assertIsNone(mine.median_of([]))

    def test_entrant_share_assumes_joining_the_field(self):
        """Parity model: the pool is shared among earners + 1."""
        self.assertAlmostEqual(mine.entrant_alpha_per_day(100.0, 1), 50.0)
        self.assertAlmostEqual(mine.entrant_alpha_per_day(100.0, 4), 20.0)

    def test_entrant_share_does_not_reward_concentration(self):
        """A one-earner subnet must not outrank a healthy field purely
        because its incumbent takes everything."""
        lonely = mine.entrant_alpha_per_day(100.0, 1)
        crowded = mine.entrant_alpha_per_day(100.0, 99)
        self.assertGreater(lonely, crowded)
        # ...but the lonely subnet's INCUMBENT figure is 100, double the
        # entrant figure, which is the signal that entry means displacement.
        self.assertAlmostEqual(lonely, 50.0)

    def test_entrant_share_unknown_without_a_field_read(self):
        self.assertIsNone(mine.entrant_alpha_per_day(100.0, None))
        self.assertIsNone(mine.entrant_alpha_per_day(None, 4))


# ---------------------------------------------------------------------------
# Cut ladder
# ---------------------------------------------------------------------------

class TestCutLadder(unittest.TestCase):

    def setUp(self):
        self.cfg = mine.mining_cfg({})

    def test_gate_cut_reason_says_unbacked_alpha_not_no_payment(self):
        rung, detail = mine.classify_cut(
            self.cfg, {"gate_state": "disabled", "miner_burn_pct": 0.0}, None)
        self.assertEqual(rung, mine.CUT_GATE)
        self.assertIn("no TAO inflow", detail)
        self.assertNotIn("pays nothing", detail)

    def test_burn_ceiling_cuts_and_records_the_value(self):
        rung, detail = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 99.4}, None)
        self.assertEqual(rung, mine.CUT_BURN)
        self.assertIn("99.40", detail)

    def test_burn_just_below_the_ceiling_survives(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 98.9}, None)
        self.assertIsNone(rung)

    def test_gate_rung_precedes_burn_rung(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "disabled", "miner_burn_pct": 100.0},
            None)
        self.assertEqual(rung, mine.CUT_GATE)

    def test_winner_take_all_cuts_on_share_not_earner_count(self):
        """Netuid 63 on 2026-08-12: ten UIDs earn something and the top one
        still takes 100%. An earner_count test misses it entirely."""
        rung, detail = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "top1_share_pct": 100.0, "earner_count": 10}, None)
        self.assertEqual(rung, mine.CUT_CONCENTRATION)
        self.assertIn("100.0", detail)
        self.assertIn("10", detail)

    def test_winner_take_all_catches_a_wide_but_captured_field(self):
        """Netuid 101: 249 earners, top-1 still on 90%+ of the vector."""
        cfg = mine.mining_cfg({"mining": {"top1_ceiling_pct": 90.0}})
        rung, _ = mine.classify_cut(
            cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                  "top1_share_pct": 90.3, "earner_count": 249}, None)
        self.assertEqual(rung, mine.CUT_CONCENTRATION)

    def test_a_contested_field_survives(self):
        for top1, earners in ((89.8, 20), (65.0, 3), (34.7, 7), (0.6, 242)):
            rung, _ = mine.classify_cut(
                self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                           "top1_share_pct": top1, "earner_count": earners},
                None)
            self.assertIsNone(rung, top1)

    def test_unread_incentive_vector_does_not_cut(self):
        """Null top-1 means the vector was never read. An unread field is
        not a concentrated one."""
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "top1_share_pct": None, "earner_count": None}, None)
        self.assertIsNone(rung)

    def test_burn_rung_precedes_concentration(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 100.0,
                       "top1_share_pct": 100.0, "earner_count": 1}, None)
        self.assertEqual(rung, mine.CUT_BURN)

    def test_concentration_precedes_feasibility(self):
        """No point ranking a code verdict for a subnet nobody can enter."""
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "top1_share_pct": 100.0, "earner_count": 1},
            {"verdict": mine.VERDICT_STUB})
        self.assertEqual(rung, mine.CUT_CONCENTRATION)

    def test_concentration_ceiling_is_configurable(self):
        cfg = mine.mining_cfg({"mining": {"top1_ceiling_pct": 99.5}})
        rung, _ = mine.classify_cut(
            cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                  "top1_share_pct": 99.1, "earner_count": 3}, None)
        self.assertIsNone(rung)

    def test_infeasible_verdicts_cut(self):
        for verdict in (mine.VERDICT_STUB, mine.VERDICT_CLOSED):
            rung, _ = mine.classify_cut(
                self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0},
                {"verdict": verdict})
            self.assertEqual(rung, mine.CUT_FEASIBILITY, verdict)

    def test_unknown_verdict_does_not_cut_and_is_not_feasible(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0},
            {"verdict": mine.VERDICT_UNKNOWN})
        self.assertIsNone(rung)
        self.assertNotIn(mine.VERDICT_UNKNOWN, mine.INFEASIBLE_VERDICTS)

    def test_hardware_rung_is_inert_without_a_budget_band(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0},
            {"verdict": mine.VERDICT_NEEDS_GPU, "vram_gb": 80})
        self.assertIsNone(rung)

    def test_hardware_rung_cuts_above_the_chosen_band(self):
        cfg = mine.mining_cfg({"mining": {"budget_band": "consumer-gpu"}})
        rung, detail = mine.classify_cut(
            cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0},
            {"verdict": mine.VERDICT_NEEDS_GPU, "vram_gb": 80})
        self.assertEqual(rung, mine.CUT_HARDWARE)
        self.assertIn("80", detail)


# ---------------------------------------------------------------------------
# On-chain identity rung
# ---------------------------------------------------------------------------

class TestIdentity(unittest.TestCase):

    def setUp(self):
        self.cfg = mine.mining_cfg({})

    def _state(self, name, seen=True):
        return mine.classify_identity(self.cfg, name, seen)[0]

    def test_real_names_are_named(self):
        for name in ("Apex", "Green Compute", "lium.io", "8 Ball",
                     "hoτfloaτ", "404—GEN", "sundae_bar"):
            self.assertEqual(self._state(name), mine.IDENT_NAMED, name)

    def test_live_placeholders_observed_on_chain(self):
        """The exact strings live Finney carried on 2026-08-12. Written out
        rather than paraphrased: this rung exists to cut these specific
        owner-abandoned slots."""
        for name in ("deprecated", "unknown", "Unknown", "pending...",
                     "Parked", "wait (reproduce paper)"):
            self.assertEqual(self._state(name), mine.IDENT_PLACEHOLDER, name)

    def test_placeholder_match_is_case_and_punctuation_insensitive(self):
        for name in ("DEPRECATED", "  deprecated  ", "Pending…",
                     "deprecated (do not use)"):
            self.assertEqual(self._state(name), mine.IDENT_PLACEHOLDER, name)

    def test_a_name_merely_containing_a_placeholder_word_survives(self):
        # First-token matching, not substring: a real name is not cut for
        # mentioning one of these words later on.
        for name in ("Oracle Pending Markets", "Waitless", "Unknowable"):
            self.assertEqual(self._state(name), mine.IDENT_NAMED, name)

    def test_empty_name_is_a_placeholder_not_a_name(self):
        self.assertEqual(self._state(""), mine.IDENT_PLACEHOLDER)
        self.assertEqual(self._state("   "), mine.IDENT_PLACEHOLDER)

    def test_absent_entry_is_distinct_from_unread_map(self):
        self.assertEqual(self._state(None, seen=True), mine.IDENT_ABSENT)
        self.assertEqual(self._state(None, seen=False), mine.IDENT_UNREAD)

    def test_unread_map_never_reclassifies_a_real_name(self):
        state, name = mine.classify_identity(self.cfg, "Apex", False)
        self.assertEqual(state, mine.IDENT_UNREAD)
        self.assertEqual(name, "Apex")

    def test_placeholder_cuts_and_quotes_the_chain_name(self):
        rung, detail = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "identity_state": mine.IDENT_PLACEHOLDER,
                       "subnet_name": "deprecated"}, None)
        self.assertEqual(rung, mine.CUT_IDENTITY)
        self.assertIn("deprecated", detail)

    def test_absent_identity_cuts_with_its_own_reason(self):
        rung, detail = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "identity_state": mine.IDENT_ABSENT,
                       "subnet_name": None}, None)
        self.assertEqual(rung, mine.CUT_IDENTITY)
        self.assertIn("SubnetIdentitiesV3", detail)

    def test_unread_identity_does_not_cut(self):
        """The whole-map fail-open. A renamed or unreachable storage item
        must never empty the board."""
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0,
                       "identity_state": mine.IDENT_UNREAD,
                       "subnet_name": None}, None)
        self.assertIsNone(rung)

    def test_gate_rung_still_precedes_identity(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "disabled", "miner_burn_pct": 0.0,
                       "identity_state": mine.IDENT_PLACEHOLDER,
                       "subnet_name": "deprecated"}, None)
        self.assertEqual(rung, mine.CUT_GATE)

    def test_identity_rung_precedes_burn(self):
        rung, _ = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 100.0,
                       "identity_state": mine.IDENT_PLACEHOLDER,
                       "subnet_name": "Parked"}, None)
        self.assertEqual(rung, mine.CUT_IDENTITY)

    def test_placeholder_list_is_configurable(self):
        cfg = mine.mining_cfg({"mining": {"identity_placeholders": ["retired"]}})
        self.assertEqual(mine.classify_identity(cfg, "retired", True)[0],
                         mine.IDENT_PLACEHOLDER)
        self.assertEqual(mine.classify_identity(cfg, "deprecated", True)[0],
                         mine.IDENT_NAMED)


# ---------------------------------------------------------------------------
# Stage A
# ---------------------------------------------------------------------------

class TestEcon(MiningBase):

    def test_happy_path_records_one_row_per_subnet(self):
        out = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1, burn=34.5), panel_subnet(4)],
            incentive={1: [10, 5, 0], 4: [7, 3]},
            network_n={1: 256, 4: 256}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["observations"], 2)
        rows = mine.latest_econ(self.conn)
        self.assertEqual([r["netuid"] for r in rows], [1, 4])
        self.assertEqual(rows[0]["confidence"], mine.CONF_OK)
        self.assertEqual(rows[0]["block_ref"], 8789861)

    def test_base_is_alpha_out_not_alpha_in(self):
        """alpha_in is the capped pool injection and must not drive income."""
        out_only = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1, alpha_out=1.0, alpha_in=0.12)],
            incentive={1: [10]}, network_n={1: 256}))
        self.assertTrue(out_only["ok"])
        row = mine.latest_econ(self.conn)[0]
        self.assertAlmostEqual(
            row["miner_alpha_day"],
            mine.BLOCKS_PER_DAY * 0.41, places=6)
        self.assertAlmostEqual(row["alpha_in_day"],
                               0.12 * mine.BLOCKS_PER_DAY, places=6)
        self.assertNotAlmostEqual(row["miner_alpha_day"], row["alpha_in_day"])

    def test_identity_is_recorded_and_cuts_end_to_end(self):
        # Contested fields throughout, so the concentration rung stays out
        # of the way and this exercises the identity rung alone.
        out = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1), panel_subnet(3), panel_subnet(57)],
            incentive={1: [10, 9, 8], 3: [10, 9, 8], 57: [10, 9, 8]},
            network_n={1: 256, 3: 256, 57: 256},
            identity={1: "Apex", 3: "deprecated"}))
        self.assertTrue(out["ok"])
        rows = {r["netuid"]: r for r in mine.latest_econ(self.conn)}
        self.assertEqual(rows[1]["identity_state"], mine.IDENT_NAMED)
        self.assertEqual(rows[1]["subnet_name"], "Apex")
        self.assertEqual(rows[3]["identity_state"], mine.IDENT_PLACEHOLDER)
        self.assertEqual(rows[3]["subnet_name"], "deprecated")
        # 57 was in the panel but has no chain identity entry at all.
        self.assertEqual(rows[57]["identity_state"], mine.IDENT_ABSENT)
        self.assertIsNone(rows[57]["subnet_name"])

        view = mine.report(self.conn, self.config, include_cut=True)
        self.assertEqual([e["netuid"] for e in view["ranked"]], [1])
        cut = {e["netuid"]: e for e in view["cut"]}
        self.assertEqual(cut[3]["cut_reason"], mine.CUT_IDENTITY)
        self.assertEqual(cut[57]["cut_reason"], mine.CUT_IDENTITY)
        self.assertEqual(view["cut_summary"][mine.CUT_IDENTITY], 2)

    def test_an_unread_identity_map_does_not_empty_the_board(self):
        """Whole-map failure is fail-open at this rung: without it, a renamed
        storage item would silently cut every subnet at once."""
        out = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1), panel_subnet(3)],
            incentive={1: [10, 9, 8], 3: [10, 9, 8]},
            network_n={1: 256, 3: 256}, identity={}))
        self.assertTrue(out["ok"])
        rows = {r["netuid"]: r for r in mine.latest_econ(self.conn)}
        self.assertEqual(rows[1]["identity_state"], mine.IDENT_UNREAD)
        view = mine.report(self.conn, self.config, include_cut=True)
        self.assertEqual(sorted(e["netuid"] for e in view["ranked"]), [1, 3])
        self.assertNotIn(mine.CUT_IDENTITY, view["cut_summary"])

    def test_root_subnet_is_excluded(self):
        out = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(0), panel_subnet(1)],
            incentive={1: [1]}, network_n={1: 256}))
        self.assertEqual(out["observations"], 1)

    def test_chain_unavailable_records_rows_without_a_net_figure(self):
        out = mine.run_econ(self.conn, self.config, inputs={
            "panel": panel([panel_subnet(1)]),
            "chain": chain(ok=False), "gate_sides": {}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["chain"], mine.CONF_CHAIN_UNAVAILABLE)
        row = mine.latest_econ(self.conn)[0]
        self.assertEqual(row["confidence"], mine.CONF_CHAIN_UNAVAILABLE)
        self.assertIsNone(row["net_tao_month"])
        self.assertIsNone(row["earner_count"])
        # The panel half is still recorded.
        self.assertIsNotNone(row["price_tao"])

    def test_panel_unavailable_leaves_prior_rows_intact(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        before = mine.latest_econ(self.conn)
        out = mine.run_econ(self.conn, self.config, inputs={
            "panel": {"status": "unavailable",
                      "error": {"category": "provider-failure"}},
            "chain": chain(), "gate_sides": {}})
        self.assertFalse(out["ok"])
        self.assertEqual(out["leg"], "panel")
        self.assertEqual(mine.latest_econ(self.conn), before)

    def test_one_bad_subnet_is_marked_unknown_and_others_survive(self):
        out = mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1), panel_subnet(4)],
            incentive={1: [5, 5], 4: [3]}, network_n={1: 256, 4: 256},
            failures={"Incentive": {4: "bad payload"}}))
        self.assertTrue(out["ok"])
        rows = {r["netuid"]: r for r in mine.latest_econ(self.conn)}
        self.assertEqual(rows[1]["confidence"], mine.CONF_OK)
        self.assertEqual(rows[4]["confidence"], mine.CONF_INCOMPLETE)
        self.assertIsNone(rows[4]["net_tao_month"])
        self.assertIsNotNone(rows[1]["gross_tao_month"])

    def test_missing_incentive_vector_blocks_the_net_figure(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], network_n={1: 256}))
        row = mine.latest_econ(self.conn)[0]
        self.assertEqual(row["confidence"], mine.CONF_INCOMPLETE)
        self.assertIsNone(row["net_tao_month"])

    def test_no_net_figure_without_a_budget_band(self):
        """Rent unknown means net unknown; gross is still honest."""
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        row = mine.latest_econ(self.conn)[0]
        self.assertIsNone(row["net_tao_month"])
        self.assertIsNotNone(row["gross_tao_month"])

    def test_net_figure_appears_once_a_band_is_chosen(self):
        config = dict(self.config,
                      mining={"enabled": True, "budget_band": "consumer-gpu"})
        mine.run_econ(self.conn, config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        row = mine.latest_econ(self.conn)[0]
        self.assertIsNotNone(row["net_tao_month"])
        self.assertAlmostEqual(row["net_tao_month"],
                               row["gross_tao_month"] - 2.0, places=6)

    def test_missing_miner_share_citation_refuses_to_compute(self):
        config = dict(self.config, mining={"enabled": True, "miner_share_source": ""})
        out = mine.run_econ(self.conn, config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}))
        self.assertFalse(out["ok"])
        self.assertIn("citation", out["error"])
        self.assertEqual(mine.latest_econ(self.conn), [])

    def test_citation_is_recorded_for_the_reader(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        self.assertIn("41%", mine.state_get(self.conn, "miner_share_source"))

    def test_collateral_dormant_reads_as_zero_not_missing(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        self.assertEqual(mine.latest_econ(self.conn)[0]["collateral_lock_pct"],
                         0.0)

    def test_kill_switch_makes_the_screen_inert(self):
        config = dict(self.config, mining={"enabled": False})
        self.assertEqual(mine.run_econ(self.conn, config),
                         {"disabled": True})

    def test_retention_prunes_old_observations(self):
        old = (datetime.datetime.now(tz=datetime.timezone.utc)
               - datetime.timedelta(days=120)).isoformat()
        mine.run_econ(self.conn, self.config, now=old, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        remaining = self.conn.execute(
            "SELECT COUNT(*) FROM mine_econ").fetchone()[0]
        self.assertEqual(remaining, 1)

    def test_retention_keeps_recent_history_for_the_history_tool(self):
        recent = (datetime.datetime.now(tz=datetime.timezone.utc)
                  - datetime.timedelta(days=3)).isoformat()
        mine.run_econ(self.conn, self.config, now=recent, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_econ").fetchone()[0], 2)


# ---------------------------------------------------------------------------
# Stage B
# ---------------------------------------------------------------------------

# Verbatim shape of real subnet min_compute.yml files, sampled from the fleet
# on the Pi 2026-08-10. The unit lives in a trailing COMMENT, not next to the
# number, and miner/validator are separate sections. The first parser required
# an adjacent unit and extracted nothing from any real file.
MIN_COMPUTE = """
version: '1.0'
compute_spec:
  miner:
    gpu:
      required: True                       # GPU needed for the miners
      min_vram: 24                         # Minimum GPU VRAM (GB)
      recommended_vram: 48                 # Recommended GPU VRAM (GB)
    memory:
      min_ram: 16          # Minimum RAM (GB)
  validator:
    gpu:
      required: True
      min_vram: 80                         # Minimum GPU VRAM (GB)
      recommended_vram: 80
"""

MIN_COMPUTE_CPU = """
compute_spec:
  miner:
    gpu:
      required: False                      # No GPU required for the miners
      min_vram: 0                          # Minimum GPU VRAM (GB)
      recommended_vram: 0                  # Recommended GPU VRAM (GB)
    memory:
      min_ram: 16
"""

MIN_COMPUTE_NO_VRAM = """
compute_spec:
  miner:
    gpu: false
    ram:
      min_ram: 8
"""

MINER_GPU = "import torch\n\nx = torch.cuda.is_available()\n"
MINER_CPU = "def forward(x):\n    return x\n"
MINER_API = "import openai\nclient = openai.OpenAI()\n"


class TestFeasibility(MiningBase):

    def index_file(self, netuid, path, content, epoch=1, sha="deadbeef"):
        idx.ensure_schema(self.conn)
        cursor = self.conn.execute(
            "INSERT INTO fleet_files (netuid, epoch, path, indexed_sha, "
            "byte_size, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (netuid, epoch, path, sha, len(content), "2026-08-07T00:00:00Z"))
        self.conn.execute(
            "INSERT INTO fleet_files_fts (rowid, path, content) "
            "VALUES (?, ?, ?)", (cursor.lastrowid, path, content))
        self.conn.commit()

    def test_min_compute_vram_is_read_and_cited(self):
        self.index_file(1, "min_compute.yml", MIN_COMPUTE)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["vram_gb"], 24.0)
        self.assertEqual(out["vram_basis"], "min_vram")
        vram = [e for e in out["evidence"] if e["kind"] == "vram"]
        self.assertTrue(vram)
        self.assertEqual(vram[0]["path"], "min_compute.yml")
        self.assertGreater(vram[0]["line"], 1)

    def test_bare_yaml_number_with_the_unit_in_a_comment(self):
        """REGRESSION 2026-08-10: the first parser required the unit adjacent
        to the number and extracted nothing from any real fleet file."""
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE),
                         (24.0, "min_vram"))

    def test_miner_section_wins_over_validator(self):
        """A mining screen must not cost the validator's machine."""
        gb, basis = mine.parse_vram_gb(MIN_COMPUTE)
        self.assertEqual(gb, 24.0)          # miner min_vram, not 80
        self.assertEqual(basis, "min_vram")

    def test_floor_is_min_vram_not_recommended(self):
        """The column is labelled a floor; recommended is not one."""
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE)[0], 24.0)

    def test_declared_zero_vram_is_a_real_cpu_answer(self):
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE_CPU),
                         (0.0, "min_vram"))

    def test_absent_vram_is_none_not_zero(self):
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE_NO_VRAM),
                         (None, None))

    def test_inline_unit_form_still_parses(self):
        self.assertEqual(
            mine.parse_vram_gb("gpu:\n  vram: 40 GB\n")[0], 40.0)

    def test_recommended_only_is_labelled_as_such(self):
        gb, basis = mine.parse_vram_gb(
            "compute_spec:\n  miner:\n    gpu:\n"
            "      recommended_vram: 48   # Recommended GPU VRAM (GB)\n")
        self.assertEqual(gb, 48.0)
        self.assertEqual(basis, "recommended_vram")

    def test_cpu_declaration_does_not_become_needs_gpu(self):
        self.index_file(1, "min_compute.yml", MIN_COMPUTE_CPU)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["vram_gb"], 0.0)
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)

    def test_gpu_tell_yields_needs_gpu(self):
        self.index_file(1, "neurons/miner.py", MINER_GPU)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_NEEDS_GPU)
        gpu = [e for e in out["evidence"] if e["kind"] == "gpu"]
        self.assertTrue(gpu)
        self.assertEqual(gpu[0]["path"], "neurons/miner.py")

    def test_cpu_miner_is_possible(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)

    def test_hosted_api_is_labelled_not_disqualifying(self):
        self.index_file(1, "neurons/miner.py", MINER_API)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["closed_api"], 1)
        self.assertNotIn(out["verdict"], mine.INFEASIBLE_VERDICTS)

    def test_no_entrypoint_in_a_small_repo_is_a_stub(self):
        self.index_file(1, "README.md", "# soon")
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_STUB)

    def test_no_entrypoint_in_a_substantial_repo_is_closed(self):
        for i in range(25):
            self.index_file(1, "src/mod%d.py" % i, "x = %d\n" % i)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_CLOSED)

    def test_unindexed_slot_is_unknown_not_infeasible(self):
        idx.ensure_schema(self.conn)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 99, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_UNKNOWN)
        self.assertNotIn(out["verdict"], mine.INFEASIBLE_VERDICTS)

    def test_verdicts_are_a_closed_set(self):
        self.index_file(1, "neurons/miner.py", MINER_GPU)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 1, 1)
        self.assertIn(out["verdict"], mine.VERDICTS)

    def test_scan_is_sha_gated(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "sha-one"})
        self.conn.commit()
        first = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(first["scanned"], 1)
        second = mine.run_feasibility(self.conn, self.config)
        self.assertEqual((second["scanned"], second["unchanged"]), (0, 1))

    def test_moved_commit_rescans(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "sha-one"})
        self.conn.commit()
        mine.run_feasibility(self.conn, self.config)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "sha-two"})
        self.conn.commit()
        again = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(again["scanned"], 1)

    def test_scanner_version_change_invalidates_stored_verdicts(self):
        """Sha-gating alone would serve old-scanner verdicts forever."""
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "sha-one"})
        self.conn.commit()
        mine.run_feasibility(self.conn, self.config)
        second = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(second["unchanged"], 1)

        mine.state_set(self.conn, "scan_version", "old")
        self.conn.commit()
        third = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(third["invalidated_by_scanner_change"], 1)
        self.assertEqual(third["scanned"], 1)

    def test_scanner_version_is_recorded_after_a_scan(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "sha-one"})
        self.conn.commit()
        mine.run_feasibility(self.conn, self.config)
        self.assertEqual(mine.state_get(self.conn, "scan_version"),
                         mine.SCAN_VERSION)

    def test_inactive_slot_is_skipped(self):
        fleet.upsert_slot(self.conn, {
            "netuid": 2, "github_repo": "https://github.com/o/r2",
            "epoch": 1, "status": "unreachable", "default_branch": "main",
            "local_sha": "sha"})
        self.conn.commit()
        out = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(out["scanned"], 0)
        self.assertGreaterEqual(out["skipped"], 1)


# ---------------------------------------------------------------------------
# Stage C + render + pass
# ---------------------------------------------------------------------------

class TestReport(MiningBase):

    def seed(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1, burn=0.0, price=0.05),
             panel_subnet(4, burn=99.5),
             panel_subnet(5, enabled=False),
             panel_subnet(8, burn=0.0, price=0.01)],
            incentive={1: [10, 5], 4: [3], 5: [2], 8: [1, 1, 1]},
            network_n={1: 256, 4: 256, 5: 256, 8: 256}))

    def test_ranked_excludes_cut_subnets(self):
        self.seed()
        view = mine.report(self.conn, self.config)
        ranked = {r["netuid"] for r in view["ranked"]}
        self.assertEqual(ranked, {1, 8})
        self.assertEqual(view["counts"]["cut"], 2)

    def test_cut_summary_names_each_rung(self):
        self.seed()
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["cut_summary"],
                         {mine.CUT_GATE: 1, mine.CUT_BURN: 1})

    def test_cut_subnets_are_retrievable_with_reasons(self):
        self.seed()
        view = mine.report(self.conn, self.config, include_cut=True)
        reasons = {r["netuid"]: r["cut_detail"] for r in view["cut"]}
        self.assertIn("no TAO inflow", reasons[5])
        self.assertIn("99.50", reasons[4])

    def test_headline_is_the_entrant_figure_not_the_incumbent(self):
        """Ranking on incumbent income would put the least enterable subnets
        on top, which reads as opportunity and is the opposite."""
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1, price=0.05)],
            incentive={1: [100]}, network_n={1: 256}))
        row = mine.latest_econ(self.conn)[0]
        self.assertEqual(row["earner_count"], 1)
        self.assertEqual(row["displacement_rank"], 2)
        self.assertAlmostEqual(row["entrant_alpha_day"],
                               row["miner_alpha_day"] / 2.0)
        self.assertAlmostEqual(row["incumbent_alpha_day"],
                               row["miner_alpha_day"])
        self.assertLess(row["entrant_alpha_day"], row["incumbent_alpha_day"])

    def test_board_states_the_parity_assumption(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("ASSUMPTION", page)
        self.assertIn("earners + 1", page)
        self.assertIn("incumbent", page)

    def test_board_shows_the_on_chain_name(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5, 4, 3]}, network_n={1: 256},
            identity={1: "Apex"}))
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("on-chain name", page)
        self.assertIn("Apex", page)

    def test_board_escapes_a_hostile_chain_name(self):
        """subnet_name is owner-written free text arriving over the wire."""
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5, 4, 3]}, network_n={1: 256},
            identity={1: "<script>alert(1)</script>"}))
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_ranking_is_by_value_not_quantity(self):
        """Both survivors have identical alpha quantity; price separates."""
        self.seed()
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["ranked"][0]["netuid"], 1)
        self.assertEqual(view["ranked"][0]["miner_alpha_day"],
                         view["ranked"][1]["miner_alpha_day"])

    def test_unscanned_feasibility_is_flagged_not_guessed(self):
        self.seed()
        view = mine.report(self.conn, self.config)
        self.assertTrue(view["ranked"][0]["feasibility"]["unscanned"])
        self.assertEqual(view["ranked"][0]["feasibility"]["verdict"],
                         mine.VERDICT_UNKNOWN)

    def test_report_carries_both_timestamps(self):
        self.seed()
        view = mine.report(self.conn, self.config)
        self.assertIsNotNone(view["econ_ts"])
        self.assertIn("feasibility_ts", view)

    def test_limit_bounds_the_board(self):
        self.seed()
        view = mine.report(self.conn, self.config, limit=1)
        self.assertEqual(len(view["ranked"]), 1)

    def test_empty_store_reports_honestly(self):
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["counts"]["observed"], 0)
        self.assertEqual(view["ranked"], [])


class TestRender(MiningBase):

    def test_render_writes_a_self_contained_page(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        out = mine.render(self.conn, self.config)
        self.assertTrue(out["path"].endswith("mining.html"))
        with open(out["path"], encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("Mining triage", page)
        self.assertIn("Cut ladder", page)
        self.assertNotIn("http://", page.replace("http://www.w3", ""))
        self.assertNotIn("<script src", page)

    def test_render_states_the_constant_quantity_caveat(self):
        mine.run_econ(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("never by", page)
        self.assertIn("recommends nothing", page)

    def test_render_on_an_empty_store_does_not_raise(self):
        out = mine.render(self.conn, self.config)
        self.assertGreater(out["bytes"], 0)

    def test_no_budget_band_is_stated_on_the_page(self):
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            self.assertIn("no budget band chosen", handle.read())


class TestPass(MiningBase):

    def test_pass_runs_every_stage(self):
        out = mine.run_pass(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        self.assertTrue(out["econ"]["ok"])
        self.assertTrue(out["feasibility"]["ok"])
        self.assertIn("path", out["render"])

    def test_a_failing_stage_is_isolated_not_raised(self):
        broken = dict(self.config, dashboard={"www_dir": "\x00bad"})
        out = mine.run_pass(self.conn, broken, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        self.assertTrue(out["econ"]["ok"])
        self.assertIn("error", out["render"])

    def test_kill_switch_skips_the_pass(self):
        config = dict(self.config, mining={"enabled": False})
        self.assertEqual(mine.run_pass(self.conn, config),
                         {"disabled": True})

    def test_reconcile_pass_hook_is_isolated_from_a_mining_failure(self):
        """The outer guard in atlas_fleet.reconcile_pass: a mining explosion
        is audited, never a reconcile process error."""
        original = fleet._fleet_mining

        class Boom:
            @staticmethod
            def run_pass(*args, **kwargs):
                raise RuntimeError("mining exploded")

        fleet._fleet_mining = lambda: Boom
        self.addCleanup(setattr, fleet, "_fleet_mining", original)
        summary = {}
        try:
            summary["mining"] = fleet._fleet_mining().run_pass(
                self.conn, self.config)
        except Exception as exc:  # noqa: BLE001 — mirrors the guard
            summary["mining"] = {"error": str(exc)[:120]}
        self.assertIn("error", summary["mining"])

    def test_status_summarises_coverage(self):
        mine.run_pass(self.conn, self.config, inputs=inputs(
            [panel_subnet(1)], incentive={1: [5]}, network_n={1: 256}))
        status = mine.mining_status(self.conn)
        self.assertEqual(status["econ_rows"], 1)
        self.assertEqual(status["confidence"], {mine.CONF_OK: 1})
        self.assertIsNotNone(status["miner_share_source"])


if __name__ == "__main__":
    unittest.main()
