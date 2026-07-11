"""Pins the reused APIs and this module's structural invariants."""

import json
import os
import unittest

from _helpers import ahv, amv, inv

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "schema",
    "atlas-memory-verification.v1.schema.json")


class ImportSurfaceTests(unittest.TestCase):
    def test_pinned_inventory_api(self):
        # a rename/refactor in atlas_inventory.py must fail HERE, not at
        # runtime on the Pi
        self.assertTrue(callable(inv.redact))
        self.assertTrue(callable(inv.schema_validate))
        self.assertIsInstance(inv.REDACTION_MARKER, str)
        for name in ("STATUS_COLLECTED", "STATUS_UNSUPPORTED",
                     "STATUS_DENIED", "STATUS_ERROR"):
            self.assertTrue(hasattr(inv, name), name)

    def test_pinned_baseline_verifier_api(self):
        # the baseline verifier machinery this module reuses
        for name in ("load_install_record", "check_install_record",
                     "compute_verdict", "build_audit", "CheckResult",
                     "_resolve", "_read_text", "_scan_for_secrets",
                     "_write_private", "_utc_now", "_account",
                     "_redact_tree", "FatalVerificationError"):
            self.assertTrue(hasattr(ahv, name), name)
        self.assertEqual(amv.inv, ahv.inv)

    def test_check_lists_are_fixed(self):
        self.assertEqual(len(amv.CHECKS), 4)
        self.assertEqual(len(amv.ATTESTATION_ITEMS), 7)
        check_enum = amv.VERIFICATION_SCHEMA["properties"]["checks"][
            "items"]["properties"]["check"]["enum"]
        self.assertEqual(set(check_enum), set(amv.CHECKS))
        attest_enum = amv.VERIFICATION_SCHEMA["properties"][
            "attestations"]["items"]["properties"]["check"]["enum"]
        self.assertEqual(set(attest_enum), set(amv.ATTESTATION_ITEMS))

    def test_pinned_hermes_facts(self):
        # source-verified on the accepted v0.18.2 install (2026-07-12);
        # a change here must be a deliberate re-pin, not drift
        self.assertEqual(amv.APPROVAL_KEYS,
                         ("memory.write_approval", "skills.write_approval"))
        self.assertEqual(amv.MEMORY_DIR_NAME, "memories")
        self.assertEqual(amv.MEMORY_FILES, ("MEMORY.md", "USER.md"))
        self.assertEqual(amv.SESSION_DB_NAME, "state.db")
        self.assertEqual(amv.SESSION_FTS_TABLE, "messages_fts")
        self.assertIn("on", amv.APPROVAL_ENABLED_VALUES)
        self.assertNotIn("off", amv.APPROVAL_ENABLED_VALUES)

    def test_markers_are_consistent(self):
        # the canary must carry the prefix (the scan keys on it) and be
        # credential-shaped (the generic secret detectors must also fire)
        self.assertTrue(amv.CANARY_SECRET.startswith(amv.CANARY_PREFIX))
        findings = []
        ahv._scan_for_secrets("key: %s" % amv.CANARY_SECRET, "t", findings)
        self.assertTrue(findings,
                        "canary must trip the generic secret detectors")
        # the recall marker must be plain FTS-queryable words
        self.assertRegex(amv.RECALL_MARKER, r"^[a-z0-9 ]+$")

    def test_status_vocabulary_reuses_inventory_statuses(self):
        self.assertEqual(ahv.CHECK_DENIED, inv.STATUS_DENIED)
        self.assertEqual(ahv.CHECK_UNSUPPORTED, inv.STATUS_UNSUPPORTED)

    def test_schema_file_matches_embedded(self):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), amv.VERIFICATION_SCHEMA,
                             "regenerate: python atlas_memory_verify.py "
                             "dump-schema > schema/...")


if __name__ == "__main__":
    unittest.main()
