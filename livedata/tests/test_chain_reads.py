"""CHAIN_READS coverage and the metadata probe (change:
runtime-upgrade-pipeline). The decoder runs against a recorded live
metadata fixture: Finney spec 486, finalized block 9423151 (refreshed by
change mining-economics-model; was spec 469, block 9133662)."""

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
FIXTURE = os.path.join(_HERE, "fixtures", "metadata-486-9423151.scale.gz")
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
        # Spec 469 retired these (change: root-weight-drift). `Weights` is
        # declared again for subnet weight rows (change:
        # mining-economics-model); the root row is never read, which
        # test_mining_snapshot.MiningContext checks.
        for item in ("RootWeightSettingEnabled", "RootWeightsCap",
                     "Keys", "TotalHotkeyAlpha"):
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

    def test_registration_keys_are_the_plain_derivation(self):
        # change: registration-knob-watch.
        items = {spec["item"]: spec
                 for spec in al.load_config()["chain_params"]["items"]}
        for name in ("NetworkImmunityPeriod", "NetworkLockReductionInterval",
                     "NetworkRateLimit"):
            expected = "0x" + (al.twox128("SubtensorModule")
                               + al.twox128(name)).hex()
            self.assertEqual(items[name]["key"], expected, name)
            self.assertEqual(items[name]["codec"], "u64")
            self.assertIn(al.ChainRead(al.SUBTENSOR_PALLET, name, (), "u64"),
                          al.CHAIN_READS)
            self.assertEqual(al.KNOB_ITEMS[name], "u64")

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
        # read matches the recorded spec 486 metadata.
        result = self.check(al.CHAIN_READS)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["ok"])

    def test_changed_default_fails_naming_both_values(self):
        # SubnetOwnerCut's runtime default is 11796 (0x2e14). A table that
        # expects 11797 stands in for a runtime that moved the default.
        key = ("SubtensorModule", "SubnetOwnerCut")
        result = ap.probe({}, reads=[read(key[0], key[1], [], "u16")],
                          rpc=fake_rpc(self.raw),
                          defaults={key: (11797).to_bytes(2, "little").hex()})
        self.assertFalse(result["ok"])
        reason = result["failures"][0]["reason"]
        self.assertEqual(reason, "default 11796, expected 11797")
        self.assertEqual(ap._plain_reason(reason),
                         "default changed (chain 11796, Atlas assumes 11797)")

    def test_fixed_point_default_shown_as_a_fraction(self):
        key = ("SubtensorModule", "EmissionBarQuantile")
        result = ap.probe({}, reads=[read(key[0], key[1], [],
                                          "FixedU128<U64>")],
                          rpc=fake_rpc(self.raw), defaults={key: "00" * 16})
        self.assertEqual(result["failures"][0]["reason"],
                         "default 0.610000, expected 0.000000")

    def test_declared_defaults_match_the_fixture(self):
        result = ap.probe({}, reads=[r for r in al.CHAIN_READS if (
            r.pallet, r.item) in al.EXPECTED_DEFAULTS],
            rpc=fake_rpc(self.raw))
        self.assertTrue(result["ok"], result["failures"])

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

    def test_drift_page_reads_in_plain_words(self):
        result = {"ok": False, "spec": 472, "block": 9201345, "failures": [
            {"pallet": "SubtensorModule", "item": "EmissionBarRank",
             "reason": "missing from metadata"},
            {"pallet": "Swap", "item": "AlphaSqrtPrice",
             "reason": "value type U64F64, declared I96F32"}]}
        text = ap.drift_message(result).plain()
        lines = text.split("\n")
        self.assertEqual(lines[0], "🔴 2 Atlas chain readers no longer "
                                   "match the live chain")
        self.assertIn("• EmissionBarRank: removed from the chain metadata",
                      text)
        self.assertIn("• AlphaSqrtPrice: type changed (chain U64F64, Atlas "
                      "expects I96F32)", text)
        self.assertIn("SubtensorModule.EmissionBarRank", text)
        self.assertTrue(lines[-1].startswith("Next: "))
        cleared = ap.cleared_message({"spec": 472, "block": 9201401})
        self.assertTrue(cleared.plain().startswith("✅ Atlas chain readers"))

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
        # Subnet 2 has no entry: the runtime default is on, so it is not
        # listed off (upgrade-sandbox-scope).
        self.assertEqual(result["SubnetEmissionEnabled"]["off"], [])


