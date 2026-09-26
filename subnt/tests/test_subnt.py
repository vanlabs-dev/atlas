"""Subnt publisher tests: store-only composition, the six data files and
their schema, per-input stale bounds, deltas against the previous subnt
publish, the attention row shape, the operator-exclusion scan, and the
fact-gated publish. Every test builds its own stores; none touches a
device, a network, or the real remote."""

import contextlib
import datetime
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "fleet"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "fleet", "tests"))

import atlas_subnt as sh  # noqa: E402


SECTION_IDS = ("network", "movers", "mining", "attention", "code-narrative")
FILE_NAMES = ("edition.json", "network.json", "movers.json", "mining.json",
              "attention.json", "code.json")


def _iso(hours_ago=0.0, anchor=None):
    base = anchor or datetime.datetime.now(datetime.timezone.utc)
    return (base - datetime.timedelta(hours=hours_ago)).isoformat()


# ---------------------------------------------------------------------------
# Fixture stores. Built with the real modules' own schema, so a column that
# moves upstream breaks these tests instead of the device.
# ---------------------------------------------------------------------------

def build_live(path, vitals_hours=2.0, gate_hours=1.0, with_names=True,
               anchor=None, rank=32, above_count=32):
    import atlas_live as live
    conn = live.open_store(path)
    conn.execute("INSERT INTO meta (key, value) VALUES ('last_live_spec', "
                 "'455')")
    conn.execute(
        "INSERT INTO gate_state (observed_at, gate_active, theta, q, "
        "q_provenance, h, h_provenance, endpoint, rank, above_count) "
        "VALUES (?, 1, 0.00412, 0.75, 'assumed-default', 0.1, "
        "'assumed-default', 'finney', ?, ?)",
        (_iso(gate_hours, anchor), rank, above_count))
    conn.execute(
        "INSERT INTO chain_param_events (item, prev_value, new_value, "
        "prev_provenance, new_provenance, observed_at) VALUES "
        "('RootWeightsCap', '4096', '8192', 'read', 'read', ?)",
        (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO gate_events (observed_at, netuid, direction, share, "
        "theta, prev_side) VALUES (?, 12, 'up', 0.005, 0.004, 'below')",
        (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO gate_sides (netuid, side, updated_at, hovering) "
        "VALUES (7, 'above', ?, 1)", (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO network_vitals (date, observed_at, total_staked_tao, "
        "subnets_share_pct, new_accounts_today, tao_usd) VALUES "
        "('2026-09-08', ?, 7313368.0, 27.65, 1420, 318.42)",
        (_iso(vitals_hours, anchor),))
    for i, (netuid, old, new) in enumerate(
            ((12, 0.00100, 0.00200), (44, 0.00500, 0.00505))):
        conn.execute(
            "INSERT INTO panel_snapshot (observed_at, block_number, netuid, "
            "share, moving_price_tao, dereg_risk_level, "
            "conviction_is_contested, takeover_eligible, name) VALUES "
            "(?, ?, ?, ?, ?, 'low', 0, 0, ?)",
            (_iso(5.0, anchor), 9018000 + i, netuid, 0.010, old,
             ("Subnet %d" % netuid) if with_names else None))
        conn.execute(
            "INSERT INTO panel_snapshot (observed_at, block_number, netuid, "
            "share, moving_price_tao, dereg_risk_level, "
            "conviction_is_contested, takeover_eligible, name) VALUES "
            "(?, ?, ?, ?, ?, 'high', 1, 0, ?)",
            (_iso(0.5, anchor), 9018443 + i, netuid, 0.020, new,
             ("Subnet %d" % netuid) if with_names else None))
    conn.commit()
    conn.close()


def build_fleet(path, verdict_text="reward split moved to the owner",
                anchor=None):
    import atlas_fleet as fleet
    import atlas_fleet_metrics as met
    import atlas_fleet_signals as sig
    import atlas_fleet_mining as mining
    conn = fleet.open_store(path)
    met.ensure_schema(conn)
    sig.ensure_schema(conn)
    mining.ensure_schema(conn)
    pass_ts = _iso(0.5, anchor)
    for netuid in (12, 44, 67):
        conn.execute(
            "INSERT INTO slots (netuid, github_repo, epoch, status, "
            "last_reconciled) VALUES (?, ?, 1, 'active', ?)",
            (netuid, "https://github.com/org%d/repo" % netuid, pass_ts))
        conn.execute(
            "INSERT INTO metric_activity (netuid, epoch, pass_ts, c7, c30, "
            "c90, a30, days_since, total_commits, total_authors) VALUES "
            "(?, 1, ?, ?, 20, 60, 3, ?, 900, 12)",
            (netuid, pass_ts, 3 if netuid != 67 else 0,
             2 if netuid != 67 else 200))
        conn.execute(
            "INSERT INTO metric_branch_tips (netuid, epoch, pass_ts, "
            "tips_json, tips_count, changed_tips) VALUES (?, 1, ?, '[]', "
            "4, ?)", (netuid, pass_ts, 2 if netuid == 12 else 0))
    conn.execute(
        "INSERT INTO signal_econ_verdicts (content_hash, netuid, "
        "matched_files, significance, direction, what_changed, outcome, "
        "created_at) VALUES ('h1', 12, 'rewards.py', 'high', 'owner', ?, "
        "'judged', ?)", (verdict_text, _iso(1.0, anchor)))
    conn.execute(
        "INSERT INTO signal_econ_verdicts (content_hash, netuid, "
        "matched_files, significance, direction, what_changed, outcome, "
        "created_at) VALUES ('h2', 44, 'weights.py', 'med', 'reshuffle', "
        "'miner ranking reshuffled', 'judged', ?)", (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO epochs (netuid, epoch, opened_at) VALUES (44, 2, ?)",
        (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO signal_adoptions (term, kind, netuid, epoch, "
        "adopted_at, seeded) VALUES ('qwen3-32b', 'model-id', 12, 1, ?, 0)",
        (_iso(1.0, anchor),))
    conn.execute(
        "INSERT INTO signal_events (class, tier, netuid, term, dedup_key, "
        "payload_json, created_at) VALUES ('narrative-cluster', 'briefing', "
        "NULL, 'agentic-rl', 'k1', '{}', ?)", (_iso(1.0, anchor),))
    conn.commit()
    # Mining rows come from the real writer: SN12 heads, SN44 second, SN67
    # is cut winner-take-all.
    import mining_fixtures as mf
    mf.seed_board(conn, {"mining": {"enabled": True}}, mf.synthetic([
        mf.subnet(12, [10, 9, 8], tao_pool=60_000.0),
        mf.subnet(44, [10, 9, 8], tao_pool=40_000.0),
        mf.subnet(67, [10, 0, 0])]), now=pass_ts)
    conn.close()


def make_config(tmp, **overrides):
    config = {
        "enabled": True,
        "publish": False,
        "checkout_dir": os.path.join(tmp, "checkout"),
        "data_dir": "data",
        "state_db": os.path.join(tmp, "state", "subnt.db"),
        "commit_name": "vanlabs-dev",
        "commit_email": "vanlabs@pm.me",
        "branch": "main",
        "window_hours": 6,
        "stale_hours": 26,
        "price_move_threshold_pct": 15,
        "share_move_threshold_pct": 25,
        "attention_rows": 10,
        "live_db": os.path.join(tmp, "livedata.db"),
        "fleet_db": os.path.join(tmp, "fleet.db"),
        "repo_db": os.path.join(tmp, "repotrack.db"),
        "knowledge_db": os.path.join(tmp, "knowledge.db"),
    }
    config.update(overrides)
    return config


def full(tmp, **overrides):
    config = make_config(tmp, **overrides)
    build_live(config["live_db"])
    build_fleet(config["fleet_db"])
    return config


def docs(files):
    return {name: json.loads(text) for name, text in files.items()}


def fact(doc, fid):
    for block in doc["blocks"]:
        for item in block["facts"]:
            if item["id"] == fid:
                return item
    return None


def texts(doc, key):
    return [t for block in doc["blocks"] for t in block.get(key, [])]


class ComposeShapeTests(unittest.TestCase):
    """The six files, full and empty, in the contract order."""

    def test_full_edition_is_six_valid_files_in_contract_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, problems = sh.build(full(tmp), None)
            self.assertEqual(problems, [])
            self.assertEqual(tuple(files), FILE_NAMES)
            parsed = docs(files)
            self.assertEqual(parsed["edition.json"]["kind"], "edition")
            self.assertEqual(
                tuple(parsed[n]["section"] for n in FILE_NAMES[1:]),
                SECTION_IDS)
            code = parsed["code.json"]
            self.assertEqual([b["id"] for b in code["blocks"]],
                             ["code", "narrative"])
            self.assertEqual([b["title"] for b in code["blocks"]],
                             ["Code", "Narrative"])
            for name in FILE_NAMES:
                self.assertEqual(parsed[name]["schema"], "subnt/1.0")
            for name in FILE_NAMES[1:]:
                self.assertEqual(parsed[name]["access"], "public")
                for block in parsed[name]["blocks"]:
                    self.assertEqual(block["access"], "public")

    def test_empty_edition_keeps_every_file_and_names_its_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            edition, files, problems = sh.build(make_config(tmp), None)
            self.assertEqual(problems, [])
            self.assertEqual(tuple(files), FILE_NAMES)
            self.assertIsNone(edition["block"])
            everything = "".join(files.values())
            for phrase in ("Missing the live store",
                           "Missing panel snapshots",
                           "Missing the mining screen",
                           "Missing the fleet store"):
                self.assertIn(phrase, everything)
            for name, doc in docs(files).items():
                if name != "edition.json":
                    self.assertTrue(doc["lead"])

    def test_every_file_is_one_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            parsed = docs(files)
            ed = parsed["edition.json"]
            for name in FILE_NAMES[1:]:
                self.assertEqual(parsed[name]["composed_at"],
                                 ed["composed_at"])
                self.assertEqual(parsed[name]["block"], ed["block"])

    def test_serialised_text_is_not_ascii_escaped(self):
        self.assertIn("τ", sh.serialise({"name": "hoτfloaτ"}))
        self.assertTrue(sh.serialise({}).endswith("\n"))


class AsOfTests(unittest.TestCase):
    """composed_at is UTC to the second; block is the newest panel block."""

    def test_block_is_the_newest_panel_snapshot_block(self):
        noon = datetime.datetime(2026, 9, 9, 12, 0, 7,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            edition, files, _p = sh.build(config, None, now=noon)
            ed = docs(files)["edition.json"]
            self.assertEqual(edition["block"], 9018444)
            self.assertEqual(ed["block"], 9018444)
            self.assertEqual(ed["composed_at"], "2026-09-09T12:00:07Z")

    def test_missing_block_is_null_in_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, problems = sh.build(make_config(tmp), None)
            self.assertEqual(problems, [])
            for doc in docs(files).values():
                self.assertIsNone(doc["block"])


class StaleBoundTests(unittest.TestCase):
    """Bounds are per input, not a blanket six hours."""

    def test_bar_past_twenty_six_hours_is_stale_and_shows_no_theta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], gate_hours=27.0)
            edition, files, _p = sh.build(config, None)
            network = docs(files)["network.json"]
            self.assertTrue(any("emission-gate bar is stale" in g
                                for g in texts(network, "gaps")))
            self.assertIsNone(fact(network, "bar"))
            self.assertNotIn("0.00412", files["network.json"])
            self.assertNotIn("theta", edition["figures"])

    def test_bar_inside_the_bound_shows_its_figure(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], gate_hours=20.0)
            edition, files, _p = sh.build(config, None)
            bar = fact(docs(files)["network.json"], "bar")
            self.assertEqual(bar["text"], "0.412%")
            self.assertEqual(bar["value"], 0.00412)
            self.assertNotIn("stale", files["network.json"])
            self.assertEqual(edition["figures"]["theta"], 0.00412)

    def test_bar_is_dated_from_its_own_row_not_the_edition_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            _e, files, _p = sh.build(config, None)
            bar = fact(docs(files)["network.json"], "bar")
            self.assertNotIn("ref_block", bar)
            self.assertRegex(bar["observed"], r"^\d{4}-\d{2}-\d{2}$")

    def test_vitals_older_than_six_hours_are_dated_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], vitals_hours=20.0)
            _e, files, _p = sh.build(config, None)
            tao = fact(docs(files)["network.json"], "tao")
            self.assertEqual(tao["text"], "$318.42")
            self.assertEqual(tao["observed"], "2026-09-08")
            self.assertEqual(tao["freshness"], "observed 2026-09-08")
            self.assertNotIn("stale", tao)
            self.assertNotIn("vitals are stale",
                             files["network.json"].lower())


class DeltaTests(unittest.TestCase):
    """Deltas compare against the previous subnt publish only."""

    def _all_deltas(self, files):
        return [f.get("delta") for d in docs(files).values()
                for b in d.get("blocks", []) for f in b["facts"]]

    def test_first_edition_states_so_and_shows_no_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            state = sh.open_state(config["state_db"])
            try:
                edition, files, _p = sh.build(config, state)
            finally:
                state.close()
            ed = docs(files)["edition.json"]
            self.assertTrue(edition["first_edition"])
            self.assertTrue(ed["first_edition"])
            self.assertIsNone(ed["previous_composed_at"])
            self.assertTrue(all(d is None for d in self._all_deltas(files)))

    def test_a_stray_figure_set_without_a_publish_shows_no_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            state = sh.open_state(config["state_db"])
            try:
                sh.state_set(state, "figures", json.dumps({"theta": 0.002}))
                _e, files, _p = sh.build(config, state)
            finally:
                state.close()
            self.assertTrue(all(d is None for d in self._all_deltas(files)))

    def test_later_edition_compares_against_the_stored_figure_set(self):
        noon = datetime.datetime(2026, 9, 9, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], anchor=noon)
            state = sh.open_state(config["state_db"])
            try:
                sh.state_set(state, "figures",
                             json.dumps({"theta": 0.00206, "tao_usd": 300.0}))
                sh.state_set(state, "published_at", _iso(6.0, noon))
                edition, files, problems = sh.build(config, state, now=noon)
            finally:
                state.close()
            self.assertEqual(problems, [])
            parsed = docs(files)
            ed = parsed["edition.json"]
            self.assertFalse(ed["first_edition"])
            self.assertEqual(ed["previous_composed_at"],
                             "2026-09-09T06:00:00Z")
            network = parsed["network.json"]
            self.assertEqual(fact(network, "bar")["delta"],
                             {"text": "+100.0% since last publish",
                              "direction": "up"})
            self.assertEqual(fact(network, "tao")["delta"],
                             {"text": "+6.1% since last publish",
                              "direction": "up"})

    def test_a_fall_reads_down(self):
        self.assertEqual(sh._delta(90.0, 100.0)["direction"], "down")

    def test_window_follows_the_previous_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            state = sh.open_state(config["state_db"])
            marker = _iso(6.0)
            try:
                sh.state_set(state, "published_at", marker)
                edition = sh.compose(config, state)
            finally:
                state.close()
            self.assertEqual(edition["window_start"], marker)

    def test_composing_without_publishing_leaves_the_stored_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            result = sh.run(config)  # publish is False
            self.assertEqual(result["status"], "composed")
            state = sh.open_state(config["state_db"])
            try:
                self.assertIsNone(sh.state_get(state, "figures"))
                self.assertIsNone(sh.state_get(state, "published_at"))
            finally:
                state.close()

    def test_notifier_store_is_never_read_for_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            notifier = os.path.join(tmp, "notifier.db")
            conn = sqlite3.connect(notifier)
            conn.executescript(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
            conn.execute("INSERT INTO meta VALUES ('briefing:figures:daily', "
                         "'{\"theta\": 999.0}')")
            conn.commit()
            conn.close()
            edition, files, _p = sh.build(config, None)
            self.assertNotEqual(edition["figures"].get("theta"), 999.0)
            everything = "".join(files.values())
            self.assertNotIn("999.0", everything)
            self.assertNotIn("briefing:figures", everything)


class AttentionTests(unittest.TestCase):
    """Order, cap, opacity filter, name gap, grouping, and no board chrome."""

    def test_rows_carry_no_score_cue_or_thesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            chunk = files["attention.json"]
            for glyph in ("▲", "▼", "◆"):
                self.assertNotIn(glyph, chunk)
            for chrome in ("PROMISING", "DANGEROUS", "WATCH", "QUIET",
                           "score", "thesis"):
                self.assertNotIn(chrome, chunk)
            rows = [r for g in docs(files)["attention.json"]["blocks"][0]
                    ["groups"] for r in g["rows"]]
            self.assertIn(12, [r["netuid"] for r in rows])
            for row in rows:
                self.assertEqual(set(row), {"netuid", "name", "summary"})

    def test_groups_state_their_reason_once_with_a_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            for group in docs(files)["attention.json"]["blocks"][0]["groups"]:
                reason = group["rows"][0]["summary"]
                count = len(group["rows"])
                self.assertEqual(
                    group["label"], "%s: %d %s"
                    % (reason, count, "subnet" if count == 1 else "subnets"))

    def test_order_and_reasons_follow_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            import atlas_telegram as tg
            import atlas_fleet_dashboard as dash
            fleet_conn = tg.open_source_ro(config["fleet_db"])
            try:
                board = dash.build_board(fleet_conn, {})
            finally:
                fleet_conn.close()
            expected = [item["row"]["netuid"] for item in
                        (board["head"] + board["mid"] + board["quiet"])
                        if not item["sc"]["pure_opaque"]][:10]
            src = sh._brief()._Sources(config)
            try:
                rows, gap = sh.attention_rows(src, config, {})
            finally:
                src.close()
            self.assertIsNone(gap)
            self.assertEqual([r["netuid"] for r in rows], expected)
            for row in rows:
                self.assertTrue(row["why"], "every row needs a reason")
                self.assertNotIn("score", row)

    def test_cap_holds_at_the_configured_row_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp, attention_rows=2)
            src = sh._brief()._Sources(config)
            try:
                rows, _gap = sh.attention_rows(src, config, {})
            finally:
                src.close()
            self.assertEqual(len(rows), 2)

    def test_missing_name_is_a_gap_not_an_invented_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], with_names=False)
            build_fleet(config["fleet_db"])
            _e, files, problems = sh.build(config, None)
            self.assertEqual(problems, [])
            block = docs(files)["attention.json"]["blocks"][0]
            for group in block["groups"]:
                for row in group["rows"]:
                    self.assertIsNone(row["name"])
            self.assertTrue(any(g.startswith("Name not recorded for SN")
                                for g in block["gaps"]))
            self.assertNotIn("org12", files["attention.json"])

    def test_pure_opaque_rows_are_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            import atlas_telegram as tg
            conn = sqlite3.connect(config["fleet_db"])
            conn.execute(
                "INSERT INTO metric_emission_scan (netuid, epoch, sha, "
                "opaque, truncated, routes, outcome, scanned_at) VALUES "
                "(44, 1, 'abc', 1, 0, 0, 'opaque', ?)", (_iso(0.5),))
            conn.commit()
            conn.close()
            src = sh._brief()._Sources(config)
            try:
                rows, _gap = sh.attention_rows(src, config, {})
            finally:
                src.close()
            fleet_conn = tg.open_source_ro(config["fleet_db"])
            try:
                import atlas_fleet_dashboard as dash
                board = dash.build_board(fleet_conn, {})
            finally:
                fleet_conn.close()
            for netuid in board["opaque_group"]:
                self.assertNotIn(netuid, [r["netuid"] for r in rows])

    def test_no_rows_names_the_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            import atlas_fleet as fleet
            conn = fleet.open_store(config["fleet_db"])  # slots, no metrics
            conn.close()
            src = sh._brief()._Sources(config)
            try:
                rows, gap = sh.attention_rows(src, config, {})
            finally:
                src.close()
            self.assertEqual(rows, [])
            self.assertIsNotNone(gap)
            section = sh.attention_section(rows, gap)
            self.assertEqual(section["blocks"][0]["gaps"], [gap])
            self.assertNotIn("groups", section["blocks"][0])


class CodeSectionTests(unittest.TestCase):
    """The push count is the stored seven-day fact."""

    def test_push_count_is_the_stored_seven_day_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            # c7 > 0 for SN12 and SN44 only; a window count over the last
            # six hours would see no commits at all in this fixture.
            edition, files, _p = sh.build(full(tmp), None)
            code = docs(files)["code.json"]
            self.assertEqual(edition["figures"]["pushed_7d"], 2)
            self.assertEqual(edition["figures"]["tracked"], 3)
            self.assertEqual(fact(code, "pushed")["text"], "2 / 3")
            self.assertEqual(code["lead"], "2 of 3 tracked subnets pushed "
                                           "code in the last seven days.")

    def test_dependency_terms_stay_out_of_the_narrative_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            conn = sqlite3.connect(config["fleet_db"])
            conn.execute(
                "INSERT INTO signal_adoptions (term, kind, netuid, epoch, "
                "adopted_at, seeded) VALUES ('numpy', 'dependency', 12, 1, "
                "?, 0)", (_iso(1.0),))
            conn.commit()
            conn.close()
            _e, files, _p = sh.build(config, None)
            narrative = docs(files)["code.json"]["blocks"][1]
            self.assertTrue(any("qwen3-32b" in n for n in narrative["notes"]))
            self.assertNotIn("numpy", files["code.json"])


class ReadOnlyTests(unittest.TestCase):
    """The metrics report performs no write."""

    def test_build_board_completes_on_a_read_only_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_fleet(config["fleet_db"])
            import atlas_telegram as tg
            import atlas_fleet_dashboard as dash
            conn = tg.open_source_ro(config["fleet_db"])
            self.assertIsNotNone(conn)
            try:
                board = dash.build_board(conn, {})
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("INSERT INTO metric_state (key, value) "
                                 "VALUES ('probe', '1')")
            finally:
                conn.close()
            self.assertTrue(board["head"] or board["mid"] or board["quiet"])


class ExclusionTests(unittest.TestCase):
    """The scan is the guard against a store row that itself carries
    operator material."""

    def test_clean_edition_scans_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            self.assertEqual(sh.scan_files(files), [])

    def test_a_leaking_verdict_row_fails_the_pass_closed(self):
        for leak in ("set mining.budget_band before rerunning",
                     "board at http://192.168.0.150:8480/",
                     "reach the operator at t.me/someone",
                     "moved to hotkey rotation"):
            with self.subTest(leak=leak):
                with tempfile.TemporaryDirectory() as tmp:
                    config = make_config(tmp, publish=True)
                    build_live(config["live_db"])
                    build_fleet(config["fleet_db"], verdict_text=leak)
                    _e, _f, problems = sh.build(config, None)
                    self.assertTrue(problems, "expected a leak for %r" % leak)
                    self.assertTrue(all(p.startswith("code.json: ")
                                        for p in problems), problems)
                    with self.assertRaises(sh.SubntError) as caught:
                        sh.run(config)
                    self.assertIn("code.json", str(caught.exception))
                    self.assertFalse(os.path.exists(config["checkout_dir"]))

    def test_a_stored_em_dash_is_rewritten_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"],
                        verdict_text="reward split \u2014 moved to the owner")
            _e, files, problems = sh.build(config, None)
            self.assertEqual(problems, [])
            self.assertNotIn("\u2014", files["code.json"])
            self.assertIn("reward split, moved to the owner",
                          files["code.json"])

    def test_wallet_and_key_material_are_caught(self):
        ss58 = "5" + "GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"[:47]
        self.assertTrue(sh.scan(json.dumps({"t": ss58})))
        self.assertTrue(sh.scan(json.dumps({"t": "0x" + "ab" * 32})))
        self.assertTrue(sh.scan(json.dumps({"t": "10.0.0.4"})))


