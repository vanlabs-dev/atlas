"""Block units, kinds, index rebuild, query, payload (change:
knowledge-retrieval)."""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from _helpers import CORPUS_DIR, akb, call_server, ingest_real_corpus, \
    tool_call

import atlas_kb_server as srv

EVAL_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "benchmark", "retrieval_eval.json")

FIXTURE = """intro line

# Title

Lead paragraph one
continues here.

## Alpha

- first item
  - nested under first
  continuation of first
- second item
1. numbered one
**Term**: bold entry

---

Paragraph after rule.

### Sub

```
code - not a block start
```

- sub item
"""


class BlockSplitterTests(unittest.TestCase):
    def units(self):
        return akb.split_units("f.md", FIXTURE)

    def test_blocks_and_paths(self):
        got = [(u["heading_path"], u["content"].splitlines()[0])
               for u in self.units()]
        self.assertEqual(got, [
            ("(preamble)", "intro line"),
            ("Title", "Lead paragraph one"),
            ("Alpha", "- first item"),
            ("Alpha", "- second item"),
            ("Alpha", "1. numbered one"),
            ("Alpha", "**Term**: bold entry"),
            ("Alpha", "Paragraph after rule."),
            ("Alpha > Sub", "```"),
            ("Alpha > Sub", "- sub item"),
        ])

    def test_nested_and_continuation_stay_with_parent(self):
        first = self.units()[2]
        self.assertIn("nested under first", first["content"])
        self.assertIn("continuation of first", first["content"])

    def test_fence_is_not_split(self):
        fence = self.units()[7]
        self.assertIn("code - not a block start", fence["content"])
        self.assertTrue(fence["content"].endswith("```"))

    def test_ids_and_lines(self):
        units = self.units()
        self.assertEqual(units[2]["unit_id"], "f.md::Alpha#1")
        self.assertEqual(units[8]["unit_id"], "f.md::Alpha > Sub#2")
        lines = FIXTURE.splitlines()
        for unit in units:
            self.assertEqual(
                lines[unit["line_start"] - 1].strip(),
                unit["content"].splitlines()[0].strip())
            self.assertEqual(
                lines[unit["line_end"] - 1].strip(),
                unit["content"].splitlines()[-1].strip())

    def test_oversize_block_splits_at_nested_items(self):
        text = "## S\n\n- lead\n" + "".join(
            "  - nested %d %s\n" % (n, "x" * 400) for n in range(6))
        units = akb.split_units("f.md", text)
        self.assertEqual(len(units), 7)
        self.assertEqual(units[0]["content"], "- lead")
        for unit in units:
            self.assertLessEqual(len(unit["content"]), akb.BLOCK_CAP)

    def test_real_corpus_every_text_line_in_one_unit(self):
        corpus = akb.load_corpus()
        for filename, info in corpus["files"].items():
            lines = info["text"].splitlines()
            covered = {}
            for unit in akb.split_units(filename, info["text"]):
                self.assertLessEqual(len(unit["content"]), akb.BLOCK_CAP,
                                     unit["unit_id"])
                for number in range(unit["line_start"],
                                    unit["line_end"] + 1):
                    self.assertNotIn(number, covered, unit["unit_id"])
                    covered[number] = unit["unit_id"]
            for number, line in enumerate(lines, 1):
                if (line.strip() and not akb._HEADING.match(line)
                        and not akb._RULE.match(line)):
                    self.assertIn(number, covered,
                                  "%s:%d not in any unit" % (filename,
                                                             number))


class KindTests(unittest.TestCase):
    def test_kind_matching(self):
        kinds = {"A": "correction", "A > B": "procedure"}
        self.assertEqual(akb.kind_for("A", kinds), "correction")
        self.assertEqual(akb.kind_for("A > C", kinds), "correction")
        self.assertEqual(akb.kind_for("A > B", kinds), "procedure")
        self.assertEqual(akb.kind_for("AB", kinds), "fact")
        self.assertEqual(akb.kind_for("Other", kinds), "fact")

    def test_every_mapped_heading_exists(self):
        kinds = akb.load_kinds()
        corpus = akb.load_corpus()
        paths = {unit["heading_path"]
                 for filename, info in corpus["files"].items()
                 for unit in akb.split_units(filename, info["text"])}
        for entry in kinds:
            self.assertTrue(
                any(path == entry or path.startswith(entry + " > ")
                    for path in paths),
                "unit-kinds.json entry %r matches no corpus heading"
                % entry)

    def test_bad_kind_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "k.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"kinds": {"A": "secret"}}, handle)
            with self.assertRaises(akb.FatalKbError):
                akb.load_kinds(path)


