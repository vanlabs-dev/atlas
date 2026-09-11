"""Shinogi renderer tests: store-only composition, the frozen page shape,
per-input stale bounds, deltas against the previous shinogi publish, the
attention row shape, the operator-exclusion scan, and the hash-gated
publish. Every test builds its own stores; none touches a device, a
network, or the real remote."""

import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "fleet"))

import atlas_shinogi as sh  # noqa: E402


SECTION_IDS = ("network", "movers", "mining", "attention", "code-narrative")


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
            "INSERT INTO mine_econ (ts, netuid, subnet_name, cut_reason, "
            "net_tao_month, gross_tao_month, rent_band, confidence) VALUES "
            "(?, ?, ?, ?, ?, ?, 'unknown', 'measured')",
            (pass_ts, netuid, "Subnet %d" % netuid,
             None if netuid != 67 else "winner-take-all",
             None if netuid == 67 else (40.0 - netuid * 0.1),
             None if netuid == 67 else 50.0))
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
    conn.close()


def make_config(tmp, **overrides):
    config = {
        "enabled": True,
        "publish": False,
        "checkout_dir": os.path.join(tmp, "checkout"),
        "page_file": "index.html",
        "state_db": os.path.join(tmp, "state", "shinogi.db"),
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


class Page(HTMLParser):
    """The same parse shinogi/tests/test_page_contract.py performs."""

    def __init__(self):
        super().__init__()
        self.ids = []
        self.h1 = []
        self.h3 = []
        self.asof = []
        self.scripts = []
        self.links = []
        self._capture = None
        self._buf = []
        self._asof_depth = 0

    def handle_starttag(self, tag, attrs):
        ad = {k: (v or "") for k, v in attrs}
        if tag == "section" and ad.get("id"):
            self.ids.append(ad["id"])
        if tag in ("h1", "h3"):
            self._capture = tag
            self._buf = []
        if tag == "div" and ad.get("class") == "asof":
            self._capture = "asof"
            self._buf = []
            self._asof_depth = 1
        elif self._capture == "asof":
            self._asof_depth += 1
        if tag == "script":
            self.scripts.append(ad)
        if tag == "link":
            self.links.append(ad)

    def handle_endtag(self, tag):
        if self._capture in ("h1", "h3") and tag == self._capture:
            getattr(self, self._capture).append("".join(self._buf).strip())
            self._capture = None
            self._buf = []
        elif self._capture == "asof" and tag == "div":
            self._asof_depth -= 1
            if self._asof_depth <= 0:
                self.asof.append("".join(self._buf).strip())
                self._capture = None
                self._buf = []
                self._asof_depth = 0

    def handle_data(self, data):
        if self._capture is not None:
            self._buf.append(data)


def parse(document):
    page = Page()
    page.feed(document)
    page.close()
    return page


class ComposeShapeTests(unittest.TestCase):
    """6.2, 6.3: the frozen page shape, full and empty."""

    def test_full_edition_matches_the_contract_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _edition, document, leaks = sh.build(config, None)
            page = parse(document)
            self.assertEqual(tuple(page.ids), SECTION_IDS)
            self.assertEqual(page.h1, ["SHINOGI"])
            self.assertEqual(page.h3, ["Code", "Narrative"])
            self.assertEqual(len(page.asof), 1)
            self.assertEqual(page.scripts, [])
            # The amended contract allows a typeface source and nothing else.
            for link in page.links:
                self.assertTrue(
                    any(h in link.get("href", "")
                        for h in ("fonts.googleapis.com",
                                  "fonts.gstatic.com")),
                    "unexpected link: %r" % link)
            self.assertEqual(leaks, [])

    def test_empty_edition_keeps_every_landmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)  # no store exists at all
            edition, document, leaks = sh.build(config, None)
            page = parse(document)
            self.assertEqual(tuple(page.ids), SECTION_IDS)
            self.assertEqual(page.h3, ["Code", "Narrative"])
            self.assertEqual(leaks, [])
            self.assertIsNone(edition["asof_block"])
            for phrase in ("Missing the live store",
                           "Missing panel snapshots",
                           "Missing the mining screen",
                           "Missing the fleet store"):
                self.assertIn(phrase, document)

    def test_no_data_is_fetched_in_the_browser(self):
        """Presentation may load a typeface. Pulling a reported figure in
        the browser may not: Atlas is the only writer."""
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _e, document, leaks = sh.build(config, None)
            self.assertEqual(leaks, [])
            for banned in ("XMLHttpRequest", "fetch(", "@import",
                           "EventSource", "new WebSocket"):
                self.assertNotIn(banned, document)
            self.assertNotIn("<script", document)
            for url in re.findall(r'(?:href|src)="(https?://[^"]+)"',
                                  document):
                self.assertTrue(
                    any(h in url for h in ("fonts.googleapis.com",
                                           "fonts.gstatic.com")),
                    "non-typeface external asset: %r" % url)