class ScanParityTests(unittest.TestCase):
    """Every token and pattern the subnt build bans (src/lib/leak.mjs),
    held here as literals, is also caught by the Atlas scan."""

    SUBNT_TOKENS = ("mining.budget_band", "budget_band", "TaoStats quota",
                    "TAOSTATS_API_KEY", "192.168.0.150", "t.me/",
                    "api.telegram.org", "next: pick mining.budget_band",
                    "rent_band", "watermark")

    SUBNT_PATTERN_SAMPLES = (
        ("SS58 address",
         "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"),
        ("private IPv4 10", "10.1.2.3"),
        ("private IPv4 127", "127.0.0.2"),
        ("private IPv4 192.168", "192.168.1.9"),
        ("private IPv4 172", "172.20.0.1"),
        ("private key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
        ("32-byte hex", "0x" + "cd" * 32),
        ("Telegram bot token", "123456789:" + "A" * 35),
        ("next line", "next: rotate the key"),
    )

    def test_each_subnt_token_is_caught(self):
        for token in self.SUBNT_TOKENS:
            with self.subTest(token=token):
                self.assertTrue(sh.scan(json.dumps({"notes": [token]})))

    def test_each_subnt_pattern_is_caught(self):
        for label, sample in self.SUBNT_PATTERN_SAMPLES:
            with self.subTest(pattern=label):
                self.assertTrue(sh.scan(sh.serialise(
                    {"notes": ["see %s" % sample if label != "next line"
                               else sample]})))

    def test_an_em_dash_is_caught(self):
        self.assertTrue(sh.scan(sh.serialise({"lead": "a \u2014 b"})))

    def test_file_names_prefix_every_hit(self):
        hits = sh.scan_files({"mining.json": json.dumps({"t": "rent_band"})})
        self.assertTrue(hits)
        self.assertTrue(all(h.startswith("mining.json: ") for h in hits))


class SchemaTests(unittest.TestCase):
    """Every file validates against the vendored subnt schema, and a file
    that does not fails the pass closed with the file named."""

    def _doctored(self, tmp, name, change):
        config = full(tmp, publish=True)
        real = sh.compose

        def doctored(*args, **kwargs):
            edition = real(*args, **kwargs)
            change(edition["docs"][name])
            return edition
        return config, mock.patch.object(sh, "compose", doctored)

    def test_full_and_empty_editions_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            self.assertEqual(sh.validate(files), [])
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(make_config(tmp), None)
            self.assertEqual(sh.validate(files), [])

    def test_doctored_files_fail_with_the_file_named(self):
        cases = (
            ("network.json", lambda d: d.__setitem__("lead", "")),
            ("movers.json", lambda d: d.__setitem__("lead", "a \u2014 b")),
            ("mining.json", lambda d: d.__setitem__("schema", "subnt/2.0")),
            ("edition.json", lambda d: d.__setitem__("block", -1)),
        )
        for name, change in cases:
            with self.subTest(file=name):
                with tempfile.TemporaryDirectory() as tmp:
                    config, patch = self._doctored(tmp, name[:-5], change)
                    with patch:
                        _e, _f, problems = sh.build(config, None)
                        self.assertTrue(problems)
                        self.assertTrue(any(p.startswith(name + ": ")
                                            for p in problems), problems)
                        with self.assertRaises(sh.SubntError):
                            sh.run(config)
                    self.assertFalse(os.path.exists(config["checkout_dir"]))

    def test_a_missing_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            with mock.patch.object(sh, "SCHEMA_FILE",
                                   os.path.join(tmp, "absent.json")), \
                    mock.patch.object(sh, "_VALIDATOR", None):
                with self.assertRaises(sh.SubntError) as caught:
                    sh.build(config, None)
            self.assertIn("cannot load schema", str(caught.exception))

    def test_a_missing_validator_library_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            with mock.patch.dict(sys.modules, {"jsonschema": None}), \
                    mock.patch.object(sh, "_VALIDATOR", None):
                with self.assertRaises(sh.SubntError) as caught:
                    sh.build(config, None)
            self.assertIn("jsonschema", str(caught.exception))


def _subnt_schema_path():
    candidates = []
    if os.environ.get("SUBNT_CHECKOUT"):
        candidates.append(os.environ["SUBNT_CHECKOUT"])
    candidates.append(os.path.expanduser("~/src/github/vanlabs-dev/subnt"))
    try:
        candidates.append(os.path.expanduser(
            sh.load_config()["checkout_dir"]))
    except sh.SubntError:
        pass
    for root in candidates:
        path = os.path.join(root, "schema", "subnt-1.0.json")
        if os.path.isfile(path):
            return path
    return None


class SchemaDriftTests(unittest.TestCase):
    """The Atlas copy is the subnt schema byte for byte."""

    def test_vendored_schema_matches_the_subnt_checkout(self):
        theirs = _subnt_schema_path()
        if theirs is None:
            self.skipTest("no subnt checkout with a schema file is present")
        with open(sh.SCHEMA_FILE, "rb") as a, open(theirs, "rb") as b:
            self.assertEqual(a.read(), b.read(),
                             "%s differs from %s" % (sh.SCHEMA_FILE, theirs))


class DigestTests(unittest.TestCase):
    """The gate ignores the clock fields and nothing else."""

    def _pair(self, tmp):
        noon = datetime.datetime(2026, 9, 9, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        config = make_config(tmp)
        build_live(config["live_db"], anchor=noon)
        build_fleet(config["fleet_db"], anchor=noon)
        state = sh.open_state(config["state_db"])
        try:
            # A fixed previous publish pins the window, so the only moving
            # part left is the compose time itself.
            sh.state_set(state, "published_at", _iso(6.0, noon))
            _e, early, _p = sh.build(config, state, now=noon)
            _e, later, _p = sh.build(
                config, state, now=noon + datetime.timedelta(hours=6))
        finally:
            state.close()
        return early, later

    def test_a_later_clock_and_block_leave_the_digest_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            early, later = self._pair(tmp)
            self.assertNotEqual(early, later)
            moved = {}
            for name, text in later.items():
                doc = json.loads(text)
                doc["block"] = 9999999
                doc["previous_composed_at"] = "2026-09-09T17:00:00Z" \
                    if name == "edition.json" else doc.get(
                        "previous_composed_at")
                if name != "edition.json":
                    doc.pop("previous_composed_at")
                moved[name] = sh.serialise(doc)
            self.assertEqual(sh.fact_digest(early), sh.fact_digest(later))
            self.assertEqual(sh.fact_digest(early), sh.fact_digest(moved))

    def test_a_moved_fact_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            early, _later = self._pair(tmp)
            doc = json.loads(early["network.json"])
            doc["lead"] = doc["lead"] + " Changed."
            moved = dict(early, **{"network.json": sh.serialise(doc)})
            self.assertNotEqual(sh.fact_digest(early), sh.fact_digest(moved))

    def test_a_missing_file_has_no_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            early, _later = self._pair(tmp)
            partial = dict(early)
            del partial["mining.json"]
            self.assertIsNone(sh.fact_digest(partial))
            self.assertIsNotNone(sh.fact_digest(early))


def _init_repo(path, remote):
    """A subnt checkout as it stands after cutover: a stale root page and
    no data yet."""
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)
    for key, value in (("user.name", "vanlabs-dev"),
                       ("user.email", "vanlabs@pm.me")):
        subprocess.run(["git", "-C", path, "config", key, value], check=True)
    with open(os.path.join(path, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<p>shell</p>\n")
    subprocess.run(["git", "-C", path, "add", "index.html"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "Shell"],
                   check=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote],
                   check=True)
    subprocess.run(["git", "-C", path, "remote", "add", "origin", remote],
                   check=True)
    subprocess.run(["git", "-C", path, "push", "-q", "-u", "origin", "main"],
                   check=True)


class PublishTests(unittest.TestCase):
    """Fact gating, authorship, scope, and failing closed. A local temp
    repository stands in for the remote; the real one is never touched."""

    def _ready(self, tmp, anchor=None):
        config = make_config(tmp, publish=True)
        build_live(config["live_db"], anchor=anchor)
        build_fleet(config["fleet_db"], anchor=anchor)
        _init_repo(config["checkout_dir"], os.path.join(tmp, "remote.git"))
        return config

    def _head(self, config):
        return subprocess.run(
            ["git", "-C", config["checkout_dir"], "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout

    def _shell_intact(self, config):
        page = os.path.join(config["checkout_dir"], "index.html")
        with open(page, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<!DOCTYPE html>\n<p>shell</p>\n")

    def test_changed_content_commits_and_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            result = sh.run(config)
            self.assertEqual(result["status"], "published")
            code = subprocess.run(
                ["git", "-C", config["checkout_dir"], "log", "-1",
                 "--format=%an <%ae>%n%B"], capture_output=True, text=True)
            self.assertIn("vanlabs-dev <vanlabs@pm.me>", code.stdout)
            self.assertNotIn("Co-Authored-By", code.stdout)
            self.assertNotIn("Generated with", code.stdout)
            self.assertNotIn("Claude", code.stdout)
            data = os.path.join(config["checkout_dir"], "data")
            self.assertEqual(sorted(os.listdir(data)), sorted(FILE_NAMES))
            with open(os.path.join(data, "network.json"),
                      encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["section"], "network")
            remote = subprocess.run(
                ["git", "-C", os.path.join(tmp, "remote.git"), "log", "-1",
                 "--format=%s"], capture_output=True, text=True).stdout
            self.assertIn("Publish edition", remote)

    def test_the_commit_touches_only_the_six_data_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            sh.run(config)
            touched = subprocess.run(
                ["git", "-C", config["checkout_dir"], "show", "--name-only",
                 "--format=", "HEAD"], capture_output=True,
                text=True).stdout.split()
            self.assertEqual(sorted(touched),
                             sorted("data/%s" % n for n in FILE_NAMES))
            self._shell_intact(config)
            status = subprocess.run(
                ["git", "-C", config["checkout_dir"], "status",
                 "--porcelain"], capture_output=True, text=True).stdout
            self.assertEqual(status, "")

    def test_unchanged_facts_make_no_commit_even_as_the_clock_moves(self):
        """The gate is on the facts. A moving compose time alone must not
        commit a new timestamp over an unchanged edition."""
        base = datetime.datetime(2026, 9, 9, 6, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp, anchor=base)
            # Pass one is the first edition; pass two drops the
            # first-edition flag and carries deltas, so both are changes.
            self.assertEqual(sh.run(config, now=base)["status"], "published")
            self.assertEqual(
                sh.run(config,
                       now=base + datetime.timedelta(hours=6))["status"],
                "published")
            before = self._head(config)
            for passes in (2, 3, 4):
                result = sh.run(
                    config,
                    now=base + datetime.timedelta(hours=6 * passes))
                self.assertEqual(result["status"], "unchanged")
                self.assertFalse(result["published"])
            self.assertEqual(before, self._head(config))
            with open(os.path.join(config["checkout_dir"], "data",
                                   "edition.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["composed_at"],
                                 "2026-09-09T12:00:00Z")

    def test_a_moved_fact_publishes_again(self):
        base = datetime.datetime(2026, 9, 9, 6, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp, anchor=base)
            sh.run(config, now=base)
            sh.run(config, now=base + datetime.timedelta(hours=6))
            before = self._head(config)
            conn = sqlite3.connect(config["live_db"])
            conn.execute("UPDATE meta SET value = '456' WHERE key = "
                         "'last_live_spec'")
            conn.commit()
            conn.close()
            result = sh.run(config, now=base + datetime.timedelta(hours=12))
            self.assertEqual(result["status"], "published")
            self.assertNotEqual(before, self._head(config))

    def test_a_missing_committed_file_publishes(self):
        base = datetime.datetime(2026, 9, 9, 6, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp, anchor=base)
            sh.run(config, now=base)
            sh.run(config, now=base + datetime.timedelta(hours=6))
            checkout = config["checkout_dir"]
            subprocess.run(["git", "-C", checkout, "rm", "-q",
                            "data/mining.json"], check=True)
            subprocess.run(["git", "-C", checkout, "commit", "-q", "-m",
                            "Drop mining"], check=True)
            subprocess.run(["git", "-C", checkout, "push", "-q", "origin",
                            "main"], check=True)
            result = sh.run(config, now=base + datetime.timedelta(hours=12))
            self.assertEqual(result["status"], "published")
            self.assertTrue(os.path.exists(
                os.path.join(checkout, "data", "mining.json")))

    def test_figures_persist_only_after_a_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            sh.run(config)
            state = sh.open_state(config["state_db"])
            try:
                self.assertIsNotNone(sh.state_get(state, "figures"))
                self.assertIsNotNone(sh.state_get(state, "published_at"))
                self.assertTrue(sh.state_get(state, "content_sha256"))
            finally:
                state.close()

    def test_missing_checkout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, publish=True)
            build_live(config["live_db"])
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("does not exist", str(caught.exception))

    def test_not_a_repository_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, publish=True)
            build_live(config["live_db"])
            os.makedirs(config["checkout_dir"])
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("not a git repository", str(caught.exception))

    def test_dirty_checkout_fails_closed_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            stray = os.path.join(config["checkout_dir"], "stray.txt")
            with open(stray, "w", encoding="utf-8") as fh:
                fh.write("uncommitted\n")
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("dirty", str(caught.exception))
            self.assertFalse(os.path.exists(
                os.path.join(config["checkout_dir"], "data")))
            self._shell_intact(config)

    def test_unreachable_remote_fails_before_writing_anything(self):
        """The sync runs first, so an unreachable remote costs nothing:
        no local commit is made that could never be pushed."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            subprocess.run(["git", "-C", config["checkout_dir"], "remote",
                            "set-url", "origin",
                            os.path.join(tmp, "no-such-remote.git")],
                           check=True)
            before = self._head(config)
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("cannot reach origin", str(caught.exception))
            self.assertEqual(before, self._head(config))
            self.assertFalse(os.path.exists(
                os.path.join(config["checkout_dir"], "data")))

    def test_a_rejected_push_leaves_a_recoverable_local_commit(self):
        """A read-only deploy key is the real case: fetch succeeds, push is
        refused. The commit stays local and nothing is reset."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            hook = os.path.join(tmp, "remote.git", "hooks", "pre-receive")
            with open(hook, "w") as fh:
                fh.write("#!/bin/sh\necho 'read-only' >&2\nexit 1\n")
            os.chmod(hook, 0o755)
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("cannot push", str(caught.exception))
            self.assertIn("local and recoverable", str(caught.exception))
            log = subprocess.run(
                ["git", "-C", config["checkout_dir"], "log", "-1",
                 "--format=%s"], capture_output=True, text=True).stdout
            self.assertIn("Publish edition", log)

    def test_an_unauthenticated_https_remote_fails_not_hangs(self):
        """Git must fail closed rather than block a timer-driven unit on a
        credential prompt."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            subprocess.run(
                ["git", "-C", config["checkout_dir"], "remote", "set-url",
                 "origin", "https://127.0.0.1:9/vanlabs-dev/subnt.git"],
                check=True)
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("cannot reach origin", str(caught.exception))

    def test_git_runs_with_prompts_disabled(self):
        self.assertEqual(sh._GIT_ENV["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("BatchMode=yes", sh._GIT_ENV["GIT_SSH_COMMAND"])

    def test_commit_does_not_depend_on_device_git_config(self):
        """There is no /home/pi/.gitconfig, so identity must be passed per
        invocation or the commit fails with 'tell me who you are'."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            for key in ("user.name", "user.email"):
                subprocess.run(["git", "-C", config["checkout_dir"],
                                "config", "--unset", key], check=False)
            self.assertEqual(sh.run(config)["status"], "published")
            author = subprocess.run(
                ["git", "-C", config["checkout_dir"], "log", "-1",
                 "--format=%an <%ae>"], capture_output=True,
                text=True).stdout.strip()
            self.assertEqual(author, "vanlabs-dev <vanlabs@pm.me>")

    def test_a_checkout_behind_origin_is_fast_forwarded(self):
        """Someone commits to the subnt repo directly (the page and its
        tests live there). The pass must catch up, not be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            other = os.path.join(tmp, "other")
            subprocess.run(["git", "clone", "-q",
                            os.path.join(tmp, "remote.git"), other],
                           check=True)
            for k, v in (("user.name", "someone"),
                         ("user.email", "s@example.com")):
                subprocess.run(["git", "-C", other, "config", k, v],
                               check=True)
            with open(os.path.join(other, "AGENTS.md"), "w") as fh:
                fh.write("edited elsewhere\n")
            subprocess.run(["git", "-C", other, "add", "AGENTS.md"],
                           check=True)
            subprocess.run(["git", "-C", other, "commit", "-q", "-m",
                            "Edit docs"], check=True)
            subprocess.run(["git", "-C", other, "push", "-q", "origin",
                            "main"], check=True)

            self.assertEqual(sh.run(config)["status"], "published")
            log = subprocess.run(
                ["git", "-C", config["checkout_dir"], "log", "--format=%s"],
                capture_output=True, text=True).stdout
            self.assertIn("Edit docs", log)
            self.assertIn("Publish edition", log)
            self.assertEqual(
                subprocess.run(["git", "-C", config["checkout_dir"], "status",
                                "-sb"], capture_output=True,
                               text=True).stdout.count("behind"), 0)

    def test_a_diverged_checkout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            other = os.path.join(tmp, "other")
            subprocess.run(["git", "clone", "-q",
                            os.path.join(tmp, "remote.git"), other],
                           check=True)
            for k, v in (("user.name", "someone"),
                         ("user.email", "s@example.com")):
                subprocess.run(["git", "-C", other, "config", k, v],
                               check=True)
            with open(os.path.join(other, "AGENTS.md"), "w") as fh:
                fh.write("theirs\n")
            subprocess.run(["git", "-C", other, "add", "-A"], check=True)
            subprocess.run(["git", "-C", other, "commit", "-q", "-m",
                            "Theirs"], check=True)
            subprocess.run(["git", "-C", other, "push", "-q", "origin",
                            "main"], check=True)
            # and a local commit the remote has never seen
            with open(os.path.join(config["checkout_dir"], "LOCAL.md"),
                      "w") as fh:
                fh.write("local only\n")
            subprocess.run(["git", "-C", config["checkout_dir"], "add",
                            "LOCAL.md"], check=True)
            subprocess.run(["git", "-C", config["checkout_dir"], "commit",
                            "-q", "-m", "Local"], check=True)
            with self.assertRaises(sh.SubntError) as caught:
                sh.run(config)
            self.assertIn("diverged", str(caught.exception))

    def test_publication_disabled_composes_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            config["publish"] = False
            result = sh.run(config)
            self.assertEqual(result["status"], "composed")
            self.assertFalse(result["published"])
            self.assertEqual(result["would_write"],
                             os.path.join(config["checkout_dir"], "data"))
            self.assertFalse(os.path.exists(result["would_write"]))
            self._shell_intact(config)

    def test_disabled_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            config["enabled"] = False
            self.assertEqual(sh.run(config), {"status": "disabled"})
            self.assertFalse(os.path.exists(config["state_db"]))


class CliTests(unittest.TestCase):
    def test_compose_out_writes_the_six_files_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(config, fh)
            out = os.path.join(tmp, "out")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), \
                    contextlib.redirect_stderr(stderr):
                code = sh.main(["--config", path, "compose", "--out", out])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(sorted(os.listdir(out)), sorted(FILE_NAMES))
            printed = json.loads(stdout.getvalue())
            self.assertEqual(sorted(printed),
                             sorted(n[:-5] for n in FILE_NAMES))
            self.assertEqual(json.loads(stderr.getvalue())["problems"],
                             "clean")
            self.assertFalse(os.path.exists(config["checkout_dir"]))


class ReadabilityTests(unittest.TestCase):
    """Public prose: counts agree in number and large figures group."""

    def test_absent_above_bar_count_is_named_not_inlined(self):
        """Seen on the device: above_count is NULL on some polls."""
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], above_count=None)
            _e, files, _p = sh.build(config, None)
            network = docs(files)["network.json"]
            self.assertEqual(fact(network, "bar")["freshness"], "rank 32")
            self.assertIn("The bar is recorded without the above-bar count.",
                          texts(network, "gaps"))
            self.assertNotIn("not recorded subnets", files["network.json"])

    def test_absent_rank_and_count_are_both_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], rank=None, above_count=None)
            _e, files, problems = sh.build(config, None)
            self.assertEqual(problems, [])
            network = docs(files)["network.json"]
            self.assertNotIn("freshness", fact(network, "bar"))
            self.assertTrue(any("without its rank and the above-bar count"
                                in g for g in texts(network, "gaps")))

    def test_a_single_subnet_above_the_bar_reads_singular(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], above_count=1)
            _e, files, _p = sh.build(config, None)
            lead = docs(files)["network.json"]["lead"]
            self.assertIn("with 1 subnet above it", lead)
            self.assertNotIn("1 subnets", lead)

    def test_singular_and_grouped_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            parsed = docs(files)
            self.assertEqual(parsed["network.json"]["lead"],
                             "The emission cut sits at 0.412% demand share "
                             "(rank 32), with 32 subnets above it.")
            self.assertTrue(any(n.startswith("1 material incentive-code "
                                             "change and")
                                for n in texts(parsed["code.json"],
                                               "notes")))
            network = parsed["network.json"]
            self.assertEqual(fact(network, "staked")["text"],
                             "7,313,368 TAO")
            self.assertIsNone(fact(network, "accounts"))
            self.assertIsNone(fact(network, "side-changes"))


class WhyPhraseTests(unittest.TestCase):
    """The reason token alone is not publishable: on the real fleet 93 of
    106 public rows score `divergence`, so the phrase must be derived."""

    def test_divergence_states_direction_in_words(self):
        cold = {"why": "divergence", "div_signed": -71, "cold": True}
        warm = {"why": "divergence", "div_signed": -71, "cold": False}
        ahead = {"why": "divergence", "div_signed": 55, "cold": False}
        self.assertEqual(sh.why_phrase(cold),
                         "priced ahead of a repository that has gone quiet")
        self.assertEqual(sh.why_phrase(warm),
                         "priced ahead of its code activity")
        self.assertEqual(sh.why_phrase(ahead),
                         "building faster than the price reflects")
        self.assertNotEqual(sh.why_phrase(cold), sh.why_phrase(ahead))

    def test_fresh_distinguishes_its_two_causes(self):
        self.assertEqual(
            sh.why_phrase({"why": "fresh", "econ_fresh": True}),
            "reward or emission code changed this pass")
        # A branch-tip count says nothing about what changed.
        self.assertIsNone(
            sh.why_phrase({"why": "fresh", "pulse_spike": True}))

    def test_unknown_token_is_a_gap_not_a_raw_token(self):
        self.assertIsNone(sh.why_phrase({"why": "something-new"}))

    def test_no_phrase_carries_a_score_or_a_glyph(self):
        for sc in ({"why": w, "div_signed": -60, "cold": True,
                    "econ_fresh": True, "pulse_spike": True}
                   for w in sh.WHY_PHRASE):
            phrase = sh.why_phrase(sc) or ""
            for glyph in ("▲", "▼", "◆"):
                self.assertNotIn(glyph, phrase)
            self.assertFalse(any(ch.isdigit() for ch in phrase))


class GroupingTests(unittest.TestCase):
    def test_identical_reasons_collapse_into_one_group(self):
        rows = [{"netuid": n, "name": "n%d" % n, "why": "priced ahead"}
                for n in range(8)]
        rows += [{"netuid": 99, "name": "x", "why": "branch spiked"}]
        groups = sh.group_attention(rows)
        self.assertEqual([g[0] for g in groups],
                         ["priced ahead", "branch spiked"])
        self.assertEqual([len(g[1]) for g in groups], [8, 1])
        section = sh.attention_section(rows, None)
        self.assertEqual(section["lead"], "9 subnets deserve a closer read; "
                                          "8 share one reason: priced ahead.")

    def test_grouping_preserves_board_order(self):
        rows = [{"netuid": 1, "why": "a"}, {"netuid": 2, "why": "b"},
                {"netuid": 3, "why": "a"}]
        groups = sh.group_attention(rows)
        self.assertEqual([g[0] for g in groups], ["a", "b"])
        self.assertEqual([r["netuid"] for r in groups[0][1]], [1, 3])

    def test_a_missing_reason_is_named(self):
        groups = sh.group_attention([{"netuid": 1, "why": None}])
        self.assertEqual(groups[0][0], "reason not recorded")


class ReleaseTextTests(unittest.TestCase):
    def test_upstream_owner_is_dropped(self):
        self.assertEqual(
            sh._release_text("Merge pull request #3196 from "
                             "RaoFoundation/feat/add-swap-basket-many"),
            "PR #3196 (feat/add-swap-basket-many)")

    def test_a_fork_owner_is_kept(self):
        self.assertEqual(
            sh._release_text("Merge pull request #12 from someone/fix-x"),
            "PR #12 (someone/fix-x)")

    def test_any_other_subject_is_unchanged(self):
        self.assertEqual(sh._release_text("Bump spec to 470"),
                         "Bump spec to 470")


class MoverNotesTests(unittest.TestCase):
    def _notes(self, tmp, extra):
        config = make_config(tmp)
        build_live(config["live_db"])
        conn = sqlite3.connect(config["live_db"])
        for netuid, rank, immune, name in extra:
            conn.execute(
                "INSERT INTO panel_snapshot (observed_at, block_number, "
                "netuid, share, dereg_risk_level, dereg_prune_rank, "
                "dereg_is_immune, name) VALUES (?, 9018500, ?, 0.001, "
                "'critical', ?, ?, ?)", (_iso(0.4), netuid, rank, immune,
                                         name))
        conn.commit()
        conn.close()
        _e, files, problems = sh.build(config, None)
        self.assertEqual(problems, [])
        return texts(docs(files)["movers.json"], "notes")

    def test_deregistration_lists_five_by_prune_rank_with_names(self):
        extra = [(113, 1, 0, "LongShort"), (82, 2, 0, "Compelle"),
                 (47, 3, 0, None), (72, 4, 0, "StreetVision"),
                 (98, 5, 0, "NeverPlayAlone"), (42, 6, 0, "Sixth"),
                 (16, 0, 1, "Immune")]
        with tempfile.TemporaryDirectory() as tmp:
            notes = self._notes(tmp, extra)
        self.assertIn("Closest to deregistration: SN113 LongShort, "
                      "SN82 Compelle, SN47, SN72 StreetVision, "
                      "SN98 NeverPlayAlone.", notes)
        self.assertFalse(any("SN16" in n or "SN42" in n for n in notes))

    def test_ownership_note_is_gone_and_near_cut_is_worded(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = self._notes(tmp, [])
        self.assertFalse(any("Ownership" in n for n in notes))
        self.assertFalse(any("Hovering" in n for n in notes))
        self.assertIn("Near the cut, where small price moves swing emission "
                      "most: SN7.", notes)


class MiningWordingTests(unittest.TestCase):
    def test_head_is_the_largest_pool_and_hardware_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, problems = sh.build(full(tmp), None)
            self.assertEqual(problems, [])
            mining = docs(files)["mining.json"]
        self.assertTrue(mining["lead"].startswith(
            "SN12 Subnet 12 has the largest earnable pool for a new "
            "independent miner; "), mining["lead"])
        self.assertEqual(fact(mining, "head")["label"],
                         "Largest earnable pool")
        self.assertIn("Ranked by estimated earnings for a new independent "
                      "miner. Hardware cost and hardware requirements are "
                      "not counted.", texts(mining, "notes"))


class OwnerBurnTests(unittest.TestCase):
    def test_only_reconciled_chain_figures_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = full(tmp)
            conn = sqlite3.connect(config["fleet_db"])
            conn.execute("UPDATE mine_econ SET owner_share_pct = 61.1, "
                         "owner_reconcile_delta = 0.0006 WHERE netuid = 12")
            conn.execute("UPDATE mine_econ SET owner_share_pct = 100.0, "
                         "owner_reconcile_delta = 1.0 WHERE netuid = 44")
            conn.commit()
            conn.close()
            src = sh._brief()._Sources(config)
            try:
                burn = sh.owner_burn(src, {})
            finally:
                src.close()
        self.assertEqual(burn.get(12), 61.1)
        self.assertNotIn(44, burn)

    def _rows(self, items, burn):
        board = mock.Mock()
        board.build_board.return_value = {"head": items, "mid": [],
                                          "quiet": []}
        src = mock.Mock(fleet=object())
        with mock.patch.object(sh, "_board", return_value=board), \
                mock.patch.object(sh, "recorded_names", return_value={}), \
                mock.patch.object(sh, "owner_burn", return_value=burn):
            return sh.attention_rows(src, {"attention_rows": 10}, {})[0]

    def test_emission_rows_carry_the_chain_figure_or_are_dropped(self):
        def item(netuid, **sc):
            base = {"pure_opaque": False}
            base.update(sc)
            return {"row": {"netuid": netuid}, "sc": base}
        rows = self._rows([
            item(54, why="emission"),
            item(9, why="emission"),
            item(4, why="emission"),
            item(7, why="fresh", pulse_spike=True, econ_fresh=False),
            item(25, why="divergence", div_signed=40)],
            {54: 61.1, 4: 0.002})
        self.assertEqual([r["netuid"] for r in rows], [54, 25])
        self.assertEqual(rows[0]["detail"], "61% of miner emission")
        section = sh.attention_section(rows, None)
        group = section["blocks"][0]["groups"][0]
        self.assertEqual(group["label"],
                         "miner emission burned through owner UIDs: "
                         "1 subnet")
        self.assertEqual(group["rows"][0]["summary"],
                         "61% of miner emission")


class SeriesTests(unittest.TestCase):
    def test_series_readers_refuse_an_unexpected_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            src = sh._brief()._Sources(config)
            try:
                with self.assertRaises(sh.SubntError):
                    sh.vitals_series(src, "1=1; DROP TABLE meta")
                with self.assertRaises(sh.SubntError):
                    sh.netuid_series(src, 12, "oops")
            finally:
                src.close()

    def test_absent_store_yields_empty_series_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            src = sh._brief()._Sources(config)
            try:
                self.assertEqual(sh.theta_series(src), [])
                self.assertEqual(sh.share_distribution(src), [])
                self.assertEqual(sh.vitals_series(src, "tao_usd"), [])
            finally:
                src.close()

    def test_distribution_is_sorted_largest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            src = sh._brief()._Sources(config)
            try:
                shares = sh.share_distribution(src)
            finally:
                src.close()
            self.assertEqual(shares, sorted(shares, key=lambda r: -r[1]))

    def test_fewer_than_two_points_yield_no_series(self):
        self.assertIsNone(sh._series("x", "line", "l", "c", []))
        self.assertIsNone(sh._series("x", "line", "l", "c", [1.0]))
        self.assertEqual(sh._series("x", "line", "l", "c",
                                    [1.0, 2.0])["points"], [1.0, 2.0])

    def test_one_bar_reading_draws_no_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            _e, files, _p = sh.build(config, None)
            ids = [s["id"] for s in
                   docs(files)["network.json"]["blocks"][0].get("series", [])]
            self.assertNotIn("bar-trend", ids)
            self.assertNotIn("tao-trend", ids)

    def test_recorded_trends_carry_their_figures_in_the_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            conn = sqlite3.connect(config["live_db"])
            conn.execute(
                "INSERT INTO gate_state (observed_at, gate_active, theta, q, "
                "q_provenance, h, h_provenance, endpoint, rank, above_count) "
                "VALUES (?, 1, 0.00500, 0.75, 'assumed-default', 0.1, "
                "'assumed-default', 'finney', 32, 32)", (_iso(0.2),))
            conn.execute(
                "INSERT INTO network_vitals (date, observed_at, "
                "total_staked_tao, subnets_share_pct, new_accounts_today, "
                "tao_usd) VALUES ('2026-09-07', ?, 7300000.0, 27.5, 1400, "
                "300.00)", (_iso(26.0),))
            conn.commit()
            conn.close()
            _e, files, problems = sh.build(config, None)
            self.assertEqual(problems, [])
            series = {s["id"]: s for s in docs(files)["network.json"]
                      ["blocks"][0]["series"]}
            self.assertEqual(
                series["bar-trend"]["caption"],
                "Emission-gate bar over the last 2 readings, from 0.412% "
                "to 0.500%.")
            self.assertEqual(series["bar-trend"]["points"], [0.00412, 0.005])
            self.assertEqual(
                series["tao-trend"]["caption"],
                "TAO over the last 2 daily readings, from $300.00 to "
                "$318.42.")

    def test_share_strip_marks_the_bar_rank(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], rank=2)
            _e, files, _p = sh.build(config, None)
            strip = [s for s in docs(files)["network.json"]["blocks"][0]
                     ["series"] if s["id"] == "share-strip"][0]
            self.assertEqual(strip["mark"], 1)
            self.assertTrue(strip["log"])
            self.assertIn("the bar sits at rank 2", strip["caption"])

    def test_a_stale_bar_draws_no_bar_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], gate_hours=27.0)
            _e, files, _p = sh.build(config, None)
            ids = [s["id"] for s in
                   docs(files)["network.json"]["blocks"][0].get("series", [])]
            self.assertNotIn("bar-trend", ids)
            self.assertNotIn("share-strip", ids)


class LedeTests(unittest.TestCase):
    def test_headline_names_the_largest_mover(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(full(tmp), None)
            parsed = docs(files)
            headline = parsed["edition.json"]["headline"]
            self.assertIn("SN", headline)
            self.assertEqual(headline, parsed["movers.json"]["lead"])

    def test_quiet_headline_explains_the_soft_gate(self):
        self.assertEqual(
            sh._lede(None, {"theta": 0.0086554, "rank": 32}),
            "Emission favours the top 32 subnets by demand share; below "
            "0.866%, a subnet's emission falls off sharply.")

    def test_headline_falls_back_rather_than_inventing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _e, files, _p = sh.build(make_config(tmp), None)
            self.assertEqual(docs(files)["edition.json"]["headline"],
                             "No recorded figure moved in this window.")


class ClipTests(unittest.TestCase):
    """Long verdict lines are shortened on a word, never mid-word."""

    LINE = ("When UAV data is missing and the partner is on mainnet, the "
            "unused UAV share now goes to the burn UID")

    def test_short_text_is_unchanged(self):
        self.assertEqual(sh._clip("reward split moved", 90),
                         "reward split moved")
        exact = "x" * 90
        self.assertEqual(sh._clip(exact, 90), exact)

    def test_long_text_ends_on_a_whole_word_with_an_ellipsis(self):
        clipped = sh._clip(self.LINE, 90)
        self.assertLessEqual(len(clipped), 90)
        self.assertTrue(clipped.endswith("\u2026"))
        self.assertTrue(self.LINE.startswith(clipped[:-1]))
        self.assertEqual(self.LINE[len(clipped) - 1], " ")

    def test_no_dangling_punctuation_before_the_ellipsis(self):
        self.assertEqual(sh._clip("alpha beta, gamma delta", 13),
                         "alpha beta\u2026")

    def test_a_single_long_word_is_cut_hard(self):
        clipped = sh._clip("a" * 120, 90)
        self.assertEqual(len(clipped), 90)
        self.assertTrue(clipped.endswith("\u2026"))

    def test_a_long_verdict_is_clipped_in_the_published_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"], verdict_text=self.LINE)
            _e, files, problems = sh.build(config, None)
            self.assertEqual(problems, [])
            notes = texts(docs(files)["code.json"], "notes")
            verdict = [n for n in notes if n.startswith("SN12, ")][0]
            self.assertIn("goes to\u2026, at commit", verdict)
            self.assertNotIn("goes to t,", verdict)


class ZeroDeltaTests(unittest.TestCase):
    def test_a_delta_that_rounds_to_zero_is_suppressed(self):
        self.assertIsNone(sh._delta_value(100.0, 100.0))
        self.assertIsNone(sh._delta(100.0, 100.0))
        self.assertEqual(sh._delta(110.0, 100.0),
                         {"text": "+10.0% since last publish",
                          "direction": "up"})


if __name__ == "__main__":
    unittest.main()
