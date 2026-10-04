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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "fleet", "tests"))

import atlas_briefing as ab  # noqa: E402
import mining_fixtures as mf  # noqa: E402
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
        "observed_at) VALUES ('BasketConcentrationCap', '4096', '2048', "
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
    conn.commit()
    # Mining rows come from the real writer (econ, then classify).
    mf.seed_board(conn, {"mining": {"enabled": True}}, BOARD_SNAPSHOT())
    conn.close()


def BOARD_SNAPSHOT():
    """SN64 Chutes heads the board, SN107 Minos second, SN3 cut at the
    identity rung, SN12 unrated (owner set unread)."""
    return mf.synthetic([
        mf.subnet(64, [10, 9, 8], name="Chutes", tao_pool=90_000.0),
        mf.subnet(107, [10, 9, 8], name="Minos", tao_pool=60_000.0),
        mf.subnet(3, [10, 9, 8], name="deprecated"),
        mf.subnet(12, [10, 9, 8], name="Twelve", owner_uids=None)])


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
        self.assertIn("Runtime spec 452", net)
        self.assertIn("Emission bar 0.830%", net)
        self.assertIn("32 subnets above", net)
        self.assertIn("TAO $198.59", net)
        self.assertIn("dated 30 Aug", net)
        rules = "\n".join(edition["sections"]["rules"])
        self.assertIn("BasketConcentrationCap 4,096 → 2,048", rules)
        prices = "\n".join(edition["sections"]["price_moves"])
        self.assertIn("fiftynine (59): 0.00250 → 0.00510 τ, +104.0%", prices)
        self.assertNotIn("block", prices)
        watch = "\n".join(edition["sections"]["watch"])
        self.assertIn("At the bar: Subnet 9", watch)
        high = edition["sections"]["high_impact"]
        self.assertEqual(high, ["Subnet 89: Signed points scoring path "
                                "added"])
        self.assertTrue(edition["first_edition"])
        self.assertIn("First edition", edition["summary"])
        self.assertIsNone(edition["closing"])
        self.assertTrue(edition["header"].startswith("Atlas daily · "))

    def test_removed_content_stays_out(self):
        edition = ab.compose(self.config, self.store, "daily")
        joined = "\n".join(line for lines in edition["sections"].values()
                           for line in lines) + "\n".join(edition["health"])
        for gone in ("staked", "subnet share", "new accounts", "contested",
                     "takeover", " med", "pushed", "re-pointed", "qwen3-14b",
                     "cluster", "board head", "ranked", "mining", "SN"):
            self.assertNotIn(gone, joined, gone)

    def test_watch_list_top_three_non_immune_by_prune_rank(self):
        live = self.config["briefing"]["live_db"]
        conn = sqlite3.connect(live)
        conn.execute("ALTER TABLE panel_snapshot ADD COLUMN "
                     "dereg_prune_rank INTEGER")
        conn.execute("ALTER TABLE panel_snapshot ADD COLUMN "
                     "dereg_is_immune INTEGER")
        rows = [(113, "LongShort", "critical", 1, 0),
                (116, "for sale", "critical", 2, 0),
                (5, "Immune One", "critical", 3, 1),
                (47, "GPUForge", "critical", 4, 0),
                (72, "StreetVision", "high", 5, 0),
                (8, "Unread", "high", 6, None)]
        conn.executemany(
            "INSERT INTO panel_snapshot (observed_at, block_number, netuid, "
            "share, moving_price_tao, dereg_risk_level, name, "
            "dereg_prune_rank, dereg_is_immune) VALUES "
            "(?, 300, ?, 0.001, 0.001, ?, ?, ?, ?)",
            [(_iso(0.5), n, level, name, rank, immune)
             for n, name, level, rank, immune in rows])
        conn.commit()
        conn.close()
        watch = ab.compose(self.config, self.store, "daily")[
            "sections"]["watch"]
        self.assertEqual(watch[:4], [
            "Closest to deregistration (not immune):",
            "1. LongShort (113)", "2. for sale (116)", "3. GPUForge (47)"])
        self.assertNotIn("Immune One", "\n".join(watch))

    def test_rule_set_then_reset_is_one_line(self):
        live = self.config["briefing"]["live_db"]
        conn = sqlite3.connect(live)
        conn.executemany(
            "INSERT INTO chain_param_events (item, prev_value, new_value, "
            "observed_at) VALUES (?, ?, ?, ?)",
            [("CollateralLockShare[82]", "0", "62258", _iso(5)),
             ("CollateralLockShare[82]", "62258", "0", _iso(4)),
             ("SubnetEmissionEnabled[82]", "true", "false", _iso(3))])
        conn.commit()
        conn.close()
        rules = ab.compose(self.config, self.store, "daily")[
            "sections"]["rules"]
        self.assertIn("Subnet 82: CollateralLockShare set, then reset to 0",
                      rules)
        self.assertIn("Subnet 82: TAO emission switched off", rules)

    def test_unavailable_stores_named_not_estimated(self):
        self.config["briefing"]["fleet_db"] = os.path.join(
            self.tmp.name, "missing.db")
        self.config["briefing"]["live_db"] = os.path.join(
            self.tmp.name, "missing-live.db")
        edition = ab.compose(self.config, self.store, "daily")
        self.assertEqual(edition["sections"]["network"],
                         ["Live store unavailable"])
        self.assertEqual(edition["sections"]["high_impact"], [])

    def test_delta_against_previous_edition(self):
        ab._meta_set(self.store, "briefing:figures:daily",
                     json.dumps({"theta": 0.0080, "tao_usd": 190.0}))
        edition = ab.compose(self.config, self.store, "daily")
        self.assertFalse(edition["first_edition"])
        net = "\n".join(edition["sections"]["network"])
        self.assertIn("Emission bar 0.830% · +3.8%", net)
        self.assertIn("+4.5% since yesterday's edition", net)
        self.assertIn("TAO rose 4.5%.", edition["summary"])

    def test_summary_names_the_largest_mover(self):
        edition = ab.compose(self.config, self.store, "daily")
        self.assertIn("fiftynine (59) price rose 104.0%.",
                      edition["summary"])
        self.assertIn("1 chain rule change.", edition["summary"])
        self.assertIn("1 high-impact incentive change.", edition["summary"])
        self.assertNotIn("Quiet day.", edition["summary"])

    def test_weekly_header_and_marker(self):
        now = datetime.datetime(2026, 10, 4, 8, 0,
                                tzinfo=datetime.timezone.utc)
        edition = ab.compose(self.config, self.store, "weekly", now=now)
        self.assertEqual(edition["header"], "Atlas weekly · 28 Sep to 4 Oct")
        msgs = ab._to_messages(edition, self.config)
        self.assertTrue(tg.render_plain(msgs[0]).startswith(
            "🗓️ Atlas weekly · 28 Sep to 4 Oct"))
        daily = ab.compose(self.config, self.store, "daily", now=now)
        self.assertTrue(tg.render_plain(ab._to_messages(
            daily, self.config)[0]).startswith("☀️ Atlas daily · Sun 4 Oct"))


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
        self.assertTrue(any("🗓️ <b>Atlas weekly" in p for p in decoded))
        again = self.run_briefing([], now=sunday.replace(hour=10))
        self.assertEqual(again["status"], "current")

    def test_no_board_link_or_button(self):
        posts = []
        self.run_briefing(posts)
        import urllib.parse
        last = urllib.parse.unquote_plus(posts[-1])
        self.assertNotIn("board.local", last)
        self.assertNotIn("reply_markup", last)
        self.assertNotIn("Next:", last)
        self.assertIn("☀️ <b>Atlas daily", last)

    def test_disabled_briefing_is_inert(self):
        self.config["briefing"]["enabled"] = False
        result = self.run_briefing([])
        self.assertEqual(result["status"], "disabled")