class AsOfTests(unittest.TestCase):
    """The as-of line states compose time and the recorded block."""

    def test_block_is_the_newest_panel_snapshot_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            edition, document, _l = sh.build(config, None)
            self.assertEqual(edition["asof_block"], 9018444)
            asof = parse(document).asof[0]
            self.assertIn("as of ", asof)
            self.assertIn("block 9018444", asof)

    def test_missing_block_is_named_and_no_number_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            _e, document, _l = sh.build(config, None)
            asof = parse(document).asof[0]
            self.assertIn("block not recorded", asof)
            self.assertNotIn("block 0", asof)


class StaleBoundTests(unittest.TestCase):
    """6.4: bounds are per input, not a blanket six hours."""

    def test_bar_past_twenty_six_hours_is_stale_and_shows_no_theta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], gate_hours=27.0)
            edition, document, _l = sh.build(config, None)
            self.assertIn("emission-gate bar is stale", document)
            self.assertNotIn("0.00412", document)
            self.assertNotIn("theta", edition["figures"])

    def test_bar_inside_the_bound_shows_its_figure(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], gate_hours=20.0)
            edition, document, _l = sh.build(config, None)
            self.assertIn("0.00412", document)
            self.assertNotIn("stale", document)
            self.assertEqual(edition["figures"]["theta"], 0.00412)

    def test_vitals_older_than_six_hours_are_dated_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], vitals_hours=20.0)
            _e, document, _l = sh.build(config, None)
            self.assertIn("318.42", document)
            self.assertIn("observed 2026-09-08", document)
            self.assertNotIn("vitals are stale", document.lower())


class DeltaTests(unittest.TestCase):
    """6.5: deltas compare against the previous shinogi publish only."""

    def test_first_edition_states_so_and_shows_no_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            state = sh.open_state(config["state_db"])
            try:
                edition, document, _l = sh.build(config, state)
            finally:
                state.close()
            self.assertTrue(edition["first_edition"])
            self.assertIn("First edition", document)
            self.assertNotIn("since last publish", document)

    def test_later_edition_compares_against_the_stored_figure_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            state = sh.open_state(config["state_db"])
            try:
                sh.state_set(state, "figures",
                             json.dumps({"theta": 0.00206, "tao_usd": 300.0}))
                sh.state_set(state, "published_at", _iso(6.0))
                edition, document, _l = sh.build(config, state)
            finally:
                state.close()
            self.assertFalse(edition["first_edition"])
            self.assertNotIn("First edition", document)
            self.assertIn("+100.0% since last publish", document)
            self.assertIn("+6.1% since last publish", document)

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
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
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
            edition, document, _l = sh.build(config, None)
            self.assertNotEqual(edition["figures"].get("theta"), 999.0)
            body = document[document.index("<body>"):]
            self.assertNotIn("999.0", body)
            self.assertNotIn("briefing:figures", document)


