"""Mining triage (changes: mining-triage, mining-board-accuracy): the chain
economics model (per-mechanism pools, owner UIDs removed and reconciled,
chain-sourced miner share, Balancer price), the ordered cut ladder with
recorded reasons, sha-gated feasibility that never cuts on absence, the
stored ranking every surface reads, the board, and pass fail-isolation."""

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
import mining_fixtures as mf  # noqa: E402
from mining_fixtures import subnet, synthetic  # noqa: E402

SHARE = 0.5 * (1 - 11796 / 65535.0)


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

    def seed(self, subnets, now=None, config=None, **kwargs):
        return mf.seed_board(self.conn, config or self.config,
                             synthetic(subnets, **kwargs), now=now)

    def rows(self):
        return {r["netuid"]: r for r in mine.latest_econ(self.conn)}

    def econ_rows(self):
        cursor = self.conn.execute("SELECT * FROM mine_econ")
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, r)) for r in cursor.fetchall()]

    def page(self):
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            return handle.read()


def mech(mecid=0, split=1.0, earners=5, top1=40.0, **extra):
    return dict({"mecid": mecid, "split": split,
                 "indep_earner_count": earners,
                 "indep_top1_share_pct": top1}, **extra)


OPEN = [mech()]


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
        for table in ("mine_econ", "mine_mechanism", "mine_feasibility"):
            self.assertIn(table, after)

    def test_primary_keys_present(self):
        def keys(table):
            return {r[1] for r in self.conn.execute(
                "PRAGMA table_info(%s)" % table) if r[5]}
        self.assertEqual(keys("mine_econ"), {"ts", "netuid"})
        self.assertEqual(keys("mine_mechanism"), {"ts", "netuid", "mecid"})
        self.assertEqual(keys("mine_feasibility"), {"netuid", "epoch", "sha"})

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
        for column in ("subnet_name", "identity_state", "rank", "rank_mecid",
                       "unrated_reason", "owner_share_pct",
                       "owner_reconcile_delta", "balancer_quote",
                       "immunity_period", "uids_full", "alpha_issuance",
                       "miner_share"):
            self.assertIn(column, names)
        # Migration is additive: the pre-existing row is still there.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_econ").fetchone()[0], 1)

    def test_percentage_columns_carry_the_unit(self):
        names = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(mine_econ)")}
        for column in ("miner_burn_pct", "top1_share_pct", "top10_share_pct",
                       "haircut_pct", "collateral_lock_pct",
                       "owner_share_pct"):
            self.assertIn(column, names)


# ---------------------------------------------------------------------------
# Pure economics
# ---------------------------------------------------------------------------

class TestEconomics(unittest.TestCase):

    def test_miner_share_follows_the_chain_owner_cut(self):
        self.assertAlmostEqual(mine.miner_share(11796, True), SHARE)
        self.assertAlmostEqual(mine.miner_share(11796, True), 0.410002,
                               places=6)

    def test_owner_cut_disabled_gives_half(self):
        self.assertAlmostEqual(mine.miner_share(11796, False), 0.5)

    def test_split_is_over_u16_max_or_even(self):
        self.assertEqual(mine.mechanism_split(2, [0, 65535]), [0.0, 1.0])
        self.assertAlmostEqual(mine.mechanism_split(2, [1311, 64224])[0],
                               0.02, places=3)
        self.assertEqual(mine.mechanism_split(2, None), [0.5, 0.5])
        # A split whose length does not match the count is legacy or
        # malformed; the runtime divides evenly (mechanism.rs:235-252).
        self.assertEqual(mine.mechanism_split(2, [65535]), [0.5, 0.5])
        self.assertEqual(mine.mechanism_split(1, None), [1.0])

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

    def test_price_is_the_weighted_pool_spot(self):
        self.assertAlmostEqual(mine.pool_price(100.0, 1000.0, 0.5), 0.1)
        # A quote weight of 0.25 triples the spot: (1 - q) / q = 3.
        self.assertAlmostEqual(mine.pool_price(100.0, 1000.0, 0.25), 0.3)
        self.assertIsNone(mine.pool_price(None, 1000.0, 0.5))
        self.assertIsNone(mine.pool_price(100.0, 1000.0, None))

    def test_haircut_at_half_weight_is_constant_product(self):
        a, t, sale = 1_000_000.0, 10_000.0, 50_000.0
        proceeds = t - t * a / (a + sale)
        expected = 100.0 * (1 - proceeds / (sale * t / a))
        self.assertAlmostEqual(mine.exit_haircut_pct(sale, a, t, 0.5),
                               expected)

    def test_balancer_weight_changes_price_and_haircut(self):
        half = mine.exit_haircut_pct(50_000.0, 1_000_000.0, 10_000.0, 0.5)
        skewed = mine.exit_haircut_pct(50_000.0, 1_000_000.0, 10_000.0, 0.3)
        self.assertNotAlmostEqual(half, skewed)
        self.assertNotAlmostEqual(mine.pool_price(1.0, 1.0, 0.5),
                                  mine.pool_price(1.0, 1.0, 0.3))

    def test_haircut_rises_with_sale_size(self):
        small = mine.exit_haircut_pct(10.0, 1_000_000.0, 10_000.0)
        large = mine.exit_haircut_pct(100_000.0, 1_000_000.0, 10_000.0)
        self.assertLess(small, large)
        self.assertGreater(large, 0.0)

    def test_haircut_unknown_without_pool_depth_or_weight(self):
        self.assertIsNone(mine.exit_haircut_pct(10.0, None, 10_000.0))
        self.assertIsNone(mine.exit_haircut_pct(10.0, 0.0, 10_000.0))
        self.assertIsNone(mine.exit_haircut_pct(10.0, 1e6, 1e4, None))

    def test_median_of_empty_is_none(self):
        self.assertIsNone(mine.median_of([]))

    def test_entrant_share_assumes_joining_the_field(self):
        """Parity model: the independent pool is shared among earners + 1."""
        self.assertAlmostEqual(mine.entrant_alpha_per_day(100.0, 1), 50.0)
        self.assertAlmostEqual(mine.entrant_alpha_per_day(100.0, 4), 20.0)

    def test_entrant_share_is_undefined_with_no_earner(self):
        """A pool divided by one would rank an empty field first."""
        self.assertIsNone(mine.entrant_alpha_per_day(100.0, 0))
        self.assertIsNone(mine.entrant_alpha_per_day(100.0, None))
        self.assertIsNone(mine.entrant_alpha_per_day(None, 4))


