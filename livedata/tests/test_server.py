"""atlas-live MCP server contract over real pipes (task 5.5)."""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIVEDATA_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _LIVEDATA_DIR)
sys.path.insert(0, _HERE)

import atlas_live as al  # noqa: E402
from _fixtures import (FixtureProvider, TEST_KEY, make_config,  # noqa: E402
                       write_config)

SERVER_SOURCE = os.path.join(_LIVEDATA_DIR, "atlas_live_server.py")


def call_server(config_path, requests, timeout=60):
    stdin = "\n".join(json.dumps(request) for request in requests) + "\n"
    env = dict(os.environ)
    env["TAOSTATS_API_KEY"] = TEST_KEY
    completed = subprocess.run(
        [sys.executable, SERVER_SOURCE, "--config", config_path],
        input=stdin, capture_output=True, text=True, timeout=timeout,
        env=env)
    payloads = {}
    for line in completed.stdout.strip().splitlines():
        response = json.loads(line)
        result = response.get("result") or {}
        if "content" in result:
            payloads[response["id"]] = json.loads(
                result["content"][0]["text"])
        else:
            payloads[response["id"]] = result
    return payloads


def tool_call(request_id, name, arguments=None):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


class ServerTests(unittest.TestCase):
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

    def test_handshake_and_tools(self):
        payloads = call_server(self.config_path, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        self.assertEqual(payloads[1]["serverInfo"]["name"], "atlas-live")
        self.assertEqual(
            sorted(tool["name"] for tool in payloads[2]["tools"]),
            ["live_burn_leaderboard", "live_chain_head", "live_metagraph",
             "live_network_stats", "live_portfolio", "live_price",
             "live_status", "live_subnets"])

    def test_price_two_providers_no_taostats(self):
        before = self.fixture.count("/api/price/latest/v1")
        db = al.open_store(self.config["db"])
        ledger_before = db.execute(
            "SELECT count(*) FROM calls WHERE provider = 'taostats'"
        ).fetchone()[0]
        db.close()
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_price")])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        kinds = sorted(price["kind"] for price in result["prices"])
        self.assertEqual(kinds, ["daily-close", "spot"])
        self.assertFalse(result["conflicting"])
        for price in result["prices"]:
            self.assertIn("upstream_timestamp", price)
        # the Q30 guarantee: zero TaoStats involvement in price checking
        self.assertEqual(self.fixture.count("/api/price/latest/v1"),
                         before)
        db = al.open_store(self.config["db"])
        taostats_calls = db.execute(
            "SELECT count(*) FROM calls WHERE provider = 'taostats'"
        ).fetchone()[0]
        db.close()
        self.assertEqual(taostats_calls, ledger_before)

    def test_price_disagreement_marked_conflicting(self):
        body = json.dumps({"bittensor": {
            "usd": 300.0, "last_updated_at": 2000000000}})
        self.fixture.set_override("/api/v3/simple/price", 200,
                                  body.encode())
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_price")])
        result = payloads[1]
        self.assertTrue(result["conflicting"])
        self.assertIn("DISAGREE", result["note"])
        self.assertEqual(len(result["prices"]), 2)
        db = al.open_store(self.config["db"])
        events = db.execute(
            "SELECT category FROM integration_health").fetchall()
        db.close()
        self.assertIn(("provider-disagreement",), events)

    def test_price_partial_when_one_provider_down(self):
        self.fixture.set_override("/api/v3/simple/price", 503)
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_price")])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["partial"])
        self.assertEqual(result["providers_failed"], ["coingecko_spot"])

    def test_outage_returns_unavailable_never_stale(self):
        self.fixture.set_override("/network-stats/", 503)
        payloads = call_server(self.config_path, [
            tool_call(1, "live_network_stats"),
            tool_call(2, "live_network_stats",
                      {"include_last_known": True}),
        ])
        self.assertEqual(payloads[1]["status"], "live-unavailable")
        self.assertNotIn("historical_snapshot", payloads[1])
        if "historical_snapshot" in payloads[2]:
            self.assertEqual(
                payloads[2]["historical_snapshot"]["label"],
                "historical-snapshot")

    def test_metagraph_requires_valid_netuid(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_metagraph", {"netuid": -1}),
            tool_call(2, "live_metagraph"),
            tool_call(3, "live_metagraph", {"netuid": 1}),
        ])
        self.assertEqual(payloads[1]["error"]["category"], "invalid")
        self.assertEqual(payloads[2]["error"]["category"], "invalid")
        self.assertEqual(payloads[3]["status"], "ok")
        # TaoSwap default: sorted by emission desc → uid 1 first
        self.assertEqual(payloads[3]["values"]["neurons"][0]["uid"], 1)
        self.assertEqual(payloads[3]["values"]["neurons"][0]["incentive"],
                         0.9)
        self.assertEqual(payloads[3]["operation"], "metagraph_taoswap")

    def test_portfolio_tool(self):
        acct = "5EcUreZxeehdR5qssdtVPP7yZPemKqhbuEc5gdG9pwcSF69m"
        # inject aliases into written config
        self.config["wallet_aliases"] = {
            "SECURE": {"ss58": acct, "role": "primary", "ledger": True},
        }
        path = write_config(self.tmp.name, self.config)
        payloads = call_server(path, [
            tool_call(1, "live_portfolio", {"account": "bad"}),
            tool_call(2, "live_portfolio",
                      {"account": acct, "kind": "both"}),
            tool_call(3, "live_portfolio",
                      {"account": "SECURE", "kind": "balance"}),
        ])
        self.assertEqual(payloads[1]["error"]["category"], "invalid")
        self.assertEqual(payloads[2]["status"], "ok")
        self.assertTrue(payloads[2]["balance"]["values"]["account_known"])
        self.assertIn("apy", payloads[2]["pnl_apy"]["values"])
        self.assertEqual(payloads[3]["status"], "ok")
        self.assertEqual(payloads[3].get("alias"), "SECURE")

    def test_burn_leaderboard(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_burn_leaderboard",
                      {"limit": 5, "min_burn": 1}),
        ])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        board = result["values"]["leaderboard"]
        self.assertTrue(board)
        self.assertGreaterEqual(board[0]["emission_miner_burn"], 1)
        self.assertIn("zero_burn_high_emission", result["values"])

    def test_subnets_exposes_miner_burn(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_subnets", {"netuid": 1}),
        ])
        subnet = payloads[1]["values"]["subnets"][0]
        self.assertEqual(subnet["emission_miner_burn"], 10.5)
        self.assertEqual(subnet["emission_miner_burn_unit"],
                         "percent_0_100")

    def test_chain_head_enactment_watch(self):
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_chain_head")])
        result = payloads[1]
        self.assertEqual(result["values"]["spec_version"], 424)
        self.assertFalse(result["values"]
                         ["conviction_ownership_enacted"])

    def test_status_reports_quota_and_health(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "live_chain_head"),
            tool_call(2, "live_status"),
        ])
        status = payloads[2]
        self.assertEqual(status["status"], "ok")
        self.assertIn("taostats", status["quota"])
        self.assertEqual(status["quota"]["taostats"]["estimate_source"],
                         "local-ledger")
        self.assertIn("window_remaining", status["quota"]["taostats"])
        self.assertIn("recent_health_events", status)
        self.assertIn("LOCAL estimate", status["note"])

    def test_auth_failure_never_leaks_the_key(self):
        self.fixture.set_override("/api/block/v1", 401,
                                  b'{"detail": "unauthorized"}')
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_chain_head")])
        self.assertNotIn(TEST_KEY, json.dumps(payloads))

    def test_unknown_tool_structured(self):
        payloads = call_server(self.config_path,
                               [tool_call(1, "live_shell")])
        error = payloads[1]["error"]
        self.assertEqual(error["category"], "invalid")
        self.assertIn("correlation_id", error)


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        with open(SERVER_SOURCE, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_import_allowlist(self):
        allowed = {"datetime", "json", "os", "sys", "secrets", "typing",
                   "__future__", "atlas_live"}
        imported = set()
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - allowed, set())
        for banned in ("subprocess", "socket", "sqlite3", "urllib"):
            self.assertNotIn(banned, imported)

    def test_only_sanctioned_atlas_live_surface(self):
        allowed = {"load_config", "load_env", "open_store", "resolve",
                   "QuotaLedger", "run_operation", "health_event",
                   "redact", "FatalLiveError", "CONFIG_FILE"}
        used = set(re.findall(r"\bal\.(\w+)", self.source))
        self.assertEqual(used - allowed, set())

    def test_no_generic_surface(self):
        # named operations only: no tool accepts a path/url/sql argument
        for banned in ('"path"', '"url"', '"sql"', '"query"',
                       '"command"'):
            for tool_block in re.findall(r'"inputSchema".*?\}\s*,\s*\}',
                                         self.source, re.DOTALL):
                self.assertNotIn(banned, tool_block)


if __name__ == "__main__":
    unittest.main()
