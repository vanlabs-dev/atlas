"""Chain-first subnet hyperparameters (change: livedata-metagraphed-gaps):
declarations, key derivation, codecs, and the chain/TaoSwap merge."""

import copy
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_live as al  # noqa: E402
from _fixtures import FixtureProvider, make_config  # noqa: E402

FIXTURE = os.path.join(_HERE, "fixtures", "hyperparams-chain-1.json")
CODEC_TYPES = {"u16": {"u16"}, "u64": {"u64", "TaoBalance"},
               "bool": {"bool"}, "i16": {"i16"}}


def recorded():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        return json.load(handle)


class DeclarationTests(unittest.TestCase):
    def test_every_item_is_declared_with_a_matching_type(self):
        for item, codec, _ in al.HYPERPARAMS:
            read = al._READ_BY_ITEM.get((al.SUBTENSOR_PALLET, item))
            self.assertIsNotNone(read, item)
            self.assertEqual(len(read.hashers), 1, item)
            self.assertIn(read.value_type, CODEC_TYPES[codec], item)

    def test_items_are_unique(self):
        items = [item for item, _, _ in al.HYPERPARAMS]
        self.assertEqual(len(items), len(set(items)))

    def test_prefix_self_test_passes(self):
        checked = al.verify_key_derivation(al.load_config())
        self.assertTrue(checked)

    def test_every_key_derives_with_its_hasher(self):
        keys = al.hyperparam_keys(1)
        raw = (1).to_bytes(2, "little")
        for item, _, _ in al.HYPERPARAMS:
            prefix = al.storage_prefix(al.SUBTENSOR_PALLET, item)
            tail = keys[item][len(prefix):]
            hasher = al._READ_BY_ITEM[(al.SUBTENSOR_PALLET, item)].hashers[0]
            expected = {
                "identity": raw.hex(),
                "blake2_128concat": al.hashlib.blake2b(
                    raw, digest_size=16).digest().hex() + raw.hex(),
                "twox64concat": al.xxh64(raw, 0).to_bytes(
                    8, "little").hex() + raw.hex(),
            }[hasher]
            self.assertTrue(keys[item].startswith(prefix), item)
            self.assertEqual(tail, expected, item)

    def test_recorded_keys_match_derivation(self):
        payloads = recorded()["payloads"]
        self.assertEqual(set(payloads), set(al.hyperparam_keys(1)))


class CodecTests(unittest.TestCase):
    def test_recorded_payload_for_each_codec(self):
        payloads = recorded()["payloads"]
        self.assertEqual(al.decode_by_codec("u16", payloads["Tempo"]), 99)
        self.assertEqual(al.decode_by_codec(
            "u64", payloads["AdjustmentAlpha"]), 17893341751498265066)
        self.assertIs(al.decode_by_codec(
            "bool", payloads["CommitRevealWeightsEnabled"]), True)

    def test_i16_signed(self):
        self.assertEqual(al.decode_by_codec("i16", "0xe803"), 1000)
        self.assertEqual(al.decode_by_codec("i16", "0x18fc"), -1000)
        with self.assertRaises(ValueError):
            al.decode_by_codec("i16", "0xe80300")


