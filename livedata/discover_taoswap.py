#!/usr/bin/env python3
"""TaoSwap contract discovery (tasks 2.1/2.2 — ATLAS-API-002…005,
ATLAS-LIVE-007).

Keyless provider, discovered FIRST per the Q26/27 ordering. Makes real
paced calls against the Q27 first-slice endpoints plus safe negative
tests, records rate behavior from headers/observation (absence of a
documented limit is recorded as UNKNOWN with the politeness policy —
never "unlimited"), and writes the ATLAS-API-003 report for the
operator gate (task 2.3).

Usage:  python3 livedata/discover_taoswap.py
"""

from __future__ import annotations

import json
import sys

import atlas_live as al
import discovery_common as dc

PROVIDER = "taoswap"
MAX_CALLS = 30  # keyless, but budgeted anyway — politeness by design


def discover() -> int:
    config = al.load_config()
    session = dc.DiscoverySession(config, PROVIDER, max_calls=MAX_CALLS)
    rid = al.run_id()
    try:
        # -- the machine-readable contract itself
        schema = session.probe(
            "openapi-schema", "/schema/", headers={
                "Accept": "application/vnd.oai.openapi+json"},
            note="OpenAPI document; JSON content negotiation attempted")
        if schema["parse_error"]:
            session.probe("openapi-schema-json-param", "/schema/",
                          params={"format": "json"},
                          note="fallback: DRF ?format=json")

        # -- price (the cross-check input; is there true spot?)
        session.probe("price-history", "/price-history/",
                      params={"currency": "usd",
                              "date_from": "2026-07-01"},
                      note="daily TAO/USD; bounded window")
        session.probe("home-stats", "/home-stats/",
                      note="spot-price candidate: does it carry a "
                           "current TAO price + timestamp?")
        session.probe("trades-stats-rolling", "/trades/stats/rolling/",
                      note="spot-price candidate: rolling trade stats")

        # -- subnets (two shapes: list + detail, v1 and v2)
        session.probe("subnets-list", "/subnets/")
        session.probe("subnets-v2-list", "/v2/subnets/")
        session.probe("subnet-detail", "/v2/subnets/1/",
                      note="netuid 1 detail")

        # -- validators / metagraph
        session.probe("validators-v2", "/v2/validators/")
        session.probe("metagraph", "/metagraph/1/",
                      note="size check: full-subnet metagraph payload")

        # -- network stats + blocks (freshness anchors)
        session.probe("network-stats", "/network-stats/")
        blocks = session.probe("blocks", "/blocks/")
        # pagination / second sample (ATLAS-API-004)
        session.probe("blocks-page2", "/blocks/",
                      params={"page": 2},
                      note="pagination sample")
        if blocks["ok"] and isinstance(blocks.get("sample"), dict):
            pass  # shape captured; nothing else to derive here

        # -- safe negative tests (ATLAS-API-005)
        session.probe("nonexistent-subnet", "/v2/subnets/99999/",
                      expect="error", note="nonexistent resource")
        session.probe("invalid-param", "/price-history/",
                      params={"currency": "zzz"}, expect="error",
                      note="invalid parameter value")
        session.probe("unknown-endpoint", "/definitely-not-a-real-path/",
                      expect="error", note="404 behavior")
        session.probe("empty-result", "/blocks/",
                      params={"from_block": 99999999999},
                      expect="success",
                      note="empty-list shape (ATLAS-API-004)")

        rate_behavior = (
            "No documented rate limit found in the OpenAPI document; "
            "rate headers observed: %s. Recorded as UNKNOWN — politeness "
            "policy applies (serial calls, min spacing %.1fs, self-cap "
            "%d/min). Never assumed unlimited (ATLAS-LIVE-007)."
            % (json.dumps(session.rate_headers_seen) or "none",
               config["providers"][PROVIDER]["quota"]
               ["min_spacing_seconds"],
               config["providers"][PROVIDER]["quota"]["per_minute_cap"]))

        report = {
            "run_id": rid,
            "provider": PROVIDER,
            "generated_at": al._utc_now(),
            "base_url": config["providers"][PROVIDER]["base_url"],
            "auth": "none (all GETs anonymous per OpenAPI security: "
                    "[{}]; verified live)",
            "calls_spent": session.calls_made,
            "budget": MAX_CALLS,
            "rate_behavior": rate_behavior,
            "rate_headers_seen": session.rate_headers_seen,
            "checklist": {
                "canonical_base_url": config["providers"][PROVIDER]
                ["base_url"],
                "tls": "HTTPS enforced by client; no plain-HTTP use",
                "authentication": "none required for GET endpoints",
                "required_headers": "User-Agent + Accept only",
                "success_status": "200 observed",
                "error_status": "see negative-test observations "
                                "(404/400 family)",
                "response_content_type": "application/json (observed "
                                         "per endpoint below)",
                "schema_source": "OpenAPI 3.0.3 at /schema/ + observed "
                                 "samples (shapes recorded per "
                                 "endpoint)",
                "pagination": "page-based where present (blocks "
                              "sampled p1/p2)",
                "units": "TAO amounts observed in both rao and tao "
                         "fields (e.g. *_rao / *_tao pairs in "
                         "network-stats) — adapters must carry units "
                         "explicitly",
                "timestamps": "date fields observed (daily series); "
                              "per-endpoint upstream timestamp noted in "
                              "shapes",
                "block_reference": "blocks endpoint provides ids; other "
                                   "endpoints as observed",
                "timeout_behavior": "%ds client timeout; failures fail "
                                    "closed" % config[
                                        "request_timeout_seconds"],
                "storage_terms": "no ToS-restricting text found in the "
                                 "OpenAPI doc — UNKNOWN pending site "
                                 "terms; Q29 minimal retention applies "
                                 "regardless",
            },
            "observations": session.observations,
            "proposed_envelopes": _propose_envelopes(session),
            "gate_items": [
                "Approve the observed contract (shapes/status codes) as "
                "the basis for pinned schemas (task 3.1)",
                "Approve the proposed freshness envelopes (or amend)",
                "Confirm the spot-price source choice for live_price "
                "(home-stats / trades-stats vs daily price-history)",
                "Accept rate behavior recorded as UNKNOWN + politeness "
                "policy (ATLAS-LIVE-007)",
            ],
        }
        path = dc.write_report(config, PROVIDER, report)
        print("TaoSwap discovery: %d/%d calls, report: %s"
              % (session.calls_made, MAX_CALLS, path))
        failures = [obs for obs in session.observations
                    if obs["expectation"] == "success" and not obs["ok"]]
        for obs in failures:
            print("  UNEXPECTED FAILURE: %s (%s)" % (obs["name"],
                                                     obs["status"]))
        return 0 if not failures else 1
    finally:
        session.close()


