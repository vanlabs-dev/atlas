"""Netuid-keyed subnet map reads (change: mining-triage): twox128 derivation
self-tested against the pinned live-verified gate keys, SCALE codecs with
their declared scales, Identity key layout, batched single-block reads, and
the empty-versus-wrong-prefix distinction.

Two of these are regressions for errors made during on-device verification on
2026-08-07. Both returned plausible wrong answers rather than failing, which
is the dangerous kind: a U96F32 read at 2^64 gave 0.0 for every subnet, and a
twox64-concat key layout gave an empty map for every netuid."""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402

# Pinned against live Finney 2026-07-28, already in livedata/config.json.
PINNED = {
    "EmissionGateBar":
        "0x658faa385070e074c85bf6b568cf05557c9b0d2964cc73e7519676c3cc4d5df9",
    "EmissionBarQuantile":
        "0x658faa385070e074c85bf6b568cf0555a772007dde2ed63e0f21b5f9d7f16650",
    "EmissionGateExponent":
        "0x658faa385070e074c85bf6b568cf055588c70e8dd0cf4af3aeb977ba2eee1df4",
    "EmissionBarRank":
        "0x658faa385070e074c85bf6b568cf0555d33bd686290d014475513443305882be",
}

CONFIG = {"gate_signal": {"storage_keys": PINNED}}


def u16_hex(value):
    return "0x" + int(value).to_bytes(2, "little").hex()


def u96f32_hex(value):
    return "0x" + int(round(value * 2 ** 32)).to_bytes(16, "little").hex()


def _vec_u8(text):
    raw = text.encode("utf-8")
    count = len(raw)
    prefix = (bytes([count << 2]) if count < 64
              else ((count << 2) | 0b01).to_bytes(2, "little"))
    return prefix + raw


def identity_hex(*fields):
    """A SubnetIdentityV3 payload: consecutive Vec<u8> fields, of which only
    the first (subnet_name) is ever decoded."""
    return "0x" + b"".join(_vec_u8(f) for f in fields).hex()


def vec_u16_hex(values):
    count = len(values)
    if count < 64:
        prefix = bytes([count << 2])
    elif count < 2 ** 14:
        prefix = ((count << 2) | 0b01).to_bytes(2, "little")
    else:
        prefix = ((count << 2) | 0b10).to_bytes(4, "little")
    body = b"".join(int(v).to_bytes(2, "little") for v in values)
    return "0x" + (prefix + body).hex()


class KeyDerivation(unittest.TestCase):

    def test_reproduces_every_pinned_gate_key(self):
        """The self-test that makes derived keys trustworthy for free."""
        for item, expected in PINNED.items():
            self.assertEqual(al.storage_prefix(al.SUBTENSOR_PALLET, item),
                             expected, item)

    def test_verify_passes_against_real_config(self):
        checked = al.verify_key_derivation(CONFIG)
        self.assertEqual(set(checked), set(PINNED))

    def test_mismatch_raises_and_blocks_derived_reads(self):
        bad = {"gate_signal": {"storage_keys": {"EmissionGateBar": "0xdead"}}}
        with self.assertRaises(al.FatalLiveError):
            al.verify_key_derivation(bad)

    def test_no_pinned_keys_is_a_fault_not_a_pass(self):
        with self.assertRaises(al.FatalLiveError):
            al.verify_key_derivation({"gate_signal": {"storage_keys": {}}})

    def test_map_key_uses_identity_two_byte_tail(self):
        """REGRESSION 2026-08-07: a twox64-concat tail returned null for every
        netuid and was indistinguishable from an empty map."""
        prefix = al.storage_prefix(al.SUBTENSOR_PALLET, "MinerBurned")
        key = al.storage_key_identity_u16(al.SUBTENSOR_PALLET,
                                          "MinerBurned", 19)
        tail = bytes.fromhex(key[2:])[len(bytes.fromhex(prefix[2:])):]
        self.assertEqual(len(tail), 2)
        self.assertEqual(int.from_bytes(tail, "little"), 19)


