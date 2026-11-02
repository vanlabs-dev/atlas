"""Out-of-band health watch (change: alert-delivery-reliability): gateway,
scan heartbeat, LLM, unit failure streaks. No systemd, no network."""

import copy
import datetime
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_health as ah  # noqa: E402
import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

with open(os.path.join(_HERE, "fixtures", "gateway_state.json")) as _f:
    STATE = json.load(_f)
NOW = datetime.datetime(2026, 11, 3, 4, 3, tzinfo=datetime.timezone.utc)


class FakeReaders(ah.Readers):
    def __init__(self):
        self.units = {"hermes-gateway.service": {
            "ActiveState": "active", "MainPID": "1808391", "NRestarts": "0"}}
        self.state = copy.deepcopy(STATE)
        self.logs = {}
        self.clock = NOW
        self.local = datetime.datetime(2026, 11, 3, 17, 3)

    def show(self, unit, props, system=False):
        return dict(self.units.get(unit, {}))

    def read_text(self, path):
        if "gateway_state" in path:
            if self.state is None:
                return None
            if isinstance(self.state, str):
                return self.state
            return json.dumps(self.state)
        return None

    def tail(self, path, limit):
        return self.logs.get(os.path.basename(path), "")

    def now(self):
        return self.clock

    def now_local(self):
        return self.local


class Base(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.conn = tg.open_store(self.config["db"])
        ah.open_health(self.conn)
        self.readers = FakeReaders()
        self.sent = []
        self.deliver = True
        # Start every test with a fresh scan heartbeat.
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            (tg.SCAN_HEARTBEAT_KEY, NOW.isoformat()))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def send(self, msg, event_class, event_id):
        if self.deliver:
            self.sent.append((event_id, msg.plain()))
        return self.deliver

    def tick(self, minutes=5):
        summary = ah.run_health(self.conn, self.config, self.send,
                                self.readers)
        self.readers.clock += datetime.timedelta(minutes=minutes)
        self.readers.local += datetime.timedelta(minutes=minutes)
        self.readers.state["updated_at"] = self.readers.clock.isoformat()
        return summary


class GatewayTests(Base):
    def test_healthy_gateway_is_silent(self):
        self.tick()
        self.tick()
        self.assertEqual(self.sent, [])

    def test_restart_does_not_page(self):
        self.tick()
        self.readers.units["hermes-gateway.service"]["NRestarts"] = "1"
        summary = self.tick()
        self.assertEqual(summary["gateway"]["reason"],
                         "the gateway service restarted")
        self.tick()
        self.assertEqual(self.sent, [])

    def test_down_two_ticks_pages_once_then_recovers(self):
        self.readers.units["hermes-gateway.service"]["ActiveState"] = (
            "activating")
        self.tick()
        self.assertEqual(self.sent, [])
        self.tick()
        self.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("The Hermes gateway is down", self.sent[0][1])
        self.assertIn("activating", self.sent[0][1])
        self.readers.units["hermes-gateway.service"]["ActiveState"] = (
            "active")
        self.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("The Hermes gateway is back", self.sent[1][1])
        self.assertTrue(self.sent[1][0].endswith(":recovered"))
        # A new outage pages again.
        self.readers.units["hermes-gateway.service"]["ActiveState"] = (
            "failed")
        self.tick()
        self.tick()
        self.assertEqual(len(self.sent), 3)

    def test_malformed_state_file(self):
        self.readers.state = "{not json"
        reason = ah.check_gateway(self.readers, self.conn,
                                  ah.health_config(self.config))
        self.assertEqual(reason, "Atlas cannot read the gateway state file")
        self.readers.state = None
        self.assertEqual(ah.check_gateway(self.readers, self.conn,
                                          ah.health_config(self.config)),
                         "Atlas cannot read the gateway state file")

    def test_state_fields(self):
        hcfg = ah.health_config(self.config)
        cases = [
            (("platforms", "telegram", "state"), "disconnected",
             "the gateway's Telegram link is disconnected"),
            (("platforms", "telegram", "needs_attention"), True,
             "the gateway's Telegram link needs attention"),
            (("pid",), 1, "the gateway state file is from another process"),
            (("gateway_state",), "stopping", "the gateway reports stopping"),
            (("updated_at",), "2026-11-03T03:00:00+00:00",
             "the gateway stopped updating its state 63 minutes ago"),
        ]
        for path, value, expected in cases:
            self.readers.state = copy.deepcopy(STATE)
            target = self.readers.state
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertEqual(ah.check_gateway(self.readers, self.conn, hcfg),
                             expected, path)

    def test_pinned_shape_is_healthy(self):
        self.assertIsNone(ah.check_gateway(
            self.readers, self.conn, ah.health_config(self.config)))

    def test_unsent_page_retries_next_tick(self):
        self.readers.units["hermes-gateway.service"]["ActiveState"] = (
            "inactive")
        self.deliver = False
        self.tick()
        self.tick()
        self.deliver = True
        self.tick()
        self.assertEqual(len(self.sent), 1)