OLD_SCHEMA = """
CREATE TABLE intake_runs (run_id TEXT PRIMARY KEY, intake_date TEXT NOT NULL,
    coverage_date TEXT NOT NULL, parser_version TEXT NOT NULL,
    kb_version TEXT NOT NULL, files_json TEXT NOT NULL);
CREATE TABLE sources (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
    filename TEXT NOT NULL, byte_size INTEGER NOT NULL, sha256 TEXT NOT NULL,
    coverage_date TEXT NOT NULL);
CREATE TABLE units (id INTEGER PRIMARY KEY, unit_id TEXT NOT NULL,
    run_id TEXT NOT NULL, source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL, heading_path TEXT NOT NULL,
    line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
    coverage_date TEXT NOT NULL, temporal_scope TEXT,
    evidence_state TEXT NOT NULL, conflict_note TEXT,
    content TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE units_fts USING fts5(heading_path, content,
    content=units, content_rowid=id);
CREATE TABLE audit (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL,
    actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
"""


def make_old_store(path):
    """A store as the pre-change code wrote it: no kind, no kb_meta, a
    unicode61 index holding every row."""
    connection = sqlite3.connect(path)
    connection.executescript(OLD_SCHEMA)
    connection.execute(
        "INSERT INTO intake_runs VALUES ('old-run', '2026-10-26T00:00:00',"
        " '2026-10-26', '1', '0.1.0', '{}')")
    rows = [("ground-truth.md::Staking", "Staking",
             "- Staking TAO on a subnet converts TAO to alpha."),
            ("ground-truth.md::Subnets", "Subnets",
             "- The network is capped at 128 subnets.")]
    for unit_id, heading, content in rows:
        cursor = connection.execute(
            "INSERT INTO units (unit_id, run_id, source_file, source_sha256,"
            " heading_path, line_start, line_end, coverage_date,"
            " temporal_scope, evidence_state, conflict_note, content,"
            " active) VALUES (?, 'old-run', 'ground-truth.md', 'x', ?, 1, 1,"
            " '2026-10-26', NULL, 'confirmed', NULL, ?, 1)",
            (unit_id, heading, content))
        connection.execute(
            "INSERT INTO units_fts (rowid, heading_path, content) VALUES "
            "(?, ?, ?)", (cursor.lastrowid, heading, content))
    connection.commit()
    connection.close()


class IndexTests(unittest.TestCase):
    def test_ingest_adds_no_index_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, _run, _ = ingest_real_corpus(tmp, activate=False)
            connection = sqlite3.connect(db)
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master")}
            self.assertNotIn("units_fts", tables)
            connection.close()

    def test_index_holds_only_active_searchable_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, first, _ = ingest_real_corpus(tmp)
            second, _ = akb.ingest(db, tmp)
            self.assertEqual(akb.activate(db, second, actor="test"), 0)
            connection = sqlite3.connect(db)
            # an external-content table's count(*) reads the content
            # table; the docsize shadow table has one row per indexed unit
            indexed = connection.execute(
                "SELECT count(*) FROM units_fts_docsize").fetchone()[0]
            searchable = connection.execute(
                "SELECT count(*) FROM units WHERE run_id = ? AND kind IN "
                "('fact', 'correction')", (second,)).fetchone()[0]
            total = connection.execute(
                "SELECT count(*) FROM units").fetchone()[0]
            self.assertEqual(indexed, searchable)
            self.assertGreater(total, indexed)
            self.assertEqual(akb.index_version(connection),
                             akb.INDEX_VERSION)
            connection.close()

    def test_procedure_units_are_not_searched_but_fetchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, _run, _ = ingest_real_corpus(tmp)
            store = srv.KnowledgeStore(db)
            # "Scan the article for these patterns" is fact-patterns'
            # preamble, mapped procedure
            result = store.search("scan the article patterns saving", 10)
            for unit in result.get("results", []):
                self.assertNotEqual(unit["kind"], "procedure")
            connection = sqlite3.connect(db)
            unit_id = connection.execute(
                "SELECT unit_id FROM units WHERE active = 1 AND kind = "
                "'procedure' LIMIT 1").fetchone()[0]
            connection.close()
            evidence = store.get_evidence(unit_id)
            self.assertEqual(evidence["status"], "ok")
            self.assertEqual(evidence["unit"]["kind"], "procedure")

    def test_failed_rebuild_keeps_prior_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, first, _ = ingest_real_corpus(tmp)
            second, _ = akb.ingest(db, tmp)
            with mock.patch.object(
                    akb, "rebuild_index",
                    side_effect=sqlite3.OperationalError("boom")):
                self.assertEqual(akb.activate(db, second, actor="test"), 1)
            store = srv.KnowledgeStore(db)
            self.assertEqual(store.kb_status()["active_run"], first)
            self.assertEqual(store.search("staking", 5)["status"], "ok")

    def test_old_store_migrates_on_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "kb.db")
            make_old_store(db)
            run_id, _ = akb.ingest(db, tmp)
            connection = sqlite3.connect(db)
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(units)")}
            self.assertIn("kind", columns)
            old = connection.execute(
                "SELECT kind, active FROM units WHERE run_id = 'old-run'"
            ).fetchall()
            self.assertEqual(old, [("fact", 1), ("fact", 1)])
            self.assertIsNone(akb.index_version(connection))
            connection.close()
            self.assertEqual(akb.activate(db, run_id, actor="test"), 0)
            store = srv.KnowledgeStore(db)
            self.assertEqual(store.kb_status()["index_version"],
                             akb.INDEX_VERSION)


