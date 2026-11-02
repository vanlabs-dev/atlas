"""TaoSwap discovery covers the metagraphed-gap endpoints inside its call
budget (change: livedata-metagraphed-gaps). No network: the session is
faked and records each probe."""

import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import discover_taoswap as dt  # noqa: E402

GAP_PATHS = {
    "/v2/subnets/64/",
    "/v2/subnets/1/validators/",
    "/v2/subnets/99999/validators/",
    "/v2/validators/%s/" % dt.SAMPLE_HOTKEY,
    "/v2/validators/not-an-ss58/",
    "/v1/account-ledger/",
    "/account-transactions/",
    "/events/",
    "/blocks/8819803/events/",
}


class FakeSession:
    instances = []

    def __init__(self, config, provider, max_calls=None, **_):
        self.max_calls = max_calls
        self.calls_made = 0
        self.rate_headers_seen = {}
        self.observations = []
        FakeSession.instances.append(self)

    def probe(self, name, path, params=None, headers=None,
              expect="success", note="", timeout=None):
        self.calls_made += 1
        obs = {"name": name, "path": path, "params": params or {},
               "expectation": expect, "ok": expect == "success",
               "status": 200 if expect == "success" else 404,
               "parse_error": None}
        self.observations.append(obs)
        return obs

    def close(self):
        pass


class DiscoveryCoverageTest(unittest.TestCase):
    def run_discovery(self):
        FakeSession.instances.clear()
        config = {"providers": {"taoswap": {
            "base_url": "https://example.invalid",
            "quota": {"min_spacing_seconds": 1.0, "per_minute_cap": 20}}},
            "request_timeout_seconds": 20}
        with mock.patch.object(dt.dc, "DiscoverySession", FakeSession), \
                mock.patch.object(dt.al, "load_config",
                                  return_value=config), \
                mock.patch.object(dt.dc, "write_report",
                                  return_value="report.json"), \
                mock.patch("builtins.print"):
            self.assertEqual(dt.discover(), 0)
        return FakeSession.instances[0]

    def test_every_gap_path_is_probed(self):
        session = self.run_discovery()
        probed = {obs["path"] for obs in session.observations}
        self.assertEqual(GAP_PATHS - probed, set())

    def test_two_samples_for_account_endpoints(self):
        session = self.run_discovery()
        for path in ("/v1/account-ledger/", "/account-transactions/"):
            accounts = {obs["params"]["account"]
                        for obs in session.observations
                        if obs["path"] == path}
            self.assertEqual(accounts, {dt.SAMPLE_COLDKEY_ACTIVE,
                                        dt.SAMPLE_COLDKEY_IDLE})

    def test_negative_tests_expect_errors(self):
        session = self.run_discovery()
        errors = {obs["path"] for obs in session.observations
                  if obs["expectation"] == "error"}
        self.assertIn("/v2/subnets/99999/validators/", errors)
        self.assertIn("/v2/validators/not-an-ss58/", errors)

    def test_calls_stay_inside_budget(self):
        session = self.run_discovery()
        self.assertEqual(session.max_calls, dt.MAX_CALLS)
        # the schema probe can add one fallback call
        self.assertLessEqual(session.calls_made + 1, dt.MAX_CALLS)


if __name__ == "__main__":
    unittest.main()
