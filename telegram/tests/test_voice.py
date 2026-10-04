"""Voice conformance (change: telegram-voice-overhaul), tasks 3.1-3.3.

- Config-to-canon: every voice.lexicon / voice.gloss entry in the shipped
  telegram/config.json exists in the telegram/docs/voice.md section-2
  tables with the same approved word / gloss text, and the maps fail
  closed when missing or malformed.
- Per-class rendered output: verdict-led structure (headline first,
  sourced facts, next-action only when a real action exists, never
  boilerplate), approved words present, banned synonyms absent, gloss on
  first use only.
- Size budget: worst-case recorded fixtures stay within
  message_max_chars with balanced tags.
- Shrink order: the expandable absorbs shrinkage first, the trailer drops
  before body lines, body lines drop before the next-action line, the
  headline is never dropped, and glosses re-apply after a drop.
"""

import datetime
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
from test_notifier import make_config, seed_livedata, seed_repotrack  # noqa: E402

VOICE_MD = os.path.join(os.path.dirname(_HERE), "docs", "voice.md")
EM_DASH = "—"
EN_DASH = "–"


def _iso(hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


# ---------------------------------------------------------------------------
# Canon parsing (voice.md section 2 tables)
# ---------------------------------------------------------------------------

def _canon_tables():
    """Parse the approved-lexicon and jargon-gloss tables out of
    voice.md section 2. Returns (lexicon, glosses): lexicon maps
    concept -> {"approved": word, "banned": [tokens]}, glosses maps
    term -> gloss text."""
    with open(VOICE_MD, "r", encoding="utf-8") as handle:
        doc = handle.read()

    def rows_after(anchor):
        rows = []
        for line in doc.split(anchor, 1)[1].splitlines():
            if line.strip().startswith("|"):
                rows.append(line)
            elif rows:
                break
        return rows

    def cells(row):
        return [cell.strip() for cell in row.strip().strip("|").split("|")]

    def backticked(cell):
        return re.findall(r"`([^`]+)`", cell)

    lexicon = {}
    for row in rows_after("Approved lexicon:")[2:]:  # skip header + rule
        concept, approved, banned = cells(row)[:3]
        lexicon[concept] = {"approved": backticked(approved)[0],
                            "banned": backticked(banned)}
    glosses = {}
    for row in rows_after("Jargon glosses")[2:]:
        term, gloss = cells(row)[:2]
        glosses[backticked(term)[0]] = gloss
    return lexicon, glosses


def _banned_hits(text, banned):
    """Banned tokens per the voice.md matching rules: word boundaries,
    case-insensitive for all-lowercase tokens, case-sensitive for tokens
    containing uppercase, never inside a hyphenated compound."""
    hits = []
    for token in banned:
        flags = 0 if any(c.isupper() for c in token) else re.IGNORECASE
        pattern = (r"(?<![\w-])" + re.escape(token) + r"(?![\w-])")
        if re.search(pattern, text, flags):
            hits.append(token)
    return hits


class CanonConformanceTests(unittest.TestCase):
    def test_canon_tables_parse(self):
        lexicon, glosses = _canon_tables()
        self.assertGreaterEqual(len(lexicon), 10)
        self.assertIn("rank-pinned", glosses)
        self.assertEqual(lexicon["emission-gate bar"]["approved"], "bar")
        self.assertIn("theta", lexicon["emission-gate bar"]["banned"])

    def test_shipped_config_entries_exist_in_canon(self):
        with open(tg.CONFIG_FILE, "r", encoding="utf-8") as handle:
            shipped = json.load(handle)
        lexicon, glosses = _canon_tables()
        for concept, word in shipped["voice"]["lexicon"].items():
            self.assertIn(concept, lexicon,
                          "config lexicon concept not in canon: %s"
                          % concept)
            self.assertEqual(lexicon[concept]["approved"], word,
                             "approved word drifted for: %s" % concept)
        for term, gloss in shipped["voice"]["gloss"].items():
            self.assertIn(term, glosses,
                          "config gloss term not in canon: %s" % term)
            self.assertEqual(glosses[term], gloss,
                             "gloss text drifted for: %s" % term)

    def test_voice_maps_fail_closed(self):
        with self.assertRaises(tg.FatalTelegramError):
            tg.voice_maps({})
        with self.assertRaises(tg.FatalTelegramError):
            tg.voice_maps({"voice": {}})
        with self.assertRaises(tg.FatalTelegramError):
            tg.voice_maps({"voice": {"lexicon": {"a": "b"}}})
        with self.assertRaises(tg.FatalTelegramError):
            tg.voice_maps({"voice": {"lexicon": {"a": ""},
                                     "gloss": {"b": "c"}}})


# ---------------------------------------------------------------------------
# Rendered fixtures: one event per class from recorded fields
# ---------------------------------------------------------------------------

LIVE_SCHEMA = """
CREATE TABLE gate_events (
    id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
    netuid INTEGER NOT NULL, direction TEXT NOT NULL, share REAL NOT NULL,
    theta REAL NOT NULL, prev_side TEXT NOT NULL, emission_enabled INTEGER,
    block_number INTEGER, prev_theta REAL
);
CREATE TABLE gate_state (
    id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, theta REAL,
    q REAL, rank INTEGER, bar_mode TEXT
);
CREATE TABLE chain_param_events (
    id INTEGER PRIMARY KEY, item TEXT NOT NULL, prev_value TEXT NOT NULL,
    new_value TEXT NOT NULL, prev_provenance TEXT NOT NULL,
    new_provenance TEXT NOT NULL, observed_at TEXT NOT NULL,
    block_number INTEGER
);
"""

FLEET_SCHEMA = """
CREATE TABLE signal_events (
    id INTEGER PRIMARY KEY, class TEXT NOT NULL, tier TEXT NOT NULL,
    netuid INTEGER, term TEXT, dedup_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE signal_entries (
    event_id INTEGER NOT NULL, netuid INTEGER NOT NULL, price_tao REAL,
    as_of TEXT, status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (event_id, netuid)
);
CREATE TABLE slots (netuid INTEGER PRIMARY KEY, github_repo TEXT);
"""

KB_SCHEMA = """
CREATE TABLE intake_runs (
    run_id TEXT PRIMARY KEY, intake_date TEXT NOT NULL,
    coverage_date TEXT NOT NULL, parser_version TEXT NOT NULL,
    kb_version TEXT NOT NULL, files_json TEXT NOT NULL
);
CREATE TABLE units (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, active INTEGER NOT NULL
);
"""


class RenderedClassBase(unittest.TestCase):
    """Build every class's events once per test; adapters are pure over
    their source stores, so one build serves every assertion."""

    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        tmp = self.tmp_ctx.name
        self.config = make_config(tmp)
        self.max_chars = int(self.config["message_max_chars"])
        self.store = tg.open_store(os.path.join(tmp, "telegram.db"))
        self.addCleanup(self.store.close)

        # livedata: runtime upgrades (one crossing the governance spec,
        # one not), gate state + two crossings, two parameter events,
        # two schema-drift rows.
        self.live_db = os.path.join(tmp, "livedata.db")
        seed_livedata(self.live_db, live_spec=424,
                      upgrades=[(424, 430, 8612004), (430, 431, 8612005)])
        conn = sqlite3.connect(self.live_db)
        conn.executescript(LIVE_SCHEMA)
        conn.execute(
            "INSERT INTO gate_state (observed_at, theta, q, rank, "
            "bar_mode) VALUES (?, 0.008, 0.75, 32, 'rank')",
            (_iso(hours_ago=1),))
        conn.execute(
            "INSERT INTO gate_events (observed_at, netuid, direction, "
            "share, theta, prev_side, emission_enabled, block_number, "
            "prev_theta) VALUES (?, 42, 'fell-below', 0.0052, 0.0093, "
            "'above', 1, 8766216, 0.0088)", (_iso(),))
        conn.execute(
            "INSERT INTO gate_events (observed_at, netuid, direction, "
            "share, theta, prev_side, emission_enabled, block_number, "
            "prev_theta) VALUES (?, 7, 'rose-above', 0.0121, 0.0093, "
            "'below', 0, 8766216, NULL)", (_iso(),))
        conn.execute(
            "INSERT INTO chain_param_events (item, prev_value, new_value, "
            "prev_provenance, new_provenance, observed_at, block_number) "
            "VALUES ('EmissionBarRank', '0', '3', 'assumed-default', "
            "'explicit', ?, 8766216)", (_iso(),))
        conn.execute(
            "INSERT INTO chain_param_events (item, prev_value, new_value, "
            "prev_provenance, new_provenance, observed_at, block_number) "
            "VALUES ('SomeRootKnob', '1', '2', 'assumed-default', "
            "'explicit', ?, 8766216)", (_iso(),))
        conn.execute(
            "INSERT INTO integration_health (timestamp, provider, "
            "operation, category, detail) VALUES (?, 'taostats', "
            "'get_subnets', 'schema-drift', 'field total_stake missing')",
            (_iso(),))
        conn.execute(
            "INSERT INTO integration_health (timestamp, provider, "
            "operation, category, detail) VALUES (?, 'taostats', "
            "'get_metagraph', 'schema-drift', NULL)", (_iso(),))
        conn.commit()
        conn.close()

        # repotrack: the four verified 2026-07-12 heads (2 significant,
        # 2 churn held pending in the store).
        self.repo_db = os.path.join(tmp, "repotrack.db")
        seed_repotrack(self.repo_db)

        # fleet: one narrative-cluster instant event.
        self.fleet_db = os.path.join(tmp, "fleet.db")
        conn = sqlite3.connect(self.fleet_db)
        conn.executescript(FLEET_SCHEMA)
        conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) VALUES "
            "('narrative-cluster', 'instant', NULL, 'ai agents', "
            "'cluster:1', ?, ?)",
            (json.dumps({"term": "ai agents",
                         "members": [{"netuid": 1}, {"netuid": 2}],
                         "window_days": 3,
                         "first_mover": {"netuid": 1,
                                         "adopted_at": "2026-08-10",
                                         "commit_sha": "abc123def456"},
                         "prevalence": {"adopters": 2,
                                        "active_slots": 10}}),
             _iso()))
        conn.commit()
        conn.close()

        # knowledge: one run with staged units, one empty run.
        self.kb_db = os.path.join(tmp, "knowledge.db")
        conn = sqlite3.connect(self.kb_db)
        conn.executescript(KB_SCHEMA)
        conn.execute(
            "INSERT INTO intake_runs VALUES "
            "('20260813T010000Z-ab12', '2026-08-13', '2026-08-12', "
            "'1', '1', '{}')")
        conn.execute(
            "INSERT INTO intake_runs VALUES "
            "('20260813T020000Z-cd34', '2026-08-13', '2026-08-12', "
            "'1', '1', '{}')")
        for _ in range(2):
            conn.execute("INSERT INTO units (run_id, active) VALUES "
                         "('20260813T010000Z-ab12', 0)")
        conn.commit()
        conn.close()

        def ctx(spec):
            return {"config": self.config, "spec": spec,
                    "connection": self.store}

        classes = self.config["classes"]
        self.events = {}
        self.events["chain-runtime-upgrade"], _ = (
            tg.chain_runtime_upgrade_events(
                self.live_db, None, ctx(classes["chain-runtime-upgrade"])))
        self.events["gate-crossing"], _ = tg.gate_crossing_events(
            self.live_db, None,
            ctx({"enabled": True, "source_db": self.live_db,
                 "cooldown_hours": 24}))
        self.events["chain-parameter-change"], _ = (
            tg.chain_parameter_change_events(
                self.live_db, None,
                ctx({"governs": {
                    "EmissionBarRank":
                    "emission gate bar selection: N > 0 pins the bar to "
                    "the Nth largest demand share, N = 0 falls back to "
                    "the q-mass quantile"}})))
        self.events["repository-update"], _ = tg.repository_update_events(
            self.repo_db, None, ctx(classes["repository-update"]))
        self.events["fleet-signal"], _ = tg.fleet_signal_events(
            self.fleet_db, None,
            ctx({"source_db": self.fleet_db, "digest_backstop_hours": 24}))
        self.events["schema-drift"], _ = tg.schema_drift_events(
            self.live_db, None, ctx(classes["schema-drift"]))
        self.events["knowledge-ingestion"], _ = (
            tg.knowledge_ingestion_events(
                self.kb_db, None, ctx(classes["knowledge-ingestion"])))

    def all_events(self):
        return [event for events in self.events.values()
                for event in events]

    def assert_layout_invariants(self, event):
        text, html = event["text"], event["html"]
        first = text.split("\n")[0]
        self.assertIn(first[:1], tuple(tg.SEVERITY_MARK.values()),
                      "severity marker must lead: %r" % text[:80])
        self.assertNotIn("Atlas · ", first)
        self.assertTrue(html.split("\n")[0].endswith("</b>"))
        self.assertNotIn(EM_DASH, text)
        self.assertNotIn(EN_DASH, text)
        self.assertNotIn(EM_DASH, html)
        self.assertNotIn(EN_DASH, html)
        self.assertLessEqual(len(text), self.max_chars)
        self.assertLessEqual(len(html), self.max_chars)
        for open_t, close_t in (("<b>", "</b>"), ("<code>", "</code>"),
                                ("<i>", "</i>"), ("<tg-time", "</tg-time>"),
                                ("<blockquote", "</blockquote>")):
            self.assertEqual(html.count(open_t), html.count(close_t),
                             "unbalanced %s in %r" % (close_t, html[:120]))
        # No raw microsecond timestamp outside the details fold.
        body = html.split("<blockquote")[0]
        self.assertIsNone(re.search(r"\d{2}:\d{2}:\d{2}\.\d{6}", body))
        # A next action, when present, is the last line.
        if "Next:" in text:
            self.assertTrue(text.split("\n")[-1].startswith("Next: "))


