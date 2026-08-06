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


def rank_hex(value):
    """SCALE u16, 2 bytes little-endian (change: network-drift-443)."""
    return "0x" + int(value).to_bytes(2, "little").hex()


RANK_32_HEX = rank_hex(32)
RANK_64_HEX = rank_hex(64)
RANK_0_HEX = rank_hex(0)
BOOL_TRUE_HEX = "0x01"
BOOL_FALSE_HEX = "0x00"

KEYS = {
    "EmissionGateBar": "0xbar",
    "EmissionBarQuantile": "0xquantile",
    "EmissionGateExponent": "0xexponent",
    "EmissionBarRank": "0xrank",
}

ROOT_SWITCH_KEY = "0xrootswitch"


def watch_items():
    return [
        {"item": "EmissionBarRank", "source": "gate-poll", "codec": "u16",
         "default": 32, "governs": "bar selection"},
        {"item": "EmissionBarQuantile", "source": "gate-poll",
         "codec": "u64f64", "default": 0.61, "governs": "q-mass threshold"},
        {"item": "EmissionGateExponent", "source": "gate-poll",
         "codec": "u64f64", "default": 3.0, "governs": "gate sharpness"},
        {"item": "RootWeightSettingEnabled", "source": "independent",
         "key": ROOT_SWITCH_KEY, "codec": "bool", "default": False,
         "governs": "Root Reborn basket curation master switch"},
    ]


