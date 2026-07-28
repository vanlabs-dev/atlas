"""Emission-gate poll (change: gate-crossing-signal): U64F64 decode and
bounds, null-storage semantics (assumed-default / gate-inactive),
fail-closed RPC handling, share-universe normalization (emission-disabled
INCLUDED), hysteresis + confirmation, and lifecycle guards (first-seed
silent, absence clears, reactivation re-seeds, restart no-replay)."""

import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402

# Live-observed encodings (Finney, 2026-07-28).
THETA_HEX = "0x3bd5bbc8102b5e020000000000000000"   # ~0.0092494
Q_075_HEX = "0x00000000000000c00000000000000000"   # 0.75
H_3_HEX = "0x" + (3 * 2 ** 64).to_bytes(16, "little").hex()
Q_BAD_HEX = "0x" + (2 * 2 ** 64).to_bytes(16, "little").hex()  # q = 2.0

KEYS = {
    "EmissionGateBar": "0xbar",
    "EmissionBarQuantile": "0xquantile",
    "EmissionGateExponent": "0xexponent",
}


def make_config(**gate_over):
    gate = {
        "enabled": True,
        "rpc_endpoints": ["https://rpc.invalid"],
        "storage_keys": dict(KEYS),
        "assumed_defaults": {"EmissionBarQuantile": 0.61,
                             "EmissionGateExponent": 3.0},
        "hysteresis_pct": 10,
        "confirm_polls": 2,
        "absence_clear_polls": 3,
        "rpc_timeout_seconds": 5,
    }
    gate.update(gate_over)
    return {
        "providers": {}, "db": "unused", "output_dir": "unused",
        "request_timeout_seconds": 5,
        "retry": {"default_attempts": 1, "retry_on_status": [],
                  "never_retry_on_status": [], "jitter_seconds": [0, 0]},
        "operations": {}, "gate_signal": gate,
    }


def fake_rpc(storage, head="0x" + "ab" * 32, number="0x84f1c1",
             fail=None):
    """storage: {pinned_key: hex_or_None}. fail: method name to fail."""
    def rpc(method, params):
        if method == fail:
            return {"ok": False, "error": "boom"}
        if method == "chain_getFinalizedHead":
            return {"ok": True, "result": head, "endpoint": "fake"}
        if method == "chain_getHeader":
            return {"ok": True, "result": {"number": number},
                    "endpoint": "fake"}
        if method == "state_getStorage":
            return {"ok": True, "result": storage.get(params[0]),
                    "endpoint": "fake"}
        raise AssertionError("unexpected method %s" % method)
    return rpc


def health_rows(conn):
    return conn.execute(
        "SELECT category, detail FROM integration_health").fetchall()


class DecodeTests(unittest.TestCase):
    def test_valid_values(self):
        self.assertAlmostEqual(al.decode_u64f64(Q_075_HEX), 0.75)
        self.assertAlmostEqual(al.decode_u64f64(H_3_HEX), 3.0)
        self.assertAlmostEqual(al.decode_u64f64(THETA_HEX),
                               0.009249393, places=6)

    def test_malformed_inputs_raise(self):
        for junk in ("0x1234", "0xzz", "nothex", None, 7):
            with self.assertRaises((ValueError, TypeError)):
                al.decode_u64f64(junk)


class PollGateStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        self.addCleanup(self.conn.close)
        self.config = make_config()

    def poll(self, storage, **kw):
        return al.poll_gate_state(self.conn, self.config,
                                  rpc=fake_rpc(storage, **kw))

    def test_valid_poll_persists_with_reference_block(self):
        state = self.poll({"0xbar": THETA_HEX, "0xquantile": Q_075_HEX,
                           "0xexponent": None})
        self.assertTrue(state["ok"] and state["gate_active"])
        row = self.conn.execute(
            "SELECT gate_active, theta, q, q_provenance, h, h_provenance, "
            "block_number FROM gate_state").fetchone()
        self.assertEqual(row[0], 1)
        self.assertAlmostEqual(row[1], 0.009249393, places=6)
        self.assertEqual((row[2], row[3]), (0.75, "explicit"))
        self.assertEqual((row[4], row[5]), (3.0, "assumed-default"))
        self.assertEqual(row[6], int("0x84f1c1", 16))

    def test_null_theta_persists_gate_inactive(self):
        state = self.poll({"0xbar": None, "0xquantile": None,
                           "0xexponent": None})
        self.assertTrue(state["ok"])
        self.assertFalse(state["gate_active"])
        row = self.conn.execute(
            "SELECT gate_active, theta, q, q_provenance FROM gate_state"
        ).fetchone()
        self.assertEqual(row[0], 0)
        self.assertIsNone(row[1])
        self.assertEqual((row[2], row[3]), (0.61, "assumed-default"))

    def test_out_of_bounds_persists_nothing(self):
        state = self.poll({"0xbar": THETA_HEX, "0xquantile": Q_BAD_HEX,
                           "0xexponent": None})
        self.assertFalse(state["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_state").fetchone()[0], 0)
        self.assertIn("validation-failure",
                      [r[0] for r in health_rows(self.conn)])

    def test_rpc_failure_fails_closed(self):
        state = al.poll_gate_state(
            self.conn, self.config,
            rpc=fake_rpc({}, fail="chain_getFinalizedHead"))
        self.assertFalse(state["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_state").fetchone()[0], 0)
        self.assertIn("provider-failure",
                      [r[0] for r in health_rows(self.conn)])

    def test_storage_read_failure_fails_closed(self):
        state = al.poll_gate_state(
            self.conn, self.config,
            rpc=fake_rpc({}, fail="state_getStorage"))
        self.assertFalse(state["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_state").fetchone()[0], 0)

    def test_parameter_change_is_visible(self):
        first = self.poll({"0xbar": THETA_HEX, "0xquantile": None,
                           "0xexponent": None})
        self.assertFalse(first["params_changed"])
        second = self.poll({"0xbar": THETA_HEX, "0xquantile": Q_075_HEX,
                            "0xexponent": None})
        self.assertTrue(second["params_changed"])
        provenances = [r[0] for r in self.conn.execute(
            "SELECT q_provenance FROM gate_state ORDER BY id")]
        self.assertEqual(provenances, ["assumed-default", "explicit"])


def panel(*rows):
    return [dict(row) for row in rows]


def subnet(netuid, price, burn=None, enabled=True):
    return {"netuid": netuid, "moving_price_tao": price,
            "emission_miner_burn": burn, "emission_is_enabled": enabled}


class DemandShareTests(unittest.TestCase):
    def test_universe_includes_disabled_and_excludes_root(self):
        shares, enabled = al.compute_demand_shares(panel(
            subnet(0, 1.0),                       # root: excluded
            subnet(1, 0.010, burn=0.0, enabled=True),
            subnet(2, 0.010, burn=0.0, enabled=False),  # stays IN
            subnet(3, 0.020, burn=50.0, enabled=True),  # weight halved
            {"netuid": 4, "moving_price_tao": None},    # unpriced: no share
        ))
        self.assertNotIn(0, shares)
        self.assertNotIn(4, shares)
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        self.assertAlmostEqual(shares[1], shares[2])
        self.assertAlmostEqual(shares[3], shares[1])  # 0.02 * 0.5 == 0.01
        self.assertEqual(enabled[2], False)

    def test_nothing_normalizable(self):
        shares, _enabled = al.compute_demand_shares(panel(
            subnet(1, 0.0), subnet(2, 0.0)))
        self.assertEqual(shares, {})