class Codecs(unittest.TestCase):

    def test_u96f32_uses_two_to_the_32(self):
        self.assertAlmostEqual(al.decode_u96f32(u96f32_hex(0.3456)),
                               0.3456, places=9)
        self.assertAlmostEqual(al.decode_u96f32(u96f32_hex(1.0)), 1.0)

    def test_u96f32_read_at_the_wrong_scale_is_not_silently_returned(self):
        """REGRESSION 2026-08-07: decoding MinerBurned at 2^64 returned 0.0
        for every subnet, which read as a clean result."""
        payload = u96f32_hex(0.3456)
        self.assertAlmostEqual(al.decode_u96f32(payload), 0.3456, places=9)
        # The 2^64 reading of the same bytes is the bug being guarded.
        self.assertLess(al.decode_u64f64(payload), 1e-9)
        self.assertNotAlmostEqual(al.decode_u64f64(payload), 0.3456, places=6)

    def test_u96f32_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            al.decode_u96f32("0x0102")

    def test_compact_single_byte_form(self):
        self.assertEqual(al._decode_compact(bytes([4 << 2]), 0), (4, 1))

    def test_compact_two_byte_form_carries_256(self):
        payload = bytes.fromhex(vec_u16_hex([0] * 256)[2:])
        self.assertEqual(al._decode_compact(payload, 0), (256, 2))

    def test_compact_four_byte_form(self):
        raw = ((70000 << 2) | 0b10).to_bytes(4, "little")
        self.assertEqual(al._decode_compact(raw, 0), (70000, 4))

    def test_compact_rejects_truncated_payload(self):
        with self.assertRaises(ValueError):
            al._decode_compact(bytes([0b01]), 0)

    def test_vec_u16_round_trips_a_full_metagraph(self):
        values = [i % 65535 for i in range(256)]
        self.assertEqual(al.decode_vec_u16(vec_u16_hex(values)), values)

    def test_vec_u16_small_form(self):
        self.assertEqual(al.decode_vec_u16(vec_u16_hex([7, 0, 9])), [7, 0, 9])

    def test_vec_u16_rejects_length_mismatch(self):
        good = vec_u16_hex([1, 2, 3])
        with self.assertRaises(ValueError):
            al.decode_vec_u16(good[:-4])

    def test_identity_name_reads_the_leading_field_only(self):
        # subnet_name followed by a second Vec<u8> field (github_repo), which
        # must be ignored rather than concatenated.
        payload = identity_hex("Apex", "https://github.com/x/y")
        self.assertEqual(al.decode_identity_name(payload), "Apex")

    def test_identity_name_survives_a_struct_that_grows(self):
        payload = identity_hex("Apex", "a", "b", "c", "d")
        self.assertEqual(al.decode_identity_name(payload), "Apex")

    def test_identity_name_empty_is_empty_not_an_error(self):
        self.assertEqual(al.decode_identity_name(identity_hex("")), "")

    def test_identity_name_keeps_non_ascii(self):
        for name in ("hoτfloaτ", "404—GEN"):
            self.assertEqual(al.decode_identity_name(identity_hex(name)), name)

    def test_identity_name_rejects_a_truncated_payload(self):
        good = identity_hex("Apex")
        with self.assertRaises(ValueError):
            al.decode_identity_name(good[:-4])

    def test_identity_name_does_not_raise_on_bad_utf8(self):
        """One subnet's malformed bytes must not blind the whole map read."""
        raw = bytes([2 << 2]) + bytes([0xFF, 0xFE])
        self.assertIsInstance(al.decode_identity_name("0x" + raw.hex()), str)

    def test_codec_registry_carries_the_new_codecs(self):
        self.assertAlmostEqual(
            al.decode_by_codec("u96f32", u96f32_hex(0.5)), 0.5, places=9)
        self.assertEqual(al.decode_by_codec("vec_u16", vec_u16_hex([1])), [1])
        self.assertEqual(
            al.decode_by_codec("identity_name", identity_hex("Apex")), "Apex")

    def test_identity_map_is_read_at_the_same_block_as_the_rest(self):
        self.assertEqual(al.SUBNET_MAP_ITEMS["SubnetIdentitiesV3"],
                         "identity_name")


class FakeChain:
    """Stub RPC serving derived keys, so the tests exercise the real
    derivation rather than a hand-written key table."""

    def __init__(self, tables, block="0xabc", number=8789861,
                 fail_method=None):
        self.tables = tables
        self.block = block
        self.number = number
        self.fail_method = fail_method
        self.calls = []

    def __call__(self, method, params):
        self.calls.append(method)
        if method == self.fail_method:
            return {"ok": False, "error": "stubbed %s failure" % method}
        if method == "chain_getFinalizedHead":
            return {"ok": True, "result": self.block}
        if method == "chain_getHeader":
            return {"ok": True, "result": {"number": hex(self.number)}}
        if method == "state_getKeysPaged":
            prefix = params[0]
            keys = []
            for item, rows in self.tables.items():
                item_prefix = al.storage_prefix(al.SUBTENSOR_PALLET, item)
                if item_prefix != prefix:
                    continue
                for netuid in sorted(rows):
                    keys.append(al.storage_key_identity_u16(
                        al.SUBTENSOR_PALLET, item, netuid))
            return {"ok": True, "result": keys}
        if method == "state_queryStorageAt":
            wanted = set(params[0])
            changes = []
            for item, rows in self.tables.items():
                for netuid, payload in rows.items():
                    key = al.storage_key_identity_u16(
                        al.SUBTENSOR_PALLET, item, netuid)
                    if key in wanted:
                        changes.append([key, payload])
            return {"ok": True,
                    "result": [{"block": self.block, "changes": changes}]}
        return {"ok": False, "error": "unexpected method %s" % method}