class FakeRpc:
    """Finney JSON-RPC replayed from the recorded read."""

    def __init__(self, payloads=None, broken=()):
        data = recorded()
        self.hash = data["block_hash"]
        self.number = data["block_number"]
        self.payloads = dict(data["payloads"] if payloads is None
                             else payloads)
        self.broken = set(broken)
        self.calls = []

    def __call__(self, method, params):
        self.calls.append(method)
        if method in self.broken or "all" in self.broken:
            return {"ok": False, "error": "%s unreachable" % method}
        if method == "chain_getFinalizedHead":
            return {"ok": True, "result": self.hash, "endpoint": "fake"}
        if method == "chain_getHeader":
            return {"ok": True, "result": {"number": hex(self.number)},
                    "endpoint": "fake"}
        if method == "state_queryStorageAt":
            keys = params[0]
            netuid1 = al.hyperparam_keys(1)
            by_key = {key: self.payloads.get(item)
                      for item, key in netuid1.items()}
            return {"ok": True, "endpoint": "fake", "result": [{
                "block": self.hash,
                "changes": [[key, by_key.get(key)] for key in keys]}]}
        return {"ok": False, "error": "unexpected %s" % method}


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureProvider()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        real = al.load_config()
        self.config = make_config(self.tmp.name, self.fixture.base_url,
                                  gate_signal=copy.deepcopy(
                                      real["gate_signal"]))
        self.connection = al.open_store(self.config["db"])
        self.addCleanup(self.connection.close)
        self.ledger = al.QuotaLedger(self.connection, self.config)
        self.fixture.overrides.clear()

    def run_hp(self, netuid=1, rpc=None):
        return al.run_hyperparams(self.connection, self.config, self.ledger,
                                  netuid, rpc=rpc or FakeRpc())

    def health(self):
        return self.connection.execute(
            "SELECT provider, category, detail FROM integration_health"
        ).fetchall()

    def test_each_source_label(self):
        result = self.run_hp()
        self.assertEqual(result["status"], "ok")
        items = result["values"]["items"]
        self.assertEqual(items["Tempo"], {"status": "chain", "value": 99,
                                          "cross_checked": "taoswap agrees"})
        self.assertEqual(items["MaxWeightsLimit"]["status"], "chain")
        self.assertEqual(items["Rho"]["status"], "taoswap")
        self.assertEqual(items["Rho"]["value"], 10)
        self.assertIn("unset", items["Rho"]["note"])
        self.assertEqual(items["AlphaSigmoidSteepness"]["value"], 1000)
        self.assertEqual(items["Yuma3On"]["status"], "unavailable")
        self.assertEqual(items["BondsPenalty"]["status"], "chain")
        self.assertNotIn("cross_checked", items["BondsPenalty"])
        self.assertEqual(result["provider"], "chain+taoswap")
        self.assertEqual(result["block_reference"]["number"], 9416594)
        self.assertTrue(result["block_reference"]["hash"].startswith("0x"))
        self.assertEqual(sum(result["values"]["counts"].values()),
                         len(al.HYPERPARAMS))

    def test_conflict_reports_both_values(self):
        result = self.run_hp()
        # recorded live: chain 5000, TaoSwap 4950
        entry = result["values"]["items"]["ActivityCutoff"]
        self.assertEqual(entry, {"status": "conflicting",
                                 "chain_value": 5000,
                                 "taoswap_value": 4950})
        self.assertEqual(result["values"]["conflicts"], ["ActivityCutoff"])
        self.assertIn(("hyperparams", "provider-disagreement"),
                      [row[:2] for row in self.health()])

    def test_chain_down_falls_back_to_taoswap(self):
        result = self.run_hp(rpc=FakeRpc(broken=["all"]))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "taoswap")
        self.assertIsNone(result["block_reference"])
        items = result["values"]["items"]
        self.assertEqual(items["Tempo"]["status"], "taoswap")
        self.assertIn("chain read failed", items["Tempo"]["note"])
        self.assertEqual(items["BondsPenalty"]["status"], "unavailable")
        self.assertIn((al.CHAIN_PROVIDER, "provider-failure"),
                      [row[:2] for row in self.health()])

    def test_self_test_failure_blocks_chain_read(self):
        self.config["gate_signal"]["storage_keys"] = {
            "EmissionGateBar": "0x" + "00" * 32}
        rpc = FakeRpc()
        result = self.run_hp(rpc=rpc)
        self.assertEqual(rpc.calls, [])
        self.assertEqual(result["provider"], "taoswap")

    def test_taoswap_down_keeps_chain_values(self):
        self.fixture.set_override("/v2/subnets/1/", 503)
        result = self.run_hp()
        items = result["values"]["items"]
        self.assertEqual(result["provider"], "chain")
        self.assertEqual(items["Tempo"], {"status": "chain", "value": 99})
        self.assertEqual(items["Rho"]["status"], "unavailable")
        self.assertIn("TaoSwap did not answer", items["Rho"]["note"])

    def test_both_down(self):
        self.fixture.set_override("/v2/subnets/1/", 503)
        result = self.run_hp(rpc=FakeRpc(broken=["all"]))
        self.assertEqual(result["status"], "live-unavailable")
        self.assertEqual(result["error"]["category"], "provider-failure")

    def test_unknown_netuid(self):
        result = self.run_hp(netuid=77, rpc=FakeRpc(payloads={}))
        self.assertEqual(result["error"]["category"], "not-found")
        self.assertNotIn("items", result)

    def test_undecodable_item_falls_back(self):
        payloads = dict(recorded()["payloads"], Tempo="0x630000")
        result = self.run_hp(rpc=FakeRpc(payloads=payloads))
        entry = result["values"]["items"]["Tempo"]
        self.assertEqual(entry["status"], "taoswap")
        self.assertIn("did not decode", entry["note"])

    def test_both_reads_audited(self):
        self.run_hp()
        providers = [row[0] for row in self.connection.execute(
            "SELECT provider FROM audit").fetchall()]
        self.assertIn(al.CHAIN_PROVIDER, providers)
        self.assertIn("taoswap", providers)

    def test_detail_for_other_netuid_is_drift(self):
        result = al.run_operation(self.connection, self.config, self.ledger,
                                  "subnet_detail_taoswap",
                                  dynamic_params={"netuid": 1})
        self.assertEqual(result["status"], "ok")
        self.fixture.set_override("/v2/subnets/2/", 200, json.dumps(
            self.fixture.routes["/v2/subnets/1/"]).encode())
        result = al.run_operation(self.connection, self.config, self.ledger,
                                  "subnet_detail_taoswap",
                                  dynamic_params={"netuid": 2})
        self.assertEqual(result["error"]["category"], "schema-drift")


class NormalizeTests(unittest.TestCase):
    def test_taoswap_shapes(self):
        norm = al._hyperparam_norm
        self.assertEqual(norm("u64", "100"), (True, 100))
        self.assertEqual(norm("u16", 65535.0), (True, 65535))
        self.assertEqual(norm("i16", -3.0), (True, -3))
        self.assertEqual(norm("u16", 1.26), (False, 1.26))
        self.assertEqual(norm("bool", True), (True, True))
        self.assertEqual(norm("u16", True), (False, True))
        self.assertEqual(norm("bool", 1), (False, 1))
        self.assertEqual(norm("u64", "n/a"), (False, "n/a"))


if __name__ == "__main__":
    unittest.main()
