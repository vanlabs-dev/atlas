"""Netuid-keyed chain-parameter watch (change: mining-triage): per-subnet
observations against each subnet's own history, dormant seeding without a
transition, the transition that fires when a subnet enables collateral, and
per-subnet failure isolation."""

import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402

CONFIG = {"chain_params": {"enabled": True}}
ITEM = "CollateralLockShare"
UNIVERSE = [1, 4, 8, 19]


class SubnetParamWatch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def watch(self, values, failures=None, block=100):
        return al.run_subnet_param_watch(
            self.conn, CONFIG, ITEM, UNIVERSE, values,
            failures=failures, block_hash="0x%x" % block, block_number=block)

    def test_composite_item_round_trips(self):
        self.assertEqual(al.netuid_item(ITEM, 19), "CollateralLockShare[19]")
        self.assertEqual(al.parse_netuid_item("CollateralLockShare[19]"),
                         (ITEM, 19))
        self.assertEqual(al.parse_netuid_item("RootWeightSettingEnabled"),
                         ("RootWeightSettingEnabled", None))

    def test_dormant_map_seeds_every_subnet_without_transitions(self):
        out = self.watch({})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["observed"]), len(UNIVERSE))
        self.assertEqual(out["transitions"], [])
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM chain_params").fetchone()[0]
        self.assertEqual(rows, len(UNIVERSE))

    def test_dormant_seed_records_assumed_default_provenance(self):
        self.watch({})
        provenance = self.conn.execute(
            "SELECT provenance FROM chain_params WHERE item = ?",
            (al.netuid_item(ITEM, 1),)).fetchone()[0]
        self.assertEqual(provenance, "assumed-default")

    def test_subnet_enabling_collateral_emits_a_transition(self):
        """The scenario the whole watch exists for."""
        self.watch({})
        out = self.watch({19: 32767}, block=200)
        self.assertEqual(len(out["transitions"]), 1)
        event = out["transitions"][0]
        self.assertEqual(event["netuid"], 19)
        self.assertEqual(event["base_item"], ITEM)
        self.assertEqual(event["prev_value"], "0")
        self.assertEqual(event["new_value"], "32767")
        self.assertEqual(event["prev_provenance"], "assumed-default")
        self.assertEqual(event["new_provenance"], "explicit")

    def test_only_the_changed_subnet_transitions(self):
        self.watch({})
        out = self.watch({19: 100}, block=200)
        self.assertEqual([t["netuid"] for t in out["transitions"]], [19])

    def test_unchanged_value_emits_nothing_on_later_passes(self):
        self.watch({})
        self.watch({19: 100}, block=200)
        out = self.watch({19: 100}, block=300)
        self.assertEqual(out["transitions"], [])

    def test_disabling_collateral_also_transitions(self):
        self.watch({})
        self.watch({19: 100}, block=200)
        out = self.watch({}, block=300)
        self.assertEqual(len(out["transitions"]), 1)
        self.assertEqual(out["transitions"][0]["new_value"], "0")

    def test_unreadable_subnet_records_nothing_and_does_not_blind_the_rest(
            self):
        out = self.watch({1: 5}, failures={8: "bad payload"})
        self.assertIn(al.netuid_item(ITEM, 8), out["skipped"])
        self.assertEqual(len(out["observed"]), len(UNIVERSE) - 1)
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM chain_params WHERE item = ?",
            (al.netuid_item(ITEM, 8),)).fetchone()[0]
        self.assertEqual(rows, 0)

    def test_recovery_after_failure_does_not_fabricate_a_transition(self):
        self.watch({8: 100})
        self.watch({8: 100}, failures={8: "transient"}, block=200)
        out = self.watch({8: 100}, block=300)
        self.assertEqual(out["transitions"], [])

    def test_transition_is_durable_and_carries_the_block(self):
        self.watch({})
        self.watch({4: 7}, block=250)
        row = self.conn.execute(
            "SELECT item, prev_value, new_value, block_number "
            "FROM chain_param_events").fetchone()
        self.assertEqual(row[0], al.netuid_item(ITEM, 4))
        self.assertEqual((row[1], row[2]), ("0", "7"))
        self.assertEqual(row[3], 250)

    def test_watch_respects_the_kill_switch(self):
        out = al.run_subnet_param_watch(
            self.conn, {"chain_params": {"enabled": False}}, ITEM,
            UNIVERSE, {})
        self.assertEqual(out["status"], "disabled")

    def test_item_without_a_documented_default_is_refused(self):
        with self.assertRaises(al.FatalLiveError):
            al.run_subnet_param_watch(self.conn, CONFIG, "SomeOtherMap",
                                      UNIVERSE, {})


