"""Unit tests for every check, with fixture evidence bundles."""

import os
import tempfile
import unittest

from _helpers import (GREEN_CONFIG, amv, base_bundle, make_record,
                      make_session_db, results_by_check, store_item,
                      text_item)


class ConfigParserTests(unittest.TestCase):
    def test_nested_scalars(self):
        scalars = amv.parse_config_scalars(GREEN_CONFIG)
        self.assertEqual(scalars.get("memory.write_approval"), "on")
        self.assertEqual(scalars.get("skills.write_approval"), "on")
        self.assertEqual(scalars.get("model.default"), "grok")

    def test_deep_nesting_and_comments(self):
        text = ("a:\n"
                "  b:\n"
                "    c: 1 # trailing comment\n"
                "# full comment line\n"
                "  d: 'quoted'\n"
                "top: yes\n")
        scalars = amv.parse_config_scalars(text)
        self.assertEqual(scalars.get("a.b.c"), "1")
        self.assertEqual(scalars.get("a.d"), "quoted")
        self.assertEqual(scalars.get("top"), "yes")
        self.assertNotIn("a.b", scalars)  # section headers hold no scalar


class ApprovalGatingTests(unittest.TestCase):
    def _run(self, config_text=None, config_status="collected"):
        bundle = base_bundle()
        if config_text is not None:
            bundle["config_file"] = text_item(text=config_text)
        else:
            bundle["config_file"] = text_item(status=config_status)
        return amv.check_approval_gating(make_record(), bundle)

    def test_both_gates_on_is_ok(self):
        result = self._run(GREEN_CONFIG)
        self.assertEqual(result.status, amv.ahv.CHECK_OK)

    def test_absent_key_is_finding_not_unknown(self):
        # pinned v0.18.2 fact: the gate DEFAULTS OFF, so absence is a
        # determinable "off", not an indeterminate state
        result = self._run("memory:\n  memory_enabled: true\n")
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertEqual(len(result.findings), 2)  # both keys absent
        self.assertIn("defaults the gate OFF", result.findings[0])

    def test_one_gate_off_is_finding(self):
        config = "memory:\n  write_approval: on\n"
        result = self._run(config)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("skills.write_approval", result.findings[0])

    def test_non_enabled_value_is_finding(self):
        config = ("memory:\n  write_approval: sometimes\n"
                  "skills:\n  write_approval: on\n")
        result = self._run(config)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertIn("sometimes", result.findings[0])

    def test_explicit_false_is_finding(self):
        config = ("memory:\n  write_approval: false\n"
                  "skills:\n  write_approval: on\n")
        result = self._run(config)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)

    def test_unreadable_config_is_denied(self):
        result = self._run(config_status="permission-denied")
        self.assertEqual(result.status, amv.ahv.CHECK_DENIED)

    def test_missing_config_is_finding(self):
        result = self._run(config_status="unsupported-on-device")
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertIn("install record is inaccurate", result.findings[0])


class MemoryHygieneTests(unittest.TestCase):
    def _run(self, memory_text=None, memory_status="collected",
             user_item=None):
        bundle = base_bundle()
        if memory_text is not None:
            bundle["memory_files"]["MEMORY.md"] = text_item(
                path="/home/pi/.hermes/memories/MEMORY.md",
                text=memory_text)
        else:
            bundle["memory_files"]["MEMORY.md"] = text_item(
                status=memory_status,
                path="/home/pi/.hermes/memories/MEMORY.md")
        if user_item is not None:
            bundle["memory_files"]["USER.md"] = user_item
        return amv.check_memory_hygiene(make_record(), bundle)

    def test_clean_memory_is_ok_with_size_evidence(self):
        result = self._run("- Operator prefers metric units.\n")
        self.assertEqual(result.status, amv.ahv.CHECK_OK)
        self.assertTrue(any("bytes" in item for item in result.evidence))

    def test_canary_in_memory_is_finding(self):
        result = self._run("- api key: %s\n" % amv.CANARY_SECRET)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertTrue(any("ATLAS-MEM-005" in finding
                            for finding in result.findings))
        # the canary value itself must never survive into the report
        self.assertFalse(any(amv.CANARY_SECRET in finding
                             for finding in result.findings))

    def test_planted_fake_secret_is_finding_and_redacted(self):
        secret = "xai-ABCDEFGHIJKLMNOP1234"
        result = self._run("- provider key is %s\n" % secret)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertFalse(any(secret in finding
                             for finding in result.findings))

    def test_domain_dump_is_finding(self):
        dump = "".join("- Bittensor subnet %d validator emission notes\n"
                       % index
                       for index in range(amv.DOMAIN_LINE_THRESHOLD))
        result = self._run(dump)
        self.assertEqual(result.status, amv.ahv.CHECK_FINDING)
        self.assertTrue(any("ATLAS-MEM-001" in finding
                            for finding in result.findings))

    def test_incidental_domain_mention_is_ok(self):
        result = self._run("- Working on the Bittensor Atlas project "
                           "in ~/atlas.\n")
        self.assertEqual(result.status, amv.ahv.CHECK_OK)

    def test_missing_memory_md_is_unknown(self):
        result = self._run(memory_status="unsupported-on-device")
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)

    def test_missing_user_md_is_acceptable(self):
        result = self._run("- clean\n",
                           user_item=text_item(
                               status="unsupported-on-device",
                               path="/home/pi/.hermes/memories/USER.md"))
        self.assertEqual(result.status, amv.ahv.CHECK_OK)
        self.assertTrue(any("not yet created" in item
                            for item in result.evidence))

    def test_unreadable_memory_file_is_denied(self):
        result = self._run(memory_status="permission-denied")
        self.assertEqual(result.status, amv.ahv.CHECK_DENIED)


