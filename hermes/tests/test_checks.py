"""Per-check evaluator behavior over fixture evidence (spec scenarios)."""

import unittest

from _helpers import (ahv, base_bundle, green_record, make_record,
                      probe_env, results_by_check, text_item)


class UnprivilegedExecutionTests(unittest.TestCase):
    def check(self, record=None, **bundle_overrides):
        return ahv.check_unprivileged_execution(
            record or green_record(), base_bundle(**bundle_overrides))

    def test_green_bundle_is_ok(self):
        result = self.check()
        self.assertEqual(result.status, ahv.CHECK_OK)

    def test_root_service_user_is_a_finding(self):
        result = self.check(record=green_record(service_user="root"))
        self.assertEqual(result.status, ahv.CHECK_FINDING)
        self.assertTrue(any("root" in finding for finding in result.findings))

    def test_sudo_group_membership_is_a_finding(self):
        result = self.check(etc_group=text_item(
            path="/etc/group", text="sudo:x:27:pi,hermes\n"))
        self.assertEqual(result.status, ahv.CHECK_FINDING)
        self.assertTrue(any("sudo" in finding for finding in result.findings))

    def test_unreadable_group_file_fails_closed(self):
        result = self.check(etc_group=text_item(status="permission-denied",
                                                path="/etc/group"))
        self.assertEqual(result.status, ahv.CHECK_DENIED)

    def test_unreadable_sudoers_fails_closed_without_findings(self):
        result = self.check(sudoers=[text_item(status="permission-denied",
                                               path="/etc/sudoers")])
        self.assertEqual(result.status, ahv.CHECK_DENIED)
        self.assertIn("/etc/sudoers", result.summary)

    def test_direct_sudoers_grant_is_a_finding(self):
        result = self.check(sudoers=[text_item(
            path="/etc/sudoers.d/hermes",
            text="hermes ALL=(ALL) NOPASSWD: ALL\n")])
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_root_hermes_process_is_a_finding(self):
        result = self.check(processes=probe_env(lines=[
            "root      999 hermes-agent serve"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_wrong_process_owner_is_a_finding(self):
        result = self.check(processes=probe_env(lines=[
            "pi        999 hermes-agent serve"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_unit_user_mismatch_is_a_finding(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "User=pi"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_system_unit_without_user_is_a_finding(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "User="]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_user_scoped_unit_without_user_is_fine(self):
        result = self.check(
            record=green_record(service_unit="user:hermes.service"),
            unit_show=probe_env(lines=["LoadState=loaded", "User="]))
        self.assertEqual(result.status, ahv.CHECK_OK)


class TelemetryTests(unittest.TestCase):
    def check(self, record=None, **bundle_overrides):
        return ahv.check_telemetry_disabled(
            record or green_record(), base_bundle(**bundle_overrides))

    def test_explicit_off_is_ok(self):
        result = self.check()
        self.assertEqual(result.status, ahv.CHECK_OK)

    def test_enabled_telemetry_is_a_finding(self):
        result = self.check(config_file=text_item(
            path="/c.yaml", text="telemetry: true\n"))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_no_setting_found_fails_closed_to_unknown(self):
        result = self.check(config_file=text_item(
            path="/c.yaml", text="model: grok\n"))
        self.assertEqual(result.status, ahv.CHECK_UNKNOWN)
        self.assertIsNotNone(result.guidance)

    def test_indeterminate_value_is_unknown(self):
        result = self.check(config_file=text_item(
            path="/c.yaml", text="telemetry: sometimes\n"))
        self.assertEqual(result.status, ahv.CHECK_UNKNOWN)

    def test_missing_config_path_is_a_finding(self):
        result = self.check(config_file=text_item(
            status="unsupported-on-device", path="/c.yaml"))
        self.assertEqual(result.status, ahv.CHECK_FINDING)
        self.assertTrue(any("install record is inaccurate" in finding
                            for finding in result.findings))

    def test_unreadable_config_fails_closed(self):
        result = self.check(config_file=text_item(
            status="permission-denied", path="/c.yaml"))
        self.assertEqual(result.status, ahv.CHECK_DENIED)

    def test_env_file_can_enable_telemetry(self):
        result = self.check(env_file=text_item(
            path="/.env", text="HERMES_ANALYTICS=1\n"))
        self.assertEqual(result.status, ahv.CHECK_FINDING)


class DiagnosticsTests(unittest.TestCase):
    def test_no_command_recorded_is_unsupported(self):
        result = ahv.check_diagnostics(make_record(),
                                       base_bundle(diagnostics=None))
        self.assertEqual(result.status, ahv.CHECK_UNSUPPORTED)
        self.assertIsNotNone(result.guidance)

    def test_clean_exit_is_ok(self):
        result = ahv.check_diagnostics(green_record(), base_bundle())
        self.assertEqual(result.status, ahv.CHECK_OK)

    def test_failure_is_a_finding(self):
        result = ahv.check_diagnostics(green_record(), base_bundle(
            diagnostics=probe_env(status="error", error="exit 2")))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_denied_fails_closed(self):
        result = ahv.check_diagnostics(green_record(), base_bundle(
            diagnostics=probe_env(status="permission-denied",
                                  error="denied")))
        self.assertEqual(result.status, ahv.CHECK_DENIED)


class ServicePersistenceTests(unittest.TestCase):
    def check(self, record=None, **bundle_overrides):
        return ahv.check_service_persistence(
            record or green_record(), base_bundle(**bundle_overrides))

    def test_green_unit_is_ok(self):
        result = self.check()
        self.assertEqual(result.status, ahv.CHECK_OK)

    def test_no_unit_recorded_is_unsupported(self):
        result = self.check(record=make_record(), unit_show=None)
        self.assertEqual(result.status, ahv.CHECK_UNSUPPORTED)

    def test_unit_not_found_is_a_finding(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=not-found"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_disabled_unit_is_a_finding(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "UnitFileState=disabled",
            "ActiveState=active",
            "ExecMainStartTimestamp=Sat 2026-07-12 09:00:00 UTC"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_inactive_unit_is_a_finding(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "UnitFileState=enabled",
            "ActiveState=inactive"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_missing_timestamp_is_unknown(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "UnitFileState=enabled",
            "ActiveState=active", "ExecMainStartTimestamp="]))
        self.assertEqual(result.status, ahv.CHECK_UNKNOWN)

    def test_start_before_install_date_is_unknown(self):
        result = self.check(unit_show=probe_env(lines=[
            "LoadState=loaded", "UnitFileState=enabled",
            "ActiveState=active",
            "ExecMainStartTimestamp=Thu 2026-07-10 09:00:00 UTC"]))
        self.assertEqual(result.status, ahv.CHECK_UNKNOWN)


class SecretFreeLogsTests(unittest.TestCase):
    def check(self, record=None, **bundle_overrides):
        return ahv.check_secret_free_logs(
            record or green_record(), base_bundle(**bundle_overrides))

    def test_clean_logs_are_ok(self):
        result = self.check()
        self.assertEqual(result.status, ahv.CHECK_OK)

    def test_planted_token_is_found_and_redacted(self):
        token = "xai-FAKE0000000000000000TEST"
        result = self.check(log_files=[text_item(
            path="/logs/hermes.log",
            text="INFO auth ok\nDEBUG key=%s used\n" % token)])
        self.assertEqual(result.status, ahv.CHECK_FINDING)
        blob = "\n".join(result.findings + result.evidence
                         + [result.summary])
        self.assertNotIn(token, blob)
        self.assertTrue(any("[REDACTED]" in finding
                            for finding in result.findings))
        self.assertTrue(any(":2:" in finding for finding in result.findings))

    def test_unreadable_log_fails_closed(self):
        result = self.check(log_files=[text_item(
            status="permission-denied", path="/logs/hermes.log")])
        self.assertEqual(result.status, ahv.CHECK_DENIED)

    def test_no_logs_at_all_is_unknown(self):
        result = self.check(log_files=[], journal=None)
        self.assertEqual(result.status, ahv.CHECK_UNKNOWN)

    def test_journal_secret_is_found(self):
        result = self.check(journal=probe_env(lines=[
            "Jul 12 09:00:00 pi hermes: Authorization: Bearer "
            "abcdefghijklmnop1234567890"]))
        self.assertEqual(result.status, ahv.CHECK_FINDING)

    def test_denied_journal_fails_closed(self):
        result = self.check(journal=probe_env(status="permission-denied",
                                              error="denied"))
        self.assertEqual(result.status, ahv.CHECK_DENIED)


class ExceptionApplicationTests(unittest.TestCase):
    def test_documented_exception_is_attached_not_erased(self):
        record = make_record(exceptions=[
            {"check": "diagnostics", "reason": "this version ships none"},
            {"check": "service-persistence", "reason": "tmux for baseline"},
        ])
        bundle = base_bundle(unit_show=None, journal=None, diagnostics=None)
        results = results_by_check(
            ahv.run_checks(record, "/tmp/r.json", bundle))
        self.assertEqual(results["diagnostics"].status,
                         ahv.CHECK_UNSUPPORTED)
        self.assertEqual(results["diagnostics"].exception,
                         "this version ships none")
        self.assertEqual(results["service-persistence"].exception,
                         "tmux for baseline")
        # an ok check never carries an exception
        self.assertIsNone(results["install-record"].exception)


if __name__ == "__main__":
    unittest.main()
