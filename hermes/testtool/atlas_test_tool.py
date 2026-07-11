#!/usr/bin/env python3
"""Atlas MCP test tool — the minimal Hermes<->Atlas tool-path proof.

A deliberately inert stdio MCP server exposing exactly one read-only tool,
`atlas_ping`, which returns static identification data. Its sole purpose is
the ATLAS-HERMES-005 check that "a local Atlas test tool can be discovered
and called" from a Hermes conversation.

By design this file has NO data-access surface: no filesystem reads, no
network, no subprocess, no parameters that influence device state
(ATLAS-TOOL-001 minimization). It is replaced — not extended — by the
production tool interface phase.

Implementation: stdlib-only JSON-RPC 2.0 over newline-delimited stdio,
covering the minimal MCP surface (initialize, ping, tools/list, tools/call).

Hermes registration (stdio MCP server):
    command: python3
    args:    [<repo>/hermes/testtool/atlas_test_tool.py]
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any, Dict, Optional

SERVER_NAME = "atlas-test-tool"
TOOL_NAME = "atlas_ping"
TOOL_VERSION = "0.1.0"

# Latest MCP protocol revision known to this server; the initialize
# handshake echoes the client's requested revision when we recognise it.
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

TOOL_DESCRIPTION = (
    "Atlas connectivity test. Returns static identification data proving "
    "the Hermes-to-Atlas local tool path works. Reads nothing, changes "
    "nothing.")


def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _ping_payload() -> Dict[str, Any]:
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "server": SERVER_NAME,
        "utc_time": datetime.datetime.now(
            tz=datetime.timezone.utc).isoformat(),
        "message": "Atlas test tool reachable over the local MCP path.",
    }


def handle_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message; None means nothing is sent back."""
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return None  # a response or malformed frame; nothing to answer
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        params = message.get("params") or {}
        requested = params.get("protocolVersion")
        version = (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                   else PROTOCOL_VERSION)
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": TOOL_VERSION},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {},
                            "additionalProperties": False},
        }]})
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != TOOL_NAME:
            return _error(request_id, INVALID_PARAMS,
                          "unknown tool: %r (only %s exists)"
                          % (params.get("name"), TOOL_NAME))
        return _result(request_id, {
            "content": [{"type": "text",
                         "text": json.dumps(_ping_payload())}],
            "isError": False,
        })
    if request_id is not None:
        return _error(request_id, METHOD_NOT_FOUND,
                      "method not supported: %s" % method)
    return None


def serve(stdin: Any = None, stdout: Any = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: Optional[Dict[str, Any]] = _error(
                None, PARSE_ERROR, "invalid JSON")
        else:
            response = (handle_message(message)
                        if isinstance(message, dict) else
                        _error(None, PARSE_ERROR,
                               "expected a JSON-RPC object"))
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
