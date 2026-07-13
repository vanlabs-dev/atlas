"""Adapter pipeline over the fixture provider (tasks 3.3/4.4): typed
validation, envelopes, drift, retries, quota, snapshots, redaction."""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_live as al  # noqa: E402
from _fixtures import (FixtureProvider, TEST_KEY, make_config)  # noqa: E402

ENV = {"TAOSTATS_API_KEY": TEST_KEY}

ENVELOPE_FIELDS = ("provider", "operation", "request_completed",
                   "upstream_timestamp", "block_reference", "units",
                   "validation_status", "freshness_status", "values")


class AdapterHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureProvider()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name, self.fixture.base_url)
        self.connection = al.open_store(self.config["db"])
        self.ledger = al.QuotaLedger(self.connection, self.config)
        self.fixture.overrides.clear()
        al.register_secret(TEST_KEY)

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def run_op(self, op, **kwargs):
        return al.run_operation(self.connection, self.config,
                                self.ledger, op, env=ENV, **kwargs)


class HappyPathTests(AdapterHarness):
    def test_every_operation_returns_the_full_envelope(self):
        for op in self.config["operations"]:
            result = self.run_op(op)
            self.assertEqual(result["status"], "ok", "%s: %s" % (op,
                             result))
            for field in ENVELOPE_FIELDS:
                self.assertIn(field, result, op)
            self.assertIn("valid (schema", result["validation_status"])

    def test_price_values_and_freshness(self):
        spot = self.run_op("price_spot_coingecko")
        self.assertEqual(spot["values"]["tao_usd"], 206.0)
        self.assertEqual(spot["freshness_status"], "fresh")
        daily = self.run_op("price_daily_taoswap")
        self.assertEqual(daily["values"]["kind"], "daily-close")
        self.assertEqual(daily["values"]["tao_usd"], 204.0)

    def test_subnet_pruning_and_netuid_filter(self):
        result = self.run_op("subnets_taoswap",
                             dynamic_params={"netuid": 1})
        subnet = result["values"]["subnets"][0]
        self.assertEqual(subnet["netuid"], 1)
        self.assertEqual(subnet["conviction"]["takeover_enforced"],
                         False)
        self.assertEqual(result["block_reference"], 8602000)

    def test_chain_head_carries_enactment_flag(self):
        result = self.run_op("chain_head_taostats")
        self.assertEqual(result["values"]["spec_version"], 424)
        self.assertFalse(result["values"]
                         ["conviction_ownership_enacted"])
        self.assertEqual(result["freshness_status"], "fresh")
        self.assertEqual(result["block_reference"], 8602147)

    def test_aged_upstream_flagged(self):
        stale = dict(self.fixture.routes["/api/v3/simple/price"])
        stale = {"bittensor": {"usd": 200.0,
                               "last_updated_at": 1700000000}}
        self.fixture.set_override("/api/v3/simple/price", 200,
                                  json.dumps(stale).encode())
        result = self.run_op("price_spot_coingecko")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["freshness_status"], "aged-upstream")