class PerClassVoiceTests(RenderedClassBase):
    def test_every_event_layout_invariants(self):
        events = self.all_events()
        self.assertEqual(len(events), 13)
        for event in events:
            self.assert_layout_invariants(event)

    def test_no_banned_synonyms_anywhere(self):
        lexicon, _glosses = _canon_tables()
        banned = [token for entry in lexicon.values()
                  for token in entry["banned"]]
        for event in self.all_events():
            for rendered in (event["text"], event["html"]):
                self.assertEqual(_banned_hits(rendered, banned), [],
                                 "banned synonym in %s" % event["event_id"])

    def test_gate_crossing_voice(self):
        fell, rose = self.events["gate-crossing"]
        self.assertEqual(fell["text"].split("\n")[0],
                         "🔴 Subnet 42 fell below the emission bar")
        self.assertIn("gated emission collapses toward zero", fell["text"])
        for word in ("demand share", "bar"):
            self.assertIn(word, fell["text"])
        self.assertIn("Shares: TaoSwap panel. Bar: chain RPC.",
                      fell["text"])
        self.assertIn("Bar: 0.930% (the 32nd largest demand share)",
                      fell["text"])
        self.assertEqual(fell["text"].split("\n")[-1],
                         "Next: review your subnet 42 position.")
        self.assertIn("<blockquote expandable>", fell["html"])
        self.assertIn("<tg-time unix=", fell["html"])
        # emission-disabled informational crossing: no action line
        self.assertTrue(rose["text"].startswith("🔵 "))
        self.assertIn("earns zero either way", rose["text"])
        self.assertNotIn("Next:", rose["text"])

    def test_chain_runtime_upgrade_voice(self):
        crossing, plain = self.events["chain-runtime-upgrade"]
        self.assertEqual(crossing["text"].split("\n")[0],
                         "🔴 Bittensor upgraded to runtime spec 430")
        for word in ("live chain", "governance spec"):
            self.assertIn(word.lower(), crossing["text"].lower())
        self.assertIn("Block 8,612,004", crossing["text"])
        self.assertEqual(crossing["text"].split("\n")[-1],
                         "Next: review your subnet positions, because "
                         "conviction enforcement is live.")
        # conviction-based glossed exactly once, in the prose sentence
        self.assertEqual(crossing["text"].count("conviction-based"), 1)
        self.assertEqual(
            crossing["text"].count("(weighted by how long a position "
                                   "is held)"), 1)
        # no governance crossing: no action line, watch marker
        self.assertTrue(plain["text"].startswith("🟠 "))
        self.assertNotIn("Next:", plain["text"])

    def test_chain_parameter_change_voice(self):
        bar, knob = self.events["chain-parameter-change"]
        self.assertEqual(bar["text"].split("\n")[0],
                         "🔴 Emission bar rule changed: EmissionBarRank "
                         "0 → 3")
        self.assertIn("emission gate", bar["text"])
        self.assertIn("Governs:", bar["text"])
        self.assertIn("Before: chain default, not stored. After: stored "
                      "value.", bar["text"])
        self.assertIn("Next: review your subnet positions against the "
                      "new gate terms", bar["text"])
        # no governs entry: says so, and the action names the config key
        self.assertIn("no plain description", knob["text"])
        self.assertIn("classes.chain-parameter-change.governs",
                      knob["text"].split("\n")[-1])

    def test_repository_update_voice(self):
        spec_bump = self.events["repository-update"][0]
        headline = spec_bump["text"].split("\n")[0]
        self.assertTrue(headline.startswith("🟠 Subtensor code for runtime "
                                            "spec 428"))
        # glosses never reach a headline or recorded data
        self.assertNotIn("(the chain's runtime code version)",
                         spec_bump["text"])
        self.assertIn("repo", spec_bump["text"])
        self.assertIn("View diff on GitHub",
                      [b[0] for b in spec_bump["buttons"]])

    def test_fleet_signal_voice(self):
        cluster = self.events["fleet-signal"][0]
        self.assertTrue(cluster["text"].startswith(
            "🟠 2 subnets adopted ai agents within 3 days"))
        self.assertIn("subnet 1", cluster["text"])
        self.assertIn("Source: fleet repos (code), not the live chain",
                      cluster["text"])

    def test_schema_drift_voice(self):
        drift, no_detail = self.events["schema-drift"]
        self.assertEqual(drift["text"].split("\n")[0],
                         "🟠 TaoStats changed its reply format. "
                         "get_subnets is paused.")
        self.assertIn("What changed: field total_stake missing",
                      drift["text"])
        self.assertIn("Source: livedata integration health", drift["text"])
        self.assertIn("Next: update the pinned schema for taostats "
                      "get_subnets", drift["text"])
        # absent recorded value carries the n/a marker
        self.assertIn("What changed: n/a", no_detail["text"])

    def test_knowledge_ingestion_voice(self):
        staged, empty = self.events["knowledge-ingestion"]
        self.assertEqual(staged["text"].split("\n")[0],
                         "🟠 2 new knowledge units are waiting for review")
        self.assertIn("Source: knowledge intake store", staged["text"])
        self.assertIn("python3 knowledge/atlas_kb.py activate --run "
                      "20260813T010000Z-ab12", staged["text"].split(
                          "\n")[-1])
        self.assertIn("<code>python3 knowledge/atlas_kb.py activate --run "
                      "20260813T010000Z-ab12</code>", staged["html"])
        # zero staged: nothing to review, no action line
        self.assertTrue(empty["text"].startswith("🔵 "))
        self.assertNotIn("Next:", empty["text"])


