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
        # The chain holds an owner hotkey and a balancer for every non-root
        # subnet; both are dense maps (change: live-data-correctness).
        "SubnetOwnerHotkey": {1: OWNER_HK, 8: OWNER_HK},
        "MechanismCountCurrent": {1: u8_hex(2)},
        "MechanismEmissionSplit": {1: vec_u16_hex([1311, 64224])},
        "SwapBalancer": {1: perquintill_hex(0.5), 8: perquintill_hex(0.5)},
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

    def test_a_missing_owner_key_is_unread_not_the_runtime_default(self):
        # Audit A13: every registered non-root subnet has a SubnetOwner key,
        # so a missing one is a read fault, never "the owner owns nothing".
        rpc = FakeChain(snapshot_tables(SubnetOwner={1: COLDKEY}),
                        points=snapshot_points())
        out = al.read_mining_snapshot(CONFIG, rpc=rpc)
        self.assertEqual(out["owners"][8], {
            "state": "unread",
            "reason": "SubnetOwner absent from dense map"})

    def test_audit_row_per_read_on_success(self):
        out, _ = self.snapshot()
        self.assertTrue(out["ok"])
        rows = self.audits()
        # Maps, SubnetOwnerCut, OwnedHotkeys, Uids, then the context: its
        # maps, Weights, BlockAtRegistration, Axons.
        self.assertEqual(len(rows), 8)
        self.assertEqual([json.loads(r["params"])["items"] for r in rows[5:]],
                         [["Weights"], ["BlockAtRegistration"], ["Axons"]])
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
        # SN1: the coldkey's hotkey plus the owner hotkey; SN8 the same.
        self.assertEqual(uids["keys_requested"]["Uids"], 4)
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


# ---------------------------------------------------------------------------
# Mining context (change: mining-economics-model)
# ---------------------------------------------------------------------------

def vec_bool_hex(flags):
    return "0x" + bytes([len(flags) << 2] + [1 if f else 0
                                             for f in flags]).hex()


def vec_u64_hex(values):
    return "0x" + (bytes([len(values) << 2]) + b"".join(
        int(v).to_bytes(8, "little") for v in values)).hex()


def pairs_hex(pairs):
    return "0x" + (bytes([len(pairs) << 2]) + b"".join(
        int(u).to_bytes(2, "little") + int(w).to_bytes(2, "little")
        for u, w in pairs)).hex()


def axon_hex(block, ip=0x7F000001, port=8091):
    return "0x" + (int(block).to_bytes(8, "little") + (1).to_bytes(4, "little")
                   + int(ip).to_bytes(16, "little")
                   + int(port).to_bytes(2, "little") + bytes([4, 0, 0, 0])
                   ).hex()


def weight_key(index, uid):
    return al._uid_key("Weights", index, uid)


def reg_key(netuid, uid):
    return al._uid_key("BlockAtRegistration", netuid, uid)


def axon_key(netuid, hotkey, bad_hash=False):
    account = bytes.fromhex(hotkey[2:])
    digest = (b"\x00" * 16 if bad_hash
              else al.hashlib.blake2b(account, digest_size=16).digest())
    return (al.storage_prefix(al.SUBTENSOR_PALLET, "Axons")
            + int(netuid).to_bytes(2, "little").hex() + digest.hex()
            + account.hex())


class AxonChain(FakeChain):
    """FakeChain plus `Axons`, a (netuid, hotkey) double map the table
    helper cannot express."""

    def __init__(self, tables, axons=(), **kwargs):
        super().__init__(tables, **kwargs)
        self.axon_rows = dict(axons)

    def __call__(self, method, params):
        if method == "state_getKeysPaged" and params[0] == al.storage_prefix(
                al.SUBTENSOR_PALLET, "Axons"):
            self.calls.append(method)
            return {"ok": True, "result": sorted(self.axon_rows)}
        if method == "state_queryStorageAt":
            out = super().__call__(method, params)
            if out.get("ok"):
                extra = [[k, v] for k, v in self.axon_rows.items()
                         if k in set(params[0])]
                out["result"][0]["changes"].extend(extra)
            return out
        return super().__call__(method, params)


def context_tables(consensus=None, **extra):
    return snapshot_tables(
        SubnetEpochConsensus=consensus if consensus is not None
        else {1: "0x01"},
        NullPruningTarget={1: u16_hex(200)},
        ValidatorPermit={1: vec_bool_hex([True, False, True, False]),
                         8: vec_bool_hex([False, True])},
        LastUpdate={1: vec_u64_hex([8789000, 0, 8780000, 0]),
                    4097: vec_u64_hex([8789500, 0, 0, 0]),
                    8: vec_u64_hex([0, 8789800])},
        ActivityCutoff={1: u16_hex(5000), 8: u16_hex(5000)},
        **extra)


