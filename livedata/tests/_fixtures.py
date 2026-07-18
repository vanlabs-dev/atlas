"""Fixture HTTP provider (stdlib http.server) replaying recorded,
schema-conformant responses — the ATLAS-API-005 controlled test path."""

import datetime
import http.server
import json
import os
import sys
import threading
from typing import Any, Dict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402


def _now_utc():
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _today():
    return _now_utc().strftime("%Y-%m-%d")


def payloads() -> Dict[str, Any]:
    """Valid canned responses per fixture path (match pinned schemas)."""
    now = _now_utc()
    return {
        "/api/v3/simple/price": {
            "bittensor": {"usd": 206.0,
                          "last_updated_at": int(now.timestamp()) - 60}},
        "/price-history/": {
            "currency": "USD",
            "results": [
                {"date": "2026-07-11", "price": 205.0, "volume": 1.0},
                {"date": _today(), "price": 204.0, "volume": 2.0}]},
        "/v2/subnets/": {
            "dereg_context": {"current_block": 8602000},
            "results": [
                {"id": 0, "name": "root", "symbol": None, "price": None,
                 "moving_price": None, "alpha_stake": None,
                 "emission_percent": None, "emission_miner_burn": None,
                 "emission_is_enabled": None, "root_proportion": None,
                 "conviction": None, "identity": None, "dereg": None},
                {"id": 1, "name": "Apex", "symbol": "APEX",
                 "price": 0.0085, "moving_price": 0.0084,
                 "alpha_stake": 100.5, "emission_percent": 2.5,
                 "emission_ema_percent": 2.4,
                 "emission_miner_burn": 10.5, "emission_value": 0.01,
                 "emission_is_enabled": True,
                 "excess_tao_emission": 0.001,
                 "excess_tao_emission_percent": 5.0,
                 "tao_in_emission": 0.008, "alpha_in_emission": 0.5,
                 "root_proportion": 0.15, "active_miners": 4,
                 "inflow": 0.1, "outflow": 0.05,
                 "root_in_pool": 1000.0, "alpha_in_pool": 2000.0,
                 "registration_cost": 0.0005, "tempo": 360,
                 "blocks_since_epoch": 10, "owner": "5H" + "d" * 46,
                 "identity": {"name": "Apex",
                              "github": "https://github.com/example/apex",
                              "url": "https://example.com",
                              "description": "test"},
                 "dereg": {"is_immune": False, "risk_level": "low",
                           "prune_rank": 10, "immunity_end_block": 1},
                 "conviction": {"king_is_owner": True,
                                "is_contested": False,
                                "takeover_eligible": False,
                                "takeover_enforced": False,
                                "gate_ceiling_pct": 1.2,
                                "total_locked_pct_supply": 3.4,
                                "holder_count": 10,
                                "owner_conviction_pct": 99.0}}]},
        "/metagraph/1/": {
            "subnet": {"id": 1, "name": "Apex", "symbol": "APEX",
                       "price": 0.0085, "emission_value": 0.01,
                       "registration_cost": 0.0005,
                       "blocks_since_epoch": 10, "tempo": 360,
                       "identity": {"ss58_address": "5H" + "d" * 46,
                                    "name": "Apex"}},
            "count": 2,
            "neurons": [
                {"uid": 0, "hotkey": "5A" + "e" * 46,
                 "coldkey": "5B" + "f" * 46, "stake": 100.0,
                 "incentive": 0.5, "emission": 10.0,
                 "emission_tao": 0.08, "emission_usd": 16.0,
                 "dividends": 0.4, "vtrust": 0.99, "consensus": 0.9,
                 "daily_rewards": 1.0, "daily_rewards_alpha": 2.0,
                 "daily_rewards_usd": 4.0, "delegate_take": 0.18,
                 "is_validator": True, "is_owner": False,
                 "status": "active", "type": "validator"},
                {"uid": 1, "hotkey": "5C" + "g" * 46,
                 "coldkey": "5D" + "h" * 46, "stake": 50.0,
                 "incentive": 0.9, "emission": 20.0,
                 "emission_tao": 0.16, "emission_usd": 32.0,
                 "dividends": 0.0, "vtrust": 0.0, "consensus": 0.1,
                 "daily_rewards": 2.0, "daily_rewards_alpha": 3.0,
                 "daily_rewards_usd": 6.0, "delegate_take": 0.0,
                 "is_validator": False, "is_owner": False,
                 "status": "active", "type": "miner"}]},
        "/blocks/": {
            "results": {
                "8602147": {
                    "id": 8602147,
                    "hash": "0x" + "a" * 64,
                    "parent_hash": "0x" + "b" * 64,
                    "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "extrinsics_count": 12, "events_count": 100,
                    "is_final": True}},
            "pagination": {"page": 1, "page_size": 1, "has_next": True,
                           "has_previous": False, "total_count": 8602147,
                           "total_pages": 100}},
        "/portfolio-balance/": {
            "account_known": True, "coldkey_swap": None,
            "rank": {"rank": 100, "rank_alpha": 50,
                     "total_accounts": 1000, "as_of": _today()},
            "value_change": {"as_of": _today(),
                             "24h": {"tao_pct": 1.0, "usd_pct": 0.5}},
            "subnet_value_change": {"as_of": _today(), "baselines": {}},
            "held_netuids": [1, 93],
            "results": [{"netuid": 1, "alpha": 10.0}]},
        "/portfolio-pnl-apy/": {
            "account_known": True,
            "as_of": now.isoformat(),
            "apy": {"alpha": {"7d": 10.0, "30d": 20.0},
                    "tao": {"7d": 1.0, "30d": 2.0}},
            "pnl": {"realized": {"tao": {"wac": 1}},
                    "unrealized": {"tao": {"wac": 2}}}},
        "/v2/validators/": {
            "results": [
                {"validator_hotkey": "5F" + "a" * 46,
                 "validator_coldkey": "5G" + "b" * 46,
                 "total_stake": "1000.5", "take": 0.18, "apy_7d": 0.09,
                 "dominance": "0.1", "count_delegators": 5,
                 "identity": {"name": "TestVal"}},
                {"validator_hotkey": "5H" + "c" * 46,
                 "validator_coldkey": None, "total_stake": "2000.0",
                 "take": 0.1, "apy_7d": 0.11, "dominance": "0.2",
                 "count_delegators": 9, "identity": None}]},
        "/network-stats/": {
            "date": _today(), "total_staked_tao": 7385095.3,
            "available_tao": 3727919.5, "root_stake_tao": 5382923.3,
            "subnets_stake_tao": 2002172.0, "subnets_share_pct": 27.11,
            "sum_alpha_price": 1.41, "subnet_reg_cost_tao": 1251.8,
            "total_accounts": 100, "new_accounts_today": 2},
        "/api/subnet/latest/v1": {
            "pagination": {"current_page": 1},
            "data": [{"netuid": 1, "block_number": 8602000,
                      "owner": {"ss58": "5H" + "d" * 46, "hex": "0x1"},
                      "emission": "1", "kappa": 32767,
                      "immunity_period": 5000, "activity_cutoff": 5000,
                      "active_validators": 64, "active_miners": 192,
                      "active_keys": 256, "max_neurons": 256,
                      "neuron_registration_cost": "500000"}]},
        "/api/metagraph/latest/v1": {
            "pagination": {"current_page": 1},
            "data": [{"hotkey": {"ss58": "5A" + "e" * 46, "hex": "0x2"},
                      "coldkey": {"ss58": "5B" + "f" * 46, "hex": "0x3"},
                      "block_number": 8602000, "active": True,
                      "alpha_stake": "123000000000",
                      "daily_reward": "456000000",
                      "incentive": "0", "dividends": "0",
                      "is_owner_hotkey": False,
                      "is_immunity_period": False}]},
        "/api/block/v1": {
            "pagination": {"current_page": 1},
            "data": [{"block_number": 8602147, "spec_version": 424,
                      "spec_name": "node-subtensor",
                      "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "hash": "0x" + "d" * 64, "events_count": 1,
                      "extrinsics_count": 1}]},
        "/api/subnet/identity/v1": {
            "pagination": {"current_page": 1, "next_page": None,
                           "prev_page": None, "per_page": 200,
                           "total_items": 2, "total_pages": 1},
            "data": [
                {"netuid": 0, "subnet_name": "Root", "github_repo": None,
                 "subnet_url": None, "discord": None, "description": None,
                 "logo_url": None, "subnet_contact": None, "additional": None,
                 "summary": None, "tags": None, "twitter": None},
                {"netuid": 1, "subnet_name": "Apex",
                 "github_repo": "https://github.com/macrocosm-os/apex",
                 "subnet_url": "https://macrocosmos.ai", "discord": "",
                 "description": "d", "logo_url": "l", "subnet_contact": "",
                 "additional": None, "summary": "s", "tags": ["ai"],
                 "twitter": "@macrocosmos"}]},
    }