class GlossFrameTests(unittest.TestCase):
    GLOSSES = {"q-mass": "a quantile of the demand-share distribution",
               "basket": "one root validator's escrowed fund"}

    def test_gloss_on_first_use_in_prose_only(self):
        msg = tg.Message("info", "q-mass headline",
                         meaning="q-mass one, q-mass two",
                         body=["q-mass body"], facts=[("Mode", "q-mass")])
        text = tg.render_plain(msg, 3500, dict(self.GLOSSES))
        lines = text.split("\n")
        self.assertEqual(lines[0], "🔵 q-mass headline")
        self.assertEqual(lines[1], "q-mass (a quantile of the "
                                   "demand-share distribution) one, "
                                   "q-mass two")
        self.assertEqual(text.count("(a quantile"), 1)
        self.assertIn("Mode: q-mass", text)
        self.assertIn("q-mass body", text)

    def test_recorded_text_is_never_glossed(self):
        msg = tg.Message("watch", "Subtensor code changed",
                         body=["• " + tg.rec("fix(basket): restore checks")],
                         details=["pallets: basket"])
        text = tg.render_plain(msg, 3500, dict(self.GLOSSES))
        self.assertIn("fix(basket): restore checks", text)
        self.assertNotIn("escrowed fund", text)

    def test_gloss_outside_code_span(self):
        msg = tg.Message("info", "h", meaning="mode %sq-mass%s at q 0.75"
                         % (tg._MONO_OPEN, tg._MONO_CLOSE))
        html = tg.render_html(msg, 3500, dict(self.GLOSSES))
        self.assertIn("<code>q-mass</code> (a quantile of the demand-share "
                      "distribution) at q 0.75", html)


