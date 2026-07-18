#!/usr/bin/env python3
"""Atlas live-data MCP server — fail-closed current Bittensor data.

Tools (ATLAS-TOOL-002/003/004, ATLAS-LIVE-001…008; gates of 2026-07-12,
widened 2026-07-15 for rich TaoSwap surfaces):

- live_price          — TAO/USD: CoinGecko spot + TaoSwap daily close,
                        cross-checked (5% tolerance); NEVER TaoStats (Q30)
- live_subnets        — TaoSwap subnet aggregates incl. emission_miner_burn
                        (0-100%), root_proportion, moving price, excess TAO,
                        flows, conviction/ownership; optional TaoStats
                        protocol params per netuid
- live_metagraph      — DEFAULT TaoSwap keyless metagraph (incentive /
                        emission / stake per neuron); optional source=taostats
- live_network_stats  — TaoSwap network snapshot
- live_chain_head     — TaoStats chain head incl. spec_version (conviction
                        enactment watch). Optional source=taoswap for block
                        head only (no spec_version).
- live_portfolio      — TaoSwap portfolio balance + PnL/APY for a coldkey (ss58 or aliases SECURE/5FART/CRUSTY)
- live_burn_leaderboard — TaoSwap miner-incentive burn ranking (0-100%)
- live_status         — integration health, per-provider quota, last calls

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
SERVER_VERSION = "0.2.1"
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
            "CURRENT Bittensor subnet state (TaoSwap, keyless): alpha "
            "price + moving_price, stake/pools, emission_percent, "
            "emission_miner_burn (0-100 percent of miner incentive "
            "withheld), emission_ema_percent, excess_tao_emission*, "
            "root_proportion, flows, active_miners, identity/github, "
            "dereg risk, and conviction/ownership status. Optional "
            "netuid filter; set include_protocol_params for TaoStats "
            "on-chain params (quota-budgeted)."),
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
            "CURRENT neuron detail for one subnet. DEFAULT source is "
            "TaoSwap (keyless): hotkeys, coldkeys, stake, incentive, "
            "emission, dividends, vtrust, daily rewards, validator/owner "
            "flags — sorted by emission desc. Optional source=taostats "
            "(quota-budgeted, thinner fields). Requires netuid."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "netuid": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": 64},
                "source": {"type": "string",
                           "enum": ["taoswap", "taostats"],
                           "description": "default taoswap (keyless)"},
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
            "CURRENT chain head. DEFAULT source=taostats (quota-budgeted): "
            "block number, timestamp, and runtime spec_version — "
            "spec_version >= 425 means conviction-based subnet ownership "
            "is enacted. source=taoswap is keyless block metadata only "
            "(no spec_version)."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "source": {"type": "string",
                           "enum": ["taostats", "taoswap"],
                           "description": "default taostats (has "
                                          "spec_version)"},
            }),
            "additionalProperties": False,
        },
    },
    {
        "name": "live_portfolio",
        "description": (
            "CURRENT coldkey portfolio from TaoSwap (keyless): balance "
            "history snapshot (rank, value_change, held_netuids, per-subnet "
            "holdings) and/or PnL+APY. account may be an ss58 coldkey OR a "
            "configured alias (SECURE, 5FART, CRUSTY). kind="
            "balance|pnl|both (default both). Public addresses only."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "account": {
                    "type": "string",
                    "description": "ss58 coldkey OR wallet alias "
                                   "(SECURE / 5FART / CRUSTY)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["balance", "pnl", "both"],
                    "description": "default both",
                },
            }),
            "required": ["account"],
            "additionalProperties": False,
        },
    },
    {
        "name": "live_burn_leaderboard",
        "description": (
            "CURRENT miner-incentive burn ranking from one TaoSwap "
            "/v2/subnets/ call (keyless). emission_miner_burn is 0-100 "
            "percent. Useful filters: min_burn, max_burn, only_enabled, "
            "exclude_full_burn (drop 100% burn parked subnets), limit "
            "(default 25). Also returns top zero-burn high-emission "
            "subnets for contrast."),
        "inputSchema": {
            "type": "object",
            "properties": dict(_LAST_KNOWN, **{
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": 128},
                "min_burn": {"type": "number", "minimum": 0,
                             "maximum": 100},
                "max_burn": {"type": "number", "minimum": 0,
                             "maximum": 100},
                "only_enabled": {"type": "boolean",
                                 "description": "only emission_is_enabled "
                                                "subnets"},
                "exclude_full_burn": {
                    "type": "boolean",
                    "description": "drop subnets with burn == 100 "
                                   "(default false)"},
            }),
            "additionalProperties": False,
        },
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

    def metagraph(self, netuid, limit, source,
                  include_last_known) -> Dict[str, Any]:
        source = (source or "taoswap").lower()
        if source == "taostats":
            # TaoStats path keeps historical limit max 25
            if limit is not None:
                limit = max(1, min(int(limit), 25))
            return self._run("metagraph_taostats",
                             dynamic_params={"netuid": netuid,
                                             "limit": limit or 10},
                             include_last_known=include_last_known)
        # TaoSwap keyless default
        if limit is not None:
            limit = max(1, min(int(limit), 64))
        return self._run("metagraph_taoswap",
                         dynamic_params={"netuid": netuid,
                                         "limit": limit or 25},
                         include_last_known=include_last_known)

    def network_stats(self, include_last_known) -> Dict[str, Any]:
        return self._run("network_stats_taoswap",
                         include_last_known=include_last_known)

    def chain_head(self, source, include_last_known) -> Dict[str, Any]:
        source = (source or "taostats").lower()
        if source == "taoswap":
            return self._run("blocks_taoswap",
                             include_last_known=include_last_known)
        return self._run("chain_head_taostats",
                         include_last_known=include_last_known)

    def portfolio(self, account: str, kind: str,
                  include_last_known: bool) -> Dict[str, Any]:
        kind = (kind or "both").lower()
        out: Dict[str, Any] = {
            "status": "ok",
            "account": account,
            "provider": "taoswap",
            "kind": kind,
            "note": "Public coldkey portfolio via TaoSwap (keyless). "
                    "Some amount fields may be in rao (1e9 rao = 1 TAO).",
        }
        failed = []
        if kind in ("balance", "both"):
            bal = self._run("portfolio_balance_taoswap",
                            dynamic_params={"account": account},
                            include_last_known=include_last_known)
            out["balance"] = bal
            if bal.get("status") != "ok":
                failed.append("balance")
        if kind in ("pnl", "both"):
            pnl = self._run("portfolio_pnl_apy_taoswap",
                            dynamic_params={"account": account},
                            include_last_known=include_last_known)
            out["pnl_apy"] = pnl
            if pnl.get("status") != "ok":
                failed.append("pnl")
        if failed and (
                (kind == "balance" and "balance" in failed)
                or (kind == "pnl" and "pnl" in failed)
                or (kind == "both" and len(failed) == 2)):
            out["status"] = "live-unavailable"
            out["message"] = "portfolio provider call(s) failed: %s" % (
                ", ".join(failed))
        elif failed:
            out["partial"] = True
            out["failed_parts"] = failed
        return out

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



    def burn_leaderboard(self, limit, min_burn, max_burn, only_enabled,
                         exclude_full_burn,
                         include_last_known) -> Dict[str, Any]:
        result = self._run("subnets_taoswap",
                           include_last_known=include_last_known)
        if result.get("status") != "ok":
            return result
        limit = max(1, min(int(limit or 25), 128))
        min_burn = 0.0 if min_burn is None else float(min_burn)
        max_burn = 100.0 if max_burn is None else float(max_burn)
        rows = []
        zero_burn_high = []
        for subnet in result["values"].get("subnets") or []:
            burn = subnet.get("emission_miner_burn")
            if burn is None:
                continue
            try:
                burn_f = float(burn)
            except (TypeError, ValueError):
                continue
            em = subnet.get("emission_percent")
            try:
                em_f = float(em) if em is not None else 0.0
            except (TypeError, ValueError):
                em_f = 0.0
            entry = {
                "netuid": subnet.get("netuid"),
                "name": subnet.get("name"),
                "emission_miner_burn": burn_f,
                "emission_percent": em_f,
                "emission_is_enabled": subnet.get("emission_is_enabled"),
                "active_miners": subnet.get("active_miners"),
                "root_proportion": subnet.get("root_proportion"),
                "moving_price_tao": subnet.get("moving_price_tao"),
                "alpha_price_tao": subnet.get("alpha_price_tao"),
            }
            if burn_f == 0 and em_f > 1.0:
                zero_burn_high.append(entry)
            if only_enabled and not subnet.get("emission_is_enabled"):
                continue
            if exclude_full_burn and burn_f >= 100.0:
                continue
            if not (min_burn <= burn_f <= max_burn):
                continue
            rows.append(entry)
        rows.sort(key=lambda r: (-r["emission_miner_burn"],
                                 -r["emission_percent"]))
        zero_burn_high.sort(key=lambda r: -r["emission_percent"])
        return {
            "status": "ok",
            "provider": result.get("provider"),
            "operation": "burn_leaderboard_from_subnets_taoswap",
            "request_completed": result.get("request_completed"),
            "block_reference": result.get("block_reference"),
            "units": "emission_miner_burn and emission_percent are 0-100",
            "validation_status": result.get("validation_status"),
            "freshness_status": result.get("freshness_status"),
            "values": {
                "leaderboard": rows[:limit],
                "count": min(len(rows), limit),
                "matched": len(rows),
                "filters": {
                    "limit": limit,
                    "min_burn": min_burn,
                    "max_burn": max_burn,
                    "only_enabled": bool(only_enabled),
                    "exclude_full_burn": bool(exclude_full_burn),
                },
                "zero_burn_high_emission": zero_burn_high[:10],
                "note": "Burn is miner incentive withheld (owner/immune "
                        "hotkey), not chain buys. 100% burn usually kills "
                        "network emission share via (1 - miner_burn).",
            },
        }

    def resolve_account(self, account_or_alias: str) -> Dict[str, Any]:
        """Resolve wallet alias from config.wallet_aliases or pass ss58."""
        raw = (account_or_alias or "").strip()
        config = al.load_config(self.config_path)
        aliases = config.get("wallet_aliases") or {}
        # allow case-insensitive alias match, skip underscore keys
        alias_map = {k.upper(): v for k, v in aliases.items()
                     if not str(k).startswith("_") and isinstance(v, dict)}
        hit = alias_map.get(raw.upper())
        if hit and hit.get("ss58"):
            return {
                "account": hit["ss58"],
                "alias": raw.upper() if raw.upper() in alias_map
                else next(k for k, v in aliases.items()
                          if isinstance(v, dict)
                          and v.get("ss58") == hit["ss58"]),
                "role": hit.get("role"),
                "ledger": hit.get("ledger"),
            }
        return {"account": raw, "alias": None}


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


def _valid_ss58(account: str) -> bool:
    if not isinstance(account, str):
        return False
    # Substrate ss58 is base58; Bittensor addresses commonly start with 5
    # and are 47–48 chars. Keep this a light structural check only.
    if not (40 <= len(account) <= 50):
        return False
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(ch in alphabet for ch in account)


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
            source = arguments.get("source") or "taoswap"
            if not isinstance(netuid, int) or isinstance(netuid, bool) \
                    or netuid < 0:
                payload = structured_error(
                    "invalid", "netuid must be a non-negative integer",
                    retry_safe=False)
            elif source not in ("taoswap", "taostats"):
                payload = structured_error(
                    "invalid", "source must be 'taoswap' or 'taostats'",
                    retry_safe=False)
            else:
                if not isinstance(limit, int) or isinstance(limit, bool) \
                        or not 1 <= limit <= 64:
                    limit = None
                payload = tools.metagraph(netuid, limit, source,
                                          include_last_known)
        elif name == "live_network_stats":
            payload = tools.network_stats(include_last_known)
        elif name == "live_chain_head":
            source = arguments.get("source") or "taostats"
            if source not in ("taostats", "taoswap"):
                payload = structured_error(
                    "invalid", "source must be 'taostats' or 'taoswap'",
                    retry_safe=False)
            else:
                payload = tools.chain_head(source, include_last_known)
        elif name == "live_portfolio":
            account_raw = arguments.get("account")
            kind = arguments.get("kind") or "both"
            resolved = tools.resolve_account(str(account_raw or ""))
            account = resolved["account"]
            if not _valid_ss58(account or ""):
                payload = structured_error(
                    "invalid",
                    "account must be an ss58 coldkey or known alias "
                    "(SECURE, 5FART, CRUSTY)",
                    retry_safe=False)
            elif kind not in ("balance", "pnl", "both"):
                payload = structured_error(
                    "invalid", "kind must be balance|pnl|both",
                    retry_safe=False)
            else:
                payload = tools.portfolio(str(account), kind,
                                          include_last_known)
                if isinstance(payload, dict) and resolved.get("alias"):
                    payload["alias"] = resolved["alias"]
                    payload["alias_role"] = resolved.get("role")
                    payload["alias_ledger"] = resolved.get("ledger")
        elif name == "live_burn_leaderboard":
            limit = arguments.get("limit")
            min_burn = arguments.get("min_burn")
            max_burn = arguments.get("max_burn")
            only_enabled = bool(arguments.get("only_enabled"))
            exclude_full = bool(arguments.get("exclude_full_burn"))
            if limit is not None and (
                    not isinstance(limit, int)
                    or isinstance(limit, bool)
                    or not 1 <= limit <= 128):
                payload = structured_error(
                    "invalid", "limit must be integer 1..128",
                    retry_safe=False)
            else:
                payload = tools.burn_leaderboard(
                    limit, min_burn, max_burn, only_enabled,
                    exclude_full, include_last_known)
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
