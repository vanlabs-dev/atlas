"""Adapters that replace the disabled metagraphed MCP (change:
livedata-metagraphed-gaps): recorded TaoSwap shapes validate, drift fails
closed with a health event, and a missing resource is `not-found`."""

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

HOTKEY = "5E2LP6EnZ54m3wS8s1yPvD5c3xo71kQroBw7aUVK32TKeZ5u"
ENVELOPE = ("provider", "operation", "request_completed",
            "upstream_timestamp", "block_reference", "units",
            "validation_status", "freshness_status", "values")


class GapHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureProvider()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = make_config(self.tmp.name, self.fixture.base_url)
        self.connection = al.open_store(self.config["db"])
        self.addCleanup(self.connection.close)
        self.ledger = al.QuotaLedger(self.connection, self.config)
        self.fixture.overrides.clear()

    def run_op(self, name, params=None):
        return al.run_operation(self.connection, self.config, self.ledger,
                                name, dynamic_params=params)

    def health(self):
        return [row[0] for row in self.connection.execute(
            "SELECT category FROM integration_health").fetchall()]

    def assert_envelope(self, result):
        self.assertEqual(result["status"], "ok", result)
        for field in ENVELOPE:
            self.assertIn(field, result)


class ValidatorAdapterTests(GapHarness):
    def test_subnet_validators_ranked_and_capped(self):
        result = self.run_op("subnet_validators_taoswap",
                             {"netuid": 1, "limit": 2})
        self.assert_envelope(result)
        values = result["values"]
        stakes = [row["stake"] for row in values["validators"]]
        self.assertEqual(stakes, sorted(stakes, reverse=True))
        self.assertEqual((values["shown"], values["cap"]), (2, 2))
        self.assertEqual(values["total_count"], 3)
        self.assertTrue(values["validators"][0]["hotkey"].startswith("5"))
        self.assertIn("percent", result["units"])
        self.assertTrue(result["upstream_timestamp"].endswith("+00:00"))

    def test_subnet_validators_default_cap(self):
        result = self.run_op("subnet_validators_taoswap", {"netuid": 1})
        self.assertEqual(result["values"]["cap"], 15)

    def test_validator_detail(self):
        result = self.run_op("validator_detail_taoswap",
                             {"hotkey": HOTKEY, "limit": 2})
        self.assert_envelope(result)
        values = result["values"]
        self.assertEqual(values["hotkey"], HOTKEY)
        self.assertEqual(len(values["subnets"]), 2)
        self.assertGreaterEqual(values["subnets"][0]["stake"],
                                values["subnets"][1]["stake"])
        self.assertEqual(values["subnets_total"], 4)
        self.assertEqual(len(values["top_delegators"]), 2)
        self.assertIsInstance(values["total_stake_tao"], float)
        self.assertGreater(values["delegators_listed"], 2)

    def test_validator_detail_sends_omit(self):
        operation = self.config["operations"]["validator_detail_taoswap"]
        self.assertEqual(operation["params"]["omit"], "monitoring,history")

    def test_ranked_list_honours_limit(self):
        result = self.run_op("validators_taoswap", {"limit": 1})
        self.assertEqual(len(result["values"]["validators"]), 1)
        self.assertEqual(result["values"]["total_listed"], 2)

    def test_drift_fails_closed_with_health_event(self):
        path = "/v2/subnets/1/validators/"
        self.fixture.set_override(path, 200, json.dumps(
            {"netuid": 1, "results": [{"hotkey": "x"}],
             "pagination": {"total_count": 1}}).encode())
        result = self.run_op("subnet_validators_taoswap", {"netuid": 1})
        self.assertEqual(result["error"]["category"], "schema-drift")
        self.assertIn("schema-drift", self.health())

    def test_detail_drift_fails_closed(self):
        path = "/v2/validators/%s/" % HOTKEY
        self.fixture.set_override(path, 200, json.dumps(
            {"validator_hotkey": HOTKEY, "total_stake": "1"}).encode())
        result = self.run_op("validator_detail_taoswap", {"hotkey": HOTKEY})
        self.assertEqual(result["error"]["category"], "schema-drift")

    def test_unknown_resource_is_not_found(self):
        result = self.run_op("subnet_validators_taoswap", {"netuid": 99999})
        self.assertEqual(result["status"], "live-unavailable")
        self.assertEqual(result["error"]["category"], "not-found")
        self.assertFalse(result["error"]["retry_safe"])
        self.assertNotIn("provider-failure", self.health())


COLDKEY = "5GsbTgfvgCH4xdqSkiPb7EaBBFLHjWH5vfEALhJaewSFpZX9"


