"""The mining chain snapshot (change: mining-board-accuracy): mechanism-
indexed incentive keys, Twox64Concat netuid tails, the new decoders, point
reads for owner resolution with a fail-closed cap, and one audit record per
chain read, failures included."""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402
from test_subnet_maps import (CONFIG, FakeChain, tables, u64_hex,  # noqa: E402
                              vec_u16_hex)

# Pinned from live Finney at block 9142865 (2026-09-25): the first Uids key
# of netuid 1, its hotkey, and its value (uid 185).
LIVE_UIDS_KEY = (
    "0x658faa385070e074c85bf6b568cf0555aab1b4e78e1ea8305462ee53b3686dc8"
    "010000c5f41db7a1fe4cbdc1a34a7316bf85c84397106379d0ebdce4437f0333d8"
    "123d46eebbcaadf181c8ba441218d3d25b")
LIVE_UIDS_HOTKEY = (
    "0xc84397106379d0ebdce4437f0333d8123d46eebbcaadf181c8ba441218d3d25b")

COLDKEY = "0x" + "11" * 32
OWNER_HK = "0x" + "22" * 32
OTHER_HK = "0x" + "33" * 32


def vec_account_hex(accounts):
    count = len(accounts)
    prefix = (bytes([count << 2]) if count < 64
              else ((count << 2) | 0b01).to_bytes(2, "little"))
    return "0x" + (prefix + b"".join(bytes.fromhex(a[2:])
                                     for a in accounts)).hex()


def u8_hex(value):
    return "0x%02x" % value


def u16_hex(value):
    return "0x" + int(value).to_bytes(2, "little").hex()


def perquintill_hex(fraction):
    return u64_hex(int(round(fraction * al.PERQUINTILL_ONE)))


def owned_key(coldkey):
    return al.storage_key(al.SUBTENSOR_PALLET, "OwnedHotkeys",
                          bytes.fromhex(coldkey[2:]))


def uids_key(netuid, hotkey):
    return al.storage_key(al.SUBTENSOR_PALLET, "Uids",
                          int(netuid).to_bytes(2, "little"),
                          bytes.fromhex(hotkey[2:]))


def snapshot_tables(**extra):
    return tables(extra=dict({
        "SubnetOwner": {1: COLDKEY, 8: COLDKEY},
        "SubnetOwnerHotkey": {1: OWNER_HK},
        "MechanismCountCurrent": {1: u8_hex(2)},
        "MechanismEmissionSplit": {1: vec_u16_hex([1311, 64224])},
        "SwapBalancer": {1: perquintill_hex(0.5)},
    }, **extra), incentive={1: vec_u16_hex([100, 0, 50, 0]),
                            4097: vec_u16_hex([0, 7, 0, 0]),
                            8: vec_u16_hex([1, 2])})


def snapshot_points(owned=None):
    return {
        owned_key(COLDKEY): vec_account_hex(owned if owned is not None
                                            else [OTHER_HK]),
        uids_key(1, OWNER_HK): u16_hex(0),
        uids_key(8, OTHER_HK): u16_hex(1),
    }


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = al.open_store(os.path.join(self.tmp.name, "live.db"))
        self.addCleanup(self.store.close)

    def audits(self):
        return [dict(zip(("provider", "operation", "params",
                          "validation_result", "error_category"), row))
                for row in self.store.execute(
                    "SELECT provider, operation, params, validation_result, "
                    "error_category FROM audit ORDER BY id")]


