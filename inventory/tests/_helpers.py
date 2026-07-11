"""Shared test helpers: import path setup, fake executors, report builders."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_inventory as ai  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture_text(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return handle.read()


def fixture_bytes(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return handle.read()


class FakeExec:
    """Executor stub returning a fixed result (or raising a fixed exception)."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((tuple(argv), timeout))
        if self.raises is not None:
            raise self.raises
        return self.returncode, self.stdout, self.stderr


class MappedExec:
    """Executor stub keyed on the first argv element; default raises FileNotFoundError."""

    def __init__(self, mapping):
        self.mapping = mapping  # {tool_name: FakeExec or exception}
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(tuple(argv))
        handler = self.mapping.get(argv[0])
        if handler is None:
            raise FileNotFoundError(argv[0])
        if isinstance(handler, BaseException):
            raise handler
        return handler(argv, timeout)


def timeout_exc(cmd="x", timeout=1):
    return subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)


def make_envelope(status="collected", command="test", data=None, **extra):
    envelope = {"status": status, "command": command, "duration_ms": 0.0}
    if data is not None:
        envelope["data"] = data
    envelope.update(extra)
    return envelope


def make_report(item_overrides=None):
    """A minimal schema-valid report; item_overrides: {category: {item: envelope}}."""
    categories = {name: {"items": {}} for name in ai.CATEGORIES}
    for category, items in (item_overrides or {}).items():
        categories[category]["items"].update(items)
    return {
        "run": {
            "run_id": "20260711T000000Z-testrun0",
            "script_version": ai.SCRIPT_VERSION,
            "schema_version": ai.SCHEMA_VERSION,
            "started_at": "2026-07-11T00:00:00+00:00",
            "finished_at": "2026-07-11T00:00:05+00:00",
            "executing_account": "test",
            "hostname": "testhost",
            "privileged": False,
            "complete": True,
        },
        "categories": categories,
    }