class AttentionTests(unittest.TestCase):
    """6.6: order, cap, opacity filter, name gap, and no board chrome."""

    def test_rows_carry_no_score_cue_or_thesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _e, document, _l = sh.build(config, None)
            start = document.find('id="attention"')
            chunk = document[start:document.find("</section>", start)]
            for glyph in ("▲", "▼", "◆"):
                self.assertNotIn(glyph, chunk)
            for chrome in ("PROMISING", "DANGEROUS", "WATCH", "QUIET",
                           "score", "thesis"):
                self.assertNotIn(chrome, chunk)
            self.assertIn("SN12", chunk)

    def test_order_and_reasons_follow_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
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
            config = make_config(tmp, attention_rows=2)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
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
            _e, document, _l = sh.build(config, None)
            start = document.find('id="attention"')
            chunk = document[start:document.find("</section>", start)]
            self.assertIn("name not recorded", chunk)
            self.assertNotIn("org12", chunk)  # never falls back to the org

    def test_pure_opaque_rows_are_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
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


class CodeSectionTests(unittest.TestCase):
    """6.7: the push count is the stored seven-day fact."""

    def test_push_count_is_the_stored_seven_day_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            # c7 > 0 for SN12 and SN44 only; a window count over the last
            # six hours would see no commits at all in this fixture.
            edition, document, _l = sh.build(config, None)
            self.assertEqual(edition["figures"]["pushed_7d"], 2)
            self.assertEqual(edition["figures"]["tracked"], 3)
            self.assertIn("2 of 3 tracked subnets pushed in the last seven "
                          "days", document)

    def test_dependency_terms_stay_out_of_the_narrative_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            conn = sqlite3.connect(config["fleet_db"])
            conn.execute(
                "INSERT INTO signal_adoptions (term, kind, netuid, epoch, "
                "adopted_at, seeded) VALUES ('numpy', 'dependency', 12, 1, "
                "?, 0)", (_iso(1.0),))
            conn.commit()
            conn.close()
            _e, document, _l = sh.build(config, None)
            self.assertIn("qwen3-32b", document)
            self.assertNotIn("numpy", document)


class ReadOnlyTests(unittest.TestCase):
    """6.9: the metrics report performs no write."""

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
    """6.8: the scan is the guard against a store row that itself carries
    operator material."""

    def test_clean_document_scans_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _e, _document, leaks = sh.build(config, None)
            self.assertEqual(leaks, [])

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
                    _e, _d, leaks = sh.build(config, None)
                    self.assertTrue(leaks, "expected a leak for %r" % leak)
                    with self.assertRaises(sh.ShinogiError):
                        sh.run(config)
                    self.assertFalse(os.path.exists(config["checkout_dir"]))

    def test_wallet_and_key_material_are_caught(self):
        ss58 = "5" + "GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"[:47]
        self.assertTrue(sh.scan("<p>%s</p>" % ss58))
        self.assertTrue(sh.scan("<p>0x%s</p>" % ("ab" * 32)))
        self.assertTrue(sh.scan("<p>10.0.0.4</p>"))

    def test_scan_rejects_data_fetch_and_non_typeface_assets(self):
        self.assertTrue(sh.scan('<script src="x"></script>'))
        self.assertTrue(sh.scan('<link rel="stylesheet" href="/a.css">'))
        self.assertTrue(sh.scan("<style>@import url(x);</style>"))
        self.assertTrue(sh.scan("<p>fetch(url)</p>"))
        self.assertTrue(sh.scan("<p>new WebSocket(u)</p>"))
        self.assertTrue(sh.scan('<a href="https://example.com">x</a>'))

    def test_scan_allows_a_typeface_and_inline_script(self):
        """The amended contract permits presentation, not data fetching."""
        self.assertEqual(sh.scan(
            '<link rel="stylesheet" '
            'href="https://fonts.googleapis.com/css2?family=Inter">'), [])
        self.assertEqual(sh.scan("<script>document.title=1</script>"), [])

    def test_exact_shinogi_contract_tokens_are_all_covered(self):
        contract_tokens = ("mining.budget_band", "TaoStats quota",
                           "192.168.0.150", "t.me/", "api.telegram.org",
                           "next: pick mining.budget_band")
        for token in contract_tokens:
            with self.subTest(token=token):
                self.assertTrue(sh.scan("<p>%s</p>" % token))