class FailClosedTests(AdapterHarness):
    def test_schema_drift_fails_closed_with_health_event(self):
        self.fixture.set_override(
            "/api/v3/simple/price", 200,
            b'{"bittensor": {"usd": "not-a-number"}}')
        result = self.run_op("price_spot_coingecko")
        self.assertEqual(result["status"], "live-unavailable")
        self.assertEqual(result["error"]["category"], "schema-drift")
        self.assertNotIn("values", result)
        events = self.connection.execute(
            "SELECT category FROM integration_health").fetchall()
        self.assertIn(("schema-drift",), events)

    def test_currency_echo_guard(self):
        body = json.dumps({"currency": "EUR", "results": [
            {"date": "2026-07-12", "price": 1.0, "volume": 0.0}]})
        self.fixture.set_override("/price-history/", 200, body.encode())
        result = self.run_op("price_daily_taoswap")
        self.assertEqual(result["error"]["category"], "schema-drift")
        self.assertIn("currency", result["error"]["message"])

    def test_429_never_retried(self):
        self.fixture.set_override("/network-stats/", 429)
        before = self.fixture.count("/network-stats/")
        result = self.run_op("network_stats_taoswap")
        self.assertEqual(result["error"]["category"],
                         "provider-failure")
        self.assertEqual(self.fixture.count("/network-stats/"),
                         before + 1)

    def test_5xx_retried_once_then_fails(self):
        self.fixture.set_override("/network-stats/", 503)
        before = self.fixture.count("/network-stats/")
        result = self.run_op("network_stats_taoswap")
        self.assertEqual(result["status"], "live-unavailable")
        self.assertEqual(self.fixture.count("/network-stats/"),
                         before + 2)
        rows = self.connection.execute(
            "SELECT error_category FROM audit").fetchall()
        self.assertIn(("provider-failure",), rows)

    def test_quota_exhaustion_blocks_before_http(self):
        self.config["providers"]["taostats"]["quota"]["window_limit"] = 1
        self.run_op("chain_head_taostats")
        before = self.fixture.count("/api/block/v1")
        result = self.run_op("chain_head_taostats")
        self.assertEqual(result["error"]["category"], "quota-exhausted")
        self.assertEqual(self.fixture.count("/api/block/v1"), before)

    def test_quota_persists_across_reopen(self):
        self.run_op("chain_head_taostats")
        self.connection.close()
        self.connection = al.open_store(self.config["db"])
        ledger = al.QuotaLedger(self.connection, self.config)
        self.assertEqual(ledger.usage("taostats")["window_count"], 1)

    def test_snapshot_only_on_explicit_request(self):
        good = self.run_op("network_stats_taoswap")
        self.assertEqual(good["status"], "ok")
        self.fixture.set_override("/network-stats/", 503)
        plain = self.run_op("network_stats_taoswap")
        self.assertIn("snapshot_available", plain)
        self.assertNotIn("historical_snapshot", plain)
        explicit = self.run_op("network_stats_taoswap",
                               include_last_known=True)
        self.assertEqual(explicit["status"], "live-unavailable")
        self.assertEqual(explicit["historical_snapshot"]["label"],
                         "historical-snapshot")
        self.assertIn("NOT live data", explicit["snapshot_warning"])

    def test_key_redacted_in_audit_and_errors(self):
        self.fixture.set_override("/api/block/v1", 401,
                                  b'{"detail": "bad key"}')
        result = self.run_op("chain_head_taostats")
        self.assertNotIn(TEST_KEY, json.dumps(result))
        rows = self.connection.execute(
            "SELECT params FROM audit").fetchall()
        self.assertNotIn(TEST_KEY, json.dumps(rows))


class SpecUpgradeTests(AdapterHarness):
    """Live runtime spec_version persistence + upgrade events
    (signal-tiering; consumed by the chain-runtime-upgrade class)."""

    def _head_payload(self, spec, block):
        import datetime as dt
        now = dt.datetime.now(tz=dt.timezone.utc)
        return json.dumps({
            "pagination": {"current_page": 1},
            "data": [{"block_number": block, "spec_version": spec,
                      "spec_name": "node-subtensor",
                      "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "hash": "0x" + "e" * 64, "events_count": 1,
                      "extrinsics_count": 1}]}).encode()

    def _upgrades(self):
        return self.connection.execute(
            "SELECT prev_spec, new_spec, block_reference FROM "
            "spec_upgrades ORDER BY id").fetchall()

    def test_first_observation_records_no_upgrade(self):
        self.assertEqual(self.run_op("chain_head_taostats")["status"], "ok")
        self.assertEqual(
            al.meta_get(self.connection, al.META_LAST_LIVE_SPEC), "424")
        self.assertEqual(self._upgrades(), [])

    def test_change_records_one_upgrade_same_value_none(self):
        self.run_op("chain_head_taostats")
        self.fixture.set_override("/api/block/v1", 200,
                                  self._head_payload(425, 8612004))
        self.run_op("chain_head_taostats")
        self.assertEqual(self._upgrades(), [(424, 425, 8612004)])
        # Same value again -> observed_at advances, no second event.
        self.run_op("chain_head_taostats")
        self.assertEqual(len(self._upgrades()), 1)
        self.assertEqual(
            al.meta_get(self.connection, al.META_LAST_LIVE_SPEC), "425")

    def test_restart_does_not_reemit(self):
        self.run_op("chain_head_taostats")
        self.fixture.set_override("/api/block/v1", 200,
                                  self._head_payload(425, 8612004))
        self.run_op("chain_head_taostats")
        # Simulate a restart: reopen the store, observe the same spec.
        self.connection.close()
        self.connection = al.open_store(self.config["db"])
        self.ledger = al.QuotaLedger(self.connection, self.config)
        self.run_op("chain_head_taostats")
        self.assertEqual(len(self._upgrades()), 1)

    def test_failed_or_invalid_response_records_nothing(self):
        self.run_op("chain_head_taostats")
        self.fixture.set_override("/api/block/v1", 503)
        self.run_op("chain_head_taostats")
        self.fixture.set_override("/api/block/v1", 200,
                                  b'{"data": [{"bogus": true}]}')
        self.run_op("chain_head_taostats")
        self.assertEqual(self._upgrades(), [])
        self.assertEqual(
            al.meta_get(self.connection, al.META_LAST_LIVE_SPEC), "424")


if __name__ == "__main__":
    unittest.main()