class Decoders(unittest.TestCase):

    def test_u8_mechid(self):
        self.assertEqual(al.decode_by_codec("u8", "0x02"), 2)
        with self.assertRaises(ValueError):
            al.decode_by_codec("u8", "0x0200")

    def test_account_id_is_32_bytes(self):
        self.assertEqual(al.decode_by_codec("account_id", COLDKEY), COLDKEY)
        with self.assertRaises(ValueError):
            al.decode_by_codec("account_id", "0x" + "11" * 31)

    def test_vec_account_id_round_trips_and_rejects_a_short_payload(self):
        payload = vec_account_hex([COLDKEY, OWNER_HK])
        self.assertEqual(al.decode_by_codec("vec_account_id", payload),
                         [COLDKEY, OWNER_HK])
        with self.assertRaises(ValueError):
            al.decode_by_codec("vec_account_id", payload[:-2])

    def test_balances_are_u64(self):
        self.assertEqual(al.decode_by_codec("u64", u64_hex(10 ** 9)),
                         10 ** 9)
        with self.assertRaises(ValueError):
            al.decode_by_codec("u64", "0x" + "00" * 16)

    def test_perquintill_is_over_1e18(self):
        self.assertAlmostEqual(
            al.decode_by_codec("perquintill", perquintill_hex(0.5)), 0.5)
        with self.assertRaises(ValueError):
            al.decode_by_codec("perquintill", u64_hex(10 ** 18 + 1))
        with self.assertRaises(ValueError):
            al.decode_by_codec("perquintill", "0x00")


class MapKeys(unittest.TestCase):

    def test_mechanism_keys_above_4096_map_to_netuid_and_mecid(self):
        out = al.read_subnet_maps(CONFIG, rpc=FakeChain(snapshot_tables()))
        self.assertTrue(out["ok"], out.get("error"))
        incentive = out["values"]["Incentive"]
        self.assertEqual(incentive[(1, 0)], [100, 0, 50, 0])
        self.assertEqual(incentive[(1, 1)], [0, 7, 0, 0])
        self.assertEqual(incentive[(8, 0)], [1, 2])
        self.assertNotIn(4097, incentive)

    def test_twox64_concat_tails_decode(self):
        out = al.read_subnet_maps(CONFIG, rpc=FakeChain(snapshot_tables()))
        self.assertEqual(out["values"]["MechanismCountCurrent"], {1: 2})
        self.assertEqual(out["values"]["MechanismEmissionSplit"],
                         {1: [1311, 64224]})

    def test_swap_pallet_item_reads_at_the_same_block(self):
        rpc = FakeChain(snapshot_tables())
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertAlmostEqual(out["values"]["SwapBalancer"][1], 0.5)
        self.assertEqual(rpc.calls.count("chain_getFinalizedHead"), 1)

    def test_point_key_matches_a_pinned_live_uids_key(self):
        self.assertEqual(uids_key(1, LIVE_UIDS_HOTKEY), LIVE_UIDS_KEY)

    def test_key_count_must_match_the_declared_hashers(self):
        with self.assertRaises(al.FatalLiveError):
            al.storage_key(al.SUBTENSOR_PALLET, "Uids",
                           (1).to_bytes(2, "little"))

    def test_undeclared_point_read_fails_naming_the_item(self):
        with self.assertRaises(al.FatalLiveError) as caught:
            al.storage_key(al.SUBTENSOR_PALLET, "Keys",
                           (1).to_bytes(2, "little"))
        self.assertIn("Keys", str(caught.exception))