class TestMechanismEconomics(unittest.TestCase):

    def run_mech(self, vector, owners, split=1.0):
        return mine.mechanism_economics(
            mine.mining_cfg({}), 0, split, vector, owners, 1000.0, 0.01,
            3_000_000.0, 25_000.0, 0.5, None)

    def test_owner_uid_is_removed_from_the_field(self):
        """SN9 at block 9142723: the owner UID holds 49.77% and one
        independent UID 99.56% of the rest."""
        vector = [0] * 256
        vector[209], vector[171], vector[5] = 4977, 5001, 22
        out = self.run_mech(vector, [209])
        self.assertEqual(out["earner_count"], 3)
        self.assertEqual(out["indep_earner_count"], 2)
        self.assertAlmostEqual(out["owner_share_pct"], 49.77)
        self.assertAlmostEqual(out["indep_top1_share_pct"],
                               100.0 * 5001 / 5023)
        self.assertAlmostEqual(out["indep_alpha_day"], 1000.0 * 0.5023)
        # Divisor is independent earners + 1, not all earners + 1.
        self.assertAlmostEqual(out["entrant_alpha_day"],
                               out["indep_alpha_day"] / 3)

    def test_owner_uid_does_not_inflate_the_parity_divisor(self):
        """4 earning UIDs, one of them the owner's: divide by 4, not 5."""
        out = self.run_mech([10, 10, 10, 10], [0])
        self.assertEqual(out["indep_earner_count"], 3)
        self.assertEqual(out["displacement_rank"], 4)
        self.assertAlmostEqual(out["entrant_alpha_day"],
                               out["indep_alpha_day"] / 4)

    def test_incumbent_is_an_independent_earner(self):
        out = self.run_mech([90, 5, 5], [0])
        self.assertAlmostEqual(out["incumbent_alpha_day"],
                               out["indep_alpha_day"] / 2)

    def test_owner_only_field_has_no_entrant_figure(self):
        out = self.run_mech([0, 40, 0], [1])
        self.assertEqual(out["indep_earner_count"], 0)
        self.assertIsNone(out["entrant_alpha_day"])
        self.assertEqual(out["no_figure_reason"], mine.MECH_EMPTY)

    def test_zero_earner_field_needs_no_owner_read(self):
        out = self.run_mech([0, 0, 0], None)
        self.assertEqual(out["indep_earner_count"], 0)
        self.assertEqual(out["owner_share_pct"], 0.0)

    def test_unread_owner_set_leaves_the_field_unknown(self):
        out = self.run_mech([5, 5], None)
        self.assertIsNone(out["indep_earner_count"])
        self.assertEqual(out["no_figure_reason"], mine.CONF_OWNERS_UNREAD)

    def test_unread_vector_is_marked(self):
        out = self.run_mech(None, [0])
        self.assertEqual(out["incentive_read"], 0)
        self.assertIsNone(out["indep_earner_count"])

    def test_zero_split_mechanism_has_no_figure(self):
        out = self.run_mech([5, 5], [], split=0.0)
        self.assertEqual(out["no_figure_reason"], mine.MECH_ZERO_SPLIT)
        self.assertIsNone(out["gross_tao_month"])


# ---------------------------------------------------------------------------
# Cut ladder
# ---------------------------------------------------------------------------

class TestCutLadder(unittest.TestCase):

    def setUp(self):
        self.cfg = mine.mining_cfg({})

    def cut(self, row, mechs=OPEN, feasibility=None, cfg=None):
        base = {"gate_state": "enabled", "miner_burn_pct": 0.0,
                "identity_state": mine.IDENT_NAMED}
        base.update(row)
        rung, detail, _ = mine.classify_cut(cfg or self.cfg, base, mechs,
                                            feasibility)
        return rung, detail

    def test_gate_cut_reason_says_unbacked_alpha_not_no_payment(self):
        rung, detail = self.cut({"gate_state": "disabled"})
        self.assertEqual(rung, "pool-side-switch-off")
        self.assertIn("pool-side emission switch", detail)
        self.assertIn("no TAO inflow", detail)
        self.assertNotIn("pays nothing", detail)
        self.assertNotIn("emission gate", detail)
        self.assertNotIn("demand", detail.lower())

    def test_burn_ceiling_cuts_and_records_the_value(self):
        rung, detail = self.cut({"miner_burn_pct": 99.4})
        self.assertEqual(rung, mine.CUT_BURN)
        self.assertIn("99.40", detail)

    def test_burn_just_below_the_ceiling_survives(self):
        self.assertIsNone(self.cut({"miner_burn_pct": 98.9})[0])

    def test_gate_rung_precedes_burn_rung(self):
        rung, _ = self.cut({"gate_state": "disabled",
                            "miner_burn_pct": 100.0})
        self.assertEqual(rung, mine.CUT_GATE)

    def test_zero_earner_field_is_cut_at_no_independent_earner(self):
        rung, detail = self.cut({}, [mech(earners=0, top1=None)])
        self.assertEqual(rung, mine.CUT_NO_EARNER)
        self.assertIn("no paying independent miner", detail)

    def test_owner_only_field_is_cut_at_no_independent_earner(self):
        rung, _ = self.cut({}, [mech(earners=0, top1=None),
                                mech(1, 0.0, earners=0, top1=None)])
        self.assertEqual(rung, mine.CUT_NO_EARNER)

    def test_burn_rung_precedes_no_independent_earner(self):
        rung, _ = self.cut({"miner_burn_pct": 100.0},
                           [mech(earners=0, top1=None)])
        self.assertEqual(rung, mine.CUT_BURN)

    def test_unknown_field_is_not_an_empty_one(self):
        rung, _ = self.cut({}, [mech(earners=None, top1=None)])
        self.assertIsNone(rung)

    def test_winner_take_all_cuts_on_share_not_earner_count(self):
        """Netuid 63 on 2026-08-12: ten UIDs earn and the top one still
        takes 100%. An earner-count test misses it entirely."""
        rung, detail = self.cut({}, [mech(earners=10, top1=100.0)])
        self.assertEqual(rung, mine.CUT_CONCENTRATION)
        self.assertIn("100.0", detail)
        self.assertIn("10 independent earner", detail)

    def test_owner_share_hides_a_winner_take_all_field(self):
        """SN9: the owner holds 49.77%, so the raw top-1 is 50%. On the
        independent field one UID holds 99.56%."""
        rung, detail = self.cut({}, [mech(earners=2, top1=99.56)])
        self.assertEqual(rung, mine.CUT_CONCENTRATION)
        self.assertIn("99.6", detail)

    def test_one_open_mechanism_keeps_the_subnet(self):
        mechs = [mech(0, 0.3, earners=1, top1=100.0),
                 mech(1, 0.7, earners=8, top1=30.0)]
        rung, _, rungs = mine.classify_cut(
            self.cfg, {"gate_state": "enabled", "miner_burn_pct": 0.0},
            mechs, None)
        self.assertIsNone(rung)
        self.assertEqual(rungs, {0: mine.MECH_CONCENTRATED})

    def test_a_zero_split_mechanism_cannot_keep_the_subnet(self):
        mechs = [mech(0, 1.0, earners=1, top1=100.0),
                 mech(1, 0.0, earners=8, top1=30.0)]
        rung, _ = self.cut({}, mechs)
        self.assertEqual(rung, mine.CUT_CONCENTRATION)

    def test_every_live_mechanism_concentrated_or_empty_is_cut(self):
        mechs = [mech(0, 0.02, earners=2, top1=99.2),
                 mech(1, 0.98, earners=0, top1=None)]
        rung, detail = self.cut({}, mechs)
        self.assertEqual(rung, mine.CUT_CONCENTRATION)
        self.assertIn("mechanism 0", detail)
        self.assertIn("mechanism 1: no independent earner", detail)

    def test_a_contested_field_survives(self):
        for top1, earners in ((89.8, 20), (65.0, 3), (34.7, 7), (0.6, 242)):
            rung, _ = self.cut({}, [mech(earners=earners, top1=top1)])
            self.assertIsNone(rung, top1)

    def test_unread_incentive_vector_does_not_cut(self):
        rung, _ = self.cut({}, [mech(earners=None, top1=None)])
        self.assertIsNone(rung)

    def test_concentration_precedes_feasibility(self):
        rung, _ = self.cut({}, [mech(earners=1, top1=100.0)],
                           {"verdict": mine.VERDICT_STUB})
        self.assertEqual(rung, mine.CUT_CONCENTRATION)

    def test_concentration_ceiling_is_configurable(self):
        cfg = mine.mining_cfg({"mining": {"top1_ceiling_pct": 99.5}})
        rung, _ = self.cut({}, [mech(earners=3, top1=99.1)], cfg=cfg)
        self.assertIsNone(rung)

    def test_positive_infeasible_verdicts_cut(self):
        for verdict in (mine.VERDICT_STUB, mine.VERDICT_CLOSED):
            rung, _ = self.cut({}, OPEN, {"verdict": verdict})
            self.assertEqual(rung, mine.CUT_FEASIBILITY, verdict)

    def test_unknown_verdict_does_not_cut_and_is_not_feasible(self):
        rung, _ = self.cut({}, OPEN, {"verdict": mine.VERDICT_UNKNOWN})
        self.assertIsNone(rung)
        self.assertNotIn(mine.VERDICT_UNKNOWN, mine.INFEASIBLE_VERDICTS)

    def test_hardware_rung_is_inert_without_a_budget_band(self):
        rung, _ = self.cut({}, OPEN, {"verdict": mine.VERDICT_NEEDS_GPU,
                                      "vram_gb": 80})
        self.assertIsNone(rung)

    def test_hardware_rung_cuts_above_the_chosen_band(self):
        cfg = mine.mining_cfg({"mining": {"budget_band": "consumer-gpu"}})
        rung, detail = self.cut({}, OPEN, {"verdict": mine.VERDICT_NEEDS_GPU,
                                           "vram_gb": 80}, cfg=cfg)
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

    def cut(self, row):
        base = {"gate_state": "enabled", "miner_burn_pct": 0.0}
        base.update(row)
        return mine.classify_cut(self.cfg, base, OPEN, None)[:2]

    def test_real_names_are_named(self):
        for name in ("Apex", "Green Compute", "lium.io", "8 Ball",
                     "hoτfloaτ", "404—GEN", "sundae_bar"):
            self.assertEqual(self._state(name), mine.IDENT_NAMED, name)

    def test_live_placeholders_observed_on_chain(self):
        """The exact strings live Finney carried on 2026-08-12."""
        for name in ("deprecated", "unknown", "Unknown", "pending...",
                     "Parked", "wait (reproduce paper)"):
            self.assertEqual(self._state(name), mine.IDENT_PLACEHOLDER, name)

    def test_placeholder_match_is_case_and_punctuation_insensitive(self):
        for name in ("DEPRECATED", "  deprecated  ", "Pending…",
                     "deprecated (do not use)"):
            self.assertEqual(self._state(name), mine.IDENT_PLACEHOLDER, name)

    def test_a_name_merely_containing_a_placeholder_word_survives(self):
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
        rung, detail = self.cut({"identity_state": mine.IDENT_PLACEHOLDER,
                                 "subnet_name": "deprecated"})
        self.assertEqual(rung, mine.CUT_IDENTITY)
        self.assertIn("deprecated", detail)

    def test_absent_identity_cuts_with_its_own_reason(self):
        rung, detail = self.cut({"identity_state": mine.IDENT_ABSENT})
        self.assertEqual(rung, mine.CUT_IDENTITY)
        self.assertIn("SubnetIdentitiesV3", detail)

    def test_unread_identity_does_not_cut(self):
        rung, _ = self.cut({"identity_state": mine.IDENT_UNREAD})
        self.assertIsNone(rung)

    def test_gate_rung_still_precedes_identity(self):
        rung, _ = self.cut({"gate_state": "disabled",
                            "identity_state": mine.IDENT_PLACEHOLDER,
                            "subnet_name": "deprecated"})
        self.assertEqual(rung, mine.CUT_GATE)

    def test_identity_rung_precedes_burn(self):
        rung, _ = self.cut({"miner_burn_pct": 100.0,
                            "identity_state": mine.IDENT_PLACEHOLDER,
                            "subnet_name": "Parked"})
        self.assertEqual(rung, mine.CUT_IDENTITY)

    def test_placeholder_list_is_configurable(self):
        cfg = mine.mining_cfg({"mining": {"identity_placeholders":
                                          ["retired"]}})
        self.assertEqual(mine.classify_identity(cfg, "retired", True)[0],
                         mine.IDENT_PLACEHOLDER)
        self.assertEqual(mine.classify_identity(cfg, "deprecated", True)[0],
                         mine.IDENT_NAMED)


