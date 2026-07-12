#!/usr/bin/env python3
"""Atlas live-data MCP server — fail-closed current Bittensor data.

Six READ-ONLY named tools over the approved provider contracts
(ATLAS-TOOL-002/003/004, ATLAS-LIVE-001…008; gates of 2026-07-12):

- live_price          — TAO/USD: CoinGecko spot + TaoSwap daily close,
                        cross-checked (5% tolerance); NEVER TaoStats (Q30)
- live_subnets        — TaoSwap subnet aggregates (+conviction state);
                        optional TaoStats protocol params per netuid
- live_metagraph      — TaoStats per-subnet neuron detail (quota-budgeted)
- live_network_stats  — TaoSwap network snapshot
- live_chain_head     — TaoStats chain head incl. spec_version (the
                        conviction enactment watch)
- live_status         — integration health, per-provider quota
                        (local estimate vs provider-reported), last calls

Every success carries the full ATLAS-LIVE-003 metadata envelope; every
failure is a structured `live-unavailable` — a cached value is returned
ONLY on explicit `include_last_known: true`, labelled historical
(ATLAS-LIVE-004). Secrets never appear in any output (ATLAS-API-008).

Hermes registration (stdio MCP server, alongside atlas-kb/atlas-repo):
    command: python3
    args:    [<repo>/livedata/atlas_live_server.py]
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import secrets as secretsmod
from typing import Any, Dict, List, Optional

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
sys.path.insert(0, _MODULE_DIR)

import atlas_live as al  # noqa: E402

SERVER_NAME = "atlas-live"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

AUDIT_FILE_NAME = "tool-audit.jsonl"
AUDIT_MAX_BYTES = 5 * 1024 * 1024

_LAST_KNOWN = {
    "include_last_known": {
        "type": "boolean",
        "description": "if the live call fails, also return the last "
                       "known value as a clearly labelled historical "
                       "snapshot (default false)"},
}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "live_price",
        "description": (
            "CURRENT TAO/USD price, live from providers: CoinGecko spot "
            "+ TaoSwap daily close, cross-checked. Each value carries "
            "its own provider and timestamp — cite them. Values marked "
            "conflicting MUST be reported as disagreeing, never "
            "averaged."),
        "inputSchema": {"type": "object", "properties": dict(_LAST_KNOWN),
                        "additionalProperties": False},
    },
    {
        "name": "live_subnets",
        "description": (
            "CURRENT Bittensor subnet state (TaoSwap): alpha price, "
            "stake, emission share, and conviction/ownership status "
            "(contested, takeover eligibility) per subnet. Optional "
            "netuid filter; set include_protocol_params for on-chain "
            "parameters (TaoStats, quota-budgeted)."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "netuid": {"type": "integer", "minimum": 0},
                "include_protocol_params": {"type": "boolean"},
            }),
            "additionalProperties": False,
        },
    },
    {
        "name": "live_metagraph",
        "description": (
            "CURRENT neuron/validator detail for one subnet (TaoStats, "
            "quota-budgeted): hotkeys, coldkeys, stake, rewards, "
            "owner/immunity flags. Requires netuid."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "netuid": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": 25},
            }),
            "required": ["netuid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "live_network_stats",
        "description": (
            "CURRENT network-wide staking snapshot (TaoSwap): total/"
            "root/subnet stake, accounts, registration cost. Daily "
            "cadence — report its date."),
        "inputSchema": {"type": "object", "properties": dict(_LAST_KNOWN),
                        "additionalProperties": False},
    },
    {
        "name": "live_chain_head",
        "description": (
            "CURRENT chain head (TaoStats, quota-budgeted): block "
            "number, timestamp, and runtime spec_version — "
            "spec_version >= 425 means conviction-based subnet "
            "ownership is enacted (as of 2026-07-12 it is NOT: "
            "spec 424)."),
        "inputSchema": {"type": "object", "properties": dict(_LAST_KNOWN),
                        "additionalProperties": False},
    },
    {
        "name": "live_status",
        "description": (
            "Live-data integration health: recent health events (drift/"
            "outage/disagreement), per-provider remaining quota (local "
            "estimate vs provider-reported), last successful calls. "
            "Makes NO provider calls."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
]


def _correlation_id() -> str:
    return secretsmod.token_hex(6)


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def structured_error(category: str, message: str,
                     retry_safe: bool) -> Dict[str, Any]:
    return {
        "error": {
            "category": category,
            "component": SERVER_NAME,
            "retry_safe": retry_safe,
            "message": al.redact(message),
            "correlation_id": _correlation_id(),
        }
    }


class LiveTools:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._env: Optional[Dict[str, str]] = None

    def _context(self):
        config = al.load_config(self.config_path)
        if self._env is None:
            self._env = al.load_env()
        connection = al.open_store(
            al.resolve(config["db"], _REPO_ROOT))
        return config, connection, al.QuotaLedger(connection, config)

    def _run(self, op_name, dynamic_params=None,
             include_last_known=False):
        config, connection, ledger = self._context()
        try:
            return al.run_operation(
                connection, config, ledger, op_name,
                dynamic_params=dynamic_params,
                include_last_known=include_last_known, env=self._env)
        finally:
            connection.close()

    # -- tools ------------------------------------------------------------

    def price(self, include_last_known: bool) -> Dict[str, Any]:
        """TaoSwap + CoinGecko ONLY — no TaoStats quota is ever spent on
        price checking (Q30 refinement, spec-pinned)."""
        config, connection, ledger = self._context()
        try:
            spot = al.run_operation(connection, config, ledger,
                                    "price_spot_coingecko",
                                    include_last_known=include_last_known,
                                    env=self._env)
            daily = al.run_operation(connection, config, ledger,
                                     "price_daily_taoswap",
                                     include_last_known=include_last_known,
                                     env=self._env)
            values = []
            for result in (spot, daily):
                if result["status"] == "ok":
                    values.append(result)
            if not values:
                return {"status": "live-unavailable",
                        "providers": {"coingecko_spot": spot,
                                      "taoswap_daily": daily},
                        "message": "no price provider is reachable — "
                                   "there is NO current price to report"}
            response: Dict[str, Any] = {
                "status": "ok",
                "prices": [{
                    "provider": item["provider"],
                    "kind": item["values"]["kind"],
                    "tao_usd": item["values"]["tao_usd"],
                    "upstream_timestamp": item["upstream_timestamp"],
                    "freshness_status": item["freshness_status"],
                } for item in values],
                "partial": len(values) < 2,
                "providers_failed": [name for name, result in
                                     (("coingecko_spot", spot),
                                      ("taoswap_daily", daily))
                                     if result["status"] != "ok"],
                "note": "Cite provider + timestamp per value. The "
                        "TaoSwap value is a daily close, not spot.",
            }
            if len(values) == 2:
                first = values[0]["values"]["tao_usd"]
                second = values[1]["values"]["tao_usd"]
                mean = (first + second) / 2.0
                deviation = abs(first - second) / mean if mean else 0.0
                tolerance = config["price_tolerance_pairwise"]
                response["pairwise_deviation"] = round(deviation, 4)
                response["tolerance"] = tolerance
                response["conflicting"] = deviation > tolerance
                if response["conflicting"]:
                    al.health_event(
                        connection, "price-comparison", "live_price",
                        "provider-disagreement",
                        "spot %.4f vs daily %.4f deviates %.2f%% > %.0f%%"
                        % (first, second, deviation * 100,
                           tolerance * 100))
                    response["note"] = (
                        "PROVIDERS DISAGREE beyond tolerance — report "
                        "BOTH values with their sources; do not pick or "
                        "average (ATLAS-LIVE-005).")
            return response
        finally:
            connection.close()

    def subnets(self, netuid, include_protocol_params,
                include_last_known) -> Dict[str, Any]:
        result = self._run("subnets_taoswap",
                           dynamic_params={"netuid": netuid}
                           if netuid is not None else None,
                           include_last_known=include_last_known)
        if (result["status"] == "ok" and include_protocol_params
                and netuid is not None):
            params = self._run("subnets_taostats",
                               dynamic_params={"netuid": netuid})
            result["protocol_params"] = params
        return result

    def metagraph(self, netuid, limit,
                  include_last_known) -> Dict[str, Any]:
        return self._run("metagraph_taostats",
                         dynamic_params={"netuid": netuid,
                                         "limit": limit or 10},
                         include_last_known=include_last_known)

    def network_stats(self, include_last_known) -> Dict[str, Any]:
        return self._run("network_stats_taoswap",
                         include_last_known=include_last_known)

    def chain_head(self, include_last_known) -> Dict[str, Any]:
        return self._run("chain_head_taostats",
                         include_last_known=include_last_known)

    def status(self) -> Dict[str, Any]:
        config, connection, ledger = self._context()
        try:
            events = connection.execute(
                "SELECT timestamp, provider, operation, category, detail "
                "FROM integration_health ORDER BY id DESC LIMIT 10"
            ).fetchall()
            last_ok = connection.execute(
                "SELECT provider, max(timestamp) FROM audit WHERE "
                "validation_result = 'valid' GROUP BY provider"
            ).fetchall()
            return {
                "status": "ok",
                "generated_at": _utc_now(),
                "quota": {provider: ledger.usage(provider)
                          for provider in config["providers"]},
                "last_valid_call": {provider: ts
                                    for provider, ts in last_ok},
                "recent_health_events": [
                    {"timestamp": ts, "provider": provider,
                     "operation": operation, "category": category,
                     "detail": detail}
                    for ts, provider, operation, category, detail
                    in events],
                "note": "window_remaining is a LOCAL estimate unless "
                        "provider_reported is present (ATLAS-LIVE-006).",
            }
        finally:
            connection.close()


class AuditLog:
    """Append-only, size-capped, redacted call log (ATLAS-TOOL-004)."""

    def __init__(self, path: str):
        self.path = path

    def record(self, tool: str, params: Dict[str, Any],
               outcome: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            if (os.path.exists(self.path)
                    and os.path.getsize(self.path) > AUDIT_MAX_BYTES):
                os.replace(self.path, self.path + ".1")
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "timestamp": _utc_now(),
                    "tool": tool,
                    "params": {key: str(value)[:120]
                               for key, value in (params or {}).items()},
                    "outcome": outcome,
                }) + "\n")
        except OSError:
            pass  # auditing must never break the tool path


def handle_tool_call(tools: LiveTools, audit: AuditLog, name: str,
                     arguments: Dict[str, Any]) -> Dict[str, Any]:
    include_last_known = bool(arguments.get("include_last_known"))
    try:
        if name == "live_price":
            payload = tools.price(include_last_known)
        elif name == "live_subnets":
            netuid = arguments.get("netuid")
            if netuid is not None and (not isinstance(netuid, int)
                                       or isinstance(netuid, bool)
                                       or netuid < 0):
                payload: Dict[str, Any] = structured_error(
                    "invalid", "netuid must be a non-negative integer",
                    retry_safe=False)
            else:
                payload = tools.subnets(
                    netuid, bool(arguments.get(
                        "include_protocol_params")), include_last_known)
        elif name == "live_metagraph":
            netuid = arguments.get("netuid")
            limit = arguments.get("limit")
            if not isinstance(netuid, int) or isinstance(netuid, bool) \
                    or netuid < 0:
                payload = structured_error(
                    "invalid", "netuid must be a non-negative integer",
                    retry_safe=False)
            else:
                if not isinstance(limit, int) or isinstance(limit, bool) \
                        or not 1 <= limit <= 25:
                    limit = None
                payload = tools.metagraph(netuid, limit,
                                          include_last_known)
        elif name == "live_network_stats":
            payload = tools.network_stats(include_last_known)
        elif name == "live_chain_head":
            payload = tools.chain_head(include_last_known)
        elif name == "live_status":
            payload = tools.status()
        else:
            payload = structured_error(
                "invalid", "unknown tool: %r (available: %s)"
                % (name, ", ".join(tool["name"] for tool in TOOLS)),
                retry_safe=False)
    except al.FatalLiveError as exc:
        payload = structured_error("unavailable", str(exc),
                                   retry_safe=False)
    except Exception as exc:  # never crash the tool path
        payload = structured_error("internal", "unexpected failure: %s"
                                   % exc, retry_safe=True)
    audit.record(name, arguments,
                 payload.get("status", "error")
                 if "error" not in payload else
                 payload["error"]["category"])
    return payload


def handle_message(tools: LiveTools, audit: AuditLog,
                   message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return None
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
            "serverInfo": {"name": SERVER_NAME,
                           "version": SERVER_VERSION},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS,
                          "tools/call needs a name and an arguments "
                          "object")
        payload = handle_tool_call(tools, audit, name, arguments)
        return _result(request_id, {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": "error" in payload,
        })
    if request_id is not None:
        return _error(request_id, METHOD_NOT_FOUND,
                      "method not supported: %s" % method)
    return None


def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def serve(config_path: str = al.CONFIG_FILE, stdin: Any = None,
          stdout: Any = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    tools = LiveTools(config_path)
    try:
        config = al.load_config(config_path)
        audit_dir = os.path.dirname(al.resolve(config["db"], _REPO_ROOT))
    except al.FatalLiveError:
        audit_dir = os.path.join(_REPO_ROOT, "var", "livedata")
    audit = AuditLog(os.path.join(audit_dir, AUDIT_FILE_NAME))
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
            response = (handle_message(tools, audit, message)
                        if isinstance(message, dict) else
                        _error(None, PARSE_ERROR,
                               "expected a JSON-RPC object"))
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    config_file = sys.argv[sys.argv.index("--config") + 1] \
        if "--config" in sys.argv else al.CONFIG_FILE
    serve(config_file)