class OwnerResolution(StoreCase):

    def snapshot(self, owned=None, **kwargs):
        rpc = FakeChain(snapshot_tables(), points=snapshot_points(owned),
                        **kwargs)
        return al.read_mining_snapshot(CONFIG, rpc=rpc,
                                       connection=self.store), rpc

    def test_owner_uids_resolve_at_the_snapshot_block(self):
        out, rpc = self.snapshot()
        self.assertTrue(out["ok"], out.get("error"))
        # Owner hotkey on SN1 holds uid 0; the coldkey's other hotkey holds
        # uid 1 on SN8 and nothing on SN1.
        self.assertEqual(out["owners"][1], {"state": "ok", "uids": [0],
                                            "hotkeys": 2})
        self.assertEqual(out["owners"][8]["uids"], [1])
        self.assertEqual(rpc.calls.count("chain_getFinalizedHead"), 1)

    def test_owner_cut_unset_is_the_runtime_default(self):
        out, _ = self.snapshot()
        self.assertEqual(out["owner_cut"], al.SUBNET_OWNER_CUT_DEFAULT)
        self.assertEqual(out["owner_cut_state"], "runtime-default")

    def test_owner_cut_set_on_chain_is_read(self):
        rpc = FakeChain(snapshot_tables(), points=dict(
            snapshot_points(),
            **{al.storage_key(al.SUBTENSOR_PALLET, "SubnetOwnerCut"):
               u16_hex(0)}))
        out = al.read_mining_snapshot(CONFIG, rpc=rpc)
        self.assertEqual(out["owner_cut"], 0)
        self.assertEqual(out["owner_cut_state"], "set")

    def test_cap_exceeded_fails_closed_for_that_subnet(self):
        many = ["0x%064x" % i for i in range(al.OWNED_HOTKEYS_CAP + 1)]
        out, _ = self.snapshot(owned=many)
        self.assertTrue(out["ok"])
        for netuid in (1, 8):
            self.assertEqual(out["owners"][netuid]["state"], "unread")
            self.assertIn("cap", out["owners"][netuid]["reason"])
            self.assertNotIn("uids", out["owners"][netuid])

    def test_undecodable_owner_set_is_unread_not_empty(self):
        rpc = FakeChain(snapshot_tables(), points=dict(
            snapshot_points(), **{owned_key(COLDKEY): "0x08"}))
        out = al.read_mining_snapshot(CONFIG, rpc=rpc)
        self.assertEqual(out["owners"][1]["state"], "unread")

    def test_an_unset_owner_coldkey_resolves_like_the_runtime_default(self):
        rpc = FakeChain(snapshot_tables(SubnetOwner={1: COLDKEY}),
                        points=snapshot_points())
        out = al.read_mining_snapshot(CONFIG, rpc=rpc)
        self.assertEqual(out["owners"][8], {"state": "ok", "uids": [],
                                            "hotkeys": 0})

    def test_audit_row_per_read_on_success(self):
        out, _ = self.snapshot()
        self.assertTrue(out["ok"])
        rows = self.audits()
        # Maps, SubnetOwnerCut, OwnedHotkeys, Uids.
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row["provider"], "finney-rpc")
            self.assertEqual(row["operation"], "chain_storage")
            self.assertEqual(row["validation_result"], "ok")
        maps = json.loads(rows[0]["params"])
        self.assertEqual(maps["block_number"], 8789861)
        self.assertEqual(maps["block_hash"], "0xabc")
        self.assertEqual(maps["keys_requested"]["Incentive"], 3)
        self.assertIn("SwapBalancer", maps["items"])
        uids = json.loads(rows[3]["params"])
        self.assertEqual(uids["items"], ["Uids"])
        self.assertEqual(uids["keys_requested"]["Uids"], 3)
        # No storage value is retained in the audit.
        self.assertNotIn(COLDKEY[2:], "".join(r["params"] for r in rows))

    def test_audit_row_on_a_failed_read(self):
        out, _ = self.snapshot(fail_method="state_queryStorageAt",
                               fail_after=2)
        self.assertFalse(out["ok"])
        rows = self.audits()
        self.assertEqual(rows[-1]["validation_result"], "failed")
        self.assertEqual(rows[-1]["error_category"], "transport")

    def test_derivation_failure_is_a_failed_audited_read(self):
        bad = {"gate_signal": {"storage_keys": {"EmissionGateBar": "0xno"}}}
        rpc = FakeChain(snapshot_tables())
        out = al.read_subnet_maps(bad, rpc=rpc, connection=self.store)
        self.assertFalse(out["ok"])
        self.assertEqual(rpc.calls, [])
        self.assertEqual(self.audits()[-1]["error_category"],
                         "key-derivation")

    def test_failed_map_read_fails_the_snapshot(self):
        rpc = FakeChain(snapshot_tables(), fail_method="state_getKeysPaged")
        out = al.read_mining_snapshot(CONFIG, rpc=rpc, connection=self.store)
        self.assertFalse(out["ok"])
        self.assertEqual(self.audits()[-1]["validation_result"], "failed")


if __name__ == "__main__":
    unittest.main()
