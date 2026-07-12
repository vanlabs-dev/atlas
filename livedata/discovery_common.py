#!/usr/bin/env python3
"""Shared contract-discovery helpers (ATLAS-API-003/004/005).

Discovery OBSERVES: it records status codes, headers, timing, and the
shape of real responses. It never invents schema or freshness values —
it proposes them for the operator gate, marked as proposals.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

import atlas_live as al


def shape_of(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Compact type-shape of an observed JSON value."""
    if depth >= max_depth:
        return "..."
    if isinstance(value, dict):
        return {key: shape_of(item, depth + 1)
                for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        if not value:
            return ["<empty>"]
        return ["len=%d" % len(value), shape_of(value[0], depth + 1)]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str(%d)" % len(value)
    return type(value).__name__


class DiscoverySession:
    """Paced probe runner writing per-call observations."""

    def __init__(self, config: Dict[str, Any], provider: str,
                 repo_root: Optional[str] = None,
                 max_calls: Optional[int] = None,
                 headers: Optional[Dict[str, str]] = None):
        self.config = config
        self.provider = provider
        self.headers = headers or {}
        self.max_calls = max_calls
        self.calls_made = 0
        self.rate_headers_seen: Dict[str, str] = {}
        self.observations: List[Dict[str, Any]] = []
        root = repo_root or al._REPO_ROOT
        self.connection = al.open_store(al.resolve(config["db"], root))
        self.ledger = al.QuotaLedger(self.connection, config)

    def probe(self, name: str, path: str,
              params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None,
              expect: str = "success",
              note: str = "",
              timeout: Optional[float] = None) -> Dict[str, Any]:
        """One observed call. `expect` is 'success' or 'error' (safe
        negative tests). Respects the provider budget hard."""
        if self.max_calls is not None and self.calls_made >= self.max_calls:
            raise al.FatalLiveError(
                "discovery budget exhausted (%d calls) — refusing to "
                "continue (ATLAS-API-005: never risk quota/abuse limits)"
                % self.max_calls)
        while True:
            refusal = self.ledger.acquire(self.provider, interactive=True)
            if refusal is None:
                break
            if refusal["category"] != "paced":
                raise al.FatalLiveError("ledger refuses discovery call: %s"
                                        % refusal["message"])
            time.sleep(1.0)
        self.calls_made += 1
        merged_headers = dict(self.headers)
        merged_headers.update(headers or {})
        result = al.http_get(self.config, self.provider, path,
                             params=params, headers=merged_headers,
                             timeout=timeout)
        self.ledger.record_reported_limits(self.provider,
                                           result.get("headers", {}))
        for key, value in result.get("headers", {}).items():
            lowered = key.lower()
            if ("limit" in lowered or "quota" in lowered
                    or "remaining" in lowered or "retry" in lowered):
                self.rate_headers_seen[key] = str(value)[:100]
        body = result.get("body") or b""
        parsed: Any = None
        parse_error = None
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                parse_error = str(exc)[:120]
        observation = {
            "name": name,
            "path": path,
            "params": {k: v for k, v in (params or {}).items()},
            "expectation": expect,
            "status": result.get("status"),
            "ok": result["ok"],
            "elapsed_s": result.get("elapsed_s"),
            "attempts": result.get("attempts"),
            "content_type": result.get("headers", {}).get(
                "Content-Type", result.get("headers", {}).get(
                    "content-type")),
            "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest() if body
            else None,
            "parse_error": parse_error,
            "shape": shape_of(parsed) if parsed is not None else None,
            "sample": _bounded_sample(parsed),
            "note": note,
            "error": result.get("error"),
        }
        self.observations.append(observation)
        return observation

    def close(self) -> None:
        self.connection.close()


def _bounded_sample(parsed: Any) -> Any:
    """A tiny redacted sample for the report — first item of lists,
    truncated strings; never the full body (Q29)."""
    if parsed is None:
        return None

    def bound(value: Any, depth: int = 0) -> Any:
        if depth >= 4:
            return "..."
        if isinstance(value, dict):
            return {key: bound(item, depth + 1)
                    for key, item in list(value.items())[:15]}
        if isinstance(value, list):
            return [bound(value[0], depth + 1)] if value else []
        if isinstance(value, str) and len(value) > 60:
            return value[:57] + "..."
        return value

    return bound(parsed)


def write_report(config: Dict[str, Any], provider: str,
                 report: Dict[str, Any],
                 repo_root: Optional[str] = None) -> str:
    root = repo_root or al._REPO_ROOT
    output_dir = al.resolve(config["output_dir"], root)
    os.makedirs(output_dir, exist_ok=True)
    # redact string values inside the tree, never the serialized JSON —
    # a redaction pattern spanning a closing quote corrupts the document
    report = al.redact_tree(report)
    path = os.path.join(output_dir, "contract-%s-%s.json"
                        % (provider, report["run_id"]))
    al.write_private(path, json.dumps(report, indent=2, sort_keys=True))
    md_path = path[:-5] + ".md"
    al.write_private(md_path, render_report(report))
    return md_path


def render_report(report: Dict[str, Any]) -> str:
    lines = [
        "# Contract discovery — %s (%s)" % (report["provider"],
                                            report["run_id"]),
        "",
        "- Generated: %s · calls spent: %d%s" % (
            report["generated_at"], report["calls_spent"],
            " / budget %d" % report["budget"]
            if report.get("budget") else ""),
        "- Base URL: %s" % report["base_url"],
        "- Auth: %s" % report["auth"],
        "- Rate behavior: %s" % report["rate_behavior"],
        "",
        "## ATLAS-API-003 checklist",
        "",
    ]
    for key, value in sorted(report["checklist"].items()):
        lines.append("- **%s**: %s" % (key, value))
    lines += ["", "## Endpoint observations", ""]
    for obs in report["observations"]:
        lines.append("### %s — `%s` (%s)" % (
            obs["name"], obs["path"],
            "ok" if obs["ok"] else "status %s" % obs["status"]))
        lines.append("")
        lines.append("- expectation: %s · status: %s · %.3fs · %d bytes"
                     % (obs["expectation"], obs["status"],
                        obs["elapsed_s"] or -1, obs["body_bytes"]))
        if obs.get("note"):
            lines.append("- note: %s" % obs["note"])
        if obs.get("shape") is not None:
            lines.append("- shape: `%s`"
                         % json.dumps(obs["shape"])[:400])
        if obs.get("sample") is not None:
            lines.append("- sample: `%s`"
                         % json.dumps(obs["sample"])[:400])
        lines.append("")
    if report.get("proposed_envelopes"):
        lines += ["## Proposed freshness envelopes (operator gate)", ""]
        for op, envelope in sorted(report["proposed_envelopes"].items()):
            lines.append("- **%s**: %s" % (op, json.dumps(envelope)))
        lines.append("")
    if report.get("comparison"):
        lines += ["## Comparison vs TaoSwap (Q25/Q27)", ""]
        for line in report["comparison"]:
            lines.append("- %s" % line)
        lines.append("")
    lines += ["## Open items for the operator gate", ""]
    for item in report["gate_items"]:
        lines.append("- [ ] %s" % item)
    lines.append("")
    return "\n".join(lines)
