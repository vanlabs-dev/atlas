"""The MCP test tool: protocol behavior and its inert code surface."""

import io
import json
import os
import subprocess
import sys
import unittest

from _helpers import TESTTOOL_SOURCE

sys.path.insert(0, os.path.dirname(TESTTOOL_SOURCE))

import atlas_test_tool as tool  # noqa: E402


def rpc(method, request_id=1, params=None):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return message


class HandshakeTests(unittest.TestCase):
    def test_initialize_echoes_supported_version(self):
        response = tool.handle_message(rpc(
            "initialize", params={"protocolVersion": "2024-11-05"}))
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_initialize_falls_back_to_latest_known_version(self):
        response = tool.handle_message(rpc(
            "initialize", params={"protocolVersion": "2099-01-01"}))
        self.assertEqual(response["result"]["protocolVersion"],
                         tool.PROTOCOL_VERSION)

    def test_initialized_notification_gets_no_reply(self):
        self.assertIsNone(tool.handle_message(
            rpc("notifications/initialized", request_id=None)))

    def test_ping(self):
        self.assertEqual(tool.handle_message(rpc("ping"))["result"], {})


class ToolTests(unittest.TestCase):
    def test_tools_list_exposes_exactly_atlas_ping(self):
        result = tool.handle_message(rpc("tools/list"))["result"]
        self.assertEqual([entry["name"] for entry in result["tools"]],
                         [tool.TOOL_NAME])
        schema = result["tools"][0]["inputSchema"]
        self.assertEqual(schema["properties"], {})
        self.assertFalse(schema["additionalProperties"])

    def test_call_returns_static_identity(self):
        response = tool.handle_message(rpc(
            "tools/call", params={"name": "atlas_ping", "arguments": {}}))
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["tool"], "atlas_ping")
        self.assertEqual(payload["tool_version"], tool.TOOL_VERSION)
        self.assertIn("utc_time", payload)
        self.assertFalse(response["result"]["isError"])

    def test_unknown_tool_is_invalid_params(self):
        response = tool.handle_message(rpc(
            "tools/call", params={"name": "shell_exec"}))
        self.assertEqual(response["error"]["code"], tool.INVALID_PARAMS)

    def test_unknown_method_with_id_is_method_not_found(self):
        response = tool.handle_message(rpc("resources/list"))
        self.assertEqual(response["error"]["code"], tool.METHOD_NOT_FOUND)

    def test_unknown_notification_is_ignored(self):
        self.assertIsNone(tool.handle_message(
            rpc("resources/updated", request_id=None)))


class ServeLoopTests(unittest.TestCase):
    def test_full_session_over_streams(self):
        lines = [
            json.dumps(rpc("initialize", 1,
                           {"protocolVersion": "2025-06-18"})),
            json.dumps(rpc("notifications/initialized", None)),
            "not json at all",
            json.dumps(rpc("tools/list", 2)),
            json.dumps(rpc("tools/call", 3, {"name": "atlas_ping"})),
        ]
        stdout = io.StringIO()
        tool.serve(stdin=io.StringIO("\n".join(lines) + "\n"), stdout=stdout)
        responses = [json.loads(line)
                     for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(responses), 4)  # notification answered nothing
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[1]["error"]["code"], tool.PARSE_ERROR)
        self.assertEqual(responses[2]["id"], 2)
        self.assertEqual(responses[3]["id"], 3)

    def test_real_process_round_trip(self):
        request = json.dumps(rpc("tools/call", 7,
                                 {"name": "atlas_ping"})) + "\n"
        completed = subprocess.run(
            [sys.executable, TESTTOOL_SOURCE], input=request,
            capture_output=True, text=True, timeout=30, check=True)
        response = json.loads(completed.stdout.strip())
        self.assertEqual(response["id"], 7)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["server"], tool.SERVER_NAME)


class InertSurfaceTests(unittest.TestCase):
    """No data access: reviewed by test, per the spec scenario."""

    def setUp(self):
        with open(TESTTOOL_SOURCE, encoding="utf-8") as handle:
            source = handle.read()
        # the module docstring documents what the code must NOT do; scan
        # the code, not the promise
        self.source = source.split('"""', 2)[2]

    def test_no_filesystem_network_or_process_surface(self):
        for forbidden in ("import os", "open(", "socket", "subprocess",
                          "urllib", "http.", "requests", "pathlib",
                          "shutil", "os.system", "eval(", "exec("):
            self.assertNotIn(forbidden, self.source, forbidden)

    def test_only_expected_imports(self):
        imports = [line.strip() for line in self.source.splitlines()
                   if line.strip().startswith(("import ", "from "))]
        allowed = {"import datetime", "import json", "import sys",
                   "from __future__ import annotations",
                   "from typing import Any, Dict, Optional"}
        self.assertTrue(set(imports) <= allowed, imports)


if __name__ == "__main__":
    unittest.main()
