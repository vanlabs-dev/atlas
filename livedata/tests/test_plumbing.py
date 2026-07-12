"""Store + quota-ledger plumbing (tasks 1.2/1.3): persistence,
headroom self-cap, reserve, redaction."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402


def make_config(tmp):
    return {
        "providers": {
            "taostats": {
                "base_url": "https://example.invalid",
                "auth": "header", "auth_header": "Authorization",
                "key_env": "TAOSTATS_API_KEY",
                "quota": {"per_minute_cap": 2, "window_kind": "month",
                          "window_limit": 10, "min_spacing_seconds": 0.0,
                          "interactive_reserve_fraction": 0.8},
            },
            "taoswap": {
                "base_url": "https://example.invalid", "auth": "none",
                "quota": {"per_minute_cap": 20,
                          "min_spacing_seconds": 0.0},
            },
        },
        "db": os.path.join(tmp, "livedata.db"),
        "output_dir": tmp,
        "cache_max_rows": 3,
        "request_timeout_seconds": 5,
        "retry": {"default_attempts": 2,
                  "retry_on_status": [500, 502, 503, 504],
                  "never_retry_on_status": [429],
                  "jitter_seconds": [0.0, 0.0]},
    }


class LedgerTests(unittest.TestCase):
    def test_self_cap_below_provider_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            connection = al.open_store(config["db"])
            ledger = al.QuotaLedger(connection, config)
            base = 1_800_000_000.0
            self.assertIsNone(ledger.acquire("taostats", now=base))
            self.assertIsNone(ledger.acquire("taostats", now=base + 1))
            refusal = ledger.acquire("taostats", now=base + 2)
            self.assertEqual(refusal["category"], "paced")
            self.assertIn("below the provider limit", refusal["message"])
            # a minute later the window has slid
            self.assertIsNone(ledger.acquire("taostats", now=base + 65))
            connection.close()

    def test_window_budget_and_interactive_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            connection = al.open_store(config["db"])
            ledger = al.QuotaLedger(connection, config)
            base = 1_800_000_000.0
            granted = 0
            for index in range(10):
                if ledger.acquire("taostats",
                                  now=base + index * 61) is None:
                    granted += 1
            self.assertEqual(granted, 10)
            refusal = ledger.acquire("taostats", now=base + 700)
            self.assertEqual(refusal["category"], "quota-exhausted")
            # non-interactive callers hit the 80% reserve earlier
            connection.execute("DELETE FROM calls")
            connection.commit()
            for index in range(8):
                ledger.acquire("taostats", now=base + index * 61)
            refusal = ledger.acquire("taostats", interactive=False,
                                     now=base + 600)
            self.assertEqual(refusal["category"], "quota-exhausted")
            self.assertIn("interactive reserve", refusal["message"])
            self.assertIsNone(ledger.acquire("taostats", now=base + 661))
            connection.close()

    def test_ledger_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            connection = al.open_store(config["db"])
            base = 1_800_000_000.0
            al.QuotaLedger(connection, config).acquire("taostats",
                                                       now=base)
            connection.close()
            connection = al.open_store(config["db"])
            usage = al.QuotaLedger(connection, config).usage(
                "taostats", now=base + 5)
            self.assertEqual(usage["window_count"], 1)
            self.assertEqual(usage["estimate_source"], "local-ledger")
            connection.close()


class StoreTests(unittest.TestCase):
    def test_cache_capped_and_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            connection = al.open_store(config["db"])
            for index in range(5):
                al.cache_put(connection, config, "taoswap",
                             "op%d" % index, "k", {"value": index})
            count = connection.execute(
                "SELECT count(*) FROM response_cache").fetchone()[0]
            self.assertLessEqual(count, config["cache_max_rows"])
            got = al.cache_get(connection, "taoswap", "op4", "k")
            self.assertEqual(got["label"], "historical-snapshot")
            self.assertEqual(got["payload"], {"value": 4})
            connection.close()

    def test_secret_redaction_in_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            connection = al.open_store(config["db"])
            al.register_secret("supersecretapikey123")
            al.audit_call(connection, "taostats", "test",
                          {"authorization": "supersecretapikey123"},
                          "t0", "t1", 200, "v1", "valid", "abc", None)
            row = connection.execute(
                "SELECT params FROM audit").fetchone()[0]
            self.assertNotIn("supersecretapikey123", row)
            self.assertIn("[REDACTED-KEY]", row)
            connection.close()

    def test_env_loader_registers_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = os.path.join(tmp, ".env")
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write("# comment\nTAOSTATS_API_KEY="
                             "\"anothersecretvalue\"\n")
            values = al.load_env(env_path)
            self.assertEqual(values["TAOSTATS_API_KEY"],
                             "anothersecretvalue")
            redacted = al.redact("x anothersecretvalue y")
            self.assertNotIn("anothersecretvalue", redacted)
            self.assertIn("[REDACTED-KEY]", redacted)


if __name__ == "__main__":
    unittest.main()