def _init_repo(path, remote):
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
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    subprocess.run(["git", "-C", path, "remote", "add", "origin", remote],
                   check=True)
    subprocess.run(["git", "-C", path, "push", "-q", "-u", "origin", "main"],
                   check=True)


class PublishTests(unittest.TestCase):
    """6.10: hash gating, authorship, and failing closed. A local temp
    repository stands in for the remote; the real one is never touched."""

    def _ready(self, tmp, anchor=None):
        config = make_config(tmp, publish=True)
        build_live(config["live_db"], anchor=anchor)
        build_fleet(config["fleet_db"], anchor=anchor)
        _init_repo(config["checkout_dir"], os.path.join(tmp, "remote.git"))
        return config

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
            page = os.path.join(config["checkout_dir"], "index.html")
            with open(page, encoding="utf-8") as fh:
                self.assertEqual(tuple(parse(fh.read()).ids), SECTION_IDS)

    def _head(self, config):
        return subprocess.run(
            ["git", "-C", config["checkout_dir"], "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout

    def test_unchanged_facts_make_no_commit_even_as_the_clock_moves(self):
        """The gate is on the facts. A moving compose time alone must not
        commit a new timestamp over an unchanged edition."""
        base = datetime.datetime(2026, 9, 9, 6, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp, anchor=base)
            # Pass one is the first edition; pass two drops the
            # first-edition line and gains deltas, so both are real changes.
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

    def test_fact_digest_ignores_only_the_as_of_line(self):
        """Two composes over one window and one store differ only in the
        compose time, so the plain hash moves and the fact digest holds."""
        noon = datetime.datetime(2026, 9, 9, 12, 0,
                                 tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], anchor=noon)
            build_fleet(config["fleet_db"], anchor=noon)
            state = sh.open_state(config["state_db"])
            try:
                # A fixed previous publish pins the window, so the only
                # moving part left is the compose time itself.
                sh.state_set(state, "published_at", _iso(6.0, noon))
                _e, early, _l = sh.build(config, state, now=noon)
                _e, later, _l = sh.build(
                    config, state, now=noon + datetime.timedelta(hours=6))
            finally:
                state.close()
            self.assertNotEqual(early, later)
            self.assertNotEqual(sh._sha256(early), sh._sha256(later))
            self.assertEqual(sh.fact_digest(early), sh.fact_digest(later))

    def test_figures_persist_only_after_a_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            sh.run(config)
            state = sh.open_state(config["state_db"])
            try:
                self.assertIsNotNone(sh.state_get(state, "figures"))
                self.assertIsNotNone(sh.state_get(state, "published_at"))
                self.assertIsNotNone(sh.state_get(state, "content_sha256"))
            finally:
                state.close()

    def test_missing_checkout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, publish=True)
            build_live(config["live_db"])
            with self.assertRaises(sh.ShinogiError) as caught:
                sh.run(config)
            self.assertIn("does not exist", str(caught.exception))

    def test_not_a_repository_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, publish=True)
            build_live(config["live_db"])
            os.makedirs(config["checkout_dir"])
            with self.assertRaises(sh.ShinogiError) as caught:
                sh.run(config)
            self.assertIn("not a git repository", str(caught.exception))

    def test_dirty_checkout_fails_closed_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            stray = os.path.join(config["checkout_dir"], "stray.txt")
            with open(stray, "w", encoding="utf-8") as fh:
                fh.write("uncommitted\n")
            with self.assertRaises(sh.ShinogiError) as caught:
                sh.run(config)
            self.assertIn("dirty", str(caught.exception))
            page = os.path.join(config["checkout_dir"], "index.html")
            with open(page, encoding="utf-8") as fh:
                self.assertIn("<p>shell</p>", fh.read())

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
            with self.assertRaises(sh.ShinogiError) as caught:
                sh.run(config)
            self.assertIn("cannot reach origin", str(caught.exception))
            self.assertEqual(before, self._head(config))
            page = os.path.join(config["checkout_dir"], "index.html")
            with open(page, encoding="utf-8") as fh:
                self.assertIn("<p>shell</p>", fh.read())

    def test_a_rejected_push_leaves_a_recoverable_local_commit(self):
        """A read-only deploy key is the real case: fetch succeeds, push is
        refused. The commit stays local and nothing is reset."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            hook = os.path.join(tmp, "remote.git", "hooks", "pre-receive")
            with open(hook, "w") as fh:
                fh.write("#!/bin/sh\necho 'read-only' >&2\nexit 1\n")
            os.chmod(hook, 0o755)
            with self.assertRaises(sh.ShinogiError) as caught:
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
                 "origin", "https://127.0.0.1:9/vanlabs-dev/shinogi.git"],
                check=True)
            with self.assertRaises(sh.ShinogiError) as caught:
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
        """Someone commits to the shinogi repo directly (the contract and
        its test live there). The pass must catch up, not be rejected."""
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
            with self.assertRaises(sh.ShinogiError) as caught:
                sh.run(config)
            self.assertIn("diverged", str(caught.exception))

    def test_publication_disabled_composes_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            config["publish"] = False
            result = sh.run(config)
            self.assertEqual(result["status"], "composed")
            self.assertFalse(result["published"])
            self.assertTrue(result["would_write"].endswith("index.html"))
            page = os.path.join(config["checkout_dir"], "index.html")
            with open(page, encoding="utf-8") as fh:
                self.assertIn("<p>shell</p>", fh.read())

    def test_disabled_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._ready(tmp)
            config["enabled"] = False
            self.assertEqual(sh.run(config), {"status": "disabled"})
            self.assertFalse(os.path.exists(config["state_db"]))


if __name__ == "__main__":
    unittest.main()


class ReadabilityTests(unittest.TestCase):
    """Public prose: counts agree in number and large figures group."""

    def test_absent_above_bar_count_is_named_not_inlined(self):
        """Seen on the device: above_count is NULL on some polls, which
        rendered as 'rank 32, not recorded subnets above it'."""
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], above_count=None)
            _e, document, _l = sh.build(config, None)
            self.assertNotIn("not recorded subnets above it", document)
            self.assertIn("Emission-gate bar at 0.00412, rank 32.", document)
            self.assertIn("The bar is recorded without the above-bar count.",
                          document)

    def test_absent_rank_and_count_are_both_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], rank=None, above_count=None)
            _e, document, _l = sh.build(config, None)
            self.assertIn("Emission-gate bar at 0.00412.", document)
            self.assertIn("without its rank and the above-bar count",
                          document)

    def test_a_single_subnet_above_the_bar_reads_singular(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"], above_count=1)
            _e, document, _l = sh.build(config, None)
            self.assertIn("1 subnet above it", document)
            self.assertNotIn("1 subnets above it", document)

    def test_singular_and_grouped_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _e, document, _l = sh.build(config, None)
            self.assertIn("1 side change at the bar", document)
            self.assertNotIn("1 side changes", document)
            self.assertIn("1 material incentive-code change and", document)
            self.assertIn("7,313,368 TAO staked", document)
            self.assertIn("1,420 new accounts", document)


class WhyPhraseTests(unittest.TestCase):
    """The reason token alone is not renderable: on the real fleet 93 of
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
        self.assertEqual(
            sh.why_phrase({"why": "fresh", "pulse_spike": True}),
            "branch activity spiked this pass")

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

    def test_grouping_preserves_board_order(self):
        rows = [{"netuid": 1, "why": "a"}, {"netuid": 2, "why": "b"},
                {"netuid": 3, "why": "a"}]
        groups = sh.group_attention(rows)
        self.assertEqual([g[0] for g in groups], ["a", "b"])
        self.assertEqual([r["netuid"] for r in groups[0][1]], [1, 3])

    def test_a_missing_reason_is_named(self):
        groups = sh.group_attention([{"netuid": 1, "why": None}])
        self.assertEqual(groups[0][0], "reason not recorded")


