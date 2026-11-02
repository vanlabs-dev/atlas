"""atlas-live tools that replace the disabled metagraphed MCP (change:
livedata-metagraphed-gaps), over real pipes against the fixture provider."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from _fixtures import FixtureProvider, make_config, write_config  # noqa: E402
from test_server import call_server, tool_call  # noqa: E402

HOTKEY = "5E2LP6EnZ54m3wS8s1yPvD5c3xo71kQroBw7aUVK32TKeZ5u"
ENVELOPE = ("provider", "operation", "request_completed",
            "upstream_timestamp", "block_reference", "units",
            "validation_status", "freshness_status", "values")


class GapServerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureProvider()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.config = make_config(cls.tmp.name, cls.fixture.base_url)
        cls.config_path = write_config(cls.tmp.name, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.fixture.overrides.clear()

    def total_requests(self):
        return sum(self.fixture.request_counts.values())

    def assert_envelope(self, payload):
        self.assertEqual(payload.get("status"), "ok", payload)
        for field in ENVELOPE:
            self.assertIn(field, payload)


class ValidatorsToolTests(GapServerBase):
    def test_three_modes(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_validators", {}),
            tool_call(2, "live_validators", {"netuid": 1, "limit": 2}),
            tool_call(3, "live_validators", {"hotkey": HOTKEY}),
        ])
        for request_id, operation in ((1, "validators_taoswap"),
                                      (2, "subnet_validators_taoswap"),
                                      (3, "validator_detail_taoswap")):
            self.assert_envelope(payloads[request_id])
            self.assertEqual(payloads[request_id]["operation"], operation)
        self.assertEqual(payloads[1]["values"]["cap"], 15)
        self.assertEqual(payloads[1]["values"]["total_listed"], 2)
        subnet = payloads[2]["values"]
        self.assertEqual((subnet["shown"], subnet["cap"],
                          subnet["total_count"]), (2, 2, 3))
        self.assertEqual(payloads[3]["values"]["hotkey"], HOTKEY)

    def test_invalid_inputs_make_no_provider_call(self):
        before = self.total_requests()
        payloads = call_server(self.config_path, [
            tool_call(1, "live_validators", {"hotkey": "5F" + "a" * 46}),
            tool_call(2, "live_validators", {"hotkey": "../../etc"}),
            tool_call(3, "live_validators", {"netuid": -1}),
            tool_call(4, "live_validators", {"netuid": 1, "hotkey": HOTKEY}),
            tool_call(5, "live_validators", {"limit": 65}),
        ])
        for request_id in range(1, 6):
            self.assertEqual(payloads[request_id]["error"]["category"],
                             "invalid", request_id)
        self.assertEqual(self.total_requests(), before)

    def test_unknown_netuid_is_not_found(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_validators", {"netuid": 99999})])
        self.assertEqual(payloads[1]["error"]["category"], "not-found")


COLDKEY = "5GsbTgfvgCH4xdqSkiPb7EaBBFLHjWH5vfEALhJaewSFpZX9"


class AccountEventsToolTests(GapServerBase):
    def test_account_both_bounded(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_account", {"account": COLDKEY, "limit": 2})])
        out = payloads[1]
        self.assertEqual(out["status"], "ok", out)
        self.assert_envelope(out["ledger"])
        self.assert_envelope(out["transfers"])
        self.assertEqual(out["ledger"]["values"]["cap"], 2)
        self.assertEqual(len(out["ledger"]["values"]["entries"]), 2)
        self.assertEqual(len(out["transfers"]["values"]["transfers"]), 2)

    def test_account_alias(self):
        self.config["wallet_aliases"] = {
            "SECURE": {"ss58": COLDKEY, "role": "primary"}}
        path = write_config(self.tmp.name, self.config)
        payloads = call_server(path, [
            tool_call(1, "live_account", {"account": "secure",
                                          "kind": "ledger"})])
        self.assertEqual(payloads[1]["alias"], "SECURE")
        self.assertNotIn("transfers", payloads[1])

    def test_account_partial_when_one_part_fails(self):
        self.fixture.set_override("/account-transactions/", 503)
        payloads = call_server(self.config_path, [
            tool_call(1, "live_account", {"account": COLDKEY})])
        self.assertTrue(payloads[1]["partial"])
        self.assertEqual(payloads[1]["failed_parts"], ["transfers"])

    def test_events_latest_and_block(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_events", {"limit": 3}),
            tool_call(2, "live_events", {"block": 8819803}),
        ])
        self.assert_envelope(payloads[1])
        self.assertEqual(len(payloads[1]["values"]["events"]), 3)
        self.assert_envelope(payloads[2])
        self.assertEqual(payloads[2]["block_reference"], 8819803)
        self.assertEqual(payloads[2]["values"]["cap"], 20)

    def test_invalid_inputs_make_no_provider_call(self):
        before = self.total_requests()
        payloads = call_server(self.config_path, [
            tool_call(1, "live_account", {"account": "5F" + "a" * 46}),
            tool_call(2, "live_account", {"account": COLDKEY,
                                          "kind": "all"}),
            tool_call(3, "live_account", {"account": COLDKEY,
                                          "limit": 51}),
            tool_call(4, "live_events", {"block": -5}),
            tool_call(5, "live_events", {"block": "8819803"}),
        ])
        for request_id in range(1, 6):
            self.assertEqual(payloads[request_id]["error"]["category"],
                             "invalid", request_id)
        self.assertEqual(self.total_requests(), before)


if __name__ == "__main__":
    unittest.main()
