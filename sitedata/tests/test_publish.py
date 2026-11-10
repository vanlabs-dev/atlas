"""The publish command (sitedata/atlas_sitedata.py). No test reaches the
network: every HTTP call goes through a fake transport."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import atlas_sitedata as s  # noqa: E402

URL = "https://example.supabase.co"
KEY = "sb_secret_testkeyAAAAAAAAAAAAAAAAAAAAAA"


def golden_raw():
    with open(os.path.join(HERE, "golden", "raw.json"), encoding="utf-8") as h:
        return json.load(h)


class FakeStore:
    """The boards table behind PostgREST, in memory."""

    def __init__(self, rows=None, down=False, post_status=201):
        self.rows = {r["name"]: r for r in (rows or [])}
        self.down = down
        self.post_status = post_status
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if self.down:
            raise OSError("connection refused to %s with key %s"
                          % (url, headers.get("apikey")))
        if headers.get("apikey") != KEY:
            return 401, b'{"message":"Invalid API key"}'
        if method == "GET":
            return 200, json.dumps([
                {k: r[k] for k in ("name", "content_hash", "generated_at")}
                for r in self.rows.values()]).encode()
        if method == "POST":
            if self.post_status >= 300:
                return self.post_status, ('{"message":"boom, key %s"}'
                                          % KEY).encode()
            for row in json.loads(body):
                self.rows[row["name"]] = row
            return self.post_status, b""
        return 405, b""


def env_file(tmp, text):
    path = os.path.join(tmp, ".env")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run(store, env_text="SUPABASE_URL=%s\nSUPABASE_SECRET_KEY=%s\n" % (URL, KEY),
        raw=golden_raw):
    err, out = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = s.run_publish(env_file(tmp, env_text), raw, store)
    return code, out.getvalue(), err.getvalue()


class PublishTest(unittest.TestCase):
    def test_first_run_uploads_every_board(self):
        store = FakeStore()
        code, out, _ = run(store)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(store.rows), sorted(s.BOARDS))
        self.assertEqual([c[0] for c in store.calls], ["GET", "POST"])
        row = store.rows["network"]
        self.assertEqual(row["data"], s.boards(golden_raw())["network"]["data"])
        self.assertEqual(row["content_hash"], s.content_hash(row["data"]))

    def test_only_changed_boards_upload(self):
        store = FakeStore()
        run(store)
        raw = golden_raw()
        raw["vitals"][0]["tao_usd"] = 999.0
        store.calls.clear()
        code, out, _ = run(store, raw=lambda: raw)
        self.assertEqual(code, 0)
        posted = json.loads(store.calls[-1][3])
        # The network data changed; the upgrades board carries a new run
        # time in a real run, but the golden input keeps it fixed.
        self.assertEqual([r["name"] for r in posted], ["network"])
        self.assertIn("mining: unchanged", out)

    def test_same_time_in_another_format_is_unchanged(self):
        store = FakeStore()
        run(store)
        for row in store.rows.values():
            row["generated_at"] = row["generated_at"].replace("+00:00", "Z")
        store.calls.clear()
        run(store)
        self.assertEqual([c[0] for c in store.calls], ["GET"])

    def test_nothing_new_uploads_nothing(self):
        store = FakeStore()
        run(store)
        store.calls.clear()
        code, out, _ = run(store)
        self.assertEqual(code, 0)
        self.assertEqual([c[0] for c in store.calls], ["GET"])

    def test_store_down_fails_and_changes_nothing(self):
        store = FakeStore()
        run(store)
        before = json.dumps(store.rows, sort_keys=True)
        store.down = True
        code, _, err = run(store)
        self.assertEqual(code, 1)
        self.assertEqual(json.dumps(store.rows, sort_keys=True), before)
        self.assertNotIn(KEY, err)
        self.assertIn("[REDACTED]", err)

    def test_upload_error_fails_and_hides_the_key(self):
        store = FakeStore(post_status=500)
        code, _, err = run(store)
        self.assertEqual(code, 1)
        self.assertEqual(store.rows, {})
        self.assertIn("HTTP 500", err)
        self.assertNotIn(KEY, err)

    def test_missing_key_exits_before_composing(self):
        def never():
            raise AssertionError("composed without credentials")
        store = FakeStore()
        code, _, err = run(store, env_text="SUPABASE_URL=%s\n" % URL, raw=never)
        self.assertEqual(code, 1)
        self.assertEqual(store.calls, [])
        self.assertIn("SUPABASE_SECRET_KEY", err)

    def test_leaky_board_is_not_uploaded_but_others_are(self):
        raw = golden_raw()
        raw["vitals"][0]["date"] = "pi@device.local"
        store = FakeStore()
        code, _, err = run(store, raw=lambda: raw)
        self.assertEqual(code, 1)
        self.assertNotIn("network", store.rows)
        self.assertEqual(sorted(store.rows), ["fleet", "mining", "upgrades"])
        self.assertIn("network board failed the scrub (host)", err)
        self.assertNotIn("device.local", err)


class EnvFileTest(unittest.TestCase):
    def test_quotes_comments_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = env_file(tmp, '# c\nexport SUPABASE_URL="%s/"\n'
                                 "SUPABASE_SECRET_KEY='%s'\n\nOTHER\n" % (URL, KEY))
            self.assertEqual(s.credentials(path, environ={}), (URL, KEY))

    def test_falls_back_to_the_environment(self):
        env = {"SUPABASE_URL": URL, "SUPABASE_SECRET_KEY": KEY}
        self.assertEqual(s.credentials("/nonexistent/.env", environ=env),
                         (URL, KEY))


if __name__ == "__main__":
    unittest.main()
