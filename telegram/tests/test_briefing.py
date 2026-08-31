"""Pulse-briefing tests: store-only composition, fixed section order,
deltas per edition, edition watermarks (one per day, weekly replaces
daily, catch-up), priority truncation, and the closing-line rule."""

import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_briefing as ab  # noqa: E402
import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config, ok_poster_factory  # noqa: E402


def _iso(hours_ago=0.0):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


def seed_live(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE gate_state (id INTEGER PRIMARY KEY, observed_at TEXT,
        gate_active INTEGER, theta REAL, rank INTEGER, above_count INTEGER);
    CREATE TABLE gate_events (id INTEGER PRIMARY KEY, observed_at TEXT,
        netuid INTEGER, hovering INTEGER);
    CREATE TABLE gate_sides (netuid INTEGER PRIMARY KEY, side TEXT,
        hovering INTEGER);
    CREATE TABLE chain_param_events (id INTEGER PRIMARY KEY, item TEXT,
        prev_value TEXT, new_value TEXT, observed_at TEXT);
    CREATE TABLE network_vitals (date TEXT PRIMARY KEY, observed_at TEXT,
        total_staked_tao REAL, subnets_share_pct REAL,
        new_accounts_today INTEGER, tao_usd REAL);
    CREATE TABLE panel_snapshot (id INTEGER PRIMARY KEY, observed_at TEXT,
        block_number INTEGER, netuid INTEGER, share REAL,
        moving_price_tao REAL, dereg_risk_level TEXT,
        conviction_is_contested INTEGER, takeover_eligible INTEGER,
        name TEXT);
    CREATE TABLE integration_health (id INTEGER PRIMARY KEY,
        timestamp TEXT, provider TEXT, operation TEXT, category TEXT,
        detail TEXT);
    CREATE TABLE calls (id INTEGER PRIMARY KEY, provider TEXT, ts REAL);
    """)
    conn.execute("INSERT INTO meta VALUES ('last_live_spec', '452')")
    conn.execute(
        "INSERT INTO gate_state (observed_at, gate_active, theta, rank, "
        "above_count) VALUES (?, 1, 0.0083, 32, 32)", (_iso(1),))
    conn.execute(
        "INSERT INTO chain_param_events (item, prev_value, new_value, "
        "observed_at) VALUES ('RootWeightSettingEnabled', 'false', 'true', "
        "?)", (_iso(3),))
    conn.execute(
        "INSERT INTO network_vitals VALUES ('2026-08-30', ?, 7417081.7, "
        "27.35, 862, 198.59)", (_iso(2),))
    # Price mover: SN59 doubles inside the window.
    conn.executemany(
        "INSERT INTO panel_snapshot (observed_at, block_number, netuid, "
        "share, moving_price_tao, dereg_risk_level, "
        "conviction_is_contested, takeover_eligible, name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(_iso(20), 100, 59, 0.002, 0.0025, None, 0, 0, "fiftynine"),
         (_iso(1), 200, 59, 0.004, 0.0051, None, 0, 0, "fiftynine"),
         (_iso(20), 100, 7, 0.010, 0.0100, "high", 1, 0, "seven"),
         (_iso(1), 200, 7, 0.010, 0.0101, "high", 1, 0, "seven")])
    conn.execute("INSERT INTO gate_sides VALUES (9, 'above', 1)")
    conn.commit()
    conn.close()


def seed_fleet(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE metric_activity (netuid INTEGER, pass_ts TEXT, c7 INTEGER);
    CREATE TABLE signal_econ_verdicts (content_hash TEXT, netuid INTEGER,
        new_sha TEXT, significance TEXT, what_changed TEXT,
        created_at TEXT);
    CREATE TABLE signal_adoptions (id INTEGER PRIMARY KEY, term TEXT,
        kind TEXT, netuid INTEGER, adopted_at TEXT, seeded INTEGER);
    CREATE TABLE signal_events (id INTEGER PRIMARY KEY, class TEXT,
        term TEXT, created_at TEXT);
    CREATE TABLE epochs (id INTEGER PRIMARY KEY, netuid INTEGER,
        epoch INTEGER, opened_at TEXT);
    CREATE TABLE mine_econ (ts TEXT, netuid INTEGER, subnet_name TEXT,
        cut_reason TEXT, net_tao_month REAL, gross_tao_month REAL,
        rent_band TEXT);
    """)
    now = _iso(0)
    conn.executemany(
        "INSERT INTO metric_activity VALUES (?, ?, ?)",
        [(1, now, 5), (2, now, 0), (3, now, 2)])
    conn.execute(
        "INSERT INTO signal_econ_verdicts VALUES ('h', 89, 'abc123def456', "
        "'high', 'Signed points scoring path added', ?)", (_iso(2),))
    conn.execute(
        "INSERT INTO signal_econ_verdicts VALUES ('m', 15, 'ddd', 'med', "
        "'x', ?)", (_iso(2),))
    conn.executemany(
        "INSERT INTO signal_adoptions (term, kind, netuid, adopted_at, "
        "seeded) VALUES (?, ?, ?, ?, 0)",
        [("qwen3-14b", "model-id", 56, _iso(3)),
         ("numpy", "dependency", 5, _iso(3))])
    conn.execute(
        "INSERT INTO epochs (netuid, epoch, opened_at) VALUES (5, 3, ?)",
        (_iso(4),))
    conn.executemany(
        "INSERT INTO mine_econ VALUES (?, ?, ?, ?, ?, ?, NULL)",
        [(now, 107, "Minos", None, None, 258.7),
         (now, 64, "Chutes", None, None, 332.1),
         (now, 3, "dead", "identity-placeholder", None, None)])
    conn.commit()
    conn.close()


