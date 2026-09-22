"""Maintenance queue contract; all delivery uses an in-memory fake poster."""
import importlib.util
from pathlib import Path
import sqlite3
import urllib.parse

import pytest

MODULE = Path(__file__).resolve().parents[1] / "atlas_telegram.py"
spec = importlib.util.spec_from_file_location("maintenance_telegram", MODULE)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

SCHEMA = """
CREATE TABLE maintenance_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('detected','blocked','activated')),
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(upgrade_id, status)
);
"""


@pytest.fixture(autouse=True)
def forbid_real_telegram(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("tests must supply an HTTP poster stub")
    monkeypatch.setattr(tg, "_do_post", forbidden)


def setup_queue(tmp_path):
    source = tmp_path / "maintenance.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(SCHEMA)
    config = tg.load_config()
    config["classes"] = {"maintenance-status": {
        "enabled": True, "tier": "instant", "source_db": str(source)}}
    config["retry"]["backoff_seconds"] = [0]
    store = tg.open_store(str(tmp_path / "telegram.db"))
    sent = []

    def poster(url, data, timeout):
        sent.append(urllib.parse.parse_qs(data.decode()))
        return 200, '{"ok":true}'

    return source, config, store, sent, poster


def insert(source, status="detected", detail="runtime spec <450> & checks", **kwargs):
    values = dict(upgrade_id="finney:450:0xabc", status=status, detail=detail,
                  created_at="2026-09-22T00:00:00+00:00")
    values.update(kwargs)
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO maintenance_notifications "
                     "(upgrade_id,status,detail,created_at) VALUES (?,?,?,?)",
                     tuple(values[k] for k in ("upgrade_id", "status", "detail", "created_at")))


def test_shipped_config_registers_maintenance_queue():
    config = tg.load_config()
    assert config["classes"].get("maintenance-status") == {
        "enabled": True, "tier": "instant",
        "source_db": "var/maintenance/maintenance.db"}


def test_retry_and_watermark_reset_never_repage_identity(tmp_path):
    http_status = 200
    source, config, store, sent, _poster = setup_queue(tmp_path)
    insert(source, "blocked")

    def poster(url, data, timeout):
        sent.append(data)
        return http_status, '{}'

    tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    attempts = len(sent)
    assert attempts == 1
    # Simulate later orchestrator retries plus a notifier watermark reset.
    store.execute("UPDATE events SET created_at='2000-01-01T00:00:00+00:00'")
    store.execute("DELETE FROM watermarks")
    store.commit()
    tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    assert len(sent) == attempts
    insert(source, "activated")
    tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    assert len(sent) == attempts * 2
    assert store.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_failed_delivery_retries_after_cooldown_without_starving(tmp_path, monkeypatch):
    source, config, store, sent, _ = setup_queue(tmp_path)
    config["classes"]["maintenance-status"]["retry_cooldown_seconds"] = 60
    now = ["2026-09-22T01:00:00+00:00"]
    monkeypatch.setattr(tg, "_utc_now", lambda: now[0])
    insert(source, "blocked")

    def failing(url, data, timeout):
        sent.append(data)
        return 503, '{}'

    tg.notify_scan(config, "fake-token", "123", store, poster=failing)
    assert len(sent) == 1  # maintenance attempts are spaced across scans
    assert int(tg.watermark_get(store, "maintenance-status") or 0) == 0
    # More than the old 50-row page: cooling failures must not starve new work.
    for n in range(55):
        insert(source, "activated", upgrade_id=f"later:{n}")

    def success(url, data, timeout):
        sent.append(data)
        return 200, '{"ok":true}'

    for _ in range(3):
        tg.notify_scan(config, "fake-token", "123", store, poster=success)
    assert len(sent) == 56
    assert store.execute("SELECT status FROM events WHERE event_id=?",
                         ("maintenance:finney:450:0xabc:blocked",)).fetchone() == ("failed",)
    now[0] = "2026-09-22T01:01:00+00:00"
    tg.notify_scan(config, "fake-token", "123", store, poster=success)
    assert len(sent) == 57
    assert store.execute("SELECT status,retry_count FROM events WHERE event_id=?",
                         ("maintenance:finney:450:0xabc:blocked",)).fetchone() == ("delivered", 2)
    store.execute("DELETE FROM watermarks")
    store.commit()
    tg.notify_scan(config, "fake-token", "123", store, poster=success)
    assert len(sent) == 57


