"""Request encoding and the recorded CoinGecko reply (change:
plain-english-alerts). CoinGecko ignored `include_last_updated_at=True`
from 2026-09-28; the lowercase form returns the field."""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_live as al  # noqa: E402

SCHEMA = os.path.join(os.path.dirname(_HERE), "schemas", "coingecko",
                      "simple-price.v1.schema.json")
# Recorded 2026-10-22 from /api/v3/simple/price?ids=bittensor&
# vs_currencies=usd&include_last_updated_at=true
RECORDED = {"bittensor": {"usd": 271.77, "last_updated_at": 1792627353}}
# The same request sent with `True`
RECORDED_IGNORED = {"bittensor": {"usd": 271.82}}


class QueryStringTests(unittest.TestCase):
    def test_booleans_are_lowercase(self):
        self.assertEqual(al.query_string({"a": True, "b": False}),
                         "a=true&b=false")

    def test_none_dropped_and_others_unchanged(self):
        self.assertEqual(al.query_string({"ids": "bittensor", "x": None,
                                          "limit": 200}),
                         "ids=bittensor&limit=200")

    def test_shipped_coingecko_request_asks_for_the_timestamp(self):
        with open(os.path.join(os.path.dirname(_HERE), "config.json")) as fh:
            op = json.load(fh)["operations"]["price_spot_coingecko"]
        self.assertIn("include_last_updated_at=true",
                      al.query_string(op["params"]))


class RecordedReplyTests(unittest.TestCase):
    def setUp(self):
        with open(SCHEMA) as fh:
            self.schema = json.load(fh)

    def test_recorded_reply_matches_the_pinned_schema(self):
        self.assertEqual(al.validate_schema(self.schema, RECORDED), [])

    def test_reply_without_the_timestamp_is_drift(self):
        problems = al.validate_schema(self.schema, RECORDED_IGNORED)
        self.assertTrue(any("last_updated_at" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
