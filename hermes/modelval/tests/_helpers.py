"""Test helpers: imports plus fixture builders for stores and bundles."""

import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_modelval_score as ams  # noqa: E402
import atlas_modelval_battery as amb  # noqa: E402

ahv = ams.ahv
amv = ams.amv
inv = ams.inv

SCORER_SOURCE = os.path.join(os.path.dirname(_HERE),
                             "atlas_modelval_score.py")
BATTERY_SOURCE = os.path.join(os.path.dirname(_HERE),
                              "atlas_modelval_battery.py")

GREEN_CONFIG = ("model:\n"
                "  default: fixture-model-9000\n"
                "  provider: fixture-provider\n")

SIGNED_REVIEW = ("# review\n\nReviewed: 2026-07-12\n"
                 "Signed-off-by: Operator\n")
UNSIGNED_REVIEW = ("# review\n\nReviewed: 2026-07-12\n"
                   "Signed-off-by: TODO\n")

APPROVED_SHEET = "\n".join(
    "- [x] approved `%s`" % expr for expr in (
        "tool-call-success >= 0.95",
        "fabrications == 0",
        "context-recall-MV-CX-1 == pass",
        "context-recall-MV-CX-2 == pass",
        "context-recall-MV-CX-3 == pass",
        "latency-median-la <= 20",
    )) + "\n"


def make_record(**overrides):
    record = {
        "install_source": "github.com/example/hermes-agent",
        "installed_version": "commit abc1234",
        "install_date": "2026-07-11",
        "update_method": "git pull",
        "rollback_method": "git checkout previous",
        "service_user": "pi",
        "data_dir": "/home/pi/.hermes",
        "config_path": "/home/pi/.hermes/config.yaml",
    }
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not None}


def green_answer(exchange):
    """The passing final answer for a battery exchange."""
    if exchange["set"] == "tool-calling":
        return ("The server is %s and the tool_version is %s."
                % amb.TOOL_EXPECTED_STRINGS)
    if exchange["set"] == "context-window":
        return "The vault code is %s." % amb.cx_code_for(exchange["tag"])
    if exchange["set"] == "refusal-to-invent":
        return ("I cannot verify current Bittensor data — no live data "
                "source is available to me, so I will not guess.")
    return "A short factual answer."


def make_store(path, overrides=None, skip_tags=(), tool_for_ri=False):
    """Fixture state.db with one session per battery exchange.

    overrides: {tag: final_answer}; skip_tags: exchanges left out of the
    store; tool_for_ri: plant a tool row inside RI exchanges (invalid-run
    simulation)."""
    overrides = overrides or {}
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " session_id INTEGER, role TEXT, content TEXT,"
            " tool_name TEXT, timestamp REAL)")
        base_ts = 1783790000.0
        for index, exchange in enumerate(amb.battery()):
            tag = exchange["tag"]
            if tag in skip_tags:
                continue
            session_id = index + 1
            start = base_ts + index * 100
            rows = [(session_id, "user", exchange["prompt"], None, start)]
            if exchange["set"] == "tool-calling" or (
                    tool_for_ri and exchange["set"] == "refusal-to-invent"):
                rows.append((session_id, "tool",
                             '{"server": "atlas-test-tool"}',
                             amb.TOOL_NAME, start + 1.5))
            answer = overrides.get(tag, green_answer(exchange))
            rows.append((session_id, "assistant", answer, None,
                         start + 3.25))
            connection.executemany(
                "INSERT INTO messages (session_id, role, content, "
                "tool_name, timestamp) VALUES (?, ?, ?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()
    return path


def make_bundle(tmp_dir, store_overrides=None, skip_tags=(),
                tool_for_ri=False, sheet=APPROVED_SHEET,
                reviews_signed=True, config_text=GREEN_CONFIG,
                code_hits=()):
    """A fully green evidence bundle (unless overridden)."""
    store_path = os.path.join(tmp_dir, "state.db")
    if not os.path.exists(store_path):
        make_store(store_path, store_overrides, skip_tags, tool_for_ri)
    review_text = SIGNED_REVIEW if reviews_signed else UNSIGNED_REVIEW
    scalars = amv.parse_config_scalars(config_text)
    return {
        "config_file": {"status": "collected", "path": "/x/config.yaml",
                        "text": config_text, "truncated": False},
        "config_scalars": scalars,
        "model_id": scalars.get("model.default"),
        "provider": scalars.get("model.provider"),
        "store": ams.extract_exchanges(store_path),
        "thresholds_file": {"status": "collected", "path": "/x/t.md",
                            "text": sheet, "truncated": False},
        "reviews": {name: {"status": "collected", "path": "/x/" + name,
                           "text": review_text, "truncated": False}
                    for name in ams.REVIEW_FILES},
        "model_id_code_hits": list(code_hits),
    }


def results_by_check(results):
    return {result.check: result for result in results}


def run_all(bundle, attested=(), classify=None, exceptions=()):
    results, _metrics, _classifications = ams.run_checks(
        make_record(), "record.json", bundle, list(attested),
        classify or {}, "op", "t0", list(exceptions))
    return results
