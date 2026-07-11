"""Classification worksheet tests (spec: Classification worksheet)."""

import os
import tempfile
import unittest

from _helpers import ai, make_report, make_envelope


def stat_match(path):
    return {"path": path, "type": "dir", "mode": "0o755", "uid": 1000,
            "gid": 1000, "size": 4096, "mtime": "2026-07-01T00:00:00+00:00"}


def stale_hermes_report():
    return make_report({
        "systemd_services": {
            "service_unit_files": make_envelope(data={"text_lines": [
                "ssh.service enabled enabled",
                "hermes.service enabled enabled",
                "mysterysvc.service enabled enabled",
                "systemd-timesyncd.service enabled enabled",
            ]}),
        },
        "packages": {
            "dpkg_packages": make_envelope(data={
                "total_installed": 4,
                "relevant": [
                    {"name": "git", "version": "1:2.39.2"},
                    {"name": "bittensor-cli", "version": "9.0.0"},
                ],
            }),
        },
        "repositories_and_app_dirs": {
            "git_repositories": make_envelope(data={"paths": [
                {"path": "/home/pi/subtensor/.git", "type": "dir"},
            ]}),
        },
        "hermes_installation": {
            "hermes_files": make_envelope(data={"matches": [
                stat_match("/opt/hermes-1.2.0"),
                stat_match("/opt/hermes-1.3.0"),
                stat_match("/home/pi/.hermes"),
            ]}),
        },
    })


def rows_by_item(rows):
    return {row.item: row for row in rows}


class WorksheetClassificationTests(unittest.TestCase):
    def setUp(self):
        self.rows = ai.build_worksheet_rows(stale_hermes_report())
        self.by_item = rows_by_item(self.rows)

    def test_stock_service_preserved(self):
        self.assertEqual(self.by_item["ssh.service"].disposition, "preserve")
        self.assertEqual(self.by_item["systemd-timesyncd.service"].disposition,
                         "preserve")

    def test_hermes_service_needs_decision(self):
        row = self.by_item["hermes.service"]
        self.assertEqual(row.disposition, "decision required")
        self.assertIn("ATLAS-ENV-001", row.note)

    def test_ambiguous_item_states_open_question(self):
        row = self.by_item["mysterysvc.service"]
        self.assertEqual(row.disposition, "decision required")
        self.assertIn("?", row.note)  # an actual question is posed

    def test_packages_classified(self):
        self.assertEqual(self.by_item["git 1:2.39.2"].disposition, "preserve")
        self.assertEqual(self.by_item["bittensor-cli 9.0.0"].disposition,
                         "decision required")

    def test_repository_needs_decision(self):
        self.assertEqual(self.by_item["/home/pi/subtensor/.git"].disposition,
                         "decision required")

    def test_older_versioned_hermes_proposed_remove_with_evidence(self):
        old = self.by_item["/opt/hermes-1.2.0"]
        self.assertEqual(old.disposition, "remove")
        self.assertIn("1.3.0", old.note)  # names the superseding install
        self.assertIn("ATLAS-ENV-002", old.note)  # removal still gated

    def test_newest_hermes_is_decision_not_preserve(self):
        self.assertEqual(self.by_item["/opt/hermes-1.3.0"].disposition,
                         "decision required")

    def test_unversioned_hermes_files_need_decision(self):
        self.assertEqual(self.by_item["/home/pi/.hermes"].disposition,
                         "decision required")

    def test_remove_never_proposed_without_version_evidence(self):
        removes = [r for r in self.rows if r.disposition == "remove"]
        self.assertEqual([r.item for r in removes], ["/opt/hermes-1.2.0"])

    def test_single_hermes_install_never_proposed_remove(self):
        report = make_report({"hermes_installation": {
            "hermes_files": make_envelope(data={"matches": [
                stat_match("/opt/hermes-1.2.0")]})}})
        rows = ai.build_worksheet_rows(report)
        self.assertEqual(rows[0].disposition, "decision required")


class WorksheetRenderTests(unittest.TestCase):
    def test_render_states_proposal_only_and_no_side_effects(self):
        report = stale_hermes_report()
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(os.listdir(tmp))
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                markdown = ai.render_worksheet(report)
            finally:
                os.chdir(cwd)
            after = sorted(os.listdir(tmp))
        self.assertEqual(before, after)  # rendering writes nothing
        self.assertIn("Proposals only", markdown)
        self.assertIn("Nothing has been deleted, stopped, or modified", markdown)
        self.assertIn("| `/opt/hermes-1.2.0` |", markdown)
        self.assertIn("## Collection status summary", markdown)

    def test_skipped_categories_do_not_break_rendering(self):
        markdown = ai.render_worksheet(make_report())
        self.assertIn("no classifiable items collected", markdown)

    def test_uncollected_envelopes_are_ignored(self):
        report = make_report({"systemd_services": {
            "service_unit_files": make_envelope(
                status="permission-denied", error="nope")}})
        rows = ai.build_worksheet_rows(report)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