class GateSideTests(unittest.TestCase):
    THETA = 0.010

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "live.db")
        self.conn = al.open_store(self.db)
        self.addCleanup(self.conn.close)
        self.gcfg = {"hysteresis_pct": 10, "confirm_polls": 2,
                     "absence_clear_polls": 3}

    def step(self, shares, conn=None):
        return al.update_gate_sides(conn or self.conn, self.gcfg,
                                    self.THETA, shares,
                                    {n: True for n in shares}, 100)

    def event_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM gate_events").fetchone()[0]

    def test_first_observation_seeds_silently(self):
        events = self.step({1: 0.020, 2: 0.002})
        self.assertEqual(events, [])
        sides = dict(self.conn.execute(
            "SELECT netuid, side FROM gate_sides"))
        self.assertEqual(sides, {1: "above", 2: "below"})

    def test_wobble_inside_band_never_flips(self):
        self.step({1: 0.020})
        for share in (0.0101, 0.0095, 0.0104, 0.0092):  # inside ±10%
            self.assertEqual(self.step({1: share}), [])
        self.assertEqual(self.event_count(), 0)

    def test_confirmed_crossing_records_one_event(self):
        self.step({1: 0.020})
        self.assertEqual(self.step({1: 0.005}), [])  # 1st poll: pending
        events = self.step({1: 0.005})               # 2nd poll: confirmed
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["direction"], "fell-below")
        self.assertEqual(self.event_count(), 1)
        # No replay while it stays below.
        self.assertEqual(self.step({1: 0.005}), [])
        self.assertEqual(self.event_count(), 1)

    def test_bounce_resets_confirmation(self):
        self.step({1: 0.020})
        self.step({1: 0.005})            # pending fell-below (1)
        self.step({1: 0.020})            # back above: pending resets
        self.assertEqual(self.step({1: 0.005}), [])  # pending restarts at 1
        self.assertEqual(self.event_count(), 0)

    def test_restart_does_not_replay(self):
        self.step({1: 0.020})
        self.step({1: 0.005})
        self.step({1: 0.005})            # crossing recorded
        self.conn.close()
        reopened = al.open_store(self.db)
        self.addCleanup(reopened.close)
        self.conn = reopened
        self.assertEqual(self.step({1: 0.005}, conn=reopened), [])
        self.assertEqual(self.event_count(), 1)

    def test_absence_clears_and_reappearance_reseeds(self):
        self.step({1: 0.020, 2: 0.002})
        for _ in range(3):               # absence_clear_polls misses
            self.step({1: 0.020})
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM gate_sides WHERE netuid = 2").fetchone())
        # Reappearance on the OTHER side of the bar: silent re-seed.
        events = self.step({1: 0.020, 2: 0.030})
        self.assertEqual(events, [])
        self.assertEqual(self.conn.execute(
            "SELECT side FROM gate_sides WHERE netuid = 2").fetchone()[0],
            "above")
        self.assertEqual(self.event_count(), 0)


class GatePassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        self.addCleanup(self.conn.close)
        self.config = make_config()
        self.panel_rows = panel(subnet(1, 0.020), subnet(2, 0.002))

    def run_pass(self, storage, panel_status="ok"):
        def run_op(_conn, _config, _ledger, op_name, **_kw):
            self.assertEqual(op_name, "subnets_taoswap")
            if panel_status != "ok":
                return {"status": panel_status}
            return {"status": "ok",
                    "values": {"subnets": self.panel_rows}}
        return al.run_gate_pass(self.conn, self.config, ledger=None,
                                rpc=fake_rpc(storage), run_op=run_op)

    def test_kill_switch_is_inert(self):
        self.config["gate_signal"]["enabled"] = False
        summary = al.run_gate_pass(self.conn, self.config, ledger=None)
        self.assertEqual(summary, {"status": "disabled"})
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_state").fetchone()[0], 0)

    def test_inactive_gate_produces_no_events(self):
        summary = self.run_pass({"0xbar": None})
        self.assertEqual(summary["status"], "ok")
        self.assertFalse(summary["gate_active"])
        self.assertEqual(summary["events_recorded"], 0)

    def test_activation_reseeds_silently(self):
        self.run_pass({"0xbar": None})                    # inactive
        summary = self.run_pass({"0xbar": THETA_HEX})     # activates
        self.assertEqual(summary["events_recorded"], 0)   # silent re-seed
        self.assertEqual(summary["sides_tracked"], 2)

    def test_no_panel_no_events(self):
        summary = self.run_pass({"0xbar": THETA_HEX},
                                panel_status="live-unavailable")
        self.assertEqual(summary["panel"], "live-unavailable")
        self.assertEqual(summary["events_recorded"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_sides").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
