#!/usr/bin/env python3
"""TaoStats contract discovery (tasks 4.1/4.2 — ATLAS-API-002…005,
ATLAS-LIVE-006).

Keyed provider, discovered SECOND under a HARD budget sized to the free
tier: at most {MAX_CALLS} calls, paced through the persisted quota
ledger (self-cap 2/min, 15s spacing). Covers the four Q25 candidate
endpoints with second samples, safe negative tests (missing/invalid
auth, bad param, nonexistent resource), records rate-limit headers, and
attempts to confirm the free-tier window (day vs month). The report
DOUBLES as the Q25/Q27 comparison: what does keyed TaoStats add over
keyless TaoSwap? — the operator picks the endpoint set from it
(gate 4.3).

Run on the Pi (where the key lives):
    python3 livedata/discover_taostats.py \
        [--taoswap-report var/livedata/contract-taoswap-<run>.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import atlas_live as al
import discovery_common as dc

PROVIDER = "taostats"
MAX_CALLS = 40  # hard ceiling; the plan below spends far less


def discover(taoswap_report_path: Optional[str]) -> int:
    config = al.load_config()
    key = al.provider_key(config, PROVIDER)
    auth = {config["providers"][PROVIDER]["auth_header"]: key}
    session = dc.DiscoverySession(config, PROVIDER, max_calls=MAX_CALLS,
                                  headers=auth)
    rid = al.run_id()
    try:
        # -- the four Q25 candidates (one call + one variant sample each)
        session.probe("price-latest", "/api/price/latest/v1",
                      params={"asset": "tao"}, timeout=45,
                      note="discovery-only: production price checking "
                           "spends NO TaoStats quota (Q30 refinement); "
                           "45s timeout — first run timed out at 20s")
        session.probe("subnets-latest", "/api/subnet/latest/v1",
                      params={"limit": 5})
        session.probe("subnets-latest-one", "/api/subnet/latest/v1",
                      params={"netuid": 1},
                      note="single-subnet shape sample (ATLAS-API-004)")
        session.probe("metagraph-latest", "/api/metagraph/latest/v1",
                      params={"netuid": 1, "limit": 5})
        session.probe("blocks", "/api/block/v1", params={"limit": 1},
                      note="chain-head freshness anchor; check for "
                           "spec_version/runtime fields (conviction "
                           "enactment bonus)")
        session.probe("blocks-page2", "/api/block/v1",
                      params={"limit": 1, "page": 2},
                      note="pagination sample")

        # -- safe negative tests (ATLAS-API-005): auth + params
        session.probe("missing-auth", "/api/price/latest/v1",
                      params={"asset": "tao"},
                      headers={config["providers"][PROVIDER]
                               ["auth_header"]: ""},
                      expect="error", note="missing authentication")
        session.probe("invalid-auth", "/api/price/latest/v1",
                      params={"asset": "tao"},
                      headers={config["providers"][PROVIDER]
                               ["auth_header"]: "invalid-key-test"},
                      expect="error", note="invalid authentication")
        session.probe("invalid-param", "/api/price/latest/v1",
                      params={"asset": "not-an-asset"}, expect="error",
                      note="invalid parameter value")
        session.probe("nonexistent-resource",
                      "/api/metagraph/latest/v1",
                      params={"netuid": 99999}, expect="error",
                      note="nonexistent netuid")

        window_evidence = _window_evidence(session.rate_headers_seen)
        rate_behavior = (
            "Provider-stated free tier: 5/min and 10,000 per "
            "day-or-month (operator says day; PRD input says month — "
            "see window evidence: %s). Self-cap in force: %d/min with "
            "%.0fs spacing — headroom by design, never filling 5/min "
            "(operator refinement 2026-07-12). Rate headers observed: %s"
            % (window_evidence,
               config["providers"][PROVIDER]["quota"]["per_minute_cap"],
               config["providers"][PROVIDER]["quota"]
               ["min_spacing_seconds"],
               json.dumps(session.rate_headers_seen) or "none"))

        comparison = _compare(session.observations, taoswap_report_path)

        report = {
            "run_id": rid,
            "provider": PROVIDER,
            "generated_at": al._utc_now(),
            "base_url": config["providers"][PROVIDER]["base_url"],
            "auth": "Authorization header (key from .env, redacted "
                    "everywhere)",
            "calls_spent": session.calls_made,
            "budget": MAX_CALLS,
            "rate_behavior": rate_behavior,
            "rate_headers_seen": session.rate_headers_seen,
            "window_evidence": window_evidence,
            "checklist": {
                "canonical_base_url": config["providers"][PROVIDER]
                ["base_url"],
                "tls": "HTTPS enforced by client",
                "authentication": "key sent via the Authorization "
                                  "request header (loaded from .env; "
                                  "redacted everywhere) — missing/"
                                  "invalid behavior in negative "
                                  "observations",
                "required_headers": "Authorization + User-Agent + Accept",
                "success_status": "200 observed",
                "error_status": "see negative-test observations",
                "response_content_type": "application/json; responses "
                                         "wrapped in {pagination, data}",
                "schema_source": "docs.taostats.io + observed samples "
                                 "(shapes recorded per endpoint)",
                "pagination": "pagination envelope observed (page-based)",
                "units": "amounts in rao (1 TAO = 1e9 rao) — adapters "
                         "must convert and carry units explicitly",
                "timestamps": "per-endpoint timestamp fields recorded in "
                              "shapes",
                "block_reference": "block endpoint provides "
                                   "block_number; others as observed",
                "timeout_behavior": "%ds client timeout; failures fail "
                                    "closed" % config[
                                        "request_timeout_seconds"],
                "storage_terms": "UNKNOWN pending terms review; Q29 "
                                 "minimal retention applies regardless",
            },
            "observations": session.observations,
            "proposed_envelopes": _propose_envelopes(session),
            "comparison": comparison,
            "gate_items": [
                "Pick the TaoStats endpoint set from the comparison "
                "(may be smaller than the four candidates; price is "
                "already excluded from production per Q30)",
                "Approve the proposed freshness envelopes for the "
                "chosen set",
                "Confirm the quota window (day vs month) from the "
                "evidence above; the ledger takes either",
                "Approve the per-minute self-cap value (config "
                "proposes 2/min)",
            ],
        }
        path = dc.write_report(config, PROVIDER, report)
        print("TaoStats discovery: %d/%d calls, report: %s"
              % (session.calls_made, MAX_CALLS, path))
        failures = [obs for obs in session.observations
                    if obs["expectation"] == "success" and not obs["ok"]]
        for obs in failures:
            print("  UNEXPECTED FAILURE: %s (%s)" % (obs["name"],
                                                     obs["status"]))
        return 0 if not failures else 1
    finally:
        session.close()


def _window_evidence(rate_headers: Dict[str, str]) -> str:
    hints = [key for key in rate_headers
             if "day" in key.lower() or "month" in key.lower()]
    if hints:
        return "header hints: %s" % ", ".join(
            "%s=%s" % (key, rate_headers[key]) for key in hints)
    return ("no day/month-scoped header observed — window kind stays at "
            "the stricter 'month' reading until documentation confirms "
            "(gate 4.3)")


def _propose_envelopes(session: dc.DiscoverySession) -> Dict[str, Any]:
    by_name = {obs["name"]: obs for obs in session.observations}
    proposals: Dict[str, Any] = {}
    if by_name.get("subnets-latest", {}).get("ok"):
        proposals["subnets_taostats"] = {
            "must_hit_provider": True,
            "expected_cadence": "near-live (latest endpoints)",
            "max_upstream_age_s": 3600, "max_local_age_s": 60,
            "status": "PROPOSED"}
    if by_name.get("metagraph-latest", {}).get("ok"):
        proposals["metagraph_taostats"] = {
            "must_hit_provider": True, "expected_cadence": "per-epoch",
            "max_upstream_age_s": 3600, "max_local_age_s": 60,
            "status": "PROPOSED"}
    if by_name.get("blocks", {}).get("ok"):
        proposals["chain_head"] = {
            "must_hit_provider": True,
            "expected_cadence": "~12s block cadence",
            "max_upstream_age_s": 120, "max_local_age_s": 60,
            "status": "PROPOSED"}
    return proposals


def _compare(observations: List[Dict[str, Any]],
             taoswap_report_path: Optional[str]) -> List[str]:
    """Factual side-by-side: what does keyed TaoStats add over keyless
    TaoSwap, per data category? Field-level, from observed shapes."""
    taoswap: Dict[str, Any] = {}
    if taoswap_report_path:
        try:
            with open(taoswap_report_path, "r",
                      encoding="utf-8") as handle:
                report = json.load(handle)
            taoswap = {obs["name"]: obs
                       for obs in report.get("observations", [])}
        except (OSError, ValueError) as exc:
            return ["taoswap report unreadable (%s) — comparison "
                    "deferred" % exc]
    by_name = {obs["name"]: obs for obs in observations}
    lines: List[str] = []

    def fields(obs: Optional[Dict[str, Any]]) -> set:
        if not obs or not isinstance(obs.get("shape"), dict):
            return set()
        shape = obs["shape"]
        # unwrap {pagination, data} / {results} envelopes
        for wrapper in ("data", "results"):
            inner = shape.get(wrapper)
            if isinstance(inner, list) and len(inner) > 1 \
                    and isinstance(inner[1], dict):
                return set(inner[1])
            if isinstance(inner, dict):
                return set(inner)
        return set(shape)

    pairs = [
        ("price", "price-latest", "price-history",
         "NOTE: production price checking uses TaoSwap+CoinGecko only "
         "(Q30) — this row informs the comparison, not an adapter"),
        ("subnets", "subnets-latest", "subnets-v2-list", ""),
        ("metagraph/validators", "metagraph-latest", "metagraph", ""),
        ("chain head", "blocks", "blocks", ""),
    ]
    for label, ts_name, tw_name, note in pairs:
        ts_fields = fields(by_name.get(ts_name))
        tw_fields = fields(taoswap.get(tw_name))
        added = sorted(ts_fields - tw_fields)
        lines.append(
            "%s: TaoStats-only fields vs TaoSwap: %s%s"
            % (label, ", ".join(added[:20]) if added else
               "(none observed — TaoSwap covers the category)",
               " — " + note if note else ""))
    return lines


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--taoswap-report", default=None,
                        help="path to the TaoSwap contract JSON for the "
                             "comparison section")
    args = parser.parse_args()
    try:
        sys.exit(discover(args.taoswap_report))
    except al.FatalLiveError as exc:
        print("FATAL: %s" % al.redact(str(exc)), file=sys.stderr)
        sys.exit(1)
