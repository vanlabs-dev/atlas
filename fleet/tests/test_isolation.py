"""Test isolation (change: mining-board-accuracy): fleet tests render into a
temp www dir, never into the repo's own var/."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import _helpers as h  # noqa: E402
import atlas_fleet_dashboard as dash  # noqa: E402
import atlas_fleet_mining as mine  # noqa: E402


class TestRepoVarGuard(unittest.TestCase):

    def test_render_paths_are_guarded(self):
        self.assertTrue(dash._atomic_write.guarded)
        self.assertTrue(mine._atomic_write.guarded)

    def test_a_write_under_the_repo_var_fails(self):
        target = os.path.join(h.REPO_VAR, "fleet", "www", "guard-probe.html")
        with self.assertRaises(h.RepoVarWrite):
            mine._atomic_write(target, "x")
        self.assertFalse(os.path.exists(target))

    def test_a_write_to_a_temp_dir_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "www", "index.html")
            dash._atomic_write(target, "x")
            self.assertTrue(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
