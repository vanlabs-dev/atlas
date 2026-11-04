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


class SecretShapeTests(unittest.TestCase):
    """Detector coverage (audit A12). Every secret-shaped fixture is built
    at runtime, so no token, key or mnemonic literal sits in the repo."""

    def scan(self, text):
        findings = []
        ahv._scan_for_secrets(text, "t", findings)
        return findings

    def assertFound(self, text, label):
        findings = self.scan(text)
        self.assertTrue(any(label in finding for finding in findings),
                        findings)
        return findings

    def test_prefixed_env_key_is_found(self):
        value = "q7" * 12
        findings = self.assertFound("TAOSTATS_API_KEY=" + value,
                                    "credential assignment")
        self.assertNotIn(value, "\n".join(findings))

    def test_dashed_header_key_is_found(self):
        self.assertFound("x-api-key: " + "Zk3" * 6, "credential assignment")

    def test_bot_token_in_url_is_found(self):
        token = "123456789:" + "Ab_-" * 8 + "xyz"
        findings = self.assertFound(
            "POST https://api.telegram.org/bot%s/sendMessage" % token,
            "Telegram bot token")
        self.assertNotIn(token, "\n".join(findings))

    def test_github_tokens_are_found(self):
        self.assertFound("push with gh" + "p_" + "a1B2" * 9,
                         "GitHub token")
        self.assertFound("github" + "_pat_" + "x9" * 12, "GitHub token")

    def test_cloud_tokens_are_found(self):
        self.assertFound("key AKIA" + "Q" * 16, "AWS access key")
        self.assertFound("xox" + "b-" + "1234-abcd-5678", "Slack token")
        self.assertFound("AIza" + "k" * 35, "Google API key")

    def test_pem_key_with_body_is_found(self):
        header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        body = "b3Bl" * 16
        self.assertFound(header + "\n" + body, "PEM private key")
        self.assertFound('{"k": "%s\\n%s"}' % (header, body),
                         "PEM private key")

    def test_bare_pem_header_is_not_a_key(self):
        header = "-----BEGIN " + "RSA PRIVATE KEY-----"
        self.assertEqual(self.scan("content = '%s'\nassert x" % header), [])

    def test_seed_phrase_is_found(self):
        words = sorted(ahv._load_bip39_words())
        phrase = " ".join(words[(index * 97) % 2048] for index in range(12))
        findings = self.assertFound("mnemonic: " + phrase, "seed phrase")
        self.assertFound('{"words": "%s"}' % phrase, "seed phrase")
        for word in phrase.split():
            self.assertFalse(any(" %s " % word in " %s " % finding
                                 for finding in findings), word)

    def test_eleven_words_is_not_a_seed(self):
        words = sorted(ahv._load_bip39_words())
        self.assertEqual(self.scan(" ".join(words[:11])), [])

    def test_prose_and_chain_ids_are_clean(self):
        for text in (
                "the miner can stake and the validator will set weights "
                "above the bar for a subnet",
                "block 0x" + "a4f5e963" * 8,
                "hotkey 5" + "F" * 47,
                "def setup(token: Optional[str] = None) -> bool:",
                "_TOKEN = re.compile(r'[A-Za-z0-9_]+')",
                "api_key = os.environ.get('TAOSTATS_API_KEY')",
                "max_tokens: 4096"):
            self.assertEqual(self.scan(text), [], text)

    def test_wordlist_is_pinned(self):
        words = ahv._load_bip39_words()
        self.assertEqual(len(words), 2048)
        self.assertIn("abandon", words)
        self.assertIn("zoo", words)


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
