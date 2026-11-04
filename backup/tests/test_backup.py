"""Backup tests: config, SQLite discovery and staging, the restic call
sequence through a fake `restic` on PATH, status writing, staging
cleanup, secret hygiene and the restore check. Every test builds its own
home directory; none touches the device, the network or a real
repository."""

import contextlib
import io
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _MODULE_DIR)

import atlas_backup as ab  # noqa: E402

SECRET = "correct-horse-battery-staple-9f2c"

# A stand-in for restic. It logs its argv as one JSON line, then acts on
# FAKE_RESTIC_MODE. `restore` copies FAKE_RESTIC_SOURCE into the target
# under the staging path, the way restic restores absolute paths.
FAKE_RESTIC = r'''#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["FAKE_RESTIC_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
mode = os.environ.get("FAKE_RESTIC_MODE", "ok")
cmd = args[0]
if mode == "fail-" + cmd:
    sys.stderr.write("Fatal: unable to open repository\n")
    sys.exit(1)
if cmd == "backup":
    print(json.dumps({"message_type": "summary", "snapshot_id": "abcdef0123456789",
                      "data_added": 1234}))
    sys.exit(3 if mode == "partial" else 0)
if cmd == "stats":
    print(json.dumps({"total_size": 98765}))
if cmd == "restore":
    target = args[args.index("--target") + 1]
    include = args[args.index("--include") + 1]
    dest = os.path.join(target, include.lstrip("/"))
    shutil.copytree(os.environ["FAKE_RESTIC_SOURCE"], dest)
sys.exit(0)
'''


def make_db(path, rows=10, wal=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)",
                     [("x" * 100,) for _ in range(rows)])
    conn.commit()
    return conn


def corrupt(path):
    """Overwrite the middle of a database so quick_check fails."""
    size = os.path.getsize(path)
    with open(path, "r+b") as fh:
        fh.seek(4096)
        fh.write(b"\xff" * min(8192, size - 4096))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="atlas-backup-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        with open(ab.DEFAULT_CONFIG, encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.cfg["min_free_bytes"] = 0
        self.conns = []
        for rel in self.cfg["required_stores"]:
            self.conns.append(make_db(os.path.join(self.home, rel)))
        self.addCleanup(lambda: [c.close() for c in self.conns])

    def layout(self):
        return ab.Layout(self.cfg, self.home)

    def write(self, rel, data=b"data"):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class ConfigTests(Base):
    def test_shipped_config_loads(self):
        cfg = ab.load_config(ab.DEFAULT_CONFIG)
        self.assertEqual(cfg["keep_daily"], 3)

    def test_missing_key_rejected(self):
        del self.cfg["required_stores"]
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as fh:
            json.dump(self.cfg, fh)
        with self.assertRaisesRegex(ab.BackupError, "required_stores"):
            ab.load_config(path)

    def test_staging_must_be_under_include(self):
        self.cfg["staging"] = "elsewhere/staging"
        with self.assertRaisesRegex(ab.BackupError, "include root"):
            self.layout()

    def test_every_rebuildable_tree_is_excluded(self):
        lay = self.layout()
        for rel in ("atlas/var/fleet/clones/sn1/repo/x.db",
                    "atlas/var/repotrack/subtensor/README.md",
                    "atlas/var/upgrade/source-486/a.rs",
                    ".hermes/hermes-agent/run.py", ".hermes/tools/node",
                    ".hermes/installs/a", ".hermes/node/a", ".hermes/lsp/a",
                    ".hermes/bin/a", ".hermes/cache/a",
                    "atlas/var/fleet/fleet.db.bak-20261104-wp8",
                    "atlas/var/fleet/fleet.db-wal",
                    ".hermes/state.db-shm"):
            self.assertTrue(lay.is_excluded(os.path.join(self.home, rel)), rel)
        for rel in ("atlas/var/fleet/fleet.db", ".hermes/config.yaml",
                    ".hermes/config.yaml.bak-wp2", ".ssh/config",
                    "atlas/var/upgrade/spec-486.diff"):
            self.assertFalse(lay.is_excluded(os.path.join(self.home, rel)), rel)