class ScanHeartbeatTests(Base):
    def test_stale_scan_pages_once(self):
        self.readers.clock = NOW + datetime.timedelta(hours=4)
        self.readers.state["updated_at"] = self.readers.clock.isoformat()
        self.tick()
        self.tick()
        scan = [s for s in self.sent if s[0].startswith("health:scan:")]
        self.assertEqual(len(scan), 1)
        self.assertIn("Atlas alerts are not being checked", scan[0][1])
        self.assertIn("atlas-alerts.service", scan[0][1])

    def test_fresh_deploy_waits_for_first_scan(self):
        self.conn.execute("DELETE FROM meta WHERE key = ?",
                          (tg.SCAN_HEARTBEAT_KEY,))
        self.tick(minutes=60)
        self.tick(minutes=60)
        self.assertEqual(self.sent, [])
        self.tick(minutes=120)
        self.tick()
        self.assertEqual(len([s for s in self.sent
                              if s[0].startswith("health:scan:")]), 1)


class LlmTests(Base):
    def test_expired_login_pages(self):
        self.readers.logs["agent.log"] = (
            "2026-11-03 16:00:01,000 INFO [x] agent.conversation_loop: "
            "API call #3: model=claude-opus-5-5 in=1 out=1\n"
            "2026-11-03 16:30:00,000 WARNING agent.conversation_loop: API "
            "call failed summary=Native API error: Failed to authenticate: "
            "OAuth session expired and could not be refreshed\n")
        self.tick()
        llm = [s for s in self.sent if s[0].startswith("health:llm:")]
        self.assertEqual(len(llm), 1)
        self.assertIn("the Claude login has expired", llm[0][1])
        self.assertNotIn("OAuth", llm[0][1])

    def test_success_after_failure_is_healthy(self):
        self.readers.logs["agent.log"] = (
            "2026-11-03 16:30:00,000 WARNING x: Failed to authenticate\n"
            "2026-11-03 16:40:00,000 INFO x: API call #1: model=m in=1\n")
        self.assertIsNone(ah.check_llm(self.readers, self.conn,
                                       ah.health_config(self.config)))

    def test_old_failure_outside_window_is_healthy(self):
        self.readers.logs["errors.log"] = (
            "2026-11-03 10:00:00,000 WARNING x: Failed to authenticate\n")
        self.assertIsNone(ah.check_llm(self.readers, self.conn,
                                       ah.health_config(self.config)))

    def _rewrite(self, event_id, note):
        tg.ledger_record(self.conn, event_id, "schema-drift",
                         (NOW - datetime.timedelta(minutes=10)).isoformat(),
                         None, "delivered", 1, None, rewrite=note)

    def test_single_fallback_is_healthy(self):
        self._rewrite("e1", "fallback:timeout: after 60s")
        self._rewrite("e2", "used")
        self.assertIsNone(ah.check_llm(self.readers, self.conn,
                                       ah.health_config(self.config)))

    def test_repeated_model_fallbacks_page(self):
        self._rewrite("e1", "fallback:hermes-error: exit 1")
        self._rewrite("e2", "fallback:timeout: after 60s")
        self.assertEqual(
            ah.check_llm(self.readers, self.conn,
                         ah.health_config(self.config)),
            "the plain-English rewrite failed 2 times in a row")


class UnitFailureTests(Base):
    def fail(self, unit="atlas-fleet.service", system=False):
        return ah.record_unit_failure(self.conn, unit, system,
                                      NOW.isoformat(), self.send)

    def test_three_failures_one_page(self):
        self.assertEqual(self.fail(), "paged")
        self.assertEqual(self.fail(), "counted")
        self.assertEqual(self.fail(), "counted")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Atlas job failed: atlas-fleet.service",
                      self.sent[0][1])
        self.assertIn("journalctl -b --user-unit=atlas-fleet.service",
                      self.sent[0][1])

    def test_fail_succeed_fail_pages_twice(self):
        self.fail()
        self.readers.units["atlas-fleet.service"] = {
            "Result": "success", "ActiveState": "inactive"}
        summary = self.tick()
        self.assertEqual(summary["units_closed"], ["atlas-fleet.service"])
        self.fail()
        self.assertEqual(len(self.sent), 2)

    def test_still_failed_keeps_streak(self):
        self.fail()
        self.readers.units["atlas-fleet.service"] = {
            "Result": "exit-code", "ActiveState": "failed"}
        self.tick()
        self.assertEqual(self.fail(), "counted")

    def test_system_unit_inspect_command(self):
        self.fail("atlas-dashboard.service", system=True)
        self.assertIn("journalctl -b -u atlas-dashboard.service",
                      self.sent[0][1])

    def test_unsent_page_is_retried_on_next_failure(self):
        self.deliver = False
        self.assertEqual(self.fail(), "unsent")
        self.deliver = True
        self.assertEqual(self.fail(), "paged")


class CliTests(unittest.TestCase):
    def test_health_and_unit_failed_commands(self):
        tg._SECRET_VALUES.clear()
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, "creds.env")
            with open(env, "w") as handle:
                handle.write("TELEGRAM_BOT_TOKEN=tok1234567890\n"
                             "TELEGRAM_ALERT_CHAT_ID=42\n")
            config = make_config(tmp, credential_env_files=[env])
            config["health"] = {
                "gateway_state_file": os.path.join(tmp, "missing.json"),
                "hermes_logs": []}
            sent = []

            def fake_send(msg, event_class, event_id=None, config=None,
                          poster=None):
                sent.append(event_id)
                return True
            original = tg.send_alert
            tg.send_alert = fake_send
            try:
                self.assertEqual(tg._cmd_unit_failed(
                    config, "atlas-probe.service", False), 0)
                self.assertEqual(tg._cmd_health(config), 0)
            finally:
                tg.send_alert = original
            self.assertTrue(sent[0].startswith(
                "unit-failure:atlas-probe.service:"))


if __name__ == "__main__":
    unittest.main()
