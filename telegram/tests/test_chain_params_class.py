"""Bar-mode attribution on gate crossings and the sixth notifier class
(change: network-drift-443).

The attribution tests encode the 2026-08-03 shape: the spec-441 bar reset
dropped theta about 14.5% in one poll and four subnets crossed in a single
pass without their demand moving. Reporting that as per-subnet demand
movement is what the shipped signal did, and it misinformed.
"""

import datetime
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

SCHEMA = """
CREATE TABLE gate_events (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    direction TEXT NOT NULL,
    share REAL NOT NULL,
    theta REAL NOT NULL,
    prev_side TEXT NOT NULL,
    emission_enabled INTEGER,
    block_number INTEGER,
    prev_theta REAL
);
CREATE TABLE gate_state (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    theta REAL,
    q REAL,
    rank INTEGER,
    bar_mode TEXT
);
CREATE TABLE chain_param_events (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    prev_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    prev_provenance TEXT NOT NULL,
    new_provenance TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    block_number INTEGER
);
"""

EM_DASH = "—"
EN_DASH = "–"


def _iso(hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


def seed(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def add_state(path, bar_mode="rank", rank=32, q=0.75, theta=0.008):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO gate_state (observed_at, theta, q, rank, bar_mode) "
        "VALUES (?, ?, ?, ?, ?)",
        (_iso(hours_ago=1), theta, q, rank, bar_mode))
    conn.commit()
    conn.close()


def add_crossing(path, netuid, direction, share, theta, prev_theta):
    conn = sqlite3.connect(path)
    cursor = conn.execute(
        "INSERT INTO gate_events (observed_at, netuid, direction, share, "
        "theta, prev_side, emission_enabled, block_number, prev_theta) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, 8766216, ?)",
        (_iso(), netuid, direction, share, theta,
         "above" if direction == "fell-below" else "below", prev_theta))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def add_param_event(path, item, prev_value, new_value,
                    prev_prov="assumed-default", new_prov="explicit"):
    conn = sqlite3.connect(path)
    cursor = conn.execute(
        "INSERT INTO chain_param_events (item, prev_value, new_value, "
        "prev_provenance, new_provenance, observed_at, block_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item, prev_value, new_value, prev_prov, new_prov, _iso(), 8766216))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live_db = os.path.join(self.tmp.name, "livedata.db")
        seed(self.live_db)
        self.config = make_config(self.tmp.name)
        self.store = tg.open_store(os.path.join(self.tmp.name,
                                                "telegram.db"))
        self.addCleanup(self.store.close)


class GateBarModeTests(_Base):
    def setUp(self):
        super().setUp()
        self.spec = {"enabled": True, "source_db": self.live_db,
                     "cooldown_hours": 24}

    def ctx(self):
        return {"config": self.config, "spec": self.spec,
                "connection": self.store}

    def body(self):
        events, _wm = tg.gate_crossing_events(self.live_db, None, self.ctx())
        self.assertEqual(len(events), 1)
        return events[0]["text"]

    def test_rank_mode_is_named(self):
        add_state(self.live_db, bar_mode="rank", rank=32)
        add_crossing(self.live_db, 49, "rose-above", 0.0090, 0.0073, 0.0088)
        text = self.body()
        self.assertIn("bar mode: rank-pinned at N 32", text)
        self.assertNotIn("q-mass at q", text)

    def test_q_mass_mode_is_named(self):
        add_state(self.live_db, bar_mode="q-mass", rank=0, q=0.75)
        add_crossing(self.live_db, 49, "rose-above", 0.0090, 0.0073, 0.0088)
        self.assertIn("bar mode: q-mass at q 0.75", self.body())

    def test_bar_driven_crossing_is_attributed_to_the_bar(self):
        # SN49's real 2026-08-03 numbers: share 0.0086 sat BELOW the old bar
        # of 0.0088 and above the new one of 0.0073. The share never moved;
        # the bar fell past it. Atlas paged this as "rose above".
        add_state(self.live_db, bar_mode="rank", rank=32)
        add_crossing(self.live_db, 49, "rose-above", 0.0086, 0.0073, 0.0088)
        text = self.body()
        self.assertIn("THE BAR MOVED onto this subnet", text)
        self.assertIn("bar moved -17.0%", text)

    def test_share_driven_crossing_is_attributed_to_the_subnet(self):
        # SN9's real shape: bar near-static, share vaults across it.
        add_state(self.live_db, bar_mode="rank", rank=32)
        add_crossing(self.live_db, 9, "rose-above", 0.0192, 0.0079, 0.0078)
        text = self.body()
        self.assertIn("the subnet's own demand share moved across", text)
        self.assertNotIn("THE BAR MOVED", text)

    def test_legacy_crossing_asserts_neither_mode_nor_movement(self):
        # Recorded before the migration: no gate_state row, no prev_theta.
        add_crossing(self.live_db, 42, "fell-below", 0.005, 0.010, None)
        text = self.body()
        self.assertNotIn("bar mode:", text)
        self.assertNotIn("bar moved", text)
        self.assertNotIn("attribution:", text)
        self.assertIn("subnet 42 fell BELOW the bar", text)

    def test_house_style_holds(self):
        add_state(self.live_db, bar_mode="rank", rank=32)
        add_crossing(self.live_db, 49, "rose-above", 0.0090, 0.0073, 0.0088)
        text = self.body()
        self.assertNotIn(EM_DASH, text)
        self.assertNotIn(EN_DASH, text)


class ChainParameterClassTests(_Base):
    def setUp(self):
        super().setUp()
        self.spec = {
            "enabled": True, "source_db": self.live_db,
            "governs": {
                "RootWeightSettingEnabled": "Root Reborn curation switch",
                "EmissionBarRank": "bar selection <rank & mode>"},
        }

    def ctx(self):
        return {"config": self.config, "spec": self.spec,
                "connection": self.store}

    def events(self, watermark=None):
        return tg.chain_parameter_change_events(
            self.live_db, watermark, self.ctx())

    def test_missing_table_is_inert(self):
        bare = os.path.join(self.tmp.name, "bare.db")
        sqlite3.connect(bare).close()
        events, wm = tg.chain_parameter_change_events(bare, None, self.ctx())
        self.assertEqual((events, wm), ([], None))

    def test_curation_flip_pages_once(self):
        row_id = add_param_event(self.live_db, "RootWeightSettingEnabled",
                                 "false", "true")
        events, wm = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(wm, str(row_id))
        event = events[0]
        self.assertEqual(event["event_class"], "chain-parameter-change")
        self.assertEqual(event["event_id"],
                         "chain-parameter-change:%d" % row_id)
        text = event["text"]
        self.assertIn("RootWeightSettingEnabled: false to true", text)
        self.assertIn("provenance: assumed-default to explicit", text)
        self.assertIn("reference block: 8766216", text)
        self.assertIn("Root Reborn curation switch", text)
        self.assertNotIn("re-priced", text)   # not a bar parameter
        self.assertNotIn(EM_DASH, text)
        self.assertIn("<b>", event["html"])

    def test_no_cooldown_between_successive_flips(self):
        add_param_event(self.live_db, "RootWeightSettingEnabled",
                        "false", "true")
        add_param_event(self.live_db, "RootWeightSettingEnabled",
                        "true", "false")
        events, _wm = self.events()
        self.assertEqual(len(events), 2)

    def test_bar_parameter_explains_the_withheld_crossings(self):
        add_param_event(self.live_db, "EmissionBarRank", "32", "64")
        events, _wm = self.events()
        text = events[0]["text"]
        self.assertIn("re-priced for EVERY subnet", text)
        self.assertIn("withheld", text)

    def test_mode_change_is_stated_in_words(self):
        first = add_param_event(self.live_db, "EmissionBarRank", "32", "0")
        events, _wm = self.events()
        self.assertIn("fallen back to Q-MASS", events[0]["text"])
        add_param_event(self.live_db, "EmissionBarRank", "0", "32")
        events, _wm = self.events(watermark=str(first))
        self.assertIn("now RANK-PINNED", events[0]["text"])

    def test_governs_text_is_escaped_in_html(self):
        add_param_event(self.live_db, "EmissionBarRank", "32", "64")
        events, _wm = self.events()
        html = events[0]["html"]
        self.assertIn("&lt;rank &amp; mode&gt;", html)
        self.assertNotIn("<rank & mode>", html)

    def test_watermark_excludes_seen_rows(self):
        first = add_param_event(self.live_db, "EmissionBarRank", "32", "64")
        events, wm = self.events(watermark=str(first))
        self.assertEqual((events, wm), ([], str(first)))

    def test_registered_in_the_adapter_table(self):
        self.assertIn("chain-parameter-change", tg._ADAPTERS)


if __name__ == "__main__":
    unittest.main()