class StageTests(Base):
    def test_stages_every_database_and_skips_excluded(self):
        self.write("atlas/var/fleet/fleet.db.bak-20261104-wp8",
                   ab.SQLITE_MAGIC + b"\0" * 100)
        make_db(os.path.join(self.home,
                             "atlas/var/fleet/clones/sn1/x.db")).close()
        make_db(os.path.join(self.home, ".hermes/cron/notepad.db")).close()
        self.write("atlas/var/telegram/notes.txt", b"plain")
        lay = self.layout()
        count, size = ab.stage(lay, 0)
        staged = sorted(
            os.path.relpath(os.path.join(d, f), lay.staging)
            for d, _, fs in os.walk(lay.staging) for f in fs)
        expected = sorted(self.cfg["required_stores"] + [".hermes/cron/notepad.db"])
        self.assertEqual(staged, expected)
        self.assertEqual(count, len(expected))
        self.assertGreater(size, 0)

    def test_copy_is_consistent_while_writer_runs(self):
        path = os.path.join(self.home, "atlas/var/fleet/fleet.db")
        writer = sqlite3.connect(path, check_same_thread=False)
        stop = threading.Event()

        def write_loop():
            while not stop.is_set():
                writer.execute("INSERT INTO t (v) VALUES (?)", ("y" * 500,))
                writer.commit()

        thread = threading.Thread(target=write_loop)
        thread.start()
        try:
            lay = self.layout()
            ab.stage(lay, 0)
        finally:
            stop.set()
            thread.join()
            writer.close()
        copy = os.path.join(lay.staging, "atlas/var/fleet/fleet.db")
        self.assertIsNone(ab.quick_check(copy))
        self.assertFalse(os.path.exists(copy + "-wal")
                         and os.path.getsize(copy + "-wal") > 0)

    def test_missing_required_store_fails(self):
        self.conns[0].close()
        os.unlink(os.path.join(self.home, self.cfg["required_stores"][0]))
        with self.assertRaisesRegex(ab.BackupError, "required store missing"):
            ab.stage(self.layout(), 0)

    def test_corrupt_copy_fails_and_names_database(self):
        conn = make_db(os.path.join(self.home, ".hermes/bad.db"), rows=2000,
                       wal=False)
        conn.close()
        corrupt(os.path.join(self.home, ".hermes/bad.db"))
        with self.assertRaisesRegex(ab.BackupError, r"\.hermes/bad\.db"):
            ab.stage(self.layout(), 0)

    def test_low_free_space_fails_before_copying(self):
        lay = self.layout()
        with self.assertRaisesRegex(ab.BackupError, "free space"):
            ab.stage(lay, 10 ** 18)
        self.assertEqual(os.listdir(lay.staging), [])