class ShrinkOrderTests(unittest.TestCase):
    def test_details_absorb_shrinkage_first(self):
        msg = tg.Message("watch", "headline", meaning="meaning",
                         facts=[("One", "fact one"), ("Two", "fact two")],
                         details=["detail " + "x" * 400 for _ in range(4)],
                         next_action="do the thing.")
        html = tg.render_html(msg, 600)
        self.assertIn("<b>headline</b>", html)
        self.assertIn("fact one", html)
        self.assertIn("fact two", html)
        self.assertIn("<b>Next:</b> do the thing.", html)
        self.assertLessEqual(len(html), 600)

    def test_body_drops_before_facts_and_next_action(self):
        msg = tg.Message("watch", "headline",
                         facts=[("Fact", "kept")],
                         body=["line %d %s" % (i, "z" * 100)
                               for i in range(6)],
                         next_action="do the thing.")
        html = tg.render_html(msg, 400)
        self.assertIn("<b>headline</b>", html)
        self.assertIn("kept", html)
        self.assertIn("do the thing.", html)
        self.assertNotIn("line 5", html)  # dropped from the end first
        self.assertLessEqual(len(html), 400)

    def test_headline_never_dropped(self):
        msg = tg.Message("act", "h" * 80, meaning="m" * 200,
                         facts=[("F", "z" * 200)], details=["x" * 500],
                         next_action="a" * 100)
        html = tg.render_html(msg, 120)
        self.assertTrue(html.startswith("🔴 <b>"))
        self.assertTrue(html.endswith("</b>"))
        self.assertLessEqual(len(html), 120)