def context_points():
    points = dict(snapshot_points())
    points.update({
        weight_key(1, 0): pairs_hex([(1, 100), (3, 0)]),
        weight_key(1, 2): pairs_hex([(1, 5), (2, 9)]),
        weight_key(4097, 0): pairs_hex([(3, 10)]),
        weight_key(8, 1): pairs_hex([(0, 1)]),
        reg_key(1, 0): u64_hex(100),
        reg_key(1, 3): u64_hex(8780000),
    })
    return points


HK_A = "0x" + "44" * 32
HK_B = "0x" + "55" * 32


class ContextCodecs(unittest.TestCase):

    def test_epoch_consensus_variants_and_unknown_index(self):
        self.assertEqual(al.decode_by_codec("epoch_consensus", "0x00"),
                         "Yuma")
        self.assertEqual(al.decode_by_codec("epoch_consensus", "0x01"),
                         "Null")
        with self.assertRaises(ValueError):
            al.decode_by_codec("epoch_consensus", "0x02")
        with self.assertRaises(ValueError):
            al.decode_by_codec("epoch_consensus", "0x0000")

    def test_vec_bool_round_trips_and_refuses_bad_input(self):
        self.assertEqual(al.decode_by_codec(
            "vec_bool", vec_bool_hex([True, False])), [True, False])
        with self.assertRaises(ValueError):
            al.decode_by_codec("vec_bool", "0x0801")  # says 2, holds 1
        with self.assertRaises(ValueError):
            al.decode_by_codec("vec_bool", "0x0402")  # byte 2 is no bool

    def test_vec_u64_round_trips_and_refuses_truncation(self):
        payload = vec_u64_hex([1, 2 ** 40])
        self.assertEqual(al.decode_by_codec("vec_u64", payload),
                         [1, 2 ** 40])
        with self.assertRaises(ValueError):
            al.decode_by_codec("vec_u64", payload[:-2])

    def test_weight_pairs_round_trip_and_refuse_truncation(self):
        payload = pairs_hex([(7, 65535), (300, 1)])
        self.assertEqual(al.decode_by_codec("vec_u16_pairs", payload),
                         [(7, 65535), (300, 1)])
        with self.assertRaises(ValueError):
            al.decode_by_codec("vec_u16_pairs", payload[:-2])

    def test_axon_decoder_returns_the_block_only(self):
        self.assertEqual(al.decode_by_codec("axon_block", axon_hex(9_000_123)),
                         9_000_123)
        with self.assertRaises(ValueError):
            al.decode_by_codec("axon_block", "0x" + "00" * 7)

    def test_mechanism_one_last_update_maps_to_netuid_and_mecid(self):
        out = al.read_subnet_maps(CONFIG, items=al.MINING_CONTEXT_MAP_ITEMS,
                                  rpc=FakeChain(context_tables()))
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["values"]["LastUpdate"][(1, 1)],
                         [8789500, 0, 0, 0])
        self.assertNotIn(4097, out["values"]["LastUpdate"])


