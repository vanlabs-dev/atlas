"""CHAIN_READS coverage and the metadata probe (change:
runtime-upgrade-pipeline). The decoder runs against a recorded live
metadata fixture: Finney spec 469, finalized block 9133662."""

import ast
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402
import atlas_probe as ap  # noqa: E402
import scale_meta as sm  # noqa: E402

PINNED = {item: al.storage_prefix(al.SUBTENSOR_PALLET, item)
          for item in al._GATE_ITEMS}
FIXTURE = os.path.join(_HERE, "fixtures", "metadata-469-9133662.scale.gz")
KEY_BUILDERS = {"storage_prefix", "storage_key_identity_u16",
                "storage_key_blake2_concat_u16", "storage_key"}


def fixture_bytes():
    with open(FIXTURE, "rb") as handle:
        return gzip.decompress(handle.read())


def read_sites():
    """Item names at every key-builder call in atlas_live.py, resolving a
    module constant to its value. A call with an item that is
    not a literal or a module constant is returned as '<dynamic>' so the
    test can check the table it came from."""
    with open(al.__file__, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            constants[node.targets[0].id] = node.value.value
    items = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in KEY_BUILDERS and len(node.args) >= 2):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Constant):
            items.add(arg.value)
        elif isinstance(arg, ast.Name) and arg.id in constants:
            items.add(constants[arg.id])
        else:
            items.add("<dynamic>")
    return items


class ChainReadCoverageTest(unittest.TestCase):
    def setUp(self):
        self.declared = {read.item for read in al.CHAIN_READS}

    def test_every_literal_read_site_is_declared(self):
        # Every read is table-driven since spec 469 (change:
        # root-weight-drift), so the scan may find only dynamic sites.
        sites = read_sites()
        self.assertTrue(sites, "found no read sites; the scan is broken")
        self.assertEqual(sorted(sites - {"<dynamic>"} - self.declared), [])

    def test_retired_root_items_are_not_declared(self):
        # Spec 469 retired these (change: root-weight-drift).
        for item in ("RootWeightSettingEnabled", "RootWeightsCap",
                     "Weights", "Keys", "TotalHotkeyAlpha"):
            self.assertNotIn(item, self.declared)

    def test_basket_cap_pinned_key_is_the_plain_derivation(self):
        items = {spec["item"]: spec
                 for spec in al.load_config()["chain_params"]["items"]}
        expected = "0x" + (al.twox128("SubtensorModule")
                           + al.twox128("BasketConcentrationCap")).hex()
        self.assertEqual(items["BasketConcentrationCap"]["key"], expected)
        self.assertIn(al.ChainRead(al.SUBTENSOR_PALLET,
                                   "BasketConcentrationCap", (), "u16"),
                      al.CHAIN_READS)

    def test_every_table_driven_read_is_declared(self):
        # Dynamic call sites take their items from these tables.
        config = al.load_config()
        tables = (set(al.SUBNET_MAP_ITEMS) | set(al._SWITCH_WATCH_ITEMS)
                  | set(al._GATE_ITEMS) | set(al.SUBNET_PARAM_DEFAULTS)
                  | set(config["gate_signal"]["storage_keys"])
                  | {spec["item"] for spec in config["chain_params"]["items"]}
                  | set(al.KNOB_ITEMS))
        self.assertEqual(sorted(tables - self.declared), [])

    def test_pinned_keys_derive_from_declared_items(self):
        config = al.load_config()
        for spec in config["chain_params"]["items"]:
            if spec.get("key"):
                self.assertTrue(spec["key"].startswith(al.storage_prefix(
                    al.SUBTENSOR_PALLET, spec["item"])), spec["item"])

    def test_undeclared_read_fails(self):
        with self.assertRaises(al.FatalLiveError) as caught:
            al.storage_prefix(al.SUBTENSOR_PALLET, "NotARealItem")
        self.assertIn("NotARealItem", str(caught.exception))


class ScaleMetaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = sm.decode_metadata(fixture_bytes())
        cls.storage = cls.meta["pallets"]["SubtensorModule"]["storage"]

    def name(self, item):
        return sm.type_name(self.meta["types"], self.storage[item]["value"])

    def test_version_and_pallets(self):
        self.assertEqual(self.meta["version"], 14)
        self.assertIn("System", self.meta["pallets"])
        self.assertIn("SubtensorModule", self.meta["pallets"])

    def test_fixed_point_scales_differ(self):
        self.assertEqual(self.name("EmissionGateBar"), "FixedU128<U64>")
        self.assertEqual(self.name("MinerBurned"), "FixedU128<U32>")

    def test_structural_names(self):
        self.assertEqual(self.name("Weights"), "Vec<(u16, u16)>")
        self.assertEqual(self.name("Incentive"), "Vec<PerU16>")
        self.assertEqual(self.name("SubnetworkN"), "u16")

    def test_hashers(self):
        self.assertEqual(self.storage["TotalHotkeyAlpha"]["hashers"],
                         ["blake2_128concat", "identity"])
        self.assertEqual(self.storage["EmissionBarRank"]["hashers"], [])

    def test_truncated_and_bad_input_raise(self):
        raw = fixture_bytes()
        with self.assertRaises(ValueError):
            sm.decode_metadata(raw[:len(raw) // 2])
        with self.assertRaises(ValueError):
            sm.decode_metadata(b"nope" + raw[4:])
        with self.assertRaises(ValueError):
            sm.decode_metadata(raw[:4] + bytes([13]) + raw[5:])


def fake_rpc(raw, spec=469, fail=False):
    def rpc(method, params):
        if fail:
            return {"ok": False, "error": "down"}
        if method == "chain_getFinalizedHead":
            return {"ok": True, "result": "0xabc"}
        if method == "chain_getHeader":
            return {"ok": True, "result": {"number": hex(9133662)}}
        if method == "state_getRuntimeVersion":
            return {"ok": True, "result": {"specVersion": spec}}
        if method == "state_getMetadata":
            return {"ok": True, "result": "0x" + raw.hex()}
        raise AssertionError(method)
    return rpc


def read(pallet, item, hashers, value_type):
    return al.ChainRead(pallet, item, tuple(hashers), value_type)


class ProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fixture_bytes()

    def check(self, reads, rpc=None):
        return ap.probe({}, reads=reads, rpc=rpc or fake_rpc(self.raw))

    def test_matching_reads_pass(self):
        result = self.check([
            read("SubtensorModule", "EmissionGateBar", [], "FixedU128<U64>"),
            read("SubtensorModule", "TotalHotkeyAlpha",
                 ["blake2_128concat", "identity"], "AlphaBalance")])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["spec"], 469)
        self.assertEqual(result["block"], 9133662)

    def test_renamed_item_fails(self):
        result = self.check([read("SubtensorModule", "EmissionGateBarOld",
                                  [], "FixedU128<U64>")])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["item"], "EmissionGateBarOld")
        self.assertIn("missing", result["failures"][0]["reason"])

    def test_hasher_change_fails(self):
        result = self.check([read("SubtensorModule", "SubnetworkN",
                                  ["twox64concat"], "u16")])
        self.assertFalse(result["ok"])
        self.assertIn("hashers", result["failures"][0]["reason"])

    def test_value_type_change_fails(self):
        result = self.check([read("SubtensorModule", "MinerBurned",
                                  ["identity"], "FixedU128<U64>")])
        self.assertFalse(result["ok"])
        self.assertIn("FixedU128<U32>", result["failures"][0]["reason"])

    def test_missing_pallet_fails_before_items(self):
        result = self.check([read("GonePallet", "Anything", [], "u16")])
        self.assertFalse(result["ok"])
        self.assertIn("pallet", result["failures"][0]["reason"])

    def test_metadata_unavailable_fails_closed(self):
        result = self.check([], rpc=fake_rpc(self.raw, fail=True))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_undecodable_metadata_fails_closed(self):
        result = self.check([], rpc=fake_rpc(self.raw[:1000]))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_live_fixture_passes_every_declared_read(self):
        # The first drift the probe found (2026-09-24) was the two root
        # weight items spec 469 retired. With them gone, every declared
        # read matches the recorded spec 469 metadata.
        result = self.check(al.CHAIN_READS)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["ok"])

    def test_check_exit_code(self):
        with redirect_stdout(io.StringIO()) as out:
            code = ap.cmd_check({}, rpc=fake_rpc(self.raw),
                                reads=al.CHAIN_READS[:1])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = {}

    def run_watch(self, result):
        return ap.watch_decide(result, self.state,
                               lambda text: self.sent.append(text) or True)

    def failing(self, *items):
        return {"ok": False, "spec": 469, "block": 1,
                "failures": [{"pallet": "P", "item": i, "reason": "missing"}
                             for i in items]}

    def test_pages_once_per_failing_set(self):
        self.run_watch(self.failing("A"))
        self.run_watch(self.failing("A"))
        self.assertEqual(len(self.sent), 1)
        self.run_watch(self.failing("A", "B"))
        self.assertEqual(len(self.sent), 2)

    def test_clear_resets_and_repages(self):
        self.run_watch(self.failing("A"))
        self.run_watch({"ok": True, "spec": 469, "block": 2, "failures": []})
        self.run_watch(self.failing("A"))
        self.assertEqual(len(self.sent), 3)

    def test_fetch_error_pages_once(self):
        error = {"ok": False, "error": "no metadata", "failures": []}
        self.run_watch(error)
        self.run_watch(error)
        self.assertEqual(len(self.sent), 1)

    def test_failed_send_retries_next_run(self):
        ap.watch_decide(self.failing("A"), self.state, lambda text: False)
        self.run_watch(self.failing("A"))
        self.assertEqual(len(self.sent), 1)


