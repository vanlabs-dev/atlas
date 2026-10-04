"""Real-data regression (change: telegram-alert-redesign).

The fixture holds source rows read from the Pi's live stores on
2026-10-04: the events the alert review was built from. Each class runs
through its real adapter, and every message must hold the house layout.
These are the rows that exposed the missing subnet number and the
glosses inside recorded text.
"""

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

FIXTURE = os.path.join(_HERE, "fixtures", "pi-2026-10-04.json")
MARKS = tuple(tg.SEVERITY_MARK.values())


def load_tables(path, tables):
    conn = sqlite3.connect(path)
    for name, table in tables.items():
        if not isinstance(table, dict) or not table.get("columns"):
            continue
        cols = table["columns"]
        conn.execute("CREATE TABLE %s (%s)" % (name, ", ".join(
            "%s INTEGER PRIMARY KEY" % c if c == "id" else c for c in cols)))
        conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (
            name, ", ".join(cols), ", ".join("?" * len(cols))),
            table["rows"])
    conn.commit()
    conn.close()


class RealSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, "r", encoding="utf-8") as handle:
            cls.data = json.load(handle)

    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = make_config(self.tmp.name)
        self.live = os.path.join(self.tmp.name, "live.db")
        self.fleet = os.path.join(self.tmp.name, "fleet.db")
        load_tables(self.live, self.data["livedata"])
        load_tables(self.fleet, {k: v for k, v in self.data["fleet"].items()
                                 if k != "digest_lines"})
        self.config["briefing"] = {"live_db": self.live}
        self.names = tg.subnet_names(self.live)

    def ctx(self, **spec):
        return {"config": self.config, "spec": spec, "connection": None}

    def check(self, event):
        text, html = event["text"], event["html"]
        self.assertIn(text[:1], MARKS, text[:60])
        self.assertNotIn("Atlas · ", text)
        self.assertNotIn("—", html)
        self.assertNotIn("–", html)
        self.assertIsNone(re.search(r"\b[Nn]etuid\b|\bSN\d", text), text)
        body = html.split("<blockquote")[0]
        self.assertIsNone(re.search(r"\d{2}:\d{2}:\d{2}\.\d{6}", body))
        for tag in re.findall(r"</?([a-z-]+)", html):
            self.assertIn(tag, ("b", "i", "code", "pre", "blockquote",
                                "tg-time"))
        self.assertLessEqual(len(html), 3500)
        if "Next:" in text:
            self.assertTrue(text.split("\n")[-1].startswith("Next: "))
        for _label, url in event.get("buttons") or []:
            self.assertTrue(url.startswith("https://"))
            self.assertNotIn("192.168.", url)

    def test_names_are_read_from_the_snapshot(self):
        self.assertEqual(self.names.get(82), "uruz")
        self.assertEqual(self.names.get(120), "Affine")

    def test_chain_parameter_names_the_subnet(self):
        events, _ = tg.chain_parameter_change_events(
            self.live, None, self.ctx(governs={}))
        self.assertTrue(events)
        for event in events:
            self.check(event)
            self.assertIn("Subnet ", event["text"].split("\n")[0])
        heads = [e["text"].split("\n")[0] for e in events]
        self.assertTrue(any("(uruz)" in h for h in heads), heads)

    def test_runtime_upgrades(self):
        events, _ = tg.chain_runtime_upgrade_events(self.live, None,
                                                    self.ctx())
        self.assertEqual(len(events), 2)
        for event in events:
            self.check(event)

    def test_gate_crossings(self):
        events, _ = tg.gate_crossing_events(self.live, None,
                                            self.ctx(cooldown_hours=24))
        self.assertTrue(events)
        for event in events:
            self.check(event)
            self.assertIn("emission bar", event["text"].split("\n")[0])

    def test_schema_drift(self):
        events, _ = tg.schema_drift_events(self.live, None, self.ctx())
        self.assertEqual(len(events), 1)
        self.check(events[0])
        self.assertTrue(events[0]["text"].startswith("🟠 CoinGecko"))

    def test_econ_and_watchlist(self):
        events, _ = tg.fleet_signal_events(
            self.fleet, None, self.ctx(source_db=self.fleet,
                                       digest_backstop_hours=24))
        classes = sorted(e["event_class"] for e in events)
        self.assertEqual(classes, ["econ-code", "watchlist"])
        for event in events:
            self.check(event)
            self.assertIsNone(re.search(r"\(\w+/\w+\)", event["text"]
                                        .split("\n")[0]))  # no repo slug

    def test_digest_lines_are_named_and_merged(self):
        lines = self.data["fleet"]["digest_lines"]
        pending = [(i, line, "x") for i, line in enumerate(lines)]
        event = tg._build_signal_digest_event(pending, 3500, None, self.names)
        self.check(event)
        self.assertNotIn("SN", event["text"])
        bullets = [ln for ln in event["text"].split("\n")
                   if ln.startswith("• ")]
        self.assertLess(len(bullets), len(lines))  # cooldown notes merged


if __name__ == "__main__":
    unittest.main()
