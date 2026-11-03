"""Mining economics model (change: mining-economics-model, audit WP4 items
D1 to D6, D9, D10): the entrant figure is the lower of the parity share and
the 25th-percentile earner, the haircut prices the whole subnet's daily
sale, a full subnet with a short immunity period is cut, each subnet is
costed at the hardware band its evidence needs, and payback is reported.
"""

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

    def test_no_gpu_evidence_is_the_cpu_band(self):
        band, assumed, basis = mine.required_band(
            cfg(), {"verdict": mine.VERDICT_POSSIBLE})
        self.assertEqual((band, assumed), ("cpu", False))
        self.assertEqual(basis, "no GPU evidence found")

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
        self.assertEqual(out["reason"], "no GPU evidence found")
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