def tables(burn=None, network_n=None, incentive=None, collateral=None,
           identity=None):
    return {
        "MinerBurned": burn if burn is not None else {
            1: u96f32_hex(0.3456), 8: u96f32_hex(0.0)},
        "SubnetworkN": network_n if network_n is not None else {
            1: u16_hex(256), 8: u16_hex(256)},
        "Incentive": incentive if incentive is not None else {
            1: vec_u16_hex([100, 0, 50, 0]), 8: vec_u16_hex([1, 2])},
        "CollateralLockShare": collateral if collateral is not None else {},
        "SubnetIdentitiesV3": identity if identity is not None else {
            1: identity_hex("Apex", "https://github.com/macrocosm-os/apex"),
            8: identity_hex("deprecated", "")},
    }


class ReadSubnetMaps(unittest.TestCase):

    def test_single_block_read_decodes_every_item(self):
        rpc = FakeChain(tables())
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertTrue(out["ok"])
        self.assertEqual(out["block_hash"], "0xabc")
        self.assertEqual(out["block_number"], 8789861)
        self.assertAlmostEqual(out["values"]["MinerBurned"][1], 0.3456,
                               places=6)
        self.assertEqual(out["values"]["SubnetworkN"][1], 256)
        self.assertEqual(out["values"]["Incentive"][1], [100, 0, 50, 0])
        self.assertEqual(out["values"]["SubnetIdentitiesV3"][1], "Apex")
        self.assertEqual(out["values"]["SubnetIdentitiesV3"][8], "deprecated")

    def test_every_value_shares_one_block(self):
        rpc = FakeChain(tables())
        al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertEqual(rpc.calls.count("chain_getFinalizedHead"), 1)
        self.assertNotIn("state_getStorage", rpc.calls)

    def test_batched_not_one_call_per_key(self):
        rpc = FakeChain(tables())
        al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertLessEqual(rpc.calls.count("state_queryStorageAt"), 2)

    def test_dormant_map_is_reported_empty_not_failed(self):
        rpc = FakeChain(tables())
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertTrue(out["ok"])
        self.assertIn("CollateralLockShare", out["empty_items"])
        self.assertEqual(out["values"]["CollateralLockShare"], {})

    def test_empty_control_map_invalidates_the_whole_read(self):
        """An empty control is the signature of a wrong prefix, not of an
        empty chain, so it must not be reported as data."""
        rpc = FakeChain(tables(burn={}))
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertFalse(out["ok"])
        self.assertIn("control map", out["error"])

    def test_unexpected_key_layout_fails_closed(self):
        rpc = FakeChain(tables())
        real = rpc.__call__

        def bad(method, params):
            out = real(method, params)
            if method == "state_getKeysPaged" and out.get("result"):
                out["result"] = [k + "00" * 8 for k in out["result"]]
            return out

        out = al.read_subnet_maps(CONFIG, rpc=bad)
        self.assertFalse(out["ok"])
        self.assertIn("key layout", out["error"])

    def test_one_bad_payload_does_not_lose_the_others(self):
        broken = {1: u96f32_hex(0.5), 8: "0xdeadbeef", 19: u96f32_hex(0.1)}
        rpc = FakeChain(tables(burn=broken))
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertTrue(out["ok"])
        self.assertIn(1, out["values"]["MinerBurned"])
        self.assertIn(19, out["values"]["MinerBurned"])
        self.assertNotIn(8, out["values"]["MinerBurned"])
        self.assertIn(8, out["failures"]["MinerBurned"])

    def test_head_failure_fails_closed(self):
        rpc = FakeChain(tables(), fail_method="chain_getFinalizedHead")
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertFalse(out["ok"])

    def test_batched_read_failure_fails_closed(self):
        rpc = FakeChain(tables(), fail_method="state_queryStorageAt")
        out = al.read_subnet_maps(CONFIG, rpc=rpc)
        self.assertFalse(out["ok"])

    def test_derivation_fault_blocks_before_any_network_call(self):
        rpc = FakeChain(tables())
        bad = {"gate_signal": {"storage_keys": {"EmissionGateBar": "0xno"}}}
        with self.assertRaises(al.FatalLiveError):
            al.read_subnet_maps(bad, rpc=rpc)
        self.assertEqual(rpc.calls, [])


if __name__ == "__main__":
    unittest.main()