# ---------------------------------------------------------------------------
# Measured chain snapshot, block 9142723
# ---------------------------------------------------------------------------

class TestMeasured(MiningBase):

    def setUp(self):
        super().setUp()
        self.result = mf.seed_board(self.conn, self.config,
                                    mf.measured_snapshot())
        self.mechs = mine._mechanism_rows(self.conn, mine.classified_ts(
            self.conn))

    def test_sn93_mechanism_0_gets_two_percent(self):
        mechs = {m["mecid"]: m for m in self.mechs[93]}
        self.assertAlmostEqual(mechs[0]["split"], 1311 / 65535.0)
        self.assertAlmostEqual(mechs[1]["split"], 64224 / 65535.0)
        # Its real entrant figure is about 8 TAO/mo, not the 410.92 the
        # whole-pool model credited it with.
        self.assertTrue(7.0 < mechs[0]["gross_tao_month"] < 9.5,
                        mechs[0]["gross_tao_month"])

    def test_sn44_mechanism_0_gets_nothing(self):
        mechs = {m["mecid"]: m for m in self.mechs[44]}
        self.assertEqual(mechs[0]["split"], 0.0)
        self.assertEqual(mechs[0]["rung"], mine.MECH_ZERO_SPLIT)
        row = self.rows()[44]
        self.assertEqual(row["rank_mecid"], 1)

    def test_sn9_is_cut_winner_take_all_on_the_independent_field(self):
        row = self.rows()[9]
        self.assertEqual(row["cut_reason"], mine.CUT_CONCENTRATION)
        self.assertIn("99.6", row["cut_detail"])
        self.assertIsNone(row["rank"])

    def test_sn120_is_cut_winner_take_all(self):
        self.assertEqual(self.rows()[120]["cut_reason"],
                         mine.CUT_CONCENTRATION)

    def test_sn80_divisor_is_three_earners_plus_one(self):
        row = self.rows()[80]
        self.assertEqual(row["earner_count"], 3)
        self.assertEqual(row["displacement_rank"], 4)
        self.assertIsNotNone(row["rank"])

    def test_reconciliation_passes_for_all_six(self):
        for netuid, row in self.rows().items():
            self.assertEqual(row["confidence"], mine.CONF_OK, netuid)
            self.assertLessEqual(abs(row["owner_reconcile_delta"]), 0.01,
                                 netuid)

    def test_owner_cut_unset_is_the_default_share(self):
        for row in self.rows().values():
            self.assertAlmostEqual(row["miner_share"], SHARE)

    def test_sn4_is_ranked_first(self):
        row = self.rows()[4]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["subnet_name"], "Targon")


# ---------------------------------------------------------------------------
# Stage A
# ---------------------------------------------------------------------------

