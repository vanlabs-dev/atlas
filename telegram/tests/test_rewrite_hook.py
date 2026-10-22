"""The rewrite hook in notify_scan (change: plain-english-alerts)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config, ok_poster_factory, seed_livedata  # noqa: E402
from test_plain_rewrite import Done, ok, runner_returning  # noqa: E402

REPLY = {
    "headline": "Bittensor has a new software version (452)",
    "meaning": "The network itself changed. It was version 450 before.",
    "facts": [["Release", "not matched to a release yet"]],
    "body": [],
    "next": None,
}
TERMS = {"emission-gate bar": "reward cutoff", "demand share": "demand",
         "runtime spec": "version"}


class HookBase(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.config["voice"]["alert_terms"] = TERMS
        self.config["rewrite"] = {
            "enabled": True, "toolset": "none", "hermes_path": "hermes",
            "timeout_seconds": 25, "scan_budget_seconds": 180,
            "next_allowed_classes": ["chain-parameter-change"]}
        self.db = self.config["classes"]["chain-runtime-upgrade"]["source_db"]
        seed_livedata(self.db, live_spec=452, upgrades=[(450, 452, 8951570)])
        self.store = tg.open_store(self.config["db"])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def scan(self, runner):
        posts = []
        tg.notify_scan(self.config, "tok", "chat", self.store,
                       poster=ok_poster_factory(posts),
                       rewrite_runner=runner)
        return [urllib.parse.unquote_plus(p) for p in posts]

    def ledger_row(self):
        return self.store.execute(
            "SELECT status, rewrite, rewrite_ms FROM events WHERE "
            "event_class = 'chain-runtime-upgrade'").fetchone()


class RewriteHookTests(HookBase):
    def test_accepted_rewrite_is_sent_and_recorded(self):
        runner = runner_returning(ok(REPLY))
        posts = self.scan(runner)
        self.assertEqual(len(runner.calls), 1)
        text = posts[0]
        self.assertIn("Bittensor has a new software version (452)", text)
        self.assertIn("It was version 450 before.", text)
        # time stays code-owned and the technical original stays in the fold
        self.assertIn("<tg-time", text)
        self.assertIn("Original: Bittensor just updated its software "
                      "(version 452)", text)
        self.assertIn("Block 8,951,570", text)
        status, rewrite, ms = self.ledger_row()
        self.assertEqual((status, rewrite), ("delivered", "used"))
        self.assertIsNotNone(ms)

    def test_hermes_down_sends_the_template(self):
        runner = runner_returning(FileNotFoundError("hermes"))
        posts = self.scan(runner)
        self.assertIn("Bittensor just updated its software (version 452)",
                      posts[0])
        status, rewrite, _ms = self.ledger_row()
        self.assertEqual(status, "delivered")
        self.assertTrue(rewrite.startswith("fallback:hermes-error"))

    def test_failed_check_sends_the_template(self):
        bad = dict(REPLY, meaning="It jumped 30 versions.")
        posts = self.scan(runner_returning(ok(bad)))
        self.assertIn("Bittensor just updated its software", posts[0])
        self.assertNotIn("jumped", posts[0])
        _s, rewrite, _ms = self.ledger_row()
        self.assertTrue(rewrite.startswith("fallback:check-failed"))

    def test_disabled_makes_no_call(self):
        self.config["rewrite"]["enabled"] = False
        runner = runner_returning(ok(REPLY))
        posts = self.scan(runner)
        self.assertEqual(runner.calls, [])
        self.assertIn("Bittensor just updated its software", posts[0])
        self.assertEqual(self.ledger_row()[1], "fallback:disabled")

    def test_spent_scan_budget_makes_no_call(self):
        self.config["rewrite"]["scan_budget_seconds"] = 0
        runner = runner_returning(ok(REPLY))
        posts = self.scan(runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(len(posts), 1)
        self.assertEqual(self.ledger_row()[1], "fallback:budget")

    def test_briefing_tier_event_makes_no_call(self):
        self.config["classes"]["chain-runtime-upgrade"]["tier"] = "briefing"
        runner = runner_returning(ok(REPLY))
        self.assertEqual(self.scan(runner), [])
        self.assertEqual(runner.calls, [])
        self.assertIsNone(self.ledger_row()[1])

    def test_already_delivered_event_makes_no_call(self):
        events, _ = tg.chain_runtime_upgrade_events(
            self.db, None, {"config": self.config, "spec":
                            self.config["classes"]["chain-runtime-upgrade"],
                            "connection": self.store})
        tg.ledger_record(self.store, events[0]["event_id"],
                         "chain-runtime-upgrade", events[0]["created_at"],
                         tg._utc_now(), tg.STATUS_DELIVERED, 1, None)
        runner = runner_returning(ok(REPLY))
        self.assertEqual(self.scan(runner), [])
        self.assertEqual(runner.calls, [])

    def test_same_content_uses_the_cache(self):
        runner = runner_returning(ok(REPLY))
        self.scan(runner)
        self.store.execute("DELETE FROM events")
        self.store.execute("DELETE FROM watermarks")
        self.scan(runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.ledger_row()[1], "cached")

    def test_status_reports_use_and_fallbacks(self):
        self.scan(runner_returning(ok(REPLY)))
        self.store.execute(
            "INSERT INTO events (event_id, event_class, created_at, status, "
            "rewrite, rewrite_ms) VALUES ('x', 'gate-crossing', ?, "
            "'delivered', 'fallback:timeout: after 25s', 25000)",
            (tg._utc_now(),))
        status = tg.rewrite_status(self.store)
        self.assertEqual(status["used"], 1)
        self.assertEqual(status["fallback"], {"timeout": 1})
        self.assertIsInstance(status["median_ms"], int)
        self.assertEqual(status["window_days"], 28)

    def test_old_ledger_migrates(self):
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        old = sqlite3.connect(path)
        old.executescript(tg.SCHEMA_SQL)
        old.close()
        migrated = tg.open_store(path)
        columns = {r[1] for r in migrated.execute(
            "PRAGMA table_info(events)")}
        migrated.close()
        self.assertTrue({"rewrite", "rewrite_ms"} <= columns)


class NextLineTests(unittest.TestCase):
    MSG = tg.Message("watch", "Subnet 82 (Noah): changed", meaning="m",
                     facts=[("When", tg.fmt_time("2026-10-08T23:32:00+00:00"))])
    REPLY = {"headline": "Subnet 82 (Noah): miners lock most of the fee",
             "meaning": "m", "facts": [["Locked", "95%"]], "body": [],
             "next": "Check the lock-up first."}

    def test_model_next_only_when_allowed(self):
        new = tg._rewritten_message(self.MSG, self.REPLY, [self.MSG.facts[0]],
                                    True)
        self.assertEqual(new.next_action, "check the lock-up first.")
        new = tg._rewritten_message(self.MSG, self.REPLY, [self.MSG.facts[0]],
                                    False)
        self.assertIsNone(new.next_action)

    def test_code_next_is_never_replaced(self):
        msg = tg.Message("watch", "h", next_action="review your position.")
        new = tg._rewritten_message(msg, self.REPLY, [], True)
        self.assertEqual(new.next_action, "review your position.")

    def test_time_fact_survives_and_facts_are_capped(self):
        reply = dict(self.REPLY, facts=[["A", "1"], ["B", "2"]])
        new = tg._rewritten_message(self.MSG, reply, [self.MSG.facts[0]], True)
        self.assertEqual(len(new.facts), 2)
        self.assertEqual(new.facts[-1], self.MSG.facts[0])


if __name__ == "__main__":
    unittest.main()