class FormatTests(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(tg.fmt_int(9197096), "9,197,096")
        self.assertEqual(tg.fmt_pct(0.008581174), "0.858%")
        self.assertEqual(tg.fmt_pct(0.0077, 2), "0.77%")
        self.assertEqual(tg.fmt_tao(0.00425), "0.00425 τ")
        self.assertEqual(tg.fmt_tao(0.0460907), "0.0461 τ")
        self.assertEqual(tg.fmt_tao(0.0000123), "0.0000123 τ")
        self.assertEqual(tg.fmt_usd(292.234), "$292.23")
        self.assertEqual(tg.fmt_change(12.64), "+12.6%")
        self.assertEqual(tg.fmt_change(-51.3), tg.MINUS + "51.3%")
        self.assertEqual(tg.plural(1, "commit"), "1 commit")
        self.assertEqual(tg.plural(1200, "file"), "1,200 files")

    def test_time_token(self):
        token = tg.fmt_time("2026-10-02T19:02:20.932792+00:00")
        msg = tg.Message("info", "h", facts=[("When", token)])
        html = tg.render_html(msg)
        self.assertIn('<tg-time unix="1790967740" format="wDT">'
                      'Fri 2 Oct, 19:02 UTC</tg-time>', html)
        self.assertIn("When: Fri 2 Oct, 19:02 UTC", tg.render_plain(msg))
        self.assertIn("(dated)", tg.fmt_time("not a time"))

    def test_subnet_names(self):
        names = {49: "Nepher Robotics", 5: "a<b"}
        self.assertEqual(tg.subnet_label(49, names),
                         "Subnet 49 (Nepher Robotics)")
        self.assertEqual(tg.subnet_label(7, names), "Subnet 7")
        self.assertEqual(tg.subnet_tag(49, names), "Nepher Robotics (49)")
        html = tg.render_html(tg.Message("info", tg.subnet_label(5, names)))
        self.assertIn("a&lt;b", html)

    def test_names_skip_unknown_and_empty(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE panel_snapshot (id INTEGER PRIMARY KEY, "
                     "netuid INTEGER, name TEXT)")
        conn.executemany("INSERT INTO panel_snapshot (netuid, name) "
                         "VALUES (?, ?)", [(1, "old"), (1, "new"),
                                           (2, "Unknown"), (3, "")])
        self.assertEqual(tg.subnet_names_from(conn), {1: "new"})

    def test_severity_table(self):
        sf = tg.severity_for
        self.assertEqual(sf("chain-runtime-upgrade"), "watch")
        self.assertEqual(sf("chain-runtime-upgrade", governance_crossed=True),
                         "act")
        self.assertEqual(sf("chain-parameter-change",
                            item="SubnetEmissionEnabled"), "act")
        self.assertEqual(sf("chain-parameter-change", item="Other"), "watch")
        self.assertEqual(sf("gate-crossing", emission_enabled=1,
                            direction="rose-above"), "good")
        self.assertEqual(sf("gate-crossing", emission_enabled=1,
                            direction="fell-below"), "act")
        self.assertEqual(sf("gate-crossing", emission_enabled=0,
                            direction="fell-below"), "info")
        for cls in ("fail-closed", "probe-drift", "upgrade-blocked"):
            self.assertEqual(sf(cls), "act")
        for cls in ("schema-drift", "repository-update", "econ-code",
                    "narrative-cluster", "watchlist", "upgrade-retrying",
                    "upgrade-stalled"):
            self.assertEqual(sf(cls), "watch")
        self.assertEqual(sf("knowledge-ingestion", staged=2), "watch")
        self.assertEqual(sf("knowledge-ingestion", staged=0), "info")
        for cls in ("churn-digest", "signal-digest", "subnet-registry",
                    "upgrade-waiting"):
            self.assertEqual(sf(cls), "info")
        for cls in ("upgrade-updated", "upgrade-dry-run", "probe-cleared",
                    "test"):
            self.assertEqual(sf(cls), "done")

    def test_links_omit_unsafe_or_missing(self):
        self.assertEqual(tg.link({}, "taostats_subnet", netuid=49),
                         "https://taostats.io/subnets/49")
        self.assertIsNone(tg.link({}, "taostats_subnet", netuid=None))
        self.assertIsNone(tg.link({}, "github_commit", repo="a/b",
                                  sha="x y"))
        self.assertIsNone(tg.link({"links": {"taostats_subnet": ""}},
                                  "taostats_subnet", netuid=1))
        self.assertEqual(tg.button({"links": {}}, "x", "nope"), [])


class WorstCaseBudgetTests(unittest.TestCase):
    def test_worst_case_fixtures_fit_with_balanced_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            max_chars = int(config["message_max_chars"])
            store = tg.open_store(os.path.join(tmp, "telegram.db"))
            self.addCleanup(store.close)
            live_db = os.path.join(tmp, "livedata.db")
            seed_livedata(live_db, live_spec=424,
                          upgrades=[(424, 430, 8612004)])
            repo_db = os.path.join(tmp, "repotrack.db")
            seed_repotrack(repo_db, truncated=True)
            ctx = {"config": config,
                   "spec": config["classes"]["repository-update"],
                   "connection": store}
            events, _wm = tg.repository_update_events(repo_db, None, ctx)
            self.assertTrue(events)
            for event in events:
                self.assertLessEqual(len(event["html"]), max_chars)
                for open_t, close_t in (("<b>", "</b>"),
                                        ("<code>", "</code>"),
                                        ("<blockquote", "</blockquote>")):
                    self.assertEqual(event["html"].count(open_t),
                                     event["html"].count(close_t))


if __name__ == "__main__":
    unittest.main()