class OldStoreServingTests(unittest.TestCase):
    def test_old_store_still_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "kb.db")
            make_old_store(db)
            store = srv.KnowledgeStore(db)
            result = store.search("How does staking work?", 5)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["results"][0]["unit_id"],
                             "ground-truth.md::Staking")
            self.assertEqual(result["results"][0]["kind"], "fact")
            self.assertIsNone(store.kb_status()["index_version"])


class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.run_id, _ = ingest_real_corpus(cls.tmp.name)
        cls.store = srv.KnowledgeStore(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_query_builder(self):
        build = srv.KnowledgeStore.build_queries
        self.assertEqual(build("How does staking work?"), ['"staking"'])
        self.assertEqual(build("the of and"), [])
        queries = build("SN82 emission")
        self.assertEqual(len(queries), 2)
        self.assertIn('"subnet 82"', queries[0])
        self.assertIn(" AND ", queries[0])
        self.assertIn(" OR ", queries[1])
        self.assertEqual(build("SN 82"), build("sn82"))
        self.assertEqual(len(build(" ".join("w%d" % n for n in range(30)))
                             [0].split(" AND ")), srv.MAX_QUERY_TERMS)

    def test_stemmed_match(self):
        result = self.store.search("halve", 5)
        self.assertEqual(result["status"], "ok")
        self.assertIn("Halving", result["results"][0]["heading_path"])

    def test_subnet_shorthand(self):
        result = self.store.search("SN82", 5)
        self.assertTrue(any("82" in unit["content"]
                            for unit in result["results"]))

    def test_question_words_do_not_steer(self):
        result = self.store.search("How does staking work?", 5)
        self.assertEqual(result["results"][0]["heading_path"], "Staking")

    def test_unknown_word_does_not_empty_ranking(self):
        # "pie" is in no unit: ranking must use the AND of the held terms,
        # which finds the split; the OR pass alone ranks conviction first
        result = self.store.search("subnet rewards share pie", 5)
        self.assertIn("distribution split", result["results"][0]["content"])

    def test_single_letters_are_dropped(self):
        self.assertNotIn('"s"', srv.KnowledgeStore.build_terms(
            "subnet's emission"))

    def test_all_stopwords_is_invalid(self):
        result = self.store.search("what is the", 5)
        self.assertEqual(result["error"]["category"], "invalid")

    def test_bounded_payload(self):
        for query in ("emission gate bar", "conviction", "subnet",
                      "staking", "root reborn"):
            result = self.store.search(query, 5)
            self.assertLessEqual(len(json.dumps(result)), 8 * 1024, query)
            for unit in result["results"]:
                self.assertLessEqual(len(unit["content"]), srv.CONTENT_CAP)

    def test_truncated_flag(self):
        unit = (("u", "f", "h", 1, 2, "d", None, "confirmed", None,
                 "x" * (srv.CONTENT_CAP + 10)), "fact")
        payload = self.store._result_payload(unit[0] + (unit[1],), True)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["content"]), srv.CONTENT_CAP)
        self.assertNotIn("conflict_note", payload)

    def test_evidence_has_section(self):
        unit_id = self.store.search("childkey take", 5)["results"][0][
            "unit_id"]
        evidence = self.store.get_evidence(unit_id)
        self.assertIn(evidence["unit"]["content"],
                      evidence["section"]["content"])
        self.assertGreater(len(evidence["section"]["content"]),
                           len(evidence["unit"]["content"]))

    def test_default_result_count_over_pipes(self):
        payloads = call_server(self.db, [tool_call(
            1, "knowledge_search", {"query": "subnet emission"})])
        self.assertEqual(len(payloads[1]["results"]),
                         srv.DEFAULT_MAX_RESULTS)


class RetrievalEvaluationTests(unittest.TestCase):
    """The committed evaluation (spec: Retrieval evaluation)."""

    def test_every_query_finds_its_marker(self):
        with open(EVAL_FILE, "r", encoding="utf-8") as handle:
            evaluation = json.load(handle)
        self.assertGreaterEqual(len(evaluation["queries"]), 20)
        audit = {"halve", "SN82", "How does staking work?", "yuma3"}
        self.assertTrue(audit <= {q["query"] for q in evaluation["queries"]})
        with tempfile.TemporaryDirectory() as tmp:
            db, _run, _ = ingest_real_corpus(tmp)
            store = srv.KnowledgeStore(db)
            misses = []
            for item in evaluation["queries"]:
                result = store.search(item["query"], evaluation["top_k"])
                if not any(item["marker"].lower() in unit["content"].lower()
                           for unit in result.get("results", [])):
                    misses.append("%r expects %r" % (item["query"],
                                                     item["marker"]))
            self.assertEqual(misses, [])


if __name__ == "__main__":
    unittest.main()
