"""Clone update lock (change: upgrade-sandbox-scope). The repotrack timer
and the upgrade job both run `update`; one waits for the other."""

import fcntl
import json
import os
import tempfile
import unittest
from unittest import mock

from _helpers import (arp, commit_origin, git, last_run, setup_tracking,
                      write_origin_file)


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class UpdateLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tracking = setup_tracking(self.tmp.name)
        self.config = load(self.tracking["config_path"])
        self.clone = self.tracking["clone"]
        write_origin_file(self.tracking["origin"], "docs/x.md", "x\n")
        self.new = commit_origin(self.tracking["origin"], "x")
        self.prev = git(self.clone, "rev-parse", "HEAD")

    def hold(self):
        handle = open(arp.clone_lock_path(self.clone), "a")
        fcntl.flock(handle, fcntl.LOCK_EX)
        self.addCleanup(handle.close)
        return handle

    def update(self, **kw):
        return arp.update(self.config, os.path.dirname(
            self.tracking["config_path"]), "test", **kw)

    def test_held_lock_records_busy_and_touches_nothing(self):
        self.hold()
        self.config["update_lock_wait_seconds"] = 0
        self.assertEqual(self.update(sleep=lambda s: None), 1)
        self.assertEqual(last_run(self.tracking["db"])["status"], "busy")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.prev)

    def test_second_update_waits_for_the_first(self):
        handle = self.hold()
        waits = []

        def sleep(seconds):
            # The first holder finishes while the second one waits.
            waits.append(seconds)
            fcntl.flock(handle, fcntl.LOCK_UN)

        self.assertEqual(self.update(sleep=sleep), 0)
        self.assertEqual(len(waits), 1)
        self.assertEqual(last_run(self.tracking["db"])["status"], "ok")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.new)

    def test_child_of_the_lock_holder_does_not_wait(self):
        self.hold()
        env = {arp.LOCK_HELD_ENV: os.path.abspath(self.clone)}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.update(sleep=self.fail), 0)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.new)


if __name__ == "__main__":
    unittest.main()