class FakeResticMixin:
    def install_fake(self, mode="ok"):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        exe = os.path.join(bindir, "restic")
        with open(exe, "w") as fh:
            fh.write(FAKE_RESTIC)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        self.restic_log = os.path.join(self.tmp, "restic.log")
        pwfile = os.path.join(self.tmp, "pw")
        with open(pwfile, "w") as fh:
            fh.write(SECRET)
        env = {
            "PATH": bindir + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_RESTIC_LOG": self.restic_log,
            "FAKE_RESTIC_MODE": mode,
            "RESTIC_REPOSITORY": "rclone:gdrive:atlas-backup",
            "RESTIC_PASSWORD_FILE": pwfile,
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def calls(self):
        if not os.path.exists(self.restic_log):
            return []
        with open(self.restic_log) as fh:
            return [json.loads(line) for line in fh]

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ab.main([*args, "--home", self.home,
                          "--config", self.config_path])
        return rc, out.getvalue()


class RunTests(FakeResticMixin, Base):
    def setUp(self):
        super().setUp()
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w") as fh:
            json.dump(self.cfg, fh)
        self.write("atlas/.env", b"TOKEN=" + SECRET.encode())

    def test_call_order_and_arguments(self):
        self.install_fake()
        rc, out = self.run_main("run")
        self.assertEqual(rc, 0, out)
        calls = self.calls()
        self.assertEqual([c[0] for c in calls],
                         ["backup", "forget", "check", "stats"])
        backup = calls[0]
        self.assertIn("--exclude-file", backup)
        paths = backup[backup.index("--exclude-file") + 2:]
        self.assertEqual(paths, [os.path.join(self.home, p)
                                 for p in ("atlas/var", "atlas/.env",
                                           ".hermes")])
        self.assertEqual(calls[1], ["forget", "--quiet", "--keep-daily", "3",
                                    "--prune"])

    def test_exclude_file_lists_live_databases_and_trees(self):
        self.install_fake()
        lay = self.layout()
        ab.stage(lay, 0)
        dbs = ab.find_databases(lay)
        lines = ab.exclude_lines(lay, dbs)
        for rel in self.cfg["required_stores"]:
            self.assertIn(os.path.join(self.home, rel), lines)
        self.assertIn(os.path.join(self.home, "atlas/var/fleet/clones"), lines)
        self.assertIn("*-wal", lines)
        self.assertFalse(any(l.startswith(lay.staging) for l in lines))

    def test_status_written_on_success(self):
        self.install_fake()
        rc, _ = self.run_main("run")
        self.assertEqual(rc, 0)
        with open(os.path.join(self.home, self.cfg["status_file"])) as fh:
            status = json.load(fh)
        self.assertEqual(status["snapshot_id"], "abcdef0123456789")
        self.assertEqual(status["staged_databases"], 6)
        self.assertEqual(status["repo_raw_bytes"], 98765)
        self.assertFalse(status["incomplete"])
        self.assertFalse(os.path.exists(self.layout().staging))

    def test_partial_backup_is_kept_and_flagged(self):
        self.install_fake("partial")
        rc, _ = self.run_main("run")
        self.assertEqual(rc, 0)
        with open(os.path.join(self.home, self.cfg["status_file"])) as fh:
            self.assertTrue(json.load(fh)["incomplete"])

    def test_failed_upload_keeps_status_and_clears_staging(self):
        self.install_fake()
        self.assertEqual(self.run_main("run")[0], 0)
        status_path = os.path.join(self.home, self.cfg["status_file"])
        with open(status_path) as fh:
            before = fh.read()
        os.environ["FAKE_RESTIC_MODE"] = "fail-backup"
        rc, out = self.run_main("run")
        self.assertEqual(rc, 1)
        self.assertIn("restic backup exited 1", out)
        with open(status_path) as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(self.layout().staging))

    def test_failed_prune_fails_run(self):
        self.install_fake("fail-forget")
        rc, out = self.run_main("run")
        self.assertEqual(rc, 1)
        self.assertIn("restic forget exited 1", out)

    def test_missing_env_fails_before_staging(self):
        self.install_fake()
        del os.environ["RESTIC_PASSWORD_FILE"]
        rc, out = self.run_main("run")
        self.assertEqual(rc, 1)
        self.assertIn("RESTIC_PASSWORD_FILE", out)
        self.assertEqual(self.calls(), [])

    def test_no_secret_in_output_or_status(self):
        self.install_fake()
        _, out_ok = self.run_main("run")
        os.environ["FAKE_RESTIC_MODE"] = "fail-backup"
        _, out_fail = self.run_main("run")
        with open(os.path.join(self.home, self.cfg["status_file"])) as fh:
            status = fh.read()
        for text in (out_ok, out_fail, status):
            self.assertNotIn(SECRET, text)


class RestoreCheckTests(FakeResticMixin, Base):
    def setUp(self):
        super().setUp()
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w") as fh:
            json.dump(self.cfg, fh)
        self.source = os.path.join(self.tmp, "snapshot")
        for rel in self.cfg["required_stores"]:
            make_db(os.path.join(self.source, rel), wal=False).close()
        os.environ.setdefault("FAKE_RESTIC_SOURCE", "")

    def test_restore_check_passes_and_cleans_up(self):
        self.install_fake()
        os.environ["FAKE_RESTIC_SOURCE"] = self.source
        rc, out = self.run_main("restore-check")
        self.assertEqual(rc, 0, out)
        self.assertIn("6 databases ok", out)
        self.assertFalse(os.path.exists(self.layout().scratch))
        restore = self.calls()[0]
        self.assertEqual(restore[restore.index("--include") + 1],
                         self.layout().staging)

    def test_restore_check_fails_on_corrupt_database(self):
        make_db(os.path.join(self.source, ".hermes/big.db"), rows=2000,
                wal=False).close()
        corrupt(os.path.join(self.source, ".hermes/big.db"))
        self.install_fake()
        os.environ["FAKE_RESTIC_SOURCE"] = self.source
        rc, out = self.run_main("restore-check")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL .hermes/big.db", out)
        self.assertFalse(os.path.exists(self.layout().scratch))

    def test_restore_check_fails_on_missing_store(self):
        os.unlink(os.path.join(self.source, ".hermes/state.db"))
        self.install_fake()
        os.environ["FAKE_RESTIC_SOURCE"] = self.source
        rc, out = self.run_main("restore-check")
        self.assertEqual(rc, 1)
        self.assertIn("restore lacks .hermes/state.db", out)


if __name__ == "__main__":
    unittest.main()
