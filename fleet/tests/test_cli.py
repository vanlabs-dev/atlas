"""Status summary, config/identity loading, and the CLI entrypoint.
The reconcile CLI is smoke-tested with a no-repo identity so it exercises
config load -> identity load -> reconcile -> summary without any network."""

import contextlib
import io
import json
import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _helpers import fleet  # noqa: E402


def write_config(tmp, **overrides):
    config = {"db": os.path.join(tmp, "fleet.db"),
              "clone_root": os.path.join(tmp, "fleet"),
              "max_new_clones_per_pass": 8,
              "caps": {"max_bytes": 1073741824, "max_files": 50000},
              "min_free_bytes": 2147483648}
    config.update(overrides)
    path = os.path.join(tmp, "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle)
    return path


class FleetStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.conn = fleet.open_store(os.path.join(self.tmp, "fleet.db"))
        self.addCleanup(self.conn.close)

    def test_status_summarizes_registry(self):
        fleet.upsert_slot(self.conn, {
            "netuid": 1, "status": "active", "clone_size_bytes": 100,
            "last_reconciled": "2026-07-14T12:00:00+00:00",
            "last_fetch_success": "2026-07-14T10:00:00+00:00"})
        fleet.upsert_slot(self.conn, {
            "netuid": 2, "status": "active", "clone_size_bytes": 200,
            "last_reconciled": "2026-07-14T12:00:00+00:00",
            "last_fetch_success": "2026-07-14T09:00:00+00:00"})
        fleet.upsert_slot(self.conn, {"netuid": 3, "status": "no-repo"})
        self.conn.commit()
        status = fleet.fleet_status(self.conn)
        self.assertEqual(status["total_slots"], 3)
        self.assertEqual(status["by_status"], {"active": 2, "no-repo": 1})
        self.assertEqual(status["total_clone_bytes"], 300)
        self.assertEqual(status["stalest"]["netuid"], 2)


class ConfigAndIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_load_config_resolves_relative_paths(self):
        path = write_config(self.tmp, db="var/fleet/fleet.db",
                            clone_root="var/fleet")
        config = fleet.load_config(path)
        self.assertTrue(os.path.isabs(config["db"]))
        self.assertTrue(os.path.isabs(config["clone_root"]))

    def test_identity_file_accepts_bare_subnet_list(self):
        path = os.path.join(self.tmp, "id.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"netuid": 1, "github_repo": "https://github.com/o/r",
                        "owner_ss58": "x", "subnet_name": "s"}], handle)
        result = fleet.load_identity_file(path)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["values"]["complete"])
        self.assertEqual(len(result["values"]["subnets"]), 1)

    def test_identity_file_accepts_full_result(self):
        path = os.path.join(self.tmp, "id.json")
        payload = {"status": "ok", "freshness_status": "fresh",
                   "values": {"subnets": [], "complete": True}}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        result = fleet.load_identity_file(path)
        self.assertEqual(result["values"]["complete"], True)


class CliMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config_path = write_config(self.tmp)

    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fleet.main(argv)
        return code, out.getvalue()

    def test_status_command_prints_summary(self):
        code, out = self._run(["--config", self.config_path, "status"])
        self.assertEqual(code, 0)
        self.assertIn("total_slots", json.loads(out))

    def test_reconcile_from_identity_file_records_no_repo(self):
        id_path = os.path.join(self.tmp, "id.json")
        with open(id_path, "w", encoding="utf-8") as handle:
            json.dump([{"netuid": 5, "github_repo": None,
                        "owner_ss58": "x", "subnet_name": "s"}], handle)
        code, out = self._run(["--config", self.config_path, "reconcile",
                               "--identity-file", id_path])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["no-repo"], 1)

    # The bare `reconcile` (no --identity-file) path uses the live TaoStats
    # aggregator; it is exercised on-device, never in unit tests, so no test
    # invokes it here (a unit test must not make a live provider call).


if __name__ == "__main__":
    unittest.main()
