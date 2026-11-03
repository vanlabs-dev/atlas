"""Mining economics model (change: mining-economics-model, audit WP4 items
D1 to D6, D9, D10): the entrant figure is the lower of the parity share and
the 25th-percentile earner, the haircut prices the whole subnet's daily
sale, a full subnet with a short immunity period is cut, each subnet is
costed at the hardware band its evidence needs, and payback is reported.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_fleet as fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402
import atlas_fleet_mining as mine  # noqa: E402
import atlas_fleet_server as srv  # noqa: E402
import mining_fixtures as mf  # noqa: E402
from mining_fixtures import subnet, synthetic  # noqa: E402

BAND = {"budget_band": "consumer-gpu"}


def cfg(**extra):
    return mine.mining_cfg({"mining": dict(BAND, **extra)})


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        mine.ensure_schema(self.conn)
        self.config = {"db": self.db,
                       "clone_root": os.path.join(self.tmp, "clones"),
                       "dashboard": {"www_dir": os.path.join(self.tmp,
                                                             "www")},
                       "mining": dict({"enabled": True}, **BAND)}

    def seed(self, subnets, config=None, **kwargs):
        return mf.seed_board(self.conn, config or self.config,
                             synthetic(subnets, **kwargs))

    def rows(self):
        return {r["netuid"]: r for r in mine.latest_econ(self.conn)}


# ---------------------------------------------------------------------------
# 1. Schema and config
# ---------------------------------------------------------------------------

class TestSchemaMigration(unittest.TestCase):

    def test_an_old_store_gains_every_new_column_idempotently(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE mine_econ (ts TEXT NOT NULL, netuid "
                     "INTEGER NOT NULL, confidence TEXT NOT NULL, "
                     "PRIMARY KEY (ts, netuid))")
        conn.execute("CREATE TABLE mine_mechanism (ts TEXT NOT NULL, netuid "
                     "INTEGER NOT NULL, mecid INTEGER NOT NULL, "
                     "incentive_read INTEGER NOT NULL, "
                     "PRIMARY KEY (ts, netuid, mecid))")
        mine.ensure_schema(conn)
        mine.ensure_schema(conn)
        econ = {r[1] for r in conn.execute("PRAGMA table_info(mine_econ)")}
        mech = {r[1] for r in conn.execute(
            "PRAGMA table_info(mine_mechanism)")}
        for column in ("pool_days", "payback_days", "required_band",
                       "band_assumed", "registered_7d", "weighted_uids",
                       "widest_weight_row", "axons_served_7d",
                       "consensus_mode", "null_pruning_target"):
            self.assertIn(column, econ)
        for column in ("parity_alpha_day", "indep_p25_alpha_day",
                       "indep_median_alpha_day"):
            self.assertIn(column, mech)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("mine_consensus_events", tables)
        self.assertIn("mine_consensus_state", tables)

    def test_retired_haircut_and_baseline_keys_are_noted_not_used(self):
        config = {"mining": {"staking_apy_pct": 5.0,
                             "daily_sale_fraction": 0.1}}
        merged = mine.mining_cfg(config)
        self.assertNotIn("staking_apy_pct", merged)
        self.assertNotIn("daily_sale_fraction", merged)
        note = " ".join(mine.retired_cfg_notes(config))
        self.assertIn("staking_apy_pct", note)
        self.assertIn("daily_sale_fraction", note)

    def test_shipped_config_carries_the_operator_band_and_dated_rent(self):
        config = fleet.load_config(fleet.CONFIG_FILE)
        merged = mine.mining_cfg(config)
        self.assertEqual(merged["budget_band"], "consumer-gpu")
        self.assertAlmostEqual(
            merged["rent_bands"]["consumer-gpu"]["rent_tao_month"], 1.5)
        self.assertAlmostEqual(
            merged["rent_bands"]["datacenter-gpu"]["rent_tao_month"], 6.3)
        self.assertIn("2026-11-03", merged["rent_source"])
        self.assertEqual(merged["min_immunity_blocks"], 720)
        self.assertEqual(merged["subnet_sale_fraction"], 1.0)
        self.assertEqual(mine.retired_cfg_notes(config), [])


# ---------------------------------------------------------------------------
# 2. Entrant figure (D1, D2)
# ---------------------------------------------------------------------------

def run_mech(vector, owners=(), alpha_day=1000.0):
    return mine.mechanism_economics(
        mine.mining_cfg({}), 0, 1.0, vector, list(owners), alpha_day, 0.01,
        3_000_000.0, 25_000.0, 0.5, 7200.0)


class TestEntrantFigure(unittest.TestCase):

    def test_percentile_interpolates_like_the_usual_definition(self):
        self.assertAlmostEqual(mine.percentile_of([1, 2, 3, 4], 25), 1.75)
        self.assertAlmostEqual(mine.percentile_of([5], 25), 5)
        self.assertIsNone(mine.percentile_of([], 25))

    def test_a_long_tail_of_tiny_earners_caps_the_headline(self):
        # Regression (audit D2, SN8): parity 147.6 alpha/day while the
        # lower quarter of earners got under 0.1. 19 independent earners:
        # one holds almost everything, 18 hold dust.
        vector = [0] + [60000] + [1] * 18
        out = run_mech(vector, owners=[0], alpha_day=2952.0)
        self.assertEqual(out["indep_earner_count"], 19)
        self.assertAlmostEqual(out["parity_alpha_day"], 2952.0 / 20)
        self.assertLess(out["indep_p25_alpha_day"], 0.1)
        self.assertAlmostEqual(out["entrant_alpha_day"],
                               out["indep_p25_alpha_day"])
        self.assertGreater(out["indep_median_alpha_day"], 0)

    def test_a_few_strong_earners_keep_the_parity_figure(self):
        out = run_mech([10, 10, 10])
        # p25 of three equal earners is 333.3, above the 250 parity share.
        self.assertAlmostEqual(out["indep_p25_alpha_day"], 1000.0 / 3)
        self.assertAlmostEqual(out["entrant_alpha_day"], 250.0)
        self.assertAlmostEqual(out["parity_alpha_day"], 250.0)

    def test_one_incumbent_never_heads_above_the_parity_share(self):
        out = run_mech([0, 100])
        self.assertAlmostEqual(out["parity_alpha_day"], 500.0)
        self.assertAlmostEqual(out["entrant_alpha_day"], 500.0)
        self.assertAlmostEqual(out["incumbent_alpha_day"], 1000.0)


class TestZeroEarners(Base):

    def test_zero_earning_uids_are_neither_a_divisor_nor_a_cut(self):
        # Regression (audit D1): 3 earners of 255 non-owner UIDs.
        vector = [0] * 256
        vector[1], vector[2], vector[3], vector[0] = 30, 30, 30, 10
        self.seed([subnet(1, vector, owner_uids=[0], network_n=256)])
        row = self.rows()[1]
        self.assertIsNone(row["cut_reason"])
        self.assertIsNotNone(row["rank"])
        self.assertEqual(row["earner_count"], 3)
        self.assertEqual(row["subnetwork_n"], 256)
        mech = mine._mechanism_rows(self.conn, row["ts"])[1][0]
        # The divisor is the 3 earners + 1, never the 255 other UIDs.
        self.assertAlmostEqual(mech["parity_alpha_day"],
                               mech["indep_alpha_day"] / 4)


# ---------------------------------------------------------------------------
# 3. Haircut and pool depth (D5)
# ---------------------------------------------------------------------------

class TestSubnetWideHaircut(Base):

    def test_a_thin_pool_is_haircut_for_the_whole_subnets_sale(self):
        # 1 alpha per block is 7,200 alpha a day into 89,898 alpha of pool.
        self.seed([subnet(1, [5, 5], alpha_pool=89_898.0, tao_pool=600.0)])
        row = self.rows()[1]
        self.assertAlmostEqual(row["pool_days"], 89_898.0 / 7200.0, 3)
        expected = mine.exit_haircut_pct(7200.0, 89_898.0, 600.0, 0.5)
        self.assertAlmostEqual(row["haircut_pct"], expected, 6)
        self.assertGreater(row["haircut_pct"], 7.0)

    def test_the_sale_fraction_scales_the_sale(self):
        config = dict(self.config, mining=dict(self.config["mining"],
                                               subnet_sale_fraction=0.5))
        self.seed([subnet(1, [5, 5], alpha_pool=89_898.0, tao_pool=600.0)],
                  config=config)
        expected = mine.exit_haircut_pct(3600.0, 89_898.0, 600.0, 0.5)
        self.assertAlmostEqual(self.rows()[1]["haircut_pct"], expected, 6)

    def test_an_unknown_pool_gives_no_haircut_and_no_figure(self):
        self.seed([subnet(1, [5, 5], alpha_pool=None)])
        row = self.rows()[1]
        self.assertIsNone(row["haircut_pct"])
        self.assertIsNone(row["gross_tao_month"])
        self.assertIsNone(row["rank"])


# ---------------------------------------------------------------------------
# 4. Ladder: prune risk, hardware band, payback (D3, D6, D9)
# ---------------------------------------------------------------------------

OPEN = [{"mecid": 0, "split": 1.0, "indep_earner_count": 5,
         "indep_top1_share_pct": 40.0}]


class TestPruneRisk(unittest.TestCase):

    def cut(self, row, feasibility=None, config=None):
        rung, detail, _ = mine.classify_cut(config or cfg(), row, OPEN,
                                            feasibility)
        return rung, detail

    def test_a_full_subnet_with_a_short_immunity_period_is_cut(self):
        # Regression (audit D6, SN53): immunity 1 block, full, ranked 20th.
        rung, detail = self.cut({"uids_full": 1, "immunity_period": 1})
        self.assertEqual(rung, mine.CUT_PRUNE)
        self.assertIn("1 block", detail)
        self.assertIn("720", detail)

    def test_an_open_subnet_with_a_short_immunity_period_survives(self):
        rung, _ = self.cut({"uids_full": 0, "immunity_period": 1})
        self.assertIsNone(rung)

    def test_unknown_immunity_or_fullness_does_not_cut(self):
        self.assertIsNone(self.cut({"uids_full": 1,
                                    "immunity_period": None})[0])
        self.assertIsNone(self.cut({"uids_full": None,
                                    "immunity_period": 1})[0])

    def test_the_floor_is_configurable(self):
        rung, _ = self.cut({"uids_full": 1, "immunity_period": 300},
                           config=cfg(min_immunity_blocks=200))
        self.assertIsNone(rung)

    def test_prune_risk_comes_after_winner_take_all(self):
        concentrated = [dict(OPEN[0], indep_top1_share_pct=99.0)]
        rung, _, _ = mine.classify_cut(cfg(), {"uids_full": 1,
                                               "immunity_period": 1},
                                       concentrated, None)
        self.assertEqual(rung, mine.CUT_CONCENTRATION)


class TestHardwareBand(unittest.TestCase):

    def test_gpu_with_no_declared_vram_is_costed_at_the_smallest_gpu_band(
            self):
        band, assumed, _ = mine.required_band(
            cfg(), {"verdict": mine.VERDICT_NEEDS_GPU, "vram_gb": None})
        self.assertEqual((band, assumed), ("consumer-gpu", True))
        rung, _, _ = mine.classify_cut(
            cfg(), {}, OPEN, {"verdict": mine.VERDICT_NEEDS_GPU})
        self.assertIsNone(rung)

    def test_a_declared_floor_above_the_budget_is_cut_with_both_sizes(self):
        rung, detail, _ = mine.classify_cut(
            cfg(), {}, OPEN, {"verdict": mine.VERDICT_NEEDS_GPU,
                              "vram_gb": 48})
        self.assertEqual(rung, mine.CUT_HARDWARE)
        self.assertIn("48 GB", detail)
        self.assertIn("24 GB", detail)

    def test_a_floor_above_every_band_is_cut(self):
        rung, detail, _ = mine.classify_cut(
            cfg(), {}, OPEN, {"verdict": mine.VERDICT_NEEDS_GPU,
                              "vram_gb": 192})
        self.assertEqual(rung, mine.CUT_HARDWARE)
        self.assertIn("more than any configured band", detail)

    def test_a_declared_floor_inside_the_budget_is_not_assumed(self):
        band, assumed, _ = mine.required_band(
            cfg(), {"verdict": mine.VERDICT_NEEDS_GPU, "vram_gb": 16})
        self.assertEqual((band, assumed), ("consumer-gpu", False))

    def test_no_gpu_code_is_the_cpu_band_marked_assumed(self):
        # Absence of GPU code is not proof of a CPU miner.
        band, assumed, basis = mine.required_band(
            cfg(), {"verdict": mine.VERDICT_POSSIBLE})
        self.assertEqual((band, assumed), ("cpu", True))
        self.assertEqual(basis, "no GPU code found")

    def test_unknown_hardware_is_the_budget_band_and_assumed(self):
        for feature in (None, {"verdict": mine.VERDICT_UNKNOWN}):
            band, assumed, _ = mine.required_band(cfg(), feature)
            self.assertEqual((band, assumed), ("consumer-gpu", True))


class TestNetAndPayback(unittest.TestCase):

    def decide(self, feasibility, reg_cost=0.5, gross=15.0, config=None):
        row = {"netuid": 1, "confidence": mine.CONF_OK, "alpha_out_day":
               7200.0, "reg_cost_tao": reg_cost}
        mechs = {1: [dict(OPEN[0], gross_tao_month=gross,
                          no_figure_reason=None)]}
        results, _ = mine.decide(config or cfg(), [row], mechs,
                                 {1: feasibility} if feasibility else {})
        return results[1], mechs[1][0]

    def test_a_declared_16_gb_floor_is_netted_at_the_consumer_rent(self):
        result, mech = self.decide({"verdict": mine.VERDICT_NEEDS_GPU,
                                    "vram_gb": 16})
        self.assertEqual(result["required_band"], "consumer-gpu")
        self.assertEqual(result["band_assumed"], 0)
        self.assertAlmostEqual(mech["net_tao_month"], 13.5)
        self.assertEqual(result["rank"], 1)

    def test_a_cpu_miner_pays_no_rent(self):
        _, mech = self.decide({"verdict": mine.VERDICT_POSSIBLE})
        self.assertAlmostEqual(mech["net_tao_month"], 15.0)

    def test_payback_is_burn_over_net_per_day(self):
        self.assertAlmostEqual(mine.payback_days(0.5, 15.0), 1.0)
        result, _ = self.decide({"verdict": mine.VERDICT_POSSIBLE},
                                reg_cost=0.5, gross=15.0)
        self.assertAlmostEqual(result["payback_days"], 1.0)

    def test_no_payback_without_positive_net(self):
        self.assertIsNone(mine.payback_days(0.5, 0.0))
        self.assertIsNone(mine.payback_days(0.5, -1.0))
        self.assertIsNone(mine.payback_days(None, 10.0))
        self.assertIsNone(mine.payback_days(0.5, None))

    def test_gross_is_never_ranked_without_a_band(self):
        result, mech = self.decide({"verdict": mine.VERDICT_POSSIBLE},
                                   config=mine.mining_cfg({}))
        self.assertIsNone(result["rank"])
        self.assertEqual(result["unrated_reason"], mine.UNRATED_NO_BAND)
        self.assertIsNone(mech["net_tao_month"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# 5. Feasibility scanner v4 (D4)
# ---------------------------------------------------------------------------


class TestScannerV4(Base):

    def index_file(self, netuid, path, content, epoch=1):
        idx.ensure_schema(self.conn)
        cursor = self.conn.execute(
            "INSERT INTO fleet_files (netuid, epoch, path, indexed_sha, "
            "byte_size, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (netuid, epoch, path, "sha", len(content),
             "2026-11-03T00:00:00Z"))
        self.conn.execute(
            "INSERT INTO fleet_files_fts (rowid, path, content) "
            "VALUES (?, ?, ?)", (cursor.lastrowid, path, content))
        self.conn.commit()

    def scan(self, netuid=1, config=None):
        return mine.scan_slot(self.conn, config or mine.mining_cfg({}),
                              netuid, 1)

    def gpu(self, result):
        return [e for e in result["evidence"] if e["kind"] == "gpu"]

    def test_gpu_code_outside_the_entrypoint_is_found(self):
        # Regression (audit D4, SN9): the entrypoint is clean and the GPU
        # code sits elsewhere in the miner subtree.
        self.index_file(1, "neurons/miner.py", "import miner.model\n")
        self.index_file(1, "miner/model.py",
                        "import torch\n\nx = torch.cuda.is_available()\n")
        out = self.scan()
        self.assertEqual(out["verdict"], mine.VERDICT_NEEDS_GPU)
        hit = self.gpu(out)[0]
        self.assertEqual((hit["path"], hit["line"]), ("miner/model.py", 3))

    def test_gpu_code_without_a_recognised_entrypoint_is_needs_gpu(self):
        self.index_file(1, "src/miner_core/engine.py",
                        "model.to('cuda:0')\n")
        out = self.scan()
        self.assertIsNone(out["entrypoint_path"])
        self.assertEqual(out["verdict"], mine.VERDICT_NEEDS_GPU)

    def test_a_bare_gpu_mention_is_recorded_and_changes_nothing(self):
        self.index_file(1, "neurons/miner.py", "print('hello')\n")
        self.index_file(1, "miner/README.md",
                        "No GPU needed: this miner runs on any box.\n")
        out = self.scan()
        self.assertEqual(out["verdict"], mine.VERDICT_POSSIBLE)
        self.assertEqual(out["reason"], "no GPU code found")
        mentions = [e for e in out["evidence"]
                    if e["kind"] == "gpu-mention"]
        self.assertEqual(mentions[0]["path"], "miner/README.md")
        self.assertEqual(self.gpu(out), [])

    def test_a_strong_token_in_prose_does_not_count(self):
        self.index_file(1, "neurons/miner.py", "print('hello')\n")
        self.index_file(1, "miner/NOTES.md", "we tried vllm once\n")
        self.assertEqual(self.scan()["verdict"], mine.VERDICT_POSSIBLE)

    def test_a_gpu_dependency_counts(self):
        self.index_file(1, "neurons/miner.py", "print('hello')\n")
        self.index_file(1, "miner/requirements.txt", "vllm==0.6.0\n")
        self.assertEqual(self.scan()["verdict"], mine.VERDICT_NEEDS_GPU)

    def test_validator_and_test_paths_are_ignored(self):
        self.index_file(1, "neurons/miner.py", "print('hello')\n")
        self.index_file(1, "validator/miner_scoring.py",
                        "x = torch.cuda.device_count()\n")
        self.index_file(1, "miner/tests/test_gpu.py", "torch.cuda.init()\n")
        self.assertEqual(self.scan()["verdict"], mine.VERDICT_POSSIBLE)

    def test_the_subtree_read_is_bounded(self):
        self.index_file(1, "neurons/miner.py", "print('hello')\n")
        self.index_file(1, "miner/a.py", "print(1)\n")
        self.index_file(1, "miner/z.py", "torch.cuda.init()\n")
        bounded = mine.mining_cfg({"mining": {"max_subtree_files": 1}})
        self.assertEqual(self.scan(config=bounded)["verdict"],
                         mine.VERDICT_POSSIBLE)
        self.assertEqual(self.scan()["verdict"], mine.VERDICT_NEEDS_GPU)

    def test_the_scanner_version_is_4(self):
        self.assertEqual(mine.SCAN_VERSION, "4")


# ---------------------------------------------------------------------------
# 5b. Activity facts and the consensus tracker
# ---------------------------------------------------------------------------

BLOCK = 9_000_000


def context(**overrides):
    """A mining context for netuid 1 at BLOCK, as live-data returns it."""
    base = {
        "block_number": BLOCK, "block_hash": "0xabc",
        "maps": {
            "SubnetEpochConsensus": {},
            "NullPruningTarget": {},
            # uids 0 and 1 hold permits; 0 is fresh, 1 is stale.
            "ValidatorPermit": {1: [True, True, False, False, False]},
            "LastUpdate": {(1, 0): [BLOCK - 10, BLOCK - 9000, 0, 0, 0]},
            "ActivityCutoff": {1: 5000},
        },
        "failures": {}, "unread": {},
        "weights": {(1, 0, 0): [2, 3, 4, 5, 6], (1, 0, 1): [2, 7]},
        "registration": {1: [100, BLOCK - 10, BLOCK - 60_000, None, 5]},
        "axons": {1: [BLOCK - 5, BLOCK - 100_000]},
    }
    base.update(overrides)
    return base


class TestActivityFacts(unittest.TestCase):

    def facts(self, ctx, count=1):
        return mine.activity_facts(1, count, ctx)

    def test_each_count_follows_its_definition(self):
        out = self.facts(context())
        self.assertEqual(out["registered_7d"], 1)
        self.assertEqual(out["axons_served_7d"], 1)
        self.assertEqual(out["weighted_uids"], 5)
        self.assertEqual(out["widest_weight_row"], 5)
        self.assertEqual(out["consensus_mode"], "Yuma")  # unset is Yuma
        self.assertIsNone(out["null_pruning_target"])

    def test_a_stale_validator_row_is_not_counted(self):
        # uid 1 weights uid 7, but it last updated 9,000 blocks ago against
        # a 5,000-block cutoff.
        self.assertNotIn(7, context()["weights"][(1, 0, 0)])
        self.assertEqual(self.facts(context())["weighted_uids"], 5)

    def test_a_row_without_a_permit_is_not_counted(self):
        ctx = context()
        ctx["weights"][(1, 0, 2)] = list(range(50, 90))
        ctx["maps"]["LastUpdate"][(1, 0)][2] = BLOCK
        self.assertEqual(self.facts(ctx)["weighted_uids"], 5)

    def test_a_top5_weighting_pattern_reads_as_a_widest_row_of_5(self):
        ctx = context()
        ctx["maps"]["ValidatorPermit"][1] = [True, True, True]
        ctx["maps"]["LastUpdate"][(1, 0)] = [BLOCK, BLOCK, BLOCK]
        ctx["weights"] = {(1, 0, 0): [3, 4, 5, 6, 7], (1, 0, 1): [3, 4, 5],
                          (1, 0, 2): []}
        self.assertEqual(self.facts(ctx)["widest_weight_row"], 5)

    def test_an_unread_input_is_none_not_zero(self):
        out = self.facts(context(unread={"BlockAtRegistration": "x",
                                         "Axons": "y", "Weights": "z",
                                         "SubnetEpochConsensus": "w"}))
        self.assertIsNone(out["registered_7d"])
        self.assertIsNone(out["axons_served_7d"])
        self.assertIsNone(out["weighted_uids"])
        self.assertIsNone(out["widest_weight_row"])
        self.assertIsNone(out["consensus_mode"])
        self.assertIsNone(self.facts(None)["registered_7d"])

    def test_a_per_subnet_decode_failure_is_none(self):
        out = self.facts(context(failures={
            "SubnetEpochConsensus": {1: "unknown index"},
            "Weights": {(1, 0, 0): "bad row"}}))
        self.assertIsNone(out["consensus_mode"])
        self.assertIsNone(out["weighted_uids"])

    def test_null_and_a_pending_prune_are_read(self):
        ctx = context()
        ctx["maps"]["SubnetEpochConsensus"] = {1: "Null"}
        ctx["maps"]["NullPruningTarget"] = {1: 200}
        out = self.facts(ctx)
        self.assertEqual(out["consensus_mode"], "Null")
        self.assertEqual(out["null_pruning_target"], 200)

    def test_no_stored_fact_holds_an_address(self):
        out = self.facts(context())
        self.assertTrue(all(v is None or isinstance(v, (int, str))
                            for v in out.values()))


class TestConsensusTracker(Base):

    def snapshot(self, modes, block):
        snap = synthetic([subnet(n, [5, 5]) for n in sorted(modes)],
                         block=block)
        snap["context"] = {"block_number": block, "maps": {
            "SubnetEpochConsensus": {n: m for n, m in modes.items()
                                     if m not in (None, "Yuma")}},
            "failures": {"SubnetEpochConsensus": {
                n: "bad" for n, m in modes.items() if m is None}},
            "unread": {}}
        return snap

    def econ_pass(self, modes, block, now):
        out = mine.run_econ(self.conn, self.config, now=now,
                            snapshot=self.snapshot(modes, block))
        self.assertTrue(out["ok"], out)

    def events(self):
        return self.conn.execute(
            "SELECT netuid, prev_mode, new_mode, block_number FROM "
            "mine_consensus_events ORDER BY id").fetchall()

    def test_the_first_pass_seeds_without_switches(self):
        modes = {n: "Yuma" for n in range(1, 129)}
        modes[24] = "Null"
        self.econ_pass(modes, 100, "2026-11-03T00:00:00+00:00")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM mine_consensus_state").fetchone()[0], 128)
        self.assertEqual(self.events(), [])

    def test_a_switch_is_recorded_with_its_block_and_no_alert(self):
        self.econ_pass({1: "Yuma"}, 100, "2026-11-03T00:00:00+00:00")
        self.econ_pass({1: "Null"}, 200, "2026-11-03T06:00:00+00:00")
        self.assertEqual(self.events(), [(1, "Yuma", "Null", 200)])
        view = mine.consensus_view(self.conn)
        self.assertEqual(view["counts"], {"Null": 1})
        self.assertEqual(view["null"][0]["since_block"], 200)
        self.assertIsNone(view["null"][0]["first_seen_by_atlas"])
        # The tracker owns no alert path: nothing reaches the chain
        # parameter watch's event table, which Telegram reads.
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("chain_param_events", tables)

    def test_a_null_subnet_seen_first_says_so(self):
        self.econ_pass({24: "Null"}, 100, "2026-11-03T00:00:00+00:00")
        entry = mine.consensus_view(self.conn)["null"][0]
        self.assertIsNone(entry["since_block"])
        self.assertEqual(entry["first_seen_by_atlas"],
                         "2026-11-03T00:00:00+00:00")

    def test_an_unknown_mode_records_nothing(self):
        self.econ_pass({1: "Yuma"}, 100, "2026-11-03T00:00:00+00:00")
        self.econ_pass({1: None}, 200, "2026-11-03T06:00:00+00:00")
        self.assertEqual(self.events(), [])
        latest = self.conn.execute(
            "SELECT consensus_mode FROM mine_econ WHERE netuid = 1 "
            "ORDER BY ts DESC LIMIT 1").fetchone()
        self.assertIsNone(latest[0])


# ---------------------------------------------------------------------------
# 6. Surfaces (D9, D10, labels)
# ---------------------------------------------------------------------------

class TestBoardPage(Base):

    def page(self):
        mine.render(self.conn, self.config)
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            return handle.read()

    def seed_with_context(self, mode="Yuma", target=None):
        snap = synthetic([subnet(1, [5, 5, 0, 0], network_n=4)],
                         block=BLOCK)
        snap["context"] = context(maps=dict(
            context()["maps"],
            SubnetEpochConsensus={1: mode} if mode != "Yuma" else {},
            NullPruningTarget={1: target} if target is not None else {}))
        mf.seed_board(self.conn, self.config, snap)

    def test_the_page_labels_spot_payback_and_the_model(self):
        self.seed_with_context()
        page = self.page()
        self.assertIn("at today's spot price", page)
        self.assertIn("payback days", page)
        self.assertIn("p25 earner", page)
        self.assertIn("median earner", page)
        self.assertIn("pool days", page)
        self.assertIn("hardware band", page)
        self.assertIn("consumer-gpu (assumed)", page)
        self.assertNotIn("enter at rank", page)

    def test_the_page_shows_each_count_with_its_definition(self):
        self.seed_with_context()
        page = self.page()
        self.assertIn("2 of 4 earning", page)
        self.assertIn("reg 7d 1", page)
        self.assertIn("weighted 5", page)
        self.assertIn("widest row 5", page)
        self.assertIn("axons 7d 1", page)
        for name, _text in mine.ACTIVITY_DEFINITIONS:
            self.assertIn("<b>%s</b>" % name, page)
        self.assertIn("1/65535", page)
        self.assertIn("last revealed weights", page)
        self.assertIn("validators included", page)

    def test_the_page_never_calls_a_uid_active_or_idle(self):
        self.seed_with_context(mode="Null", target=2)
        page = self.page().lower()
        for word in ("active", "idle", "inactive"):
            self.assertNotRegex(page, r"\b%s\b" % word)

    def test_a_null_subnet_and_a_pending_prune_are_flagged(self):
        self.seed_with_context(mode="Null", target=2)
        page = self.page()
        self.assertIn("Consensus mode", page)
        self.assertIn(mine.NULL_FLAG, page)
        self.assertIn("owner pruning pending: target 2 of 4 registered",
                      page)
        self.assertIn("first seen by Atlas", page)

    def test_possible_reads_as_no_gpu_code_found(self):
        cell, _ = mine._feasibility_cells(
            {"feasibility": {"verdict": mine.VERDICT_POSSIBLE}})
        self.assertEqual(cell, "no GPU code found")
        self.assertNotIn("CPU", cell)

    def test_gpu_mentions_are_counted_beside_possible(self):
        # SN44 and SN48 at block 9423301: no GPU code, but GPU mentioned in
        # miner docs and min_compute.yml.
        feature = {"verdict": mine.VERDICT_POSSIBLE, "evidence": {
            "evidence": [{"kind": "gpu-mention", "path": "miner/MINER.md"},
                         {"kind": "gpu-mention", "path": "miner/MINER.md"},
                         {"kind": "gpu-mention", "path": "miner/README.md"},
                         {"kind": "entrypoint", "path": "neurons/miner.py"}]}}
        self.assertEqual(mine.hardware_label(feature),
                         "no GPU code found; GPU mentioned in 2 file(s)")
        row = mine.compact_row({"feasibility": feature})
        self.assertEqual(row["hardware_evidence"]["verdict"],
                         "no GPU code found; GPU mentioned in 2 file(s)")


class TestHistoryModelBoundary(Base):
    """Regression: after the model-3 pass, SN8's history would jump from
    147.6 to 0.07 alpha/day with nothing saying the model changed."""

    def test_rows_carry_their_model_version(self):
        self.seed([subnet(1, [5, 5])])
        self.assertEqual(self.rows()[1]["model_version"],
                         mine.MODEL_VERSION)

    def test_history_marks_observations_from_an_earlier_model(self):
        mf.seed_board(self.conn, self.config, synthetic([subnet(1, [5, 5])]),
                      now="2026-11-03T00:00:00+00:00")
        old_ts = self.rows()[1]["ts"]
        # A pre-deploy row: same subnet, no recorded version.
        self.conn.execute("UPDATE mine_econ SET model_version = NULL "
                          "WHERE ts = ?", (old_ts,))
        self.conn.commit()
        mf.seed_board(self.conn, self.config, synthetic(
            [subnet(1, [5, 5])]), now="2026-11-03T06:00:00+00:00")
        config = os.path.join(self.tmp, "config.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"db": self.db, "clone_root": os.path.join(
                self.tmp, "clones"), "mining": self.config["mining"]},
                handle)
        os.makedirs(os.path.join(self.tmp, "clones"), exist_ok=True)
        out = srv.FleetStore(config).mining_history(1, None, 10)
        self.assertEqual(out.get("status"), "ok", out)
        self.assertTrue(out["model_boundary"])
        self.assertIn("earlier economics model", out["model_note"])
        flags = [o["same_model_as_latest"] for o in out["observations"]]
        self.assertEqual(flags, [True, False])
