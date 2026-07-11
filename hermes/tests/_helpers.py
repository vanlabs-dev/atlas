"""Test helpers: imports plus fixture builders for records and evidence."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_hermes_verify as ahv  # noqa: E402

inv = ahv.inv

TESTTOOL_SOURCE = os.path.join(os.path.dirname(_HERE), "testtool",
                               "atlas_test_tool.py")
VERIFIER_SOURCE = os.path.join(os.path.dirname(_HERE),
                               "atlas_hermes_verify.py")


def make_record(**overrides):
    """Complete, valid install record; None removes a field."""
    record = {
        "install_source": "github.com/example/hermes-agent official "
                          "installer, cloned to /home/hermes/.hermes/"
                          "hermes-agent",
        "installed_version": "commit abc1234def5678",
        "install_date": "2026-07-11",
        "update_method": "git pull in the clone, re-run installer",
        "rollback_method": "git checkout <previous>, re-run installer",
        "service_user": "hermes",
        "data_dir": "/home/hermes/.hermes",
        "config_path": "/home/hermes/.hermes/config.yaml",
    }
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not None}


def text_item(status="collected", path="/tmp/x", text="", truncated=False):
    item = {"status": status, "path": path}
    if status == "collected":
        item["text"] = text
        item["truncated"] = truncated
    else:
        item["error"] = status
    return item


def probe_env(status="collected", lines=None, error=None):
    env = {"status": status, "command": "test", "duration_ms": 0.0}
    if lines is not None:
        env["data"] = {"text_lines": list(lines)}
    if error is not None:
        env["error"] = error
    return env


GREEN_UNIT_LINES = (
    "LoadState=loaded",
    "UnitFileState=enabled",
    "ActiveState=active",
    "SubState=running",
    "User=hermes",
    "ExecMainStartTimestamp=Sat 2026-07-12 09:00:00 UTC",
)


def base_bundle(**overrides):
    """Evidence bundle in which every check passes for make_record()."""
    bundle = {
        "config_file": text_item(path="/home/hermes/.hermes/config.yaml",
                                 text="model: grok\ntelemetry: false\n"),
        "env_file": text_item(status="unsupported-on-device",
                              path="/home/hermes/.hermes/.env"),
        "etc_group": text_item(path="/etc/group",
                               text="root:x:0:\nsudo:x:27:pi\n"
                                    "hermes:x:1001:\n"),
        "sudoers": [text_item(path="/etc/sudoers",
                              text="# defaults\n%sudo ALL=(ALL:ALL) ALL\n")],
        "processes": probe_env(lines=[
            "hermes    1234 python3 /home/hermes/.hermes/hermes-agent/run.py"]),
        "unit_show": probe_env(lines=GREEN_UNIT_LINES),
        "journal": probe_env(lines=["Jul 12 09:00:00 pi hermes: started"]),
        "diagnostics": probe_env(lines=["all diagnostics passed"]),
        "log_files": [text_item(path="/home/hermes/.hermes/logs/hermes.log",
                                text="INFO agent started\nINFO ready\n")],
    }
    bundle.update(overrides)
    return bundle


def green_record(**overrides):
    """Record matching base_bundle: unit + diagnostics recorded."""
    record = make_record(service_unit="hermes.service",
                         diagnostics_command="hermes doctor")
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not None}


def results_by_check(results):
    return {result.check: result for result in results}
