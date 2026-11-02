"""Pi pre-commit guard: only the personal identity may commit."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HOOKS = os.path.join(ROOT, "tools", "git-hooks")
sys.path.insert(0, os.path.join(ROOT, "upgrade"))

import atlas_upgrade as au  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "git not installed")
class PreCommitTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
        self.env.update(HOME=self.repo, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q")
        self.git("config", "user.name", au.AUTHOR_NAME)
        self.git("config", "user.email", au.AUTHOR_EMAIL)
        self.git("config", "core.hooksPath", HOOKS)
        self.count = 0

    def git(self, *args, env=None):
        return subprocess.run(["git"] + list(args), cwd=self.repo,
                              env=env or self.env, capture_output=True,
                              text=True)

    def commit(self, *args, env=None):
        self.count += 1
        with open(os.path.join(self.repo, "f"), "a") as handle:
            handle.write("%d\n" % self.count)
        self.git("add", "f")
        return self.git(*(list(args) or ["commit"]) + ["-qm", "m"],
                        env=env).returncode

    def test_expected_identity_matches_upgrade_job(self):
        with open(os.path.join(HOOKS, "pre-commit")) as handle:
            text = handle.read()
        self.assertEqual(re.search(r'^expected="(.*)"$', text, re.M).group(1),
                         au.AUTHOR_IDENT)

    def test_hook_is_executable(self):
        self.assertTrue(os.access(os.path.join(HOOKS, "pre-commit"), os.X_OK))

    def test_personal_identity_commits(self):
        self.assertEqual(self.commit(), 0)

    def test_config_override_rejected(self):
        self.assertNotEqual(self.commit(
            "-c", "user.name=Atlas", "-c", "user.email=atlas@localhost",
            "commit"), 0)

    def test_env_override_rejected(self):
        for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL"):
            env = dict(self.env, **{key: "atlas"})
            self.assertNotEqual(self.commit(env=env), 0, key)

    def test_author_flag_rejected(self):
        self.assertNotEqual(self.commit(
            "commit", "--author=Atlas <atlas@localhost>"), 0)


if __name__ == "__main__":
    unittest.main()