class ChartTests(unittest.TestCase):
    def test_sparkline_needs_two_points(self):
        self.assertEqual(sh.sparkline([]), "")
        self.assertEqual(sh.sparkline([1.0]), "")
        self.assertIn("<svg", sh.sparkline([1.0, 2.0, 1.5]))

    def test_sparkline_is_inline_and_fetches_nothing(self):
        svg = sh.sparkline([1.0, 2.0, 3.0], fill_id="x", label="t")
        self.assertEqual(sh.scan(svg), [])
        self.assertNotIn("http", svg)

    def test_distribution_marks_the_rank_and_the_faller(self):
        shares = [(i, (128 - i) / 1000.0) for i in range(128)]
        svg = sh.distribution_svg(shares, rank=32, falling=[7])
        self.assertEqual(svg.count("<rect"), 128)
        self.assertIn('class="b fall"', svg)
        self.assertIn('class="thresh"', svg)
        self.assertIn("rank 1<", svg)
        self.assertEqual(sh.scan(svg), [])

    def test_distribution_without_a_rank_draws_no_threshold(self):
        shares = [(i, 0.01) for i in range(10)]
        self.assertNotIn("thresh", sh.distribution_svg(shares, rank=None))

    def test_distribution_needs_two_subnets(self):
        self.assertEqual(sh.distribution_svg([(1, 0.5)], rank=1), "")

    def test_zero_share_does_not_break_the_log_scale(self):
        svg = sh.distribution_svg([(1, 0.09), (2, 0.0), (3, 0.0)], rank=1)
        self.assertIn("<rect", svg)
        self.assertNotIn("nan", svg.lower())