class AccountEventAdapterTests(GapHarness):
    def test_ledger_newest_first_in_tao(self):
        result = self.run_op("account_ledger_taoswap",
                             {"account": COLDKEY, "limit": 3})
        self.assert_envelope(result)
        entries = result["values"]["entries"]
        blocks = [row["block"] for row in entries]
        self.assertEqual(blocks, sorted(blocks, reverse=True))
        self.assertEqual(len(entries), 3)
        self.assertEqual(result["values"]["total_count"], 368)
        self.assertEqual(result["block_reference"], blocks[0])
        self.assertTrue(any(row["tao"] == 1.0 for row in entries))
        self.assertIsNotNone(result["upstream_timestamp"])

    def test_transactions_two_lists_capped(self):
        result = self.run_op("account_transactions_taoswap",
                             {"account": COLDKEY, "limit_shown": 2})
        self.assert_envelope(result)
        values = result["values"]
        self.assertEqual(len(values["stake_transfers"]), 2)
        self.assertEqual(len(values["transfers"]), 2)
        blocks = [row["block"] for row in values["stake_transfers"]]
        self.assertEqual(blocks, sorted(blocks, reverse=True))
        self.assertTrue(result["upstream_timestamp"].endswith("+00:00"))

    def test_transactions_pin_provider_limit(self):
        operation = self.config["operations"][
            "account_transactions_taoswap"]
        self.assertEqual(operation["params"]["limit"], 50)
        self.assertIn("limit_shown", operation["client_params"])

    def test_events_newest_first(self):
        result = self.run_op("events_taoswap", {"limit": 2})
        self.assert_envelope(result)
        events = result["values"]["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual(result["block_reference"], events[0]["block"])
        self.assertEqual(result["freshness_status"], "unknown-upstream")

    def test_block_events_cut_long_data(self):
        result = self.run_op("block_events_taoswap", {"block": 8819803})
        self.assert_envelope(result)
        self.assertEqual(result["block_reference"], 8819803)
        self.assertEqual(result["values"]["total_count"], 194)
        self.assertTrue(all(len(row["data"]) <= 200
                            for row in result["values"]["events"]))

    def test_block_events_for_another_block_fail_closed(self):
        self.fixture.set_override("/blocks/1/events/", 200, json.dumps(
            self.fixture.routes["/blocks/8819803/events/"]).encode())
        result = self.run_op("block_events_taoswap", {"block": 1})
        self.assertEqual(result["error"]["category"], "schema-drift")

    def test_drift_on_each_schema(self):
        cases = (("account_ledger_taoswap", "/v1/account-ledger/",
                  {"account": COLDKEY}, {"results": []}),
                 ("account_transactions_taoswap", "/account-transactions/",
                  {"account": COLDKEY}, {"transfers": []}),
                 ("events_taoswap", "/events/", None,
                  {"pagination": {}, "results": [{"block": 1}]}),
                 ("block_events_taoswap", "/blocks/5/events/",
                  {"block": 5}, {"results": []}))
        for op, path, params, body in cases:
            self.fixture.set_override(path, 200, json.dumps(body).encode())
            result = self.run_op(op, params)
            self.assertEqual(result["error"]["category"], "schema-drift",
                             op)


class Ss58Tests(unittest.TestCase):
    GOOD = (HOTKEY,
            "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            "5EcUreZxeehdR5qssdtVPP7yZPemKqhbuEc5gdG9pwcSF69m")

    def test_known_good_addresses(self):
        for address in self.GOOD:
            self.assertTrue(al.valid_ss58(address), address)

    def test_bad_checksum(self):
        good = self.GOOD[1]
        flipped = good[:-1] + ("Z" if good[-1] != "Z" else "Y")
        self.assertFalse(al.valid_ss58(flipped))

    def test_wrong_length(self):
        self.assertFalse(al.valid_ss58(self.GOOD[1][:-3]))
        self.assertFalse(al.valid_ss58(self.GOOD[1] + "1"))

    def test_non_base58_and_non_string(self):
        for value in ("0" + self.GOOD[1][1:], "5F" + "l" * 46, "",
                      "../etc/passwd", None, 42):
            self.assertFalse(al.valid_ss58(value), value)

    def test_structurally_plausible_fakes_rejected(self):
        # the old check (length + alphabet) accepted these
        self.assertFalse(al.valid_ss58("5F" + "a" * 46))
        self.assertFalse(al.valid_ss58("5H" + "c" * 46))


if __name__ == "__main__":
    unittest.main()