class WatchExitTest(unittest.TestCase):
    def test_drift_is_paged_not_a_unit_failure(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            config = {"output_dir": tmp}
            failing = {"ok": False, "spec": 1, "block": 1, "failures": [
                {"pallet": "P", "item": "I", "reason": "missing"}]}
            with mock.patch.object(ap, "probe", return_value=failing), \
                    mock.patch.object(ap, "telegram_send",
                                      return_value=True), \
                    mock.patch.object(ap.al, "resolve", side_effect=str):
                self.assertEqual(ap.cmd_watch(config), 0)



def encode_default(codec, value):
    """SCALE bytes of a configured default, by its declared codec.
    Fixed point uses the runtime's own conversion, never a float compare."""
    if codec == "bool":
        return bytes([1 if value else 0])
    if codec == "u16":
        return int(value).to_bytes(2, "little")
    if codec == "u64":
        return int(value).to_bytes(8, "little")
    if codec == "u64f64":
        return round(value * 2 ** 64).to_bytes(16, "little")
    raise AssertionError("no encoder for codec %r" % codec)


class ExpectedDefaultsTest(unittest.TestCase):
    """Every default Atlas substitutes for an unset chain read equals the
    declared EXPECTED_DEFAULTS table (change: upgrade-sandbox-scope)."""

    def setUp(self):
        with open(os.path.join(os.path.dirname(_HERE), "config.json"),
                  "r", encoding="utf-8") as handle:
            self.config = json.load(handle)

    def assert_matches(self, item, codec, value):
        self.assertIn((al.SUBTENSOR_PALLET, item), al.EXPECTED_DEFAULTS,
                      "%s has a default but no EXPECTED_DEFAULTS entry"
                      % item)
        self.assertEqual(encode_default(codec, value).hex(),
                         al.expected_default(item).hex(), item)

    def test_table_only_names_declared_reads(self):
        for key in al.EXPECTED_DEFAULTS:
            self.assertIn(key, al._DECLARED_READS, key)

    def test_gate_assumed_defaults(self):
        codecs = {"EmissionBarRank": "u16"}
        for item, value in self.config["gate_signal"][
                "assumed_defaults"].items():
            self.assert_matches(item, codecs.get(item, "u64f64"), value)

    def test_chain_param_watch_defaults(self):
        for entry in self.config["chain_params"]["items"]:
            if "default" in entry:
                self.assert_matches(entry["item"], entry["codec"],
                                    entry["default"])

    def test_subnet_param_defaults(self):
        for item, value in al.SUBNET_PARAM_DEFAULTS.items():
            self.assert_matches(item, al.SUBNET_MAP_ITEMS[item], value)

    def test_code_constants(self):
        self.assert_matches("SubnetOwnerCut", "u16",
                            al.SUBNET_OWNER_CUT_DEFAULT)
        self.assertEqual(al.SUBNET_OWNER_CUT_DEFAULT, 11796)
        self.assertEqual(bytes.fromhex(al.ZERO_ACCOUNT[2:]),
                         al.expected_default("SubnetOwner"))

    def test_a_drifted_config_default_fails(self):
        with self.assertRaises(AssertionError):
            self.assert_matches("EmissionBarRank", "u16", 64)

    def test_emission_switch_default_is_on(self):
        # Atlas assumed false until 2026-11-03; live metadata at spec 486
        # (the test fixture) says true.
        self.assertEqual(al.SUBNET_PARAM_DEFAULTS["SubnetEmissionEnabled"],
                         True)
        meta = sm.decode_metadata(fixture_bytes())
        entry = meta["pallets"]["SubtensorModule"]["storage"][
            "SubnetEmissionEnabled"]
        self.assertEqual(entry["default"], b"\x01")
        self.assertEqual(entry["modifier"], "default")


if __name__ == "__main__":
    unittest.main()
