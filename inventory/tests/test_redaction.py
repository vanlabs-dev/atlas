"""Adversarial tests for the redaction filter (spec: Secret redaction)."""

import unittest

from _helpers import ai, fixture_text


PLANTED = ["PLANTED%04d" % n for n in range(1, 17)]


class RedactionTests(unittest.TestCase):
    def assert_no_planted(self, text: str, source: str) -> None:
        for marker in PLANTED:
            self.assertNotIn(marker, text, "%s leaked from %s" % (marker, source))

    def test_env_dump_secrets_removed(self):
        redacted = ai.redact(fixture_text("env_dump.txt"))
        self.assert_no_planted(redacted, "env_dump")
        # variable NAMES survive; only values are redacted
        self.assertIn("TAOSTATS_API_KEY=", redacted)
        self.assertIn("TELEGRAM_BOT_TOKEN=", redacted)
        # non-secret values survive
        self.assertIn("HOME=/home/pi", redacted)
        self.assertIn("GIT_COMMITTER_NAME=pi", redacted)

    def test_process_list_secrets_removed(self):
        redacted = ai.redact(fixture_text("process_list.txt"))
        self.assert_no_planted(redacted, "process_list")
        # a git commit SHA is NOT a secret and must survive
        self.assertIn("4f2a9c1d8e3b5a7f6c0d2e4b8a1f3c5d7e9b0a2c", redacted)
        self.assertIn("/usr/sbin/sshd -D", redacted)

    def test_pem_and_key_formats_removed(self):
        redacted = ai.redact(fixture_text("pem_and_keys.txt"))
        self.assert_no_planted(redacted, "pem_and_keys")
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", redacted)
        self.assertIn("plain text after", redacted)
        self.assertIn("config dump follows", redacted)

    def test_url_credentials(self):
        redacted = ai.redact("origin https://leunis:PLANTED9999@github.com/x/y.git")
        self.assertNotIn("PLANTED9999", redacted)
        self.assertIn("github.com/x/y.git", redacted)

    def test_non_utf8_bytes_decode_then_redact(self):
        raw = b"\xff\xfe binary \x00 SECRET_TOKEN=PLANTED8888 \xf0 more"
        decoded = ai._decode(raw)
        redacted = ai.redact(decoded)
        self.assertNotIn("PLANTED8888", redacted)
        self.assertIn("binary", redacted)

    def test_marker_used(self):
        redacted = ai.redact("API_KEY=abc123def456")
        self.assertIn(ai.REDACTION_MARKER, redacted)


if __name__ == "__main__":
    unittest.main()