class SessionStoreCheckTests(unittest.TestCase):
    def _run(self, store):
        return amv.check_session_store(make_record(),
                                       base_bundle(session_store=store))

    def test_marker_found_is_ok(self):
        result = self._run(store_item(marker_hits=1))
        self.assertEqual(result.status, amv.ahv.CHECK_OK)

    def test_marker_absent_is_unknown(self):
        result = self._run(store_item(marker_hits=0))
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)
        self.assertIn("plant it", result.summary)

    def test_fts_missing_is_unknown(self):
        result = self._run(store_item(
            tables=("messages", "sessions"), fts_present=False,
            marker_hits=None))
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)
        self.assertIn("messages_fts", result.summary)

    def test_expected_table_missing_is_unknown(self):
        result = self._run(store_item(tables=("messages", "messages_fts")))
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)
        self.assertIn("schema drift", result.summary)

    def test_missing_store_is_unknown(self):
        result = self._run(store_item(status="unsupported-on-device"))
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)

    def test_unreadable_store_is_denied(self):
        result = self._run(store_item(status="permission-denied"))
        self.assertEqual(result.status, amv.ahv.CHECK_DENIED)

    def test_errored_store_is_unknown_with_guidance(self):
        result = self._run(store_item(status="error",
                                      error="database is locked"))
        self.assertEqual(result.status, amv.ahv.CHECK_UNKNOWN)
        self.assertIn("database is locked", result.summary)


class SessionStoreInspectionTests(unittest.TestCase):
    """inspect_session_store against real fixture SQLite files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _db(self, name="state.db", **kwargs):
        return make_session_db(os.path.join(self.tmp.name, name), **kwargs)

    def test_marker_present(self):
        store = amv.inspect_session_store(self._db())
        self.assertEqual(store["status"], amv.inv.STATUS_COLLECTED)
        self.assertTrue(store["fts_present"])
        self.assertEqual(store["marker_hits"], 1)

    def test_marker_absent(self):
        store = amv.inspect_session_store(self._db(plant_marker=False))
        self.assertEqual(store["marker_hits"], 0)

    def test_fts_missing(self):
        store = amv.inspect_session_store(
            self._db(with_fts=False, plant_marker=False))
        self.assertFalse(store["fts_present"])
        self.assertIsNone(store["marker_hits"])

    def test_missing_file(self):
        store = amv.inspect_session_store(
            os.path.join(self.tmp.name, "absent.db"))
        self.assertEqual(store["status"], amv.inv.STATUS_UNSUPPORTED)

    def test_read_only_open(self):
        # the mode=ro URI must refuse writes by construction
        import sqlite3
        from urllib.request import pathname2url
        path = self._db()
        uri = "file:%s?mode=ro" % pathname2url(os.path.abspath(path))
        connection = sqlite3.connect(uri, uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("INSERT INTO messages_fts (content) "
                               "VALUES ('x')")
        connection.close()


class ExceptionsFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "exceptions.json")

    def _write(self, content):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_absent_file_means_no_exceptions(self):
        entries, problems, present = amv.load_exceptions(self.path)
        self.assertEqual((entries, problems, present), ([], [], False))

    def test_valid_entries_load(self):
        self._write('[{"check": "session-store", "reason": "documented"}]')
        entries, problems, present = amv.load_exceptions(self.path)
        self.assertEqual(problems, [])
        self.assertTrue(present)
        self.assertEqual(entries[0]["check"], "session-store")

    def test_unknown_check_is_problem(self):
        self._write('[{"check": "nope", "reason": "x"}]')
        entries, problems, _present = amv.load_exceptions(self.path)
        self.assertEqual(entries, [])
        self.assertTrue(problems)

    def test_invalid_json_is_problem(self):
        self._write("{not json")
        entries, problems, _present = amv.load_exceptions(self.path)
        self.assertEqual(entries, [])
        self.assertTrue(problems)

    def test_exception_applies_to_non_ok_check(self):
        bundle = base_bundle(session_store=store_item(marker_hits=0))
        results = results_by_check(amv.run_checks(
            make_record(), "record.json", bundle,
            [{"check": "session-store", "reason": "documented deviation"}]))
        self.assertEqual(results["session-store"].exception,
                         "documented deviation")
        # an exception never rewrites the status, only the verdict math
        self.assertEqual(results["session-store"].status,
                         amv.ahv.CHECK_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