class FixtureProvider:
    """Threaded HTTP server; per-path override + request counting."""

    def __init__(self):
        self.routes: Dict[str, Any] = payloads()
        self.overrides: Dict[str, Any] = {}
        self.request_counts: Dict[str, int] = {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = self.path.split("?", 1)[0]
                outer.request_counts[path] = \
                    outer.request_counts.get(path, 0) + 1
                override = outer.overrides.get(path)
                if override is not None:
                    status, body = override
                else:
                    payload = outer.routes.get(path)
                    if payload is None:
                        status, body = 404, b'{"detail": "not found"}'
                    else:
                        status, body = 200, json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # silence
                pass

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%d" % self.server.server_port

    def set_override(self, path, status, body=b"{}"):
        self.overrides[path] = (status, body)

    def clear_override(self, path):
        self.overrides.pop(path, None)

    def count(self, path):
        return self.request_counts.get(path, 0)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def make_config(tmp_dir: str, base_url: str,
                **overrides: Any) -> Dict[str, Any]:
    config = {
        "providers": {
            "taoswap": {"base_url": base_url, "auth": "none",
                        "quota": {"per_minute_cap": 100,
                                  "min_spacing_seconds": 0.0}},
            "taostats": {"base_url": base_url, "auth": "header",
                         "auth_header": "Authorization",
                         "key_env": "TAOSTATS_API_KEY",
                         "quota": {"per_minute_cap": 100,
                                   "window_kind": "month",
                                   "window_limit": 10000,
                                   "interactive_reserve_fraction": 0.8,
                                   "min_spacing_seconds": 0.0}},
            "coingecko": {"base_url": base_url, "auth": "none",
                          "quota": {"per_minute_cap": 100,
                                    "min_spacing_seconds": 0.0}},
        },
        "db": os.path.join(tmp_dir, "livedata.db"),
        "output_dir": tmp_dir,
        "cache_max_rows": 50,
        "request_timeout_seconds": 5,
        "retry": {"default_attempts": 2,
                  "retry_on_status": [500, 502, 503, 504],
                  "never_retry_on_status": [429],
                  "jitter_seconds": [0.0, 0.0]},
        "price_tolerance_pairwise": 0.05,
    }
    real = al.load_config(al.CONFIG_FILE)
    config["operations"] = real["operations"]
    config.update(overrides)
    return config


def write_config(tmp_dir: str, config: Dict[str, Any]) -> str:
    path = os.path.join(tmp_dir, "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle)
    return path


TEST_KEY = "fixture-taostats-key-0123456789abcdef"