class LiveSpecTest(unittest.TestCase):
    def test_reads_spec_at_finalized_head(self):
        result = al.read_live_spec({}, fake_rpc(b"", spec=470))
        self.assertEqual((result["spec_version"], result["block_number"],
                          result["source"]), (470, 9133662, "rpc"))

    def test_invalid_spec_fails(self):
        for bad in (None, "470", True, 0):
            def rpc(method, params, bad=bad):
                if method == "state_getRuntimeVersion":
                    return {"ok": True, "result": {"specVersion": bad}}
                return fake_rpc(b"")(method, params)
            self.assertFalse(al.read_live_spec({}, rpc)["ok"], bad)

    def test_upgrade_records_rpc_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = al.open_store(os.path.join(tmp, "live.db"))
            for spec in (469, 470):
                al.record_spec_observation(connection, al.read_live_spec(
                    {}, fake_rpc(b"", spec=spec)))
            row = connection.execute(
                "SELECT prev_spec, new_spec, source FROM spec_upgrades"
            ).fetchall()
            connection.close()
        self.assertEqual(row, [(469, 470, "rpc")])


class ReadKnobsTest(unittest.TestCase):
    def test_one_block_and_unset_is_not_a_default(self):
        seen = set()
        on = al.storage_key_identity_u16(al.SUBTENSOR_PALLET,
                                         "SubnetEmissionEnabled", 1)

        def rpc(method, params):
            if method in ("state_getStorage", "state_getKeysPaged",
                          "state_queryStorageAt"):
                seen.add(params[-1])
            if method == "state_getStorage":
                rank = al.storage_prefix(al.SUBTENSOR_PALLET,
                                         "EmissionBarRank")
                return {"ok": True,
                        "result": "0x2000" if params[0] == rank else None}
            if method == "state_getKeysPaged":
                prefix = params[0]
                if prefix == al.storage_prefix(al.SUBTENSOR_PALLET,
                                               "SubnetworkN"):
                    return {"ok": True, "result": [
                        prefix + n.to_bytes(2, "little").hex()
                        for n in (0, 1, 2)] if params[2] == prefix else []}
                return {"ok": True,
                        "result": [on] if params[2] == prefix else []}
            if method == "state_queryStorageAt":
                return {"ok": True, "result": [{"changes": [
                    [key, "0x01" if key == on else "0x0100"]
                    for key in params[0]]}]}
            return fake_rpc(b"")(method, params)

        result = al.read_knobs({"gate_signal": {"storage_keys": PINNED}},
                               rpc)
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen, {"0xabc"})
        self.assertEqual(result["knobs"]["EmissionBarRank"]["value"], 32)
        self.assertEqual(result["knobs"]["BasketTradingEnabled"],
                         {"value": None, "raw": None, "state": "unset"})
        self.assertEqual(result["SubnetEmissionEnabled"]["off"], [2])


if __name__ == "__main__":
    unittest.main()
