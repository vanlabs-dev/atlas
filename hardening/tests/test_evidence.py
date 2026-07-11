"""Evidence layer tests (spec: Evidence-grounded output)."""

import datetime
import json
import os
import tempfile
import unittest

from _helpers import ah, base_inventory


def write_report(directory, report, name="report-x.json"):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    return path


class LoadReportTests(unittest.TestCase):
    def test_valid_report_loads_with_age(self):
        now = datetime.datetime(2026, 7, 11, 8, 22, 11,
                                tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(tmp, base_inventory())
            report, consumed = ah.load_inventory_report(path, 72, now=now)
        self.assertEqual(consumed["run_id"], "20260711T062206Z-5be02d8f")
        self.assertAlmostEqual(consumed["age_hours"], 2.0, places=1)
        self.assertFalse(consumed["stale"])
        self.assertIn("categories", report)

    def test_stale_report_flagged(self):
        now = datetime.datetime(2026, 7, 20, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(tmp, base_inventory())
            _, consumed = ah.load_inventory_report(path, 72, now=now)
        self.assertTrue(consumed["stale"])

    def test_invalid_report_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(tmp, {"not": "a report"})
            with self.assertRaises(ah.FatalAssessmentError) as ctx:
                ah.load_inventory_report(path)
        self.assertIn("schema validation", str(ctx.exception))

    def test_unreadable_report_is_fatal(self):
        with self.assertRaises(ah.FatalAssessmentError):
            ah.load_inventory_report("/definitely/not/here.json")

    def test_find_latest_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ah.find_latest_report(tmp))
            write_report(tmp, {}, "report-20260101T000000Z-aa.json")
            newest = write_report(tmp, {}, "report-20260711T000000Z-bb.json")
            self.assertEqual(ah.find_latest_report(tmp), newest)


class SupplementaryProbeTests(unittest.TestCase):
    def test_probes_map_missing_tools_to_unsupported(self):
        class Missing:
            def __call__(self, argv, timeout):
                raise FileNotFoundError(argv[0])

        results = ah.run_supplementary_probes(Missing())
        self.assertEqual(set(results),
                         {p.item_id for p in ah.SUPPLEMENTARY_PROBES})
        self.assertEqual(results["time_sync"]["status"],
                         "unsupported-on-device")
        self.assertEqual(results["sshd_restart_policy"]["status"],
                         "unsupported-on-device")

    def test_probe_output_redacted(self):
        class Leaky:
            def __call__(self, argv, timeout):
                return 0, b"NTP=yes\napi_key=PLANTEDPROBE01\n", b""

        results = ah.run_supplementary_probes(Leaky())
        self.assertNotIn("PLANTEDPROBE01", json.dumps(results))


if __name__ == "__main__":
    unittest.main()