class MiningContext(StoreCase):

    def snapshot(self, tables=None, points=None, axons=None, **kwargs):
        rpc = AxonChain(tables or context_tables(),
                        axons=axons if axons is not None else {
                            axon_key(1, HK_A): axon_hex(8789000),
                            axon_key(1, HK_B): axon_hex(100)},
                        points=points or context_points(), **kwargs)
        return al.read_mining_snapshot(CONFIG, rpc=rpc,
                                       connection=self.store), rpc

    def test_context_shares_the_snapshot_block(self):
        out, _ = self.snapshot()
        self.assertTrue(out["ok"], out.get("error"))
        context = out["context"]
        self.assertEqual(context["block_number"], out["block_number"])
        self.assertEqual(context["block_hash"], out["block_hash"])
        self.assertEqual(context["unread"], {})
        self.assertEqual(context["maps"]["SubnetEpochConsensus"], {1: "Null"})
        self.assertEqual(context["maps"]["NullPruningTarget"], {1: 200})

    def test_weights_are_read_for_permit_holders_per_mechanism(self):
        out, _ = self.snapshot()
        weights = out["context"]["weights"]
        # SN1 permits uids 0 and 2 and runs 2 mechanisms; SN8 permits uid 1.
        self.assertEqual(sorted(weights), [(1, 0, 0), (1, 0, 2), (1, 1, 0),
                                           (1, 1, 2), (8, 0, 1)])
        self.assertEqual(weights[(1, 0, 0)], [1])  # zero weight dropped
        self.assertEqual(weights[(1, 0, 2)], [1, 2])
        self.assertEqual(weights[(1, 1, 0)], [3])
        self.assertEqual(weights[(1, 1, 2)], [])  # absent row is empty

    def test_registration_blocks_cover_registered_uids_only(self):
        out, _ = self.snapshot()
        reg = out["context"]["registration"]
        self.assertEqual(len(reg[1]), 256)
        self.assertEqual(reg[1][0], 100)
        self.assertEqual(reg[1][3], 8780000)
        self.assertIsNone(reg[1][1])  # unset is unknown, not block 0

    def test_axons_return_serving_blocks_only(self):
        out, _ = self.snapshot()
        self.assertEqual(sorted(out["context"]["axons"][1]), [100, 8789000])
        text = repr(out["context"])
        self.assertNotIn("7f000001", text)
        self.assertNotIn(HK_A[2:], text)

    def test_root_weights_are_never_read(self):
        tables = context_tables()
        tables["ValidatorPermit"][0] = vec_bool_hex([True])
        tables["SubnetworkN"][0] = u16_hex(1)
        rpc = AxonChain(tables, points=context_points())
        requested = []
        original = rpc.__call__

        def spy(method, params):
            if method == "state_queryStorageAt":
                requested.extend(params[0])
            return original(method, params)
        out = al.read_mining_snapshot(CONFIG, rpc=spy)
        self.assertTrue(out["ok"], out.get("error"))
        self.assertNotIn(weight_key(0, 0), requested)
        self.assertNotIn(0, {label[0] for label in out["context"]["weights"]})

    def queries_before_context(self):
        """How many storage queries the snapshot makes before its first
        context read, measured on a clean run rather than assumed."""
        rpc = AxonChain(context_tables(), points=context_points())
        consensus = al.storage_prefix(al.SUBTENSOR_PALLET,
                                      "SubnetEpochConsensus")
        seen = []
        original = rpc.__call__

        def spy(method, params):
            if method == "state_queryStorageAt":
                seen.append(any(k.startswith(consensus) for k in params[0]))
            return original(method, params)
        al.read_mining_snapshot(CONFIG, rpc=spy)
        return seen.index(True)

    def test_failed_context_read_leaves_the_snapshot_ok(self):
        # Every storage query from the first context read on fails.
        out, _ = self.snapshot(fail_method="state_queryStorageAt",
                               fail_after=self.queries_before_context())
        self.assertTrue(out["ok"], out.get("error"))
        self.assertIn("SubnetEpochConsensus", out["context"]["unread"])
        self.assertIn("Weights", out["context"]["unread"])
        self.assertIn("BlockAtRegistration", out["context"]["unread"])
        self.assertIn("Axons", out["context"]["unread"])
        self.assertTrue(out["owners"])

    def test_short_context_batch_is_unread_not_default(self):
        # A short batch fails the item (change: live-data-correctness); the
        # context must say so, or every subnet would read as Yuma.
        out, _ = self.snapshot(drop_query_item="SubnetEpochConsensus")
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["context"]["unread"]["SubnetEpochConsensus"],
                         "short batch")
        self.assertEqual(out["context"]["maps"]["SubnetEpochConsensus"], {})

    def test_unknown_consensus_index_fails_that_subnet_only(self):
        out, _ = self.snapshot(tables=context_tables(
            consensus={1: "0x02", 8: "0x00"}))
        self.assertTrue(out["ok"])
        context = out["context"]
        self.assertIn(1, context["failures"]["SubnetEpochConsensus"])
        self.assertEqual(context["maps"]["SubnetEpochConsensus"], {8: "Yuma"})

    def test_bad_axon_key_layout_marks_axons_unread(self):
        out, _ = self.snapshot(axons={axon_key(1, HK_A, bad_hash=True):
                                      axon_hex(5)})
        self.assertTrue(out["ok"])
        self.assertIn("Axons", out["context"]["unread"])
        self.assertEqual(out["context"]["axons"], {})

    def test_registered_count_above_the_cap_is_refused_for_that_subnet(self):
        tables = context_tables()
        tables["SubnetworkN"][8] = u16_hex(al.CONTEXT_UID_CAP + 1)
        out, _ = self.snapshot(tables=tables)
        self.assertNotIn(8, out["context"]["registration"])
        self.assertIn(8, out["context"]["failures"]["BlockAtRegistration"])
        self.assertIn(1, out["context"]["registration"])