def test_exhausted_retries_report_blocked_across_restart(tmp_path, monkeypatch):
    source, config, store, sent, _ = setup_queue(tmp_path)
    config["retry"]["max_attempts"] = 2
    config["classes"]["maintenance-status"]["retry_cooldown_seconds"] = 60
    now = ["2026-09-22T01:00:00+00:00"]
    monkeypatch.setattr(tg, "_utc_now", lambda: now[0])
    insert(source)

    def failing(url, data, timeout):
        sent.append(data)
        return 503, '{}'

    tg.notify_scan(config, "fake-token", "123", store, poster=failing)
    store.close()
    store = tg.open_store(str(tmp_path / "telegram.db"))
    now[0] = "2026-09-22T01:01:00+00:00"
    result = tg.notify_scan(config, "fake-token", "123", store, poster=failing)
    assert len(sent) == 2
    assert result["classes"]["maintenance-status"]["health"] == "blocked"
    assert result["classes"]["maintenance-status"]["retry_exhausted"] == 1
    now[0] = "2026-09-23T01:01:00+00:00"
    store.execute("DELETE FROM watermarks")
    store.commit()
    for _ in range(3):
        result = tg.notify_scan(config, "fake-token", "123", store, poster=failing)
        assert result["classes"]["maintenance-status"]["health"] == "blocked"
    assert len(sent) == 2
    assert tg.watermark_get(store, "maintenance-status") == "1"
    assert store.execute("SELECT status,retry_count FROM events").fetchone() == ("failed", 2)


@pytest.mark.parametrize("failure", ["html-400", "unexpected-exception"])
def test_all_failure_paths_respect_lifetime_budget(tmp_path, monkeypatch, failure):
    source, config, store, sent, _ = setup_queue(tmp_path)
    config["retry"]["max_attempts"] = 1
    config["classes"]["maintenance-status"]["retry_cooldown_seconds"] = 0
    insert(source)

    def failing(url, data, timeout):
        sent.append(data)
        if failure == "unexpected-exception":
            raise RuntimeError("poster failed")
        return 400, '{}'

    for _ in range(3):
        result = tg.notify_scan(config, "fake-token", "123", store, poster=failing)
    assert len(sent) == 1
    assert result["classes"]["maintenance-status"]["health"] == "blocked"
    assert store.execute("SELECT retry_count FROM events").fetchone() == (1,)


@pytest.mark.parametrize("field,value", [
    ("status", "working"), ("upgrade_id", ""), ("upgrade_id", "bad\nidentity"),
    ("detail", ""), ("detail", "bad\x01markup"), ("detail", "x" * 1001),
    ("created_at", "yesterday"), ("created_at", "2026-09-22T00:00:00"),
])
def test_malformed_batch_fails_closed_without_advancing(tmp_path, field, value):
    source, config, store, sent, poster = setup_queue(tmp_path)
    insert(source)
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("INSERT INTO maintenance_notifications "
                     "(upgrade_id,status,detail,created_at) VALUES "
                     "('second','blocked','checks failed','2026-09-22T00:00:00Z')")
        conn.execute("UPDATE maintenance_notifications SET " + field + "=? WHERE id=2", (value,))
    result = tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    assert result["classes"]["maintenance-status"]["error"] == "malformed maintenance notification"
    assert not sent
    assert tg.watermark_get(store, "maintenance-status") is None


@pytest.mark.parametrize("missing", ["database", "table"])
def test_missing_source_is_quiet(tmp_path, missing):
    source, config, store, sent, poster = setup_queue(tmp_path)
    if missing == "database":
        source.unlink()
    else:
        with sqlite3.connect(source) as conn:
            conn.execute("DROP TABLE maintenance_notifications")
    result = tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    assert result["classes"]["maintenance-status"]["error"] == 0
    assert not sent
    assert tg.watermark_get(store, "maintenance-status") is None
    if missing == "database":
        assert not source.exists()


@pytest.mark.parametrize("status", ["detected", "blocked", "activated"])
def test_maintenance_status_uses_existing_delivery_pipeline(tmp_path, status):
    source, config, store, sent, poster = setup_queue(tmp_path)
    insert(source, status)
    result = tg.notify_scan(config, "fake-token", "123", store, poster=poster)
    assert result["classes"]["maintenance-status"].get("delivered") == 1
    assert len(sent) == 1
    assert status in sent[0]["text"][0]
    assert "&lt;450&gt; &amp; checks" in sent[0]["text"][0]
    assert sent[0]["parse_mode"] == ["HTML"]
    assert store.execute("SELECT event_id, status FROM events").fetchone() == (
        "maintenance:finney:450:0xabc:" + status, "delivered")
    assert tg.watermark_get(store, "maintenance-status") == "1"
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT COUNT(*) FROM maintenance_notifications").fetchone()[0] == 1