SWITCH = "SubnetEmissionEnabled"


class EmissionSwitchWatch(unittest.TestCase):
    """Pool-side emission switch (change: network-drift-455)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def watch(self, values, failures=None, block=100):
        return al.run_subnet_param_watch(
            self.conn, CONFIG, SWITCH, UNIVERSE, values,
            failures=failures, block_hash="0x%x" % block, block_number=block)

    def test_first_observation_seeds_every_subnet_without_transitions(self):
        out = self.watch({1: True, 4: True, 8: True, 19: True})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["observed"]), len(UNIVERSE))
        self.assertEqual(out["transitions"], [])

    def test_absent_entry_seeds_as_off_not_as_a_failed_read(self):
        out = self.watch({1: True, 4: True, 8: True})
        self.assertEqual(out["transitions"], [])
        name = al.netuid_item(SWITCH, 19)
        row = self.conn.execute(
            "SELECT value, provenance FROM chain_params WHERE item = ?",
            (name,)).fetchone()
        self.assertEqual(row, ("false", "assumed-default"))
        self.assertNotIn(name, out["skipped"])

    def test_seed_then_transition_carries_netuid_values_and_block(self):
        self.watch({n: True for n in UNIVERSE})
        out = self.watch({1: True, 4: True, 8: True, 19: False}, block=200)
        self.assertEqual(len(out["transitions"]), 1)
        event = out["transitions"][0]
        self.assertEqual(event["netuid"], 19)
        self.assertEqual(event["base_item"], SWITCH)
        self.assertEqual(event["prev_value"], "true")
        self.assertEqual(event["new_value"], "false")
        row = self.conn.execute(
            "SELECT block_number FROM chain_param_events").fetchone()
        self.assertEqual(row[0], 200)

    def test_same_block_batch_records_every_netuid(self):
        self.watch({n: False for n in UNIVERSE})
        out = self.watch({n: True for n in UNIVERSE}, block=9029889)
        self.assertEqual(len(out["transitions"]), len(UNIVERSE))
        self.assertEqual({t["netuid"] for t in out["transitions"]},
                         set(UNIVERSE))
        stored = [r[0] for r in self.conn.execute(
            "SELECT block_number FROM chain_param_events")]
        self.assertEqual(stored, [9029889] * len(UNIVERSE))

    def test_short_batch_skips_the_switch_without_touching_collateral(self):
        """A failed switch read must not prevent CollateralLockShare from
        seeding, which is the 'other watched items' isolation."""
        al.run_subnet_param_watch(
            self.conn, CONFIG, ITEM, UNIVERSE, {}, block_number=100)
        skipped = al.watch_subnet_emission_switch(
            self.conn, CONFIG,
            maps={"ok": True,
                  "values": {"SubnetworkN": {n: 256 for n in UNIVERSE},
                             "SubnetEmissionEnabled": {}},
                  "failures": {},
                  "failed_items": {"SubnetEmissionEnabled": "short batch"},
                  "block_number": 200})
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "short batch")
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM chain_params WHERE item LIKE ?",
            (SWITCH + "[%",)).fetchone()[0]
        self.assertEqual(rows, 0)
        collateral = self.conn.execute(
            "SELECT COUNT(*) FROM chain_params WHERE item LIKE ?",
            (ITEM + "[%",)).fetchone()[0]
        self.assertEqual(collateral, len(UNIVERSE))


if __name__ == "__main__":
    unittest.main()
