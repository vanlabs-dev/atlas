"""Board building for the public site (sitedata/atlas_sitedata.py)."""

import datetime
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SITEDATA = os.path.dirname(HERE)
ROOT = os.path.dirname(SITEDATA)
sys.path.insert(0, SITEDATA)
sys.path.insert(0, os.path.join(ROOT, "fleet"))

import atlas_sitedata as s  # noqa: E402


def strict_diff(a, b, path="$"):
    """Differences between two JSON values, telling 5 from 5.0."""
    if type(a) is not type(b):
        return ["%s: %r vs %r" % (path, a, b)]
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return ["%s: keys %s vs %s" % (path, sorted(a), sorted(b))]
        return [d for k in a for d in strict_diff(a[k], b[k], path + "." + k)]
    if isinstance(a, list):
        if len(a) != len(b):
            return ["%s: length %d vs %d" % (path, len(a), len(b))]
        return [d for i, (x, y) in enumerate(zip(a, b))
                for d in strict_diff(x, y, "%s[%d]" % (path, i))]
    return [] if a == b else ["%s: %r vs %r" % (path, a, b)]


def load(name):
    with open(os.path.join(HERE, "golden", name), encoding="utf-8") as handle:
        return json.load(handle)


class GoldenTest(unittest.TestCase):
    def test_same_boards_as_the_typescript_export(self):
        # golden/boards.json came from the TypeScript fixture export's
        # pick, rounding and binning on golden/raw.json (2026-11-10). The
        # same check on that day's real Pi rows also gave no difference.
        self.assertEqual(strict_diff(load("boards.json"),
                                     s.boards(load("raw.json"))), [])

    def test_unlisted_source_field_never_appears(self):
        text = json.dumps(s.boards(load("raw.json")))
        self.assertIn("hotkey_private", json.dumps(load("raw.json")))
        self.assertNotIn("hotkey_private", text)
        self.assertNotIn("never published", text)


class RoundTest(unittest.TestCase):
    def test_matches_javascript_to_precision(self):
        # Number(v.toPrecision(4)) in Node 24.
        cases = {1.0625: 1.063, 0.125: 0.125, 257.16123: 257.2,
                 123456.7: 123500, -2.55555: -2.556,
                 0.000012345: 0.00001234, 99995: 99995, 1e21: 10 ** 21}
        for value, want in cases.items():
            got = s.round4(value)
            self.assertEqual(got, want, value)
            self.assertIs(type(got), type(want), value)

    def test_integral_float_is_an_integer(self):
        self.assertIs(type(s.round4(5.0)), int)


class PickTest(unittest.TestCase):
    def test_unlisted_fields_drop(self):
        record = s.pick("mining", {
            "netuid": 7, "subnet_name": "Seven",
            "owner_ss58": "5F3sa2TJAWMqDhXG6jhV4N8ko9SxwGy8TpaNS1repo5EYjQX",
            "hotkey": "secret"})
        self.assertEqual(list(record), list(s.ALLOWLIST["mining"]))
        self.assertEqual(record["netuid"], 7)
        self.assertNotIn("5F3sa2", json.dumps(record))

    def test_rounds_and_strips_em_dashes(self):
        record = s.pick("vitals", {"tao_usd": 257.16123, "date": "a — b"})
        self.assertEqual(record["taoUsd"], 257.2)
        self.assertEqual(record["date"], "a - b")

    def test_rejects_nested_values(self):
        with self.assertRaises(ValueError):
            s.pick("signal", {"class": {"nested": True}})

    def test_accepts_only_a_90_day_integer_series(self):
        good = [i % 3 for i in range(90)]
        self.assertEqual(s.pick("activity", {"netuid": 1, "daily": good})
                         ["daily"], good)
        self.assertIsNone(s.pick("activity", {"netuid": 1, "daily": None})
                          ["daily"])
        for bad in (good[1:], good[1:] + [-1], good[1:] + [0.5],
                    good[1:] + ["x"], good[1:] + [True]):
            with self.assertRaises(ValueError):
                s.pick("activity", {"netuid": 1, "daily": bad})


class BinTest(unittest.TestCase):
    def test_a_commit_exactly_7_days_old_is_in_the_7_day_bins(self):
        d = s.bin_daily([7.0, 7.000001, 0.2, -0.1, 30, 30.5, 90, 90.1])
        self.assertEqual(len(d), 90)
        self.assertEqual(sum(d[-7:]), 3)  # 7.0, 0.2 and the skewed -0.1
        self.assertEqual(sum(d[-30:]), 5)  # plus 7.000001 and 30
        self.assertEqual(sum(d), 7)  # 90.1 drops

    def test_bins_agree_with_the_activity_metric(self):
        import atlas_fleet_metrics as m
        now = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
        ages = [0, 0.5, 6.99, 7, 7.01, 13, 29.999, 30, 30.0001, 45, 89, 90]
        commits = [(now - datetime.timedelta(days=a), "dev@example.org")
                   for a in ages]
        commits.append((now - datetime.timedelta(days=1),
                        "41898282+github-actions[bot]@users.noreply.github.com"))
        bots = m.compile_bot_patterns(
            m.DEFAULT_METRICS_CFG["bot_author_patterns"])
        windows = m.compute_activity(commits, [7, 30, 90], now, bots)["windows"]
        d = s.bin_daily(ages)
        self.assertEqual(sum(d[-7:]), windows[7])
        self.assertEqual(sum(d[-30:]), windows[30])
        self.assertEqual(sum(d), windows[90])


PLANTED = [
    "ghp_aB3dE5fG7hJ9kL1mN3pQ5rS7",
    "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1",
    "10.1.2.3",
    "pi@device.local",
    "/home/someone/project/store.db",
    "5F3sa2TJAWMqDhXG6jhV4N8ko9SxwGy8TpaNS1repo5EYjQX",
    "netTaoMonth",
    "rentBand",
    "a \u2014 b",
]


class ScrubTest(unittest.TestCase):
    def test_golden_boards_are_clean(self):
        self.assertEqual(s.scrub(s.boards(load("raw.json"))), {})

    def test_each_planted_leak_blocks_only_its_board(self):
        for leak in PLANTED:
            built = s.boards(load("raw.json"))
            built["network"]["data"]["vitals"][0]["date"] = leak
            leaks = s.scrub(built)
            self.assertEqual(list(leaks), ["network"], leak)
            self.assertTrue(leaks["network"], leak)

    def test_public_commit_titles_pass(self):
        # "parents" and "current" are not the rent field.
        self.assertEqual(s.find_leaks("Fix parents of current block"), [])

    def test_same_rules_as_the_web_test(self):
        with open(os.path.join(ROOT, "web", "scripts", "scrub.ts"),
                  encoding="utf-8") as handle:
            self.assertIn("sitedata/scrub.json", handle.read())


if __name__ == "__main__":
    unittest.main()
