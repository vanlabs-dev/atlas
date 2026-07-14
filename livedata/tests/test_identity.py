"""subnet-identity adapter (subnet-repo-fleet §1): the pinned-schema
per-page operation plus the pagination aggregator that produces the
fleet-consumable netuid->identity map. HTTP fixture for the real request
path; injected page-fetcher for the aggregation loop."""

import json
import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402
import _fixtures as fx  # noqa: E402


class SubnetIdentityOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.provider = fx.FixtureProvider()
        self.addCleanup(self.provider.close)
        self.config = fx.make_config(self.tmp, self.provider.base_url)
        self.conn = al.open_store(self.config["db"])
        self.addCleanup(self.conn.close)
        self.ledger = al.QuotaLedger(self.conn, self.config)
        self.env = {"TAOSTATS_API_KEY": fx.TEST_KEY}

    def _run(self, **params):
        return al.run_operation(self.conn, self.config, self.ledger,
                                "subnet_identity_taostats",
                                dynamic_params=params, interactive=False,
                                env=self.env)

    def test_valid_page_extracts_netuid_repo_map(self):
        result = self._run()
        self.assertEqual(result["status"], "ok")
        subs = {s["netuid"]: s for s in result["values"]["subnets"]}
        self.assertIsNone(subs[0]["github_repo"])
        self.assertEqual(subs[1]["github_repo"],
                         "https://github.com/macrocosm-os/apex")
        # the identity endpoint does not carry the owner ss58
        self.assertIsNone(subs[1]["owner_ss58"])

    def test_pagination_metadata_is_surfaced(self):
        values = self._run()["values"]
        self.assertEqual(values["current_page"], 1)
        self.assertEqual(values["total_pages"], 1)
        self.assertIsNone(values["next_page"])

    def test_schema_drift_missing_netuid_fails_closed(self):
        bad = json.dumps({
            "pagination": {"current_page": 1, "total_pages": 1,
                           "next_page": None},
            "data": [{"subnet_name": "x", "github_repo": None}]}).encode()
        self.provider.set_override("/api/subnet/identity/v1", 200, bad)
        result = self._run()
        self.assertEqual(result["status"], "live-unavailable")
        self.assertEqual(result["error"]["category"], "schema-drift")


class RunSubnetIdentityAggregatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.provider = fx.FixtureProvider()
        self.addCleanup(self.provider.close)
        self.config = fx.make_config(self.tmp, self.provider.base_url)
        self.conn = al.open_store(self.config["db"])
        self.addCleanup(self.conn.close)
        self.ledger = al.QuotaLedger(self.conn, self.config)
        self.env = {"TAOSTATS_API_KEY": fx.TEST_KEY}

    def test_single_page_completes_in_one_call(self):
        result = al.run_subnet_identity(self.conn, self.config, self.ledger,
                                        self.env)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["values"]["complete"])
        self.assertEqual(result["values"]["count"], 2)
        self.assertEqual(self.provider.count("/api/subnet/identity/v1"), 1)

    def test_multi_page_aggregates_to_completion(self):
        pages = [
            {"status": "ok", "freshness_status": "unknown-upstream",
             "values": {"subnets": [{"netuid": 1, "github_repo": "u1",
                                     "subnet_name": "a", "owner_ss58": None}],
                        "current_page": 1, "total_pages": 2, "next_page": 2}},
            {"status": "ok", "freshness_status": "unknown-upstream",
             "values": {"subnets": [{"netuid": 2, "github_repo": "u2",
                                     "subnet_name": "b", "owner_ss58": None}],
                        "current_page": 2, "total_pages": 2,
                        "next_page": None}}]
        seen = []

        def run_op(conn, config, ledger, op, dynamic_params=None,
                   interactive=True, env=None):
            page = (dynamic_params or {}).get("page", 1)
            seen.append(page)
            return pages[page - 1]

        result = al.run_subnet_identity(None, {}, None, run_op=run_op)
        self.assertTrue(result["values"]["complete"])
        self.assertEqual([s["netuid"] for s in result["values"]["subnets"]],
                         [1, 2])
        self.assertEqual(seen, [1, 2])

    def test_failed_page_reports_degraded_incomplete(self):
        def run_op(*args, **kwargs):
            return {"status": "live-unavailable",
                    "error": {"category": "provider-failure"}}

        result = al.run_subnet_identity(None, {}, None, run_op=run_op)
        self.assertEqual(result["status"], "live-unavailable")
        self.assertFalse(result["values"]["complete"])


if __name__ == "__main__":
    unittest.main()
