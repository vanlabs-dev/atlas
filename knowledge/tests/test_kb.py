"""Intake, splitting, marking, activation — against the real snapshot."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from _helpers import CORPUS_DIR, akb, ingest_real_corpus


class SplitterTests(unittest.TestCase):
    def test_real_corpus_splits_into_sections(self):
        corpus = akb.load_corpus()
        total = 0
        for filename, info in corpus["files"].items():
            units = akb.split_units(filename, info["text"])
            total += len(units)
            for unit in units:
                self.assertTrue(unit["content"].strip())
                self.assertLessEqual(unit["line_start"], unit["line_end"])
                self.assertTrue(unit["unit_id"].startswith(filename))
        self.assertGreaterEqual(total, 15)
        self.assertLessEqual(total, 40)

    def test_unique_unit_ids_in_real_corpus(self):
        corpus = akb.load_corpus()
        ids = []
        for filename, info in corpus["files"].items():
            ids += [unit["unit_id"] for unit
                    in akb.split_units(filename, info["text"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_temporal_scope_extraction(self):
        scope = akb.extract_temporal_scope(
            "Taoflow applied from November 2025 to June 2026; since "
            "June 2026 the model is price-based.")
        self.assertIn("November 2025 to June 2026", scope)

    def test_preamble_unit(self):
        units = akb.split_units("x.md", "intro line\n\n## A\ncontent\n")
        self.assertEqual(units[0]["heading_path"], "(preamble)")
        self.assertEqual(units[1]["heading_path"], "A")


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ingest_records_real_corpus(self):
        # The 2026-08-06 re-sync absorbed all supersession markers, so the
        # real corpus stages with no conflicting units.
        db, run_id, report = ingest_real_corpus(self.tmp.name,
                                                activate=False)
        self.assertNotIn("conflicting", report["unit_counts_by_state"])
        self.assertGreater(
            report["unit_counts_by_state"].get("confirmed", 0), 0)
        self.assertEqual(report["secret_scan_findings"], [])
        self.assertEqual(report["duplicate_unit_ids"], [])
        connection = sqlite3.connect(db)
        try:
            run = connection.execute(
                "SELECT coverage_date, parser_version FROM intake_runs "
                "WHERE run_id = ?", (run_id,)).fetchone()
            self.assertEqual(run, ("2026-08-06", akb.PARSER_VERSION))
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM units WHERE active = 1"
            ).fetchone()[0], 0, "units must stage inactive")
        finally:
            connection.close()

    def test_markers_mark_conflicts(self):
        markers = os.path.join(self.tmp.name, "markers.json")
        with open(markers, "w", encoding="utf-8") as handle:
            json.dump([{"match": "emission gate",
                        "state": "conflicting",
                        "note": "synthetic test marker"}], handle)
        db, run_id, report = ingest_real_corpus(self.tmp.name,
                                                activate=False,
                                                markers_file=markers)
        self.assertGreaterEqual(
            report["unit_counts_by_state"]["conflicting"], 1)
        connection = sqlite3.connect(db)
        try:
            conflict = connection.execute(
                "SELECT conflict_note FROM units WHERE "
                "evidence_state = 'conflicting'").fetchone()
            self.assertEqual(conflict[0], "synthetic test marker")
        finally:
            connection.close()
        with open(os.path.join(self.tmp.name,
                               "validation-report-%s.md" % run_id),
                  "r", encoding="utf-8") as handle:
            self.assertIn("Marked conflicts", handle.read())

    def test_activation_flips_active_and_audits(self):
        db, run_id, _report = ingest_real_corpus(self.tmp.name,
                                                 activate=False)
        self.assertEqual(akb.activate(db, run_id, actor="op"), 0)
        connection = sqlite3.connect(db)
        try:
            active = connection.execute(
                "SELECT count(*) FROM units WHERE active = 1"
            ).fetchone()[0]
            audit = connection.execute(
                "SELECT actor, action FROM audit ORDER BY id DESC "
                "LIMIT 1").fetchone()
        finally:
            connection.close()
        self.assertGreater(active, 0)
        self.assertEqual(audit, ("op", "activate"))

    def test_second_activation_deactivates_first(self):
        db, run1, _r1 = ingest_real_corpus(self.tmp.name, activate=False)
        akb.activate(db, run1, actor="op")
        run2, _r2 = akb.ingest(db, self.tmp.name)
        akb.activate(db, run2, actor="op")
        connection = sqlite3.connect(db)
        try:
            active_runs = connection.execute(
                "SELECT DISTINCT run_id FROM units WHERE active = 1"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(active_runs, [(run2,)])

    def test_activate_unknown_run_fails(self):
        db, _run, _report = ingest_real_corpus(self.tmp.name,
                                               activate=False)
        self.assertEqual(akb.activate(db, "nope", actor="op"), 1)

    def test_hash_mismatch_aborts(self):
        tampered = os.path.join(self.tmp.name, "corpus")
        shutil.copytree(CORPUS_DIR, tampered)
        with open(os.path.join(tampered, "ground-truth.md"), "a",
                  encoding="utf-8") as handle:
            handle.write("\ntampered\n")
        with self.assertRaises(akb.FatalKbError) as context:
            akb.load_corpus(tampered,
                            os.path.join(tampered, "hashes.json"))
        self.assertIn("ground-truth.md", str(context.exception))

    def test_report_files_written(self):
        _db, run_id, _report = ingest_real_corpus(self.tmp.name,
                                                  activate=False)
        names = os.listdir(self.tmp.name)
        self.assertIn("validation-report-%s.json" % run_id, names)
        self.assertIn("validation-report-%s.md" % run_id, names)
        with open(os.path.join(self.tmp.name,
                               "validation-report-%s.md" % run_id),
                  "r", encoding="utf-8") as handle:
            summary = handle.read()
        self.assertIn("## Activation", summary)

    def test_bad_marker_file_is_fatal(self):
        path = os.path.join(self.tmp.name, "markers.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"match": "x", "state": "bogus", "note": "n"}],
                      handle)
        with self.assertRaises(akb.FatalKbError):
            akb.load_markers(path)


if __name__ == "__main__":
    unittest.main()
