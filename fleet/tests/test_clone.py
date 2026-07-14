"""Clone/update executor, exercised against throwaway local git origins
(no network, no mocks). Covers the blobless minimal-footprint clone policy,
size/file caps with quarantine, the token non-persistence guarantee, and
the fetch -> fast-forward-or-reset update with a recorded change range."""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402


def git_config(clone_dir, key):
    code, out, _ = fleet._run_git(clone_dir, ["config", "--get", key])
    return out.strip() if code == 0 else None


class SetupCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = h.make_origin(self.tmp, files={
            "README.md": "# subnet\n", "src/main.py": "print('hi')\n"})
        self.clone = os.path.join(self.tmp, "fleet", "23")

    def test_clone_creates_active_checkout(self):
        state = fleet.setup_clone(self.clone, self.origin)
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["default_branch"], "main")
        self.assertTrue(os.path.isfile(os.path.join(self.clone, "README.md")))
        self.assertTrue(state["local_sha"])

    def test_clone_is_partial_not_shallow(self):
        fleet.setup_clone(self.clone, self.origin)
        self.assertEqual(
            git_config(self.clone, "remote.origin.partialclonefilter"),
            "blob:none")
        code, out, _ = fleet._run_git(
            self.clone, ["rev-parse", "--is-shallow-repository"])
        self.assertEqual(out.strip(), "false")

    def test_clone_disables_push_url(self):
        fleet.setup_clone(self.clone, self.origin)
        self.assertEqual(
            git_config(self.clone, "remote.origin.pushurl"), "DISABLED")

    def test_clone_records_non_default_branch(self):
        origin = h.make_origin(self.tmp, name="dev-origin", branch="develop")
        clone = os.path.join(self.tmp, "fleet", "24")
        state = fleet.setup_clone(clone, origin)
        self.assertEqual(state["default_branch"], "develop")

    def test_clone_is_idempotent(self):
        first = fleet.setup_clone(self.clone, self.origin)
        second = fleet.setup_clone(self.clone, self.origin)
        self.assertEqual(second["status"], "active")
        self.assertEqual(second["local_sha"], first["local_sha"])

    def test_file_count_cap_quarantines_and_cleans_up(self):
        state = fleet.setup_clone(self.clone, self.origin,
                                  caps={"max_files": 1})
        self.assertEqual(state["status"], "quarantined")
        self.assertFalse(os.path.isdir(self.clone))

    def test_size_cap_quarantines_and_cleans_up(self):
        import secrets
        # count-objects reports KiB, so the fixture must be comfortably
        # larger than the cap and incompressible enough to survive packing.
        big_origin = h.make_origin(self.tmp, name="big-origin", files={
            "data.txt": secrets.token_hex(200000)})
        clone = os.path.join(self.tmp, "fleet", "99")
        state = fleet.setup_clone(clone, big_origin, caps={"max_bytes": 4096})
        self.assertEqual(state["status"], "quarantined")
        self.assertFalse(os.path.isdir(clone))

    def test_unreachable_origin_reports_unreachable(self):
        state = fleet.setup_clone(
            self.clone, os.path.join(self.tmp, "does-not-exist"))
        self.assertEqual(state["status"], "unreachable")
        self.assertFalse(os.path.isdir(self.clone))

    def test_submodule_content_is_not_fetched(self):
        sub = h.make_origin(self.tmp, name="subrepo",
                            files={"secret.txt": "sensitive\n"})
        parent = h.make_origin(self.tmp, name="parent")
        h.git(parent, "-c", "protocol.file.allow=always", "submodule", "add",
              sub, "vendor/sub")
        h.git(parent, "commit", "-m", "add submodule")
        clone = os.path.join(self.tmp, "fleet", "77")
        state = fleet.setup_clone(clone, parent)
        self.assertEqual(state["status"], "active")
        self.assertFalse(os.path.isfile(
            os.path.join(clone, "vendor", "sub", "secret.txt")))

    def test_token_is_never_persisted_to_clone_config(self):
        token = "ghp_supersecrettoken1234567890"
        fleet.setup_clone(self.clone, self.origin, token=token)
        with open(os.path.join(self.clone, ".git", "config"),
                  encoding="utf-8") as handle:
            config_text = handle.read()
        self.assertNotIn(token, config_text)
        self.assertNotIn("extraheader", config_text.lower())


class UpdateCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = h.make_origin(self.tmp, files={"README.md": "# subnet\n"})
        self.clone = os.path.join(self.tmp, "fleet", "23")
        self.state = fleet.setup_clone(self.clone, self.origin)
        self.branch = self.state["default_branch"]
        self.prev = self.state["local_sha"]

    def test_no_change_is_reported(self):
        result = fleet.update_clone(self.clone, self.branch, self.prev)
        self.assertEqual(result["status"], "no-change")

    def test_fast_forward_advances_and_records_range(self):
        h.add_commit(self.origin, "src/new.py", "x = 1\n", "feat: add new")
        result = fleet.update_clone(self.clone, self.branch, self.prev)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["fast_forward"])
        self.assertNotEqual(result["new_sha"], self.prev)
        subjects = [c["subject"] for c in result["range"]["commits"]]
        self.assertIn("feat: add new", subjects)
        paths = [f["path"] for f in result["range"]["files"]]
        self.assertIn("src/new.py", paths)

    def test_rewritten_history_resets_not_merges(self):
        h.git(self.origin, "commit", "--amend", "-m", "rewritten root")
        new_head = h.git(self.origin, "rev-parse", "HEAD")
        result = fleet.update_clone(self.clone, self.branch, self.prev)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["fast_forward"])
        self.assertEqual(result["local_sha"], new_head)

    def test_unrecordable_range_advances_but_reports_record_failed(self):
        # prev_sha no longer reachable (history rewritten past it): the clone
        # must still advance to the new head, but the range cannot be built.
        h.add_commit(self.origin, "src/new.py", "x = 1\n", "feat: add new")
        new_head = h.git(self.origin, "rev-parse", "HEAD")
        result = fleet.update_clone(self.clone, self.branch, "0" * 40)
        self.assertEqual(result["status"], "record-failed")
        self.assertEqual(result["local_sha"], new_head)

    def test_dirty_tree_aborts_before_fetch(self):
        with open(os.path.join(self.clone, "README.md"), "a",
                  encoding="utf-8") as handle:
            handle.write("local tampering\n")
        result = fleet.update_clone(self.clone, self.branch, self.prev)
        self.assertEqual(result["status"], "local-modifications")


class RedactionTests(unittest.TestCase):
    def test_registered_secret_is_redacted(self):
        secret = "ghp_anothersecret0987654321"
        fleet.register_secret(secret)
        self.assertNotIn(secret, fleet.redact("error near %s here" % secret))

    def test_audit_line_redacts_registered_secret(self):
        conn = fleet.open_store(os.path.join(tempfile.mkdtemp(), "fleet.db"))
        self.addCleanup(conn.close)
        secret = "ghp_tokenleakingintoauditline123"
        fleet.register_secret(secret)
        fleet.audit(conn, "fleet", "clone", 1,
                    "cloning with %s embedded" % secret)
        conn.commit()
        detail = conn.execute("SELECT detail FROM audit").fetchone()[0]
        self.assertNotIn(secret, detail)


if __name__ == "__main__":
    unittest.main()