class BriefingBase(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = make_config(self.tmp.name)
        live = os.path.join(self.tmp.name, "livedata.db")
        fleet = os.path.join(self.tmp.name, "fleet.db")
        seed_live(live)
        seed_fleet(fleet)
        self.config["briefing"] = {
            "enabled": True, "daily_hour_utc": 7, "weekly_weekday": 6,
            "max_messages_daily": 2, "max_messages_weekly": 3,
            "live_db": live, "fleet_db": fleet,
            "repo_db": os.path.join(self.tmp.name, "absent-repo.db"),
            "knowledge_db": os.path.join(self.tmp.name, "absent-kb.db"),
            "board_url": "http://board.local/",
        }
        self.store = tg.open_store(self.config["db"])
        self.addCleanup(self.store.close)

    def run_briefing(self, posts, now=None):
        now = now or datetime.datetime(2026, 9, 1, 8, 0,
                                       tzinfo=datetime.timezone.utc)
        return ab.run_briefing(self.config, "tok", "chat", self.store,
                               poster=ok_poster_factory(posts), now=now)


class CompositionTests(BriefingBase):
    def test_sections_in_order_from_stores_only(self):
        edition = ab.compose(self.config, self.store, "daily")
        self.assertEqual(list(edition["sections"]),
                         list(ab.SECTION_ORDER))
        net = "\n".join(edition["sections"]["network"])
        self.assertIn("runtime spec 452", net)
        self.assertIn("rule change: RootWeightSettingEnabled false to true",
                      net)
        self.assertIn("bar 0.00830", net)
        self.assertIn("TAO 198.59 USD", net)
        self.assertIn("dated 2026-08-30", net)
        subnets = "\n".join(edition["sections"]["subnets"])
        self.assertIn("SN59 price +104.0%", subnets)
        self.assertIn("block 100 to", subnets)
        self.assertIn("dereg risk high: SN7", subnets)
        self.assertIn("ownership contested", subnets)
        self.assertIn("hovering at the bar (1): SN9", subnets)
        code = "\n".join(edition["sections"]["code"])
        self.assertIn("2 of 3 tracked subnets pushed", code)
        self.assertIn("SN89 high · Signed points scoring path added",
                      code)
        self.assertIn("1 high · 1 med", code)
        self.assertIn("SN5 repo re-pointed (epoch 3)", code)
        narrative = "\n".join(edition["sections"]["narrative"])
        self.assertIn("model qwen3-14b · SN56", narrative)
        self.assertNotIn("numpy", narrative)
        mining = "\n".join(edition["sections"]["mining"])
        self.assertIn("board head: SN64 Chutes", mining)
        self.assertIn("2 ranked · 1 cut · 3 observed", mining)
        self.assertIn("budget band unset", mining)
        self.assertTrue(edition["first_edition"])
        self.assertIn("next: pick mining.budget_band", edition["closing"])

    def test_unavailable_stores_named_not_estimated(self):
        self.config["briefing"]["fleet_db"] = os.path.join(
            self.tmp.name, "missing.db")
        edition = ab.compose(self.config, self.store, "daily")
        self.assertEqual(edition["sections"]["code"],
                         ["fleet store: unavailable"])
        self.assertEqual(edition["sections"]["mining"],
                         ["mining screen: unavailable"])

    def test_delta_against_previous_edition(self):
        ab._meta_set(self.store, "briefing:figures:daily",
                     json.dumps({"theta": 0.0080, "tao_usd": 190.0,
                                 "mining_top10": [107, 64]}))
        edition = ab.compose(self.config, self.store, "daily")
        self.assertFalse(edition["first_edition"])
        net = "\n".join(edition["sections"]["network"])
        self.assertIn("+3.8% vs last edition", net)
        self.assertIn("(+4.5%)", net)  # TAO/USD delta
        mining = "\n".join(edition["sections"]["mining"])
        self.assertIn("top ten unchanged", mining)


class DeliveryTests(BriefingBase):
    def test_one_daily_edition_with_watermark(self):
        posts = []
        result = self.run_briefing(posts)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["kind"], "daily")
        self.assertTrue(posts)
        again = self.run_briefing(posts)
        self.assertEqual(again["status"], "current")

    def test_not_due_before_hour(self):
        early = datetime.datetime(2026, 9, 1, 6, 59,
                                  tzinfo=datetime.timezone.utc)
        result = self.run_briefing([], now=early)
        self.assertEqual(result["status"], "not-due")

    def test_catch_up_after_failed_delivery(self):
        def bad_poster(url, data, timeout):
            return 500, '{"ok":false}'
        now = datetime.datetime(2026, 9, 1, 8, 0,
                                tzinfo=datetime.timezone.utc)
        result = ab.run_briefing(self.config, "tok", "chat", self.store,
                                 poster=bad_poster, now=now)
        self.assertEqual(result["status"], "failed")
        posts = []
        retry = self.run_briefing(posts, now=now.replace(hour=9))
        self.assertEqual(retry["status"], "sent")

    def test_weekly_replaces_daily(self):
        sunday = datetime.datetime(2026, 9, 6, 8, 0,
                                   tzinfo=datetime.timezone.utc)
        self.assertEqual(sunday.weekday(), 6)
        posts = []
        result = self.run_briefing(posts, now=sunday)
        self.assertEqual(result["kind"], "weekly")
        import urllib.parse
        decoded = [urllib.parse.unquote_plus(p) for p in posts]
        self.assertTrue(any("weekly pulse" in p for p in decoded))
        again = self.run_briefing([], now=sunday.replace(hour=10))
        self.assertEqual(again["status"], "current")

    def test_closing_line_is_last(self):
        posts = []
        self.run_briefing(posts)
        import urllib.parse
        last = urllib.parse.unquote_plus(posts[-1])
        self.assertIn("next: pick mining.budget_band", last)

    def test_disabled_briefing_is_inert(self):
        self.config["briefing"]["enabled"] = False
        result = self.run_briefing([])
        self.assertEqual(result["status"], "disabled")


class TruncationTests(BriefingBase):
    def test_lowest_priority_drops_first_network_never(self):
        edition = ab.compose(self.config, self.store, "daily")
        edition["sections"]["narrative"] = [
            "model filler-%d · SN1" % i for i in range(200)]
        self.config["message_max_chars"] = 1200
        messages = ab._to_messages(edition, self.config)
        self.assertLessEqual(len(messages), 2)
        joined = "\n".join("\n".join(lines) for _h, lines in messages)
        self.assertIn("runtime spec 452", joined)       # network intact
        self.assertIn("omitted for size", joined)
        self.assertLess(joined.count("filler"), 200)

    def test_closing_line_present_after_truncation(self):
        edition = ab.compose(self.config, self.store, "daily")
        self.config["message_max_chars"] = 1500
        messages = ab._to_messages(edition, self.config)
        _head, lines = messages[-1]
        self.assertEqual(lines[-1], edition["closing"])


if __name__ == "__main__":
    unittest.main()