class TestEcon(MiningBase):

    def test_happy_path_records_one_row_per_subnet(self):
        out = mine.run_econ(self.conn, self.config, snapshot=synthetic(
            [subnet(1, [10, 5, 0]), subnet(4, [7, 3])]))
        self.assertTrue(out["ok"])
        self.assertEqual(out["observations"], 2)
        rows = self.econ_rows()
        self.assertEqual(sorted(r["netuid"] for r in rows), [1, 4])
        self.assertEqual(rows[0]["confidence"], mine.CONF_OK)
        self.assertEqual(rows[0]["block_ref"], 8789861)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_mechanism").fetchone()[0], 2)

    def test_base_is_the_chain_participant_distribution(self):
        self.seed([subnet(1, [10, 9])])
        row = self.rows()[1]
        self.assertAlmostEqual(row["alpha_out_day"], mine.BLOCKS_PER_DAY)
        self.assertAlmostEqual(row["miner_alpha_day"],
                               mine.BLOCKS_PER_DAY * SHARE)
        # The pool injection is not read and never drives income.
        self.assertIsNone(row["alpha_in_day"])

    def test_a_halved_subnet_is_priced_at_its_own_rate(self):
        self.seed([subnet(1, [10, 9]), subnet(2, [10, 9], alpha_out=0.5)])
        rows = self.rows()
        self.assertAlmostEqual(rows[2]["miner_alpha_day"],
                               rows[1]["miner_alpha_day"] / 2)
        self.assertAlmostEqual(rows[2]["entrant_alpha_day"],
                               rows[1]["entrant_alpha_day"] / 2)

    def test_owner_cut_disabled_gives_half_the_distribution(self):
        self.seed([subnet(1, [10, 9], cut_enabled=False)])
        self.assertAlmostEqual(self.rows()[1]["miner_share"], 0.5)

    def test_owner_cut_set_on_chain_is_used(self):
        self.seed([subnet(1, [10, 9])], owner_cut=0)
        self.assertAlmostEqual(self.rows()[1]["miner_share"], 0.5)

    def test_second_mechanism_takes_its_split(self):
        self.seed([subnet(1, {0: [10, 9, 8], 1: [10, 9, 8]}, count=2,
                          split=[1311, 64224])])
        mechs = {m["mecid"]: m for m in mine._mechanism_rows(
            self.conn, mine.classified_ts(self.conn))[1]}
        total = mechs[0]["miner_alpha_day"] + mechs[1]["miner_alpha_day"]
        self.assertAlmostEqual(total, self.rows()[1]["miner_alpha_day"])
        self.assertAlmostEqual(mechs[0]["miner_alpha_day"] / total,
                               1311 / 65535.0)
        self.assertEqual(self.rows()[1]["rank_mecid"], 1)

    def test_owner_removal_reconciles_and_is_recorded(self):
        self.seed([subnet(1, [50, 25, 25], owner_uids=[0])])
        row = self.rows()[1]
        self.assertEqual(row["confidence"], mine.CONF_OK)
        self.assertAlmostEqual(row["owner_share_pct"], 50.0)
        self.assertAlmostEqual(row["owner_reconcile_delta"], 0.0)
        # The burn is not applied a second time on top of the removal.
        self.assertAlmostEqual(
            row["entrant_alpha_day"],
            mine.BLOCKS_PER_DAY * SHARE * 0.5 / 3)

    def test_reconciliation_failure_blocks_the_figure(self):
        self.seed([subnet(1, [50, 25, 25], owner_uids=[0], burn=0.2)])
        row = self.rows()[1]
        self.assertEqual(row["confidence"], mine.CONF_RECONCILE)
        self.assertIsNone(row["gross_tao_month"])
        self.assertIsNone(row["rank"])
        self.assertEqual(row["unrated_reason"], mine.CONF_RECONCILE)

    def test_reconciliation_tolerance_is_configurable(self):
        config = dict(self.config, mining={
            "enabled": True, "owner_reconcile_tolerance": 0.5})
        self.seed([subnet(1, [50, 25, 25], owner_uids=[0], burn=0.2)],
                  config=config)
        self.assertEqual(self.rows()[1]["confidence"], mine.CONF_OK)

    def test_unread_owner_set_is_unrated(self):
        self.seed([subnet(1, [50, 25, 25], owner_uids=None)])
        row = self.rows()[1]
        self.assertTrue(row["confidence"].startswith(
            mine.CONF_OWNERS_UNREAD))
        self.assertIsNone(row["rank"])
        self.assertIsNone(row["cut_reason"])
        self.assertTrue(row["unrated_reason"].startswith(
            mine.CONF_OWNERS_UNREAD))

    def test_a_subnet_not_emitting_is_unrated_not_ranked_on_zero(self):
        self.seed([subnet(1, [10, 9]), subnet(2, [10, 9], alpha_out=0)])
        rows = self.rows()
        self.assertEqual(rows[2]["unrated_reason"], mine.UNRATED_NOT_EMITTING)
        self.assertIsNone(rows[2]["rank"])
        self.assertEqual(rows[1]["rank"], 1)

    def test_unknown_weight_blocks_the_figure(self):
        self.seed([subnet(1, [10, 9], quote=None)])
        row = self.rows()[1]
        self.assertIsNone(row["haircut_pct"])
        self.assertIsNone(row["gross_tao_month"])
        self.assertIn("SwapBalancer", row["unrated_reason"])

    def test_missing_reserve_blocks_the_figure(self):
        self.seed([subnet(1, [10, 9], tao_pool=None)])
        row = self.rows()[1]
        self.assertIsNone(row["price_tao"])
        self.assertIsNone(row["gross_tao_month"])
        self.assertEqual(row["unrated_reason"], "price-unknown")

    def test_switch_is_read_from_chain(self):
        self.seed([subnet(1, [10, 9]), subnet(2, [10, 9], enabled=False)])
        rows = self.rows()
        self.assertEqual(rows[1]["gate_state"], "enabled")
        self.assertEqual(rows[2]["gate_state"], "disabled")
        self.assertEqual(rows[2]["cut_reason"], mine.CUT_GATE)

    def test_an_unread_switch_does_not_cut(self):
        self.seed([subnet(1, [10, 9], enabled=False)],
                  failed_items={"SubnetEmissionEnabled": "empty batch"})
        row = self.rows()[1]
        self.assertIsNone(row["gate_state"])
        self.assertNotEqual(row["cut_reason"], mine.CUT_GATE)

    def test_identity_is_recorded_and_cuts_end_to_end(self):
        self.seed([subnet(1, [10, 9, 8], name="Apex"),
                   subnet(3, [10, 9, 8], name="deprecated"),
                   subnet(57, [10, 9, 8], name=False)])
        rows = self.rows()
        self.assertEqual(rows[1]["identity_state"], mine.IDENT_NAMED)
        self.assertEqual(rows[3]["identity_state"], mine.IDENT_PLACEHOLDER)
        self.assertEqual(rows[57]["identity_state"], mine.IDENT_ABSENT)
        view = mine.report(self.conn, self.config, include_cut=True)
        self.assertEqual([e["netuid"] for e in view["ranked"]], [1])
        self.assertEqual(view["cut_summary"][mine.CUT_IDENTITY], 2)

    def test_an_unread_identity_map_does_not_empty_the_board(self):
        self.seed([subnet(1, [10, 9, 8]), subnet(3, [10, 9, 8])],
                  identity=False)
        rows = self.rows()
        self.assertEqual(rows[1]["identity_state"], mine.IDENT_UNREAD)
        view = mine.report(self.conn, self.config)
        self.assertEqual(sorted(e["netuid"] for e in view["ranked"]), [1, 3])

    def test_one_undecodable_identity_is_unread_not_unnamed(self):
        self.seed([subnet(1, [10, 9, 8]), subnet(3, [10, 9, 8], name=False)],
                  failures={"SubnetIdentitiesV3": {3: "truncated"}})
        row = self.rows()[3]
        self.assertEqual(row["identity_state"], mine.IDENT_UNREAD)
        self.assertIsNone(row["cut_reason"])

    def test_one_malformed_subnet_is_isolated(self):
        self.seed([subnet(1, [5, 5]), subnet(4, {0: None})])
        rows = self.rows()
        self.assertEqual(rows[1]["confidence"], mine.CONF_OK)
        self.assertTrue(rows[4]["confidence"].startswith(
            mine.CONF_INCOMPLETE))
        self.assertIn("Incentive[0]", rows[4]["confidence"])
        self.assertIsNone(rows[4]["gross_tao_month"])
        self.assertIsNotNone(rows[1]["gross_tao_month"])

    def test_chain_failure_writes_nothing_and_keeps_the_last_pass(self):
        self.seed([subnet(1, [5, 5])], now="2026-09-25T00:00:00+00:00")
        before = mine.latest_econ(self.conn)
        out = mine.run_econ(self.conn, self.config,
                            snapshot={"ok": False, "error": "rpc down"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["leg"], "chain")
        self.assertEqual(mine.latest_econ(self.conn), before)
        self.assertEqual(len(self.econ_rows()), 1)
        view = mine.report(self.conn, self.config,
                           now="2026-09-26T00:00:00+00:00")
        self.assertAlmostEqual(view["econ_age_hours"], 24.0)
        self.assertTrue(view["stale"])

    def test_a_mid_econ_fault_commits_nothing(self):
        original = mine._insert
        calls = []

        def flaky(connection, table, row):
            calls.append(table)
            if len(calls) == 2:
                raise RuntimeError("disk vanished")
            original(connection, table, row)

        mine._insert = flaky
        self.addCleanup(setattr, mine, "_insert", original)
        with self.assertRaises(RuntimeError):
            mine.run_econ(self.conn, self.config, snapshot=synthetic(
                [subnet(1, [5, 5]), subnet(2, [5, 5])]))
        self.assertEqual(self.econ_rows(), [])
        self.assertIsNone(mine.state_get(self.conn, "last_econ_ts"))

    def test_root_subnet_is_excluded(self):
        out = mine.run_econ(self.conn, self.config, snapshot=synthetic(
            [subnet(0, [1]), subnet(1, [1, 1])]))
        self.assertEqual(out["observations"], 1)

    def test_no_net_figure_without_a_budget_band(self):
        self.seed([subnet(1, [5, 5])])
        row = self.rows()[1]
        self.assertIsNone(row["net_tao_month"])
        self.assertIsNotNone(row["gross_tao_month"])
        # No rent, so no fabricated zero baseline either.
        self.assertIsNone(row["baseline_tao_month"])

    def test_net_figure_appears_once_a_band_is_chosen(self):
        config = dict(self.config,
                      mining={"enabled": True, "budget_band": "consumer-gpu"})
        self.seed([subnet(1, [5, 5])], config=config)
        row = self.rows()[1]
        self.assertAlmostEqual(row["net_tao_month"],
                               row["gross_tao_month"] - 2.0, places=6)
        self.assertIsNotNone(row["baseline_tao_month"])

    def test_missing_split_citation_refuses_to_compute(self):
        original = mine.MINER_SPLIT_SOURCE
        mine.MINER_SPLIT_SOURCE = ""
        self.addCleanup(setattr, mine, "MINER_SPLIT_SOURCE", original)
        out = mine.run_econ(self.conn, self.config,
                            snapshot=synthetic([subnet(1, [5, 5])]))
        self.assertFalse(out["ok"])
        self.assertIn("citation", out["error"])
        self.assertEqual(self.econ_rows(), [])

    def test_citation_is_recorded_for_the_reader(self):
        self.seed([subnet(1, [5, 5])])
        self.assertIn("run_coinbase.rs:326-329",
                      mine.state_get(self.conn, "miner_split_source"))

    def test_leftover_miner_share_config_is_ignored_with_a_note(self):
        config = dict(self.config, mining={
            "enabled": True, "miner_share": 0.9,
            "miner_share_source": "old"})
        out = mine.run_econ(self.conn, config,
                            snapshot=synthetic([subnet(1, [5, 5])]))
        self.assertTrue(out["ok"])
        self.assertIn("mining.miner_share", out["notes"][0])
        self.assertAlmostEqual(self.econ_rows()[0]["miner_share"], SHARE)

    def test_collateral_dormant_reads_as_zero_and_unread_as_unknown(self):
        self.seed([subnet(1, [5, 5]), subnet(2, [5, 5])],
                  failures={"CollateralLockShare": {2: "bad"}})
        rows = self.rows()
        self.assertEqual(rows[1]["collateral_lock_pct"], 0.0)
        self.assertIsNone(rows[2]["collateral_lock_pct"])

    def test_entry_context_is_recorded(self):
        self.seed([subnet(1, [5, 5], network_n=256, max_uids=256,
                          immunity=7520, reg_burn=0.0005),
                   subnet(2, [5, 5], network_n=200, max_uids=256)])
        rows = self.rows()
        self.assertEqual(rows[1]["uids_full"], 1)
        self.assertEqual(rows[2]["uids_full"], 0)
        self.assertEqual(rows[1]["immunity_period"], 7520)
        self.assertAlmostEqual(rows[1]["reg_cost_tao"], 0.0005)
        self.assertIsNotNone(rows[1]["alpha_issuance"])

    def test_kill_switch_makes_the_screen_inert(self):
        config = dict(self.config, mining={"enabled": False})
        self.assertEqual(mine.run_econ(self.conn, config),
                         {"disabled": True})

    def test_retention_prunes_old_observations(self):
        old = (datetime.datetime.now(tz=datetime.timezone.utc)
               - datetime.timedelta(days=120)).isoformat()
        self.seed([subnet(1, [5, 5])], now=old)
        self.seed([subnet(1, [5, 5])])
        self.assertEqual(len(self.econ_rows()), 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_mechanism").fetchone()[0], 1)

    def test_retention_keeps_recent_history_for_the_history_tool(self):
        recent = (datetime.datetime.now(tz=datetime.timezone.utc)
                  - datetime.timedelta(days=3)).isoformat()
        self.seed([subnet(1, [5, 5])], now=recent)
        self.seed([subnet(1, [5, 5])])
        self.assertEqual(len(self.econ_rows()), 2)


# ---------------------------------------------------------------------------
# Stage B
# ---------------------------------------------------------------------------

# Verbatim shape of real subnet min_compute.yml files, sampled from the fleet
# on the Pi 2026-08-10. The unit lives in a trailing COMMENT, not next to the
# number, and miner/validator are separate sections.
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

MIN_COMPUTE_VALIDATOR_FIRST = """
compute_spec:
  validator:
    gpu:
      min_vram: 80
  miner:
    gpu:
      min_vram: 16
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

with open(os.path.join(_HERE, "fixtures", "template_min_compute.yml"),
          encoding="utf-8") as _handle:
    TEMPLATE_MIN_COMPUTE = _handle.read()

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

    def slot(self, netuid=1, sha="sha-one", epoch=1, status="active",
             indexed=None):
        """An active slot whose index holds `indexed` (default: `sha`)."""
        idx.ensure_schema(self.conn)
        fleet.upsert_slot(self.conn, {
            "netuid": netuid, "github_repo": "https://github.com/o/r%d"
            % netuid, "epoch": epoch, "status": status,
            "default_branch": "main", "local_sha": sha})
        self.conn.execute(
            "INSERT INTO index_state (netuid, epoch, indexed_sha, "
            "indexer_schema, files, indexed_at) VALUES (?, ?, ?, '1', 1, "
            "'2026-09-25T00:00:00Z') ON CONFLICT(netuid) DO UPDATE SET "
            "epoch = excluded.epoch, indexed_sha = excluded.indexed_sha",
            (netuid, epoch, indexed or sha))
        self.conn.commit()

    def scan(self, netuid=1):
        return mine.scan_slot(self.conn, mine.mining_cfg({}), netuid, 1)

    def test_min_compute_vram_is_read_and_cited(self):
        self.index_file(1, "min_compute.yml", MIN_COMPUTE)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = self.scan()
        self.assertEqual(out["vram_gb"], 24.0)
        self.assertEqual(out["vram_basis"], "min_vram")
        vram = [e for e in out["evidence"] if e["kind"] == "vram"]
        self.assertEqual(vram[0]["path"], "min_compute.yml")
        self.assertEqual(vram[0]["line"], 7)

    def test_bare_yaml_number_with_the_unit_in_a_comment(self):
        """REGRESSION 2026-08-10: the first parser required the unit adjacent
        to the number and extracted nothing from any real fleet file."""
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE)[:2],
                         (24.0, "min_vram"))

    def test_miner_section_wins_over_validator(self):
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE)[0], 24.0)

    def test_vram_evidence_line_is_in_the_miner_section(self):
        """REGRESSION: the evidence line was searched over the whole file,
        so a validator block first cited the validator's line."""
        gb, basis, line = mine.parse_vram_gb(MIN_COMPUTE_VALIDATOR_FIRST)
        self.assertEqual(gb, 16.0)
        self.assertEqual(
            MIN_COMPUTE_VALIDATOR_FIRST.splitlines()[line - 1].strip(),
            "min_vram: 16")

    def test_vram_basis_follows_the_value_kept(self):
        self.index_file(1, "a/min_compute.yml", "gpu:\n  vram: 40 GB\n")
        self.index_file(1, "b/min_compute.yml", MIN_COMPUTE_CPU)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = self.scan()
        self.assertEqual(out["vram_gb"], 40.0)
        self.assertEqual(out["vram_basis"], "inline")

    def test_declared_zero_vram_is_a_real_cpu_answer(self):
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE_CPU)[:2],
                         (0.0, "min_vram"))

    def test_absent_vram_is_none_not_zero(self):
        self.assertEqual(mine.parse_vram_gb(MIN_COMPUTE_NO_VRAM),
                         (None, None, None))

    def test_inline_unit_form_still_parses(self):
        self.assertEqual(
            mine.parse_vram_gb("gpu:\n  vram: 40 GB\n")[0], 40.0)

    def test_recommended_only_is_labelled_as_such(self):
        gb, basis, _ = mine.parse_vram_gb(
            "compute_spec:\n  miner:\n    gpu:\n"
            "      recommended_vram: 48   # Recommended GPU VRAM (GB)\n")
        self.assertEqual((gb, basis), (48.0, "recommended_vram"))

    def test_template_min_compute_is_not_a_declaration(self):
        self.assertTrue(mine.is_template_min_compute(TEMPLATE_MIN_COMPUTE))
        self.index_file(1, "min_compute.yml", TEMPLATE_MIN_COMPUTE)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = self.scan()
        self.assertIsNone(out["vram_gb"])
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)
        self.assertEqual([e["kind"] for e in out["evidence"]
                          if e["kind"] == "template"], ["template"])

    def test_an_edited_template_is_a_declaration(self):
        edited = TEMPLATE_MIN_COMPUTE.replace("min_vram: 8 ", "min_vram: 12 ",
                                              1)
        self.assertFalse(mine.is_template_min_compute(edited))
        self.assertEqual(mine.parse_vram_gb(edited)[0], 12.0)

    def test_cpu_declaration_does_not_become_needs_gpu(self):
        self.index_file(1, "min_compute.yml", MIN_COMPUTE_CPU)
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        out = self.scan()
        self.assertEqual(out["vram_gb"], 0.0)
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)

    def test_gpu_tell_yields_needs_gpu(self):
        self.index_file(1, "neurons/miner.py", MINER_GPU)
        out = self.scan()
        self.assertEqual(out["verdict"], mine.VERDICT_NEEDS_GPU)
        gpu = [e for e in out["evidence"] if e["kind"] == "gpu"]
        self.assertEqual(gpu[0]["path"], "neurons/miner.py")

    def test_hosted_api_is_labelled_not_disqualifying(self):
        self.index_file(1, "neurons/miner.py", MINER_API)
        out = self.scan()
        self.assertEqual(out["closed_api"], 1)
        self.assertNotIn(out["verdict"], mine.INFEASIBLE_VERDICTS)

    def test_go_miner_is_recognised(self):
        self.index_file(1, "cmd/miner/main.go", "package main\n")
        self.index_file(1, "cmd/validator/main.go", "package main\n")
        out = self.scan()
        self.assertEqual(out["entrypoint_path"], "cmd/miner/main.go")
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)

    def test_miner_package_is_recognised(self):
        self.index_file(1, "miner/__init__.py", "")
        self.index_file(1, "miner/asgi.py", MINER_CPU)
        out = self.scan()
        self.assertEqual(out["entrypoint_path"], "miner/__init__.py")

    def test_rust_bin_is_recognised(self):
        self.index_file(1, "src/bin/miner.rs", "fn main() {}\n")
        self.assertEqual(self.scan()["entrypoint_path"], "src/bin/miner.rs")

    def test_python_cli_and_run_modules_are_recognised(self):
        for path in ("miner/cli.py", "pkg/miner/__main__.py",
                     "miner/run_miner.py", "neurons/miner_v2.py"):
            self.assertIsNotNone(mine.entrypoint_precedence(path), path)

    def test_precedence_prefers_the_neurons_entrypoint(self):
        self.index_file(1, "miner/__init__.py", "")
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.assertEqual(self.scan()["entrypoint_path"], "neurons/miner.py")

    def test_non_miner_paths_are_not_entrypoints(self):
        for path in ("validator/miner/main.go", "api/miner/main.py",
                     "routes/miner/__init__.py",
                     "migrations/miner/__init__.py",
                     "tests/neurons/miner.py", "scripts/miner/main.py",
                     "validators/neurons/miner.py"):
            self.assertIsNone(mine.entrypoint_precedence(path), path)
        self.index_file(1, "validator/miner/main.go", "package main\n")
        self.index_file(1, "scripts/register_miner.py", "x = 1\n")
        out = self.scan()
        self.assertIsNone(out["entrypoint_path"])
        self.assertEqual(out["verdict"], mine.VERDICT_UNKNOWN)

    def test_no_entrypoint_is_unknown_whatever_the_repo_size(self):
        """REGRESSION: 22 of 43 `closed` subnets had plain miner code.
        Absence of a recognised entrypoint is not evidence."""
        self.index_file(1, "README.md", "# soon")
        self.assertEqual(self.scan()["verdict"], mine.VERDICT_UNKNOWN)
        for i in range(25):
            self.index_file(2, "src/mod%d.py" % i, "x = %d\n" % i)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 2, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_UNKNOWN)
        self.assertIn("25 indexed source files", out["reason"])

    def test_unindexed_slot_is_unknown_not_infeasible(self):
        idx.ensure_schema(self.conn)
        out = mine.scan_slot(self.conn, mine.mining_cfg({}), 99, 1)
        self.assertEqual(out["verdict"], mine.VERDICT_UNKNOWN)

    def test_verdicts_are_a_closed_set(self):
        self.index_file(1, "neurons/miner.py", MINER_GPU)
        self.assertIn(self.scan()["verdict"], mine.VERDICTS)

    def test_scan_is_gated_on_the_indexed_commit(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot()
        first = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(first["scanned"], 1)
        second = mine.run_feasibility(self.conn, self.config)
        self.assertEqual((second["scanned"], second["unchanged"]), (0, 1))
        row = self.conn.execute(
            "SELECT sha FROM mine_feasibility").fetchone()
        self.assertEqual(row[0], "sha-one")

    def test_moved_indexed_commit_rescans_and_prunes_the_old_verdict(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot(sha="sha-one")
        mine.run_feasibility(self.conn, self.config)
        self.slot(sha="sha-two")
        again = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(again["scanned"], 1)
        self.assertEqual(again["superseded_pruned"], 1)
        self.assertEqual([r[0] for r in self.conn.execute(
            "SELECT sha FROM mine_feasibility")], ["sha-two"])

    def test_index_behind_its_clone_is_skipped(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot(sha="sha-new", indexed="sha-old")
        out = mine.run_feasibility(self.conn, self.config)
        self.assertEqual((out["scanned"], out["index_behind"]), (0, 1))

    def test_a_repointed_slot_does_not_inherit_the_old_verdict(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot(sha="sha-one", epoch=1)
        mine.run_feasibility(self.conn, self.config)
        self.assertIn(1, mine.latest_feasibility(self.conn))
        # Re-pointed to a new repository: new epoch, not yet indexed.
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/new/r",
            "epoch": 2, "status": "active", "default_branch": "main",
            "local_sha": "sha-x"})
        self.conn.commit()
        self.assertNotIn(1, mine.latest_feasibility(self.conn))
        out = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(out["scanned"], 0)

    def test_an_inactive_slot_has_no_current_verdict(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot()
        mine.run_feasibility(self.conn, self.config)
        self.slot(status="discarded")
        self.assertEqual(mine.latest_feasibility(self.conn), {})
        out = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(out["scanned"], 0)
        self.assertGreaterEqual(out["skipped"], 1)

    def test_status_counts_only_current_verdicts(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot()
        mine.run_feasibility(self.conn, self.config)
        self.slot(status="discarded")
        status = mine.mining_status(self.conn)
        self.assertEqual(status["feasibility_verdicts"], {})
        self.assertEqual(status["feasibility_not_current"], 1)

    def test_scanner_version_change_invalidates_stored_verdicts(self):
        self.index_file(1, "neurons/miner.py", MINER_CPU)
        self.slot()
        mine.run_feasibility(self.conn, self.config)
        mine.state_set(self.conn, "scan_version", "old")
        self.conn.commit()
        third = mine.run_feasibility(self.conn, self.config)
        self.assertEqual(third["invalidated_by_scanner_change"], 1)
        self.assertEqual(third["scanned"], 1)
        self.assertEqual(mine.state_get(self.conn, "scan_version"), "3")


# ---------------------------------------------------------------------------
# Stage C, the stored result, render, pass
# ---------------------------------------------------------------------------

BOARD = [subnet(1, [10, 5], tao_pool=125_000.0),   # ranked, higher price
         subnet(4, [10, 5], burn=0.995),           # owner-capture
         subnet(5, [10, 5], enabled=False),        # switch off
         subnet(8, [10, 5, 5]),                    # ranked
         subnet(9, [0, 0, 0]),                     # no independent earner
         subnet(10, [10, 5], owner_uids=None)]     # unrated


class TestClassify(MiningBase):

    def test_every_row_carries_exactly_one_outcome(self):
        self.seed(BOARD)
        for row in self.econ_rows():
            outcomes = [row["cut_reason"] is not None,
                        row["rank"] is not None,
                        row["unrated_reason"] is not None]
            self.assertEqual(sum(outcomes), 1, row["netuid"])

    def test_ranks_are_stored_in_order(self):
        self.seed(BOARD)
        rows = self.rows()
        self.assertEqual((rows[1]["rank"], rows[8]["rank"]), (1, 2))
        self.assertEqual(rows[9]["cut_reason"], mine.CUT_NO_EARNER)
        self.assertEqual(rows[4]["cut_reason"], mine.CUT_BURN)
        self.assertTrue(rows[10]["unrated_reason"])

    def test_classify_is_idempotent(self):
        result = self.seed(BOARD)
        before = self.econ_rows()
        again = mine.run_classify(self.conn, self.config, result["ts"])
        self.assertEqual(self.econ_rows(), before)
        self.assertEqual(again["ranked"], result["ranked"])

    def test_classify_records_the_model_version(self):
        self.seed(BOARD)
        self.assertEqual(mine.state_get(self.conn, "model_version"), "2")

    def test_classify_does_not_run_after_a_failed_econ(self):
        self.seed(BOARD, now="2026-09-25T00:00:00+00:00")
        stamp = mine.classified_ts(self.conn)
        out = mine.run_pass(self.conn, self.config,
                            now="2026-09-25T06:00:00+00:00",
                            snapshot={"ok": False, "error": "rpc down"})
        self.assertIn("skipped", out["classify"])
        self.assertEqual(mine.classified_ts(self.conn), stamp)

    def test_a_failed_classify_leaves_the_last_complete_pass_current(self):
        self.seed(BOARD, now="2026-09-25T00:00:00+00:00")
        original = mine.decide

        def boom(*args, **kwargs):
            raise RuntimeError("ladder exploded")

        mine.decide = boom
        self.addCleanup(setattr, mine, "decide", original)
        out = mine.run_pass(self.conn, self.config,
                            now="2026-09-25T06:00:00+00:00",
                            snapshot=synthetic(BOARD))
        self.assertIn("error", out["classify"])
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["econ_ts"], "2026-09-25T00:00:00+00:00")
        self.assertEqual(view["counts"]["ranked"], 2)

    def test_feasibility_is_joined_at_classify(self):
        self.seed([subnet(1, [10, 5])])
        self.conn.execute(
            "INSERT INTO mine_feasibility (netuid, epoch, sha, verdict, "
            "scanned_at) VALUES (1, 1, 'abc', 'closed', 'now')")
        idx.ensure_schema(self.conn)
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "github_repo": "https://github.com/o/r",
            "epoch": 1, "status": "active", "default_branch": "main",
            "local_sha": "abc"})
        self.conn.execute(
            "INSERT INTO index_state VALUES (1, 1, 'abc', '1', 1, 'now')")
        self.conn.commit()
        mine.run_classify(self.conn, self.config,
                          mine.classified_ts(self.conn))
        self.assertEqual(self.rows()[1]["cut_reason"], mine.CUT_FEASIBILITY)


class TestReport(MiningBase):

    def test_report_reads_the_stored_rank(self):
        self.seed(BOARD)
        # Swap the stored ranks: the report follows the store, never a
        # recomputation.
        ts = mine.classified_ts(self.conn)
        self.conn.execute("UPDATE mine_econ SET rank = 3 WHERE netuid = 1 "
                          "AND ts = ?", (ts,))
        self.conn.execute("UPDATE mine_econ SET rank = 1 WHERE netuid = 8 "
                          "AND ts = ?", (ts,))
        self.conn.commit()
        view = mine.report(self.conn, self.config)
        self.assertEqual([e["netuid"] for e in view["ranked"]], [8, 1])

    def test_counts_keep_unrated_apart(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config, include_cut=True)
        self.assertEqual(view["counts"], {"observed": 6, "ranked": 2,
                                          "cut": 3, "unrated": 1})
        self.assertEqual([e["netuid"] for e in view["unrated"]], [10])
        self.assertNotIn(10, [e["netuid"] for e in view["ranked"]])

    def test_cut_summary_names_each_rung(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["cut_summary"],
                         {mine.CUT_GATE: 1, mine.CUT_BURN: 1,
                          mine.CUT_NO_EARNER: 1})
        self.assertEqual(view["switch_block_ref"], 8789861)
        self.assertEqual(view["econ_block"], 8789861)

    def test_cut_subnets_are_retrievable_with_stored_reasons(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config, include_cut=True)
        reasons = {r["netuid"]: r["cut_detail"] for r in view["cut"]}
        self.assertIn("no TAO inflow", reasons[5])
        self.assertNotIn("emission gate", reasons[5])
        self.assertIn("99.50", reasons[4])

    def test_cut_list_is_bounded_with_an_omitted_count(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config, include_cut=True,
                           cut_limit=1)
        self.assertEqual(len(view["cut"]), 1)
        self.assertEqual(view["cut_omitted"], 2)

    def test_ranked_rows_carry_their_mechanisms(self):
        self.seed(BOARD)
        entry = mine.report(self.conn, self.config)["ranked"][0]
        self.assertEqual(entry["rank_mecid"], 0)
        self.assertEqual(len(entry["mechanisms"]), 1)

    def test_headline_is_the_entrant_figure_not_the_incumbent(self):
        self.seed([subnet(1, [100, 0])])
        row = self.rows()[1]
        self.assertEqual(row["earner_count"], 1)
        self.assertEqual(row["displacement_rank"], 2)
        self.assertAlmostEqual(row["entrant_alpha_day"],
                               row["miner_alpha_day"] / 2.0)
        self.assertLess(row["entrant_alpha_day"], row["incumbent_alpha_day"])

    def test_report_states_the_parity_model(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config)
        self.assertIn("MODEL", view["parity_model"])
        self.assertIn("independent earners + 1", view["parity_model"])

    def test_unscanned_feasibility_is_flagged_not_guessed(self):
        self.seed(BOARD)
        entry = mine.report(self.conn, self.config)["ranked"][0]
        self.assertTrue(entry["feasibility"]["unscanned"])
        self.assertEqual(entry["feasibility"]["verdict"],
                         mine.VERDICT_UNKNOWN)

    def test_report_carries_both_timestamps(self):
        self.seed(BOARD)
        view = mine.report(self.conn, self.config)
        self.assertIsNotNone(view["econ_ts"])
        self.assertIn("feasibility_ts", view)

    def test_limit_bounds_the_board(self):
        self.seed(BOARD)
        self.assertEqual(len(mine.report(self.conn, self.config,
                                         limit=1)["ranked"]), 1)

    def test_empty_store_reports_honestly(self):
        view = mine.report(self.conn, self.config)
        self.assertEqual(view["counts"]["observed"], 0)
        self.assertEqual(view["ranked"], [])

    def test_an_unclassified_pass_is_not_presented(self):
        mine.run_econ(self.conn, self.config,
                      snapshot=synthetic([subnet(1, [5, 5])]))
        self.assertEqual(mine.report(self.conn, self.config)["ranked"], [])


class TestRender(MiningBase):

    def test_render_writes_a_self_contained_page(self):
        self.seed(BOARD)
        out = mine.render(self.conn, self.config)
        self.assertTrue(out["path"].endswith("mining.html"))
        page = self.page()
        self.assertIn("Mining triage", page)
        self.assertIn("Cut ladder", page)
        self.assertNotIn("http://", page.replace("http://www.w3", ""))
        self.assertNotIn("<script src", page)

    def test_board_states_the_parity_assumption(self):
        self.seed(BOARD)
        mine.render(self.conn, self.config)
        page = self.page()
        self.assertIn("ASSUMPTION", page)
        self.assertIn("independent earners + 1", page)
        self.assertIn("incumbent", page)

    def test_board_names_the_ranking_mechanism(self):
        self.seed([subnet(1, {0: [10, 9, 8], 1: [10, 9, 8]}, count=2,
                          split=[1311, 64224])])
        mine.render(self.conn, self.config)
        self.assertIn("1 of 2 (98% split)", self.page())

    def test_board_lists_unrated_and_per_subnet_cuts(self):
        self.seed(BOARD)
        mine.render(self.conn, self.config)
        page = self.page()
        self.assertIn("Unrated", page)
        self.assertIn(mine.CONF_OWNERS_UNREAD, page)
        self.assertIn("stored reason", page)
        self.assertIn("no paying independent miner", page)

    def test_board_shows_entry_context(self):
        self.seed(BOARD)
        mine.render(self.conn, self.config)
        page = self.page()
        self.assertIn("full: deregisters a UID", page)
        self.assertIn("immunity 5000 blk", page)

    def test_unknown_feasibility_is_marked_unverified(self):
        self.seed(BOARD)
        mine.render(self.conn, self.config)
        self.assertIn("unverified", self.page())

    def test_board_states_its_age_and_block(self):
        self.seed(BOARD, now="2026-09-25T00:00:00+00:00")
        mine.render(self.conn, self.config, now="2026-09-25T02:00:00+00:00")
        page = self.page()
        self.assertIn("at block 8789861", page)
        self.assertIn("age 2.0h", page)
        self.assertNotIn("STALE", page)

    def test_a_stale_board_says_so(self):
        self.seed(BOARD, now="2026-09-25T00:00:00+00:00")
        mine.render(self.conn, self.config, now="2026-09-26T00:00:00+00:00")
        self.assertIn("STALE", self.page())

    def test_board_shows_the_on_chain_name(self):
        self.seed([subnet(1, [5, 4, 3], name="Apex")])
        mine.render(self.conn, self.config)
        self.assertIn("Apex", self.page())

    def test_board_escapes_a_hostile_chain_name(self):
        self.seed([subnet(1, [5, 4, 3], name="<script>alert(1)</script>")])
        mine.render(self.conn, self.config)
        page = self.page()
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_board_links_back_to_the_attention_board(self):
        mine.render(self.conn, self.config)
        self.assertIn('href="index.html"', self.page())

    def test_render_on_an_empty_store_does_not_raise(self):
        self.assertGreater(mine.render(self.conn, self.config)["bytes"], 0)

    def test_no_budget_band_is_stated_on_the_page(self):
        mine.render(self.conn, self.config)
        self.assertIn("no budget band chosen", self.page())


class TestPass(MiningBase):

    def test_pass_runs_every_stage_in_order(self):
        out = mine.run_pass(self.conn, self.config,
                            snapshot=synthetic([subnet(1, [5, 5])]))
        self.assertEqual(list(out), ["econ", "feasibility", "classify",
                                     "render"])
        self.assertTrue(out["econ"]["ok"])
        self.assertTrue(out["feasibility"]["ok"])
        self.assertTrue(out["classify"]["ok"])
        self.assertIn("path", out["render"])

    def test_a_failing_stage_is_isolated_not_raised(self):
        broken = dict(self.config, dashboard={"www_dir": "\x00bad"})
        out = mine.run_pass(self.conn, broken,
                            snapshot=synthetic([subnet(1, [5, 5])]))
        self.assertTrue(out["econ"]["ok"])
        self.assertIn("error", out["render"])

    def test_kill_switch_skips_the_pass(self):
        config = dict(self.config, mining={"enabled": False})
        self.assertEqual(mine.run_pass(self.conn, config),
                         {"disabled": True})

    def test_reconcile_pass_hook_is_isolated_from_a_mining_failure(self):
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
        mine.run_pass(self.conn, self.config,
                      snapshot=synthetic([subnet(1, [5, 5])]))
        status = mine.mining_status(self.conn)
        self.assertEqual(status["econ_rows"], 1)
        self.assertEqual(status["confidence"], {mine.CONF_OK: 1})
        self.assertIsNotNone(status["miner_split_source"])
        self.assertIsNotNone(status["last_classified_ts"])


if __name__ == "__main__":
    unittest.main()