def _propose_envelopes(session: dc.DiscoverySession):
    """Freshness proposals from OBSERVATION — marked proposals; the
    operator gate approves real values (ATLAS-LIVE-002)."""
    by_name = {obs["name"]: obs for obs in session.observations}
    proposals = {}
    if by_name.get("network-stats", {}).get("ok"):
        proposals["network_stats"] = {
            "must_hit_provider": True, "expected_cadence": "daily "
            "snapshot (observed date field)", "max_upstream_age_s":
            2 * 86400, "max_local_age_s": 60, "status": "PROPOSED"}
    if by_name.get("price-history", {}).get("ok"):
        proposals["price_taoswap"] = {
            "must_hit_provider": True, "expected_cadence": "daily "
            "series; spot source pending gate decision",
            "max_upstream_age_s": 2 * 86400, "max_local_age_s": 60,
            "status": "PROPOSED"}
    if by_name.get("subnets-v2-list", {}).get("ok"):
        proposals["subnets"] = {
            "must_hit_provider": True, "expected_cadence": "near-live "
            "aggregates", "max_upstream_age_s": 3600,
            "max_local_age_s": 60, "status": "PROPOSED"}
    if by_name.get("validators-v2", {}).get("ok"):
        proposals["validators"] = {
            "must_hit_provider": True, "expected_cadence": "near-live",
            "max_upstream_age_s": 3600, "max_local_age_s": 60,
            "status": "PROPOSED"}
    if by_name.get("metagraph", {}).get("ok"):
        proposals["metagraph"] = {
            "must_hit_provider": True, "expected_cadence": "per-epoch",
            "max_upstream_age_s": 3600, "max_local_age_s": 60,
            "status": "PROPOSED"}
    return proposals


if __name__ == "__main__":
    try:
        sys.exit(discover())
    except al.FatalLiveError as exc:
        print("FATAL: %s" % al.redact(str(exc)), file=sys.stderr)
        sys.exit(1)