class SeriesTests(unittest.TestCase):
    def test_series_readers_refuse_an_unexpected_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            src = sh._brief()._Sources(config)
            try:
                with self.assertRaises(sh.ShinogiError):
                    sh.vitals_series(src, "1=1; DROP TABLE meta")
                with self.assertRaises(sh.ShinogiError):
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


class LedeTests(unittest.TestCase):
    def test_lede_names_the_largest_mover(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            edition, document, _l = sh.build(config, None)
            self.assertIn("SN", edition["lede"])
            self.assertIn(edition["lede"], document)

    def test_lede_falls_back_rather_than_inventing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            edition, _d, _l = sh.build(config, None)
            self.assertEqual(edition["lede"],
                             "No recorded figure moved in this window.")


class ZeroDeltaTests(unittest.TestCase):
    def test_a_delta_that_rounds_to_zero_is_suppressed(self):
        self.assertIsNone(sh._delta_value(100.0, 100.0))
        self.assertEqual(sh._delta(100.0, 100.0), "")
        self.assertIn("+10.0%", sh._delta(110.0, 100.0))


class ScriptingOffTests(unittest.TestCase):
    """The page must not need script to be read. Atlas is the only writer,
    so every figure is in the delivered document."""

    def test_stripping_every_script_leaves_the_page_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            build_live(config["live_db"])
            build_fleet(config["fleet_db"])
            _e, document, _l = sh.build(config, None)
            stripped = re.sub(r"<script\b.*?</script>", "", document,
                              flags=re.S | re.I)
            page = parse(stripped)
            self.assertEqual(tuple(page.ids), SECTION_IDS)
            self.assertEqual(page.h1, ["SHINOGI"])
            self.assertEqual(page.h3, ["Code", "Narrative"])
            self.assertEqual(len(page.asof), 1)
            for figure in ("0.00412", "318.42", "7,313,368"):
                self.assertIn(figure, stripped)

    def test_a_chart_introduces_no_figure_the_page_does_not_report(self):
        """A chart may only draw what is already recorded."""
        # share is a fraction of the whole, so 0.09 is 9 percent
        svg = sh.distribution_svg([(1, 0.09), (2, 0.04)], rank=1)
        self.assertIn("9.000% demand share", svg)
        self.assertIn("4.000% demand share", svg)
        self.assertNotIn("nan", svg.lower())
        self.assertEqual(svg.count("<rect"), 2)