class TruncationTests(BriefingBase):
    def test_lowest_priority_drops_first_network_never(self):
        edition = ab.compose(self.config, self.store, "daily")
        edition["sections"]["high_impact"] = [
            "Filler (%d): change" % i for i in range(200)]
        edition["health"] = ["health line %d" % i for i in range(50)]
        self.config["message_max_chars"] = 1200
        messages = ab._to_messages(edition, self.config)
        self.assertLessEqual(len(messages), 2)
        joined = "\n".join(tg.render_plain(m, 1200) for m in messages)
        self.assertIn("Runtime spec 452", joined)       # network intact
        self.assertIn("omitted for size", joined)
        self.assertLess(joined.count("Filler"), 200)
        self.assertNotIn("health line", joined)        # fold shed first
        for m in messages:
            self.assertLessEqual(len(tg.render_html(m, 1200)), 1200)

    def test_closing_line_present_after_truncation(self):
        edition = ab.compose(self.config, self.store, "daily")
        edition["closing"] = "do the thing."
        edition["sections"]["high_impact"] = [
            "Filler (%d): change" % i for i in range(200)]
        self.config["message_max_chars"] = 1500
        messages = ab._to_messages(edition, self.config)
        last = tg.render_plain(messages[-1], 1500)
        self.assertEqual(last.split("\n")[-1], "Next: do the thing.")


if __name__ == "__main__":
    unittest.main()