def make_config(watch_enabled=False, **gate_over):
    gate = {
        "enabled": True,
        "rpc_endpoints": ["https://rpc.invalid"],
        "storage_keys": dict(KEYS),
        "assumed_defaults": {"EmissionBarQuantile": 0.61,
                             "EmissionGateExponent": 3.0,
                             "EmissionBarRank": 32},
        "hysteresis_pct": 10,
        "confirm_polls": 2,
        "absence_clear_polls": 3,
        "rpc_timeout_seconds": 5,
        "above_count_tolerance": 0,
    }
    gate.update(gate_over)
    return {
        "providers": {}, "db": "unused", "output_dir": "unused",
        "request_timeout_seconds": 5,
        "retry": {"default_attempts": 1, "retry_on_status": [],
                  "never_retry_on_status": [], "jitter_seconds": [0, 0]},
        "operations": {}, "gate_signal": gate,
        "chain_params": {"enabled": watch_enabled, "items": watch_items()},
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

    # --- per-item codecs (change: network-drift-443) -------------------

    def test_u16_round_trip(self):
        for value in (0, 1, 32, 64, 65535):
            self.assertEqual(al.decode_u16(rank_hex(value)), value)

    def test_bool_round_trip(self):
        self.assertIs(al.decode_bool(BOOL_TRUE_HEX), True)
        self.assertIs(al.decode_bool(BOOL_FALSE_HEX), False)

    def test_codecs_are_not_interchangeable(self):
        # The whole point of a declared codec: a fixed-point payload fed to
        # the integer decoder must fail loudly, not decode to nonsense.
        with self.assertRaises(ValueError):
            al.decode_u16(Q_075_HEX)
        with self.assertRaises(ValueError):
            al.decode_u64f64(RANK_32_HEX)
        with self.assertRaises(ValueError):
            al.decode_bool(RANK_32_HEX)

    def test_bool_rejects_correct_length_non_boolean(self):
        # Length checking alone would pass 0x02.
        with self.assertRaises(ValueError):
            al.decode_bool("0x02")

    def test_codec_dispatch(self):
        self.assertEqual(al.decode_by_codec("u16", RANK_32_HEX), 32)
        self.assertIs(al.decode_by_codec("bool", BOOL_TRUE_HEX), True)
        self.assertAlmostEqual(al.decode_by_codec("u64f64", Q_075_HEX), 0.75)
        with self.assertRaises(ValueError):
            al.decode_by_codec("nonesuch", RANK_32_HEX)

    def test_param_value_text_is_canonical(self):
        self.assertEqual(al.param_value_text(True), "true")
        self.assertEqual(al.param_value_text(False), "false")
        self.assertEqual(al.param_value_text(32), "32")
        self.assertEqual(al.param_value_text(0.75), "0.75")


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
        self.poll({"0xbar": THETA_HEX, "0xquantile": None,
                   "0xexponent": None})
        self.poll({"0xbar": THETA_HEX, "0xquantile": Q_075_HEX,
                   "0xexponent": None})
        provenances = [r[0] for r in self.conn.execute(
            "SELECT q_provenance FROM gate_state ORDER BY id")]
        self.assertEqual(provenances, ["assumed-default", "explicit"])

    # --- rank / bar mode (change: network-drift-443) -------------------

    def test_rank_explicit_sets_rank_mode(self):
        state = self.poll({"0xbar": THETA_HEX, "0xrank": RANK_64_HEX})
        self.assertEqual((state["rank"], state["rank_provenance"]),
                         (64, "explicit"))
        self.assertEqual(state["bar_mode"], al.GATE_MODE_RANK)
        row = self.conn.execute(
            "SELECT rank, rank_provenance, bar_mode FROM gate_state"
        ).fetchone()
        self.assertEqual(row, (64, "explicit", "rank"))

    def test_null_rank_uses_assumed_default(self):
        state = self.poll({"0xbar": THETA_HEX, "0xrank": None})
        self.assertEqual((state["rank"], state["rank_provenance"]),
                         (32, "assumed-default"))
        # Mode is derived from the EFFECTIVE rank, default included.
        self.assertEqual(state["bar_mode"], al.GATE_MODE_RANK)

    def test_zero_rank_is_q_mass_mode(self):
        state = self.poll({"0xbar": THETA_HEX, "0xrank": RANK_0_HEX})
        self.assertEqual(state["rank"], 0)
        self.assertEqual(state["bar_mode"], al.GATE_MODE_QMASS)

    def test_malformed_rank_persists_nothing(self):
        # A U64F64 payload where a u16 is expected must fail loudly.
        state = self.poll({"0xbar": THETA_HEX, "0xrank": Q_075_HEX})
        self.assertFalse(state["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_state").fetchone()[0], 0)
        self.assertIn("validation-failure",
                      [r[0] for r in health_rows(self.conn)])

    def test_bar_params_are_handed_to_the_watch(self):
        state = self.poll({"0xbar": THETA_HEX, "0xquantile": Q_075_HEX,
                           "0xrank": RANK_64_HEX})
        self.assertEqual(state["bar_params"]["EmissionBarRank"],
                         (64, "explicit"))
        self.assertEqual(state["bar_params"]["EmissionBarQuantile"],
                         (0.75, "explicit"))
        self.assertEqual(state["bar_params"]["EmissionGateExponent"],
                         (3.0, "assumed-default"))

    def test_prev_theta_is_carried_forward(self):
        first = self.poll({"0xbar": THETA_HEX})
        self.assertIsNone(first["prev_theta"])
        other = "0x" + int(0.005 * 2 ** 64).to_bytes(16, "little").hex()
        second = self.poll({"0xbar": other})
        self.assertAlmostEqual(second["prev_theta"], 0.009249393, places=6)


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


# ---------------------------------------------------------------------------
# Chain-parameter watch (change: network-drift-443)
# ---------------------------------------------------------------------------

class ChainParamWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        # Bound late: the restart test swaps self.conn, and the replacement
        # must be the one that gets closed or Windows keeps the file locked.
        self.addCleanup(lambda: self.conn.close())
        self.config = make_config(watch_enabled=True)

    def watch(self, storage, bar_params=None, **kw):
        return al.run_chain_param_watch(
            self.conn, self.config, rpc=fake_rpc(storage, **kw),
            bar_params=bar_params)

    def values(self, item):
        return [r[0] for r in self.conn.execute(
            "SELECT value FROM chain_params WHERE item = ? ORDER BY id",
            (item,))]

    def transitions(self):
        return self.conn.execute(
            "SELECT item, prev_value, new_value FROM chain_param_events "
            "ORDER BY id").fetchall()

    def test_disabled_watch_is_inert(self):
        self.config["chain_params"]["enabled"] = False
        result = al.run_chain_param_watch(self.conn, self.config)
        self.assertEqual(result, {"status": "disabled"})
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM chain_params").fetchone()[0], 0)

    def test_first_observation_seeds_without_transition(self):
        result = self.watch({ROOT_SWITCH_KEY: None},
                            bar_params={"EmissionBarRank":
                                        (32, "assumed-default")})
        self.assertIn("EmissionBarRank", result["observed"])
        self.assertIn("RootWeightSettingEnabled", result["observed"])
        self.assertEqual(result["transitions"], [])
        self.assertEqual(self.transitions(), [])

    def test_value_change_records_a_transition(self):
        self.watch({ROOT_SWITCH_KEY: None})
        result = self.watch({ROOT_SWITCH_KEY: BOOL_TRUE_HEX})
        self.assertEqual(
            [(t["item"], t["prev_value"], t["new_value"])
             for t in result["transitions"]],
            [("RootWeightSettingEnabled", "false", "true")])
        self.assertEqual(
            self.transitions(),
            [("RootWeightSettingEnabled", "false", "true")])

    def test_provenance_only_change_is_not_a_transition(self):
        # Governance pinning the switch to the value it already had by
        # default changes nothing economically.
        self.watch({ROOT_SWITCH_KEY: None})            # assumed-default
        result = self.watch({ROOT_SWITCH_KEY: BOOL_FALSE_HEX})  # explicit
        self.assertEqual(result["transitions"], [])
        self.assertEqual(self.transitions(), [])
        provenances = [r[0] for r in self.conn.execute(
            "SELECT provenance FROM chain_params "
            "WHERE item = 'RootWeightSettingEnabled' ORDER BY id")]
        self.assertEqual(provenances, ["assumed-default", "explicit"])

    def test_bar_params_recorded_without_a_second_read(self):
        reads = []

        def counting_rpc(method, params):
            if method == "state_getStorage":
                reads.append(params[0])
                return {"ok": True, "result": None, "endpoint": "fake"}
            if method == "chain_getFinalizedHead":
                return {"ok": True, "result": "0xhead", "endpoint": "fake"}
            return {"ok": True, "result": {"number": "0x1"},
                    "endpoint": "fake"}

        al.run_chain_param_watch(
            self.conn, self.config, rpc=counting_rpc,
            bar_params={"EmissionBarRank": (32, "explicit"),
                        "EmissionBarQuantile": (0.75, "explicit"),
                        "EmissionGateExponent": (3.0, "assumed-default")},
            block_hash="0xhead", block_number=7)
        # Only the independent item is read from storage.
        self.assertEqual(reads, [ROOT_SWITCH_KEY])
        self.assertEqual(self.values("EmissionBarRank"), ["32"])

    def test_gate_params_skipped_when_gate_poll_did_not_run(self):
        result = self.watch({ROOT_SWITCH_KEY: None}, bar_params=None)
        self.assertEqual(result["observed"], ["RootWeightSettingEnabled"])
        self.assertIn("EmissionBarRank", result["skipped"])

    def test_watch_runs_without_a_supplied_block(self):
        # Gate kill-switch path: the watch obtains its own head.
        result = self.watch({ROOT_SWITCH_KEY: BOOL_TRUE_HEX})
        self.assertEqual(result["observed"], ["RootWeightSettingEnabled"])
        self.assertEqual(self.values("RootWeightSettingEnabled"), ["true"])

    def test_one_unreadable_item_does_not_blind_the_rest(self):
        result = self.watch({}, bar_params={"EmissionBarRank":
                                            (32, "explicit")},
                            fail="state_getStorage")
        self.assertEqual(result["observed"], ["EmissionBarRank"])
        self.assertIn("RootWeightSettingEnabled", result["skipped"])
        self.assertIn("provider-failure",
                      [r[0] for r in health_rows(self.conn)])

    def test_malformed_independent_item_is_isolated(self):
        result = self.watch({ROOT_SWITCH_KEY: "0x02"},
                            bar_params={"EmissionBarRank":
                                        (32, "explicit")})
        self.assertEqual(result["observed"], ["EmissionBarRank"])
        self.assertIn("RootWeightSettingEnabled", result["skipped"])
        self.assertIn("validation-failure",
                      [r[0] for r in health_rows(self.conn)])

    def test_no_re_emission_across_restart(self):
        self.watch({ROOT_SWITCH_KEY: None})
        self.watch({ROOT_SWITCH_KEY: BOOL_TRUE_HEX})     # one transition
        self.conn.close()
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        result = self.watch({ROOT_SWITCH_KEY: BOOL_TRUE_HEX})
        self.assertEqual(result["transitions"], [])
        self.assertEqual(len(self.transitions()), 1)


# ---------------------------------------------------------------------------
# Storm suppression, attribution, and the rank invariant
# (change: network-drift-443)
# ---------------------------------------------------------------------------

class BarRepricingTests(unittest.TestCase):
    """The spec-441 bar reset on 2026-08-03 dropped theta ~14.5% in one
    poll and pushed four subnets across the bar in a single pass. Their
    demand had not moved; the bar came down onto them. Those four alerts
    were paged as demand events, and misinformed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        self.addCleanup(self.conn.close)
        self.config = make_config(watch_enabled=True, confirm_polls=1)
        # Four subnets parked just above a falling bar, one far below.
        self.panel_rows = panel(subnet(49, 0.0086), subnet(67, 0.0089),
                                subnet(79, 0.0094), subnet(81, 0.0086),
                                subnet(9, 0.0002))

    def run_pass(self, storage):
        def run_op(_conn, _config, _ledger, _op, **_kw):
            return {"status": "ok",
                    "values": {"subnets": self.panel_rows}}
        return al.run_gate_pass(self.conn, self.config, ledger=None,
                                rpc=fake_rpc(storage), run_op=run_op)

    @staticmethod
    def theta_hex(value):
        return "0x" + int(value * 2 ** 64).to_bytes(16, "little").hex()

    def test_bar_parameter_change_reseeds_instead_of_storming(self):
        # Pass 1: high bar, rank 32 -> everyone below, sides seeded.
        self.run_pass({"0xbar": self.theta_hex(0.30),
                       "0xrank": RANK_32_HEX})
        # Pass 2: governance moves the rank AND the bar drops onto the four.
        summary = self.run_pass({"0xbar": self.theta_hex(0.0073),
                                 "0xrank": RANK_64_HEX})
        self.assertEqual(summary["reseeded"], ["EmissionBarRank"])
        self.assertEqual(summary["events_recorded"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM gate_events").fetchone()[0], 0)
        # Sides were re-seeded, not left stale.
        self.assertEqual(summary["sides_tracked"], 5)
        above = self.conn.execute(
            "SELECT COUNT(*) FROM gate_sides WHERE side = 'above'"
        ).fetchone()[0]
        self.assertEqual(above, 4)
        # The transition itself is durable and reportable.
        self.assertEqual(self.conn.execute(
            "SELECT item, prev_value, new_value FROM chain_param_events"
        ).fetchall(), [("EmissionBarRank", "32", "64")])

    def test_ordinary_crossing_still_pages_and_carries_prev_theta(self):
        self.run_pass({"0xbar": self.theta_hex(0.30),
                       "0xrank": RANK_32_HEX})      # all below
        # Bar unchanged in parameter terms; subnet demand moves instead.
        self.panel_rows = panel(subnet(49, 0.90), subnet(67, 0.0089),
                                subnet(79, 0.0094), subnet(81, 0.0086),
                                subnet(9, 0.0002))
        summary = self.run_pass({"0xbar": self.theta_hex(0.30),
                                 "0xrank": RANK_32_HEX})
        self.assertNotIn("reseeded", summary)
        self.assertEqual(summary["events_recorded"], 1)
        row = self.conn.execute(
            "SELECT netuid, direction, theta, prev_theta FROM gate_events"
        ).fetchone()
        self.assertEqual((row[0], row[1]), (49, "rose-above"))
        # prev_theta lets a reader tell a moved bar from a moved share.
        self.assertAlmostEqual(row[2], row[3], places=9)


class RankInvariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = al.open_store(os.path.join(self.tmp.name, "live.db"))
        self.addCleanup(self.conn.close)
        self.config = make_config()
        # Three of five shares sit at or above theta = 0.15.
        self.panel_rows = panel(subnet(1, 0.30), subnet(2, 0.30),
                                subnet(3, 0.30), subnet(4, 0.05),
                                subnet(5, 0.05))

    def run_pass(self, rank):
        def run_op(_conn, _config, _ledger, _op, **_kw):
            return {"status": "ok",
                    "values": {"subnets": self.panel_rows}}
        theta = "0x" + int(0.15 * 2 ** 64).to_bytes(16, "little").hex()
        return al.run_gate_pass(
            self.conn, self.config, ledger=None,
            rpc=fake_rpc({"0xbar": theta, "0xrank": rank_hex(rank)}),
            run_op=run_op)

    def categories(self):
        return [r[0] for r in health_rows(self.conn)]

    def test_agreeing_count_is_silent(self):
        summary = self.run_pass(3)
        self.assertEqual(summary["above_count"], 3)
        self.assertNotIn("invariant-divergence", self.categories())
        self.assertEqual(self.conn.execute(
            "SELECT above_count FROM gate_state ORDER BY id DESC LIMIT 1"
        ).fetchone()[0], 3)

    def test_diverging_count_raises_a_health_event(self):
        summary = self.run_pass(32)
        self.assertEqual(summary["above_count"], 3)
        self.assertIn("invariant-divergence", self.categories())
        # Information, not an error: the pass still persisted.
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["sides_tracked"], 5)

    def test_no_check_in_q_mass_mode(self):
        summary = self.run_pass(0)
        self.assertIsNone(summary["above_count"])
        self.assertNotIn("invariant-divergence", self.categories())


if __name__ == "__main__":
    unittest.main()
