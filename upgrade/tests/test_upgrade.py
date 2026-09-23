"""Runtime upgrade job (change: runtime-upgrade-pipeline). Every gate,
retry, and report path runs against fakes for git, claude, RPC, and
Telegram; nothing here reaches the network or a real repository."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import allowed_paths as ap  # noqa: E402
import atlas_upgrade as au  # noqa: E402

SOURCES = "| Grounded at | Finney `spec_version` **%d** |\n"
BASE, COMMIT = "b" * 40, "c" * 40


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def make_tree(root, grounded):
    write(os.path.join(root, "knowledge", "corpus", "SOURCES.md"),
          SOURCES % grounded)
    write(os.path.join(root, "knowledge", "corpus", "ground-truth.md"),
          "facts\n")
    write(os.path.join(root, "knowledge", "corpus", "hashes.json"),
          json.dumps({"grounded_spec": grounded,
                      "files": {"ground-truth.md": "x"}}))
    write(os.path.join(root, "livedata", "tests", "test_x.py"), "")


class FakeJob(au.Job):
    """Scripted world. `broken` names the command families that fail."""

    def __init__(self, tmp, live=470, corpus=469, clone=470):
        self.tmp = tmp
        root = os.path.join(tmp, "atlas")
        make_tree(root, corpus)
        write(os.path.join(root, "var", "repotrack", "subtensor", "runtime",
                           "src", "lib.rs"), "spec_version: %d,\n" % clone)
        super().__init__(root=root, worktree=os.path.join(tmp, "wt"))
        self.live = live
        self.clock = 1000000.0
        self.sent = []
        self.calls = []
        self.broken = set()
        self.changed = []
        self.branches = set()
        self.edit = self.default_edit
        self.deliver = True
        self.pushed = False

    def now(self):
        return self.clock

    def live_spec(self):
        if "rpc" in self.broken:
            return {"ok": False, "error": "down"}
        return {"ok": True, "spec_version": self.live}

    def send(self, text):
        if self.deliver:
            self.sent.append(text)
        return self.deliver

    def default_edit(self, wt):
        write(os.path.join(wt, "knowledge", "corpus", "SOURCES.md"),
              SOURCES % self.live)
        self.changed.append("knowledge/corpus/SOURCES.md")

    def run(self, cmd, cwd, timeout, env=None):
        self.calls.append(cmd)
        ok = au.Result(0, "", "")
        if cmd[0] == "git":
            return self.git_fake(cmd[1:], cwd)
        if cmd[0] == self.claude:
            if cmd[-1] == "reply ok":
                return au.Result(1, "", "auth") if "smoke" in self.broken \
                    else au.Result(0, "ok", "")
            if "claude" in self.broken:
                return au.Result(124, "", "timed out")
            self.edit(cwd)
            return au.Result(0, "summary of edits", "")
        script = os.path.basename(cmd[1]) if len(cmd) > 1 else ""
        if cmd[1:3] == ["-m", "unittest"]:
            return au.Result(1, "", "FAILED") if "suite" in self.broken else ok
        if script == "atlas_probe.py":
            return au.Result(1, '{"ok": false}', "") \
                if "probe" in self.broken and cwd == self.worktree \
                else au.Result(0, '{"ok": true}', "")
        if script == "atlas_kb.py" and cmd[2] == "ingest":
            report = {"secret_scan_findings": [],
                      "duplicate_unit_ids": ["dup"] if "ingest" in self.broken
                      else []}
            write(os.path.join(self.root, "var", "knowledge",
                               "validation-report-R1.json"),
                  json.dumps(report))
            return au.Result(0, "Ingest run R1: 3 units staged", "")
        if script == "atlas_kb.py" and cmd[2] == "activate":
            return au.Result(1, "", "no") if "activate" in self.broken else ok
        return ok  # repotrack update, read-knobs

    def git_fake(self, args, cwd):
        ok = au.Result(0, "", "")
        if "git-" + args[0] in self.broken:
            return au.Result(1, "", "%s failed" % args[0])
        if args[0] == "var":
            return au.Result(0, "vaNlabs <vanlabs@pm.me> 1 +0000", "")
        if args[0] == "status":
            if cwd == self.root:
                return au.Result(0, " M x" if "dirty" in self.broken else "",
                                 "")
            return au.Result(0, "".join(" M %s\0" % p for p in self.changed),
                             "")
        if args[0] == "rev-parse" and args[1] == "--verify":
            return ok if args[-1][len("refs/heads/"):] in self.branches \
                else au.Result(1, "", "")
        if args[0] == "rev-parse":
            if "moved" in self.broken and cwd == self.worktree:
                return au.Result(0, "d" * 40, "")
            return au.Result(0, COMMIT if self.pushed or (
                cwd == self.worktree and "commit" in self.calls_flat())
                else BASE, "")
        if args[0] == "worktree" and args[1] == "add":
            self.branches.add(args[3])
            shutil.copytree(os.path.join(self.root, "knowledge"),
                            os.path.join(args[4], "knowledge"))
            shutil.copytree(os.path.join(self.root, "livedata"),
                            os.path.join(args[4], "livedata"))
            self.changed = []
            return ok
        if args[0] == "worktree" and args[1] == "remove":
            shutil.rmtree(args[3])
            return ok
        if args[0] == "log" and "--format=%an <%ae>" in args:
            return au.Result(0, au.AUTHOR_IDENT, "")
        if args[0] == "push":
            self.pushed = True
            return ok
        if args[0] == "ls-remote":
            return au.Result(0, "%s\trefs/heads/main" % (
                "e" * 40 if "readback" in self.broken else COMMIT), "")
        return ok

    def calls_flat(self):
        return [part for call in self.calls for part in call]

    def state(self):
        return self.load_state()

    def ran(self, prefix):
        return any(call[:len(prefix)] == prefix for call in self.calls)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def job(self, **kw):
        return FakeJob(self.tmp, **kw)

    def claude_calls(self, job):
        return [c for c in job.calls if c[0] == job.claude
                and c[-1] != "reply ok"]


class DetectTest(Base):
    def test_live_moved_starts_run_and_updates(self):
        job = self.job()
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual((state["status"], state["spec"], state["attempt"]),
                         ("updated", 470, 1))
        self.assertEqual(len(self.claude_calls(job)), 1)
        self.assertEqual(len(job.sent), 1)
        self.assertIn("updated to spec 470", job.sent[0])
        self.assertTrue(job.ran(["git", "push", "origin", "HEAD:main"]))

    def test_corpus_equals_live_does_nothing(self):
        job = self.job(live=469)
        self.assertEqual(job.run_once(), 0)
        self.assertEqual(job.calls, [])
        self.assertEqual(job.sent, [])

    def test_only_repo_moved_does_nothing(self):
        job = self.job(live=469, clone=470)
        job.run_once()
        self.assertEqual(self.claude_calls(job), [])

    def test_live_spec_unavailable(self):
        job = self.job()
        job.broken.add("rpc")
        self.assertEqual(job.run_once(), 1)
        self.assertEqual(job.sent, [])

    def test_order_activation_after_push(self):
        job = self.job()
        job.run_once()
        order = [c for c in job.calls if c[:2] in (["git", "push"],
                                                   ["git", "pull"])
                 or (len(c) > 2 and c[2] == "activate")]
        self.assertEqual([c[1] if c[0] == "git" else "activate"
                          for c in order], ["push", "pull", "activate"])

    def test_hashes_regenerated_with_live_spec(self):
        job = self.job()
        job.run_once()
        with open(os.path.join(job.worktree, "knowledge", "corpus",
                               "hashes.json")) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["grounded_spec"], 470)
        self.assertEqual(manifest["files"]["ground-truth.md"],
                         hashlib.sha256(b"facts\n").hexdigest())

    def test_model_call_is_restricted(self):
        job = self.job()
        job.run_once()
        cmd = self.claude_calls(job)[0]
        for flag in ("--restricted", "--strict-mcp-config", "--max-turns"):
            self.assertIn(flag, cmd)
        self.assertNotIn("Bash", cmd[cmd.index("--tools") + 1])
        self.assertIn(job.clone, cmd)
        self.assertEqual(job.calls[-1][0], sys.executable)  # activate last


class GateTest(Base):
    def fails_at(self, gate, prepare):
        job = self.job()
        prepare(job)
        self.assertEqual(job.run_once(), 1)
        state = job.state()
        self.assertEqual(state["status"], "retrying")
        self.assertTrue(state["last_error"].startswith(gate + ":"),
                        state["last_error"])
        self.assertFalse(job.pushed)
        self.assertFalse(any(len(c) > 2 and c[2] == "activate"
                             for c in job.calls))
        self.assertEqual(len(job.sent), 1)
        self.assertIn("retrying", job.sent[0])
        return job

    def test_claude_auth(self):
        self.fails_at("preflight", lambda j: j.broken.add("smoke"))

    def test_dirty_live_tree(self):
        self.fails_at("preflight", lambda j: j.broken.add("dirty"))

    def test_edit_timeout(self):
        self.fails_at("edit", lambda j: j.broken.add("claude"))

    def test_empty_edit(self):
        def nothing(job):
            job.edit = lambda wt: None
        job = self.fails_at("goal", nothing)
        self.assertIn("changed no file", job.state()["last_error"])

    def test_spec_not_grounded(self):
        def stale(job):
            def edit(wt):
                write(os.path.join(wt, "knowledge", "corpus",
                                   "ground-truth.md"), "new\n")
                job.changed.append("knowledge/corpus/ground-truth.md")
            job.edit = edit
        job = self.fails_at("goal", stale)
        self.assertIn("grounds spec 469, live spec is 470",
                      job.state()["last_error"])

    def test_edit_outside_scope(self):
        def tests(job):
            def edit(wt):
                job.default_edit(wt)
                job.changed.append("livedata/tests/test_gate.py")
            job.edit = edit
        job = self.fails_at("scope", tests)
        self.assertIn("livedata/tests/test_gate.py",
                      job.state()["last_error"])

    def test_probe_edited(self):
        def probe(job):
            def edit(wt):
                job.default_edit(wt)
                job.changed.append("livedata/atlas_probe.py")
            job.edit = edit
        self.fails_at("scope", probe)

    def test_model_moved_head(self):
        self.fails_at("scope", lambda j: j.broken.add("moved"))

    def test_suite_fails(self):
        job = self.fails_at("test", lambda j: j.broken.add("suite"))
        self.assertIn("livedata/tests", job.state()["last_error"])

    def test_probe_fails(self):
        self.fails_at("probe", lambda j: j.broken.add("probe"))

    def test_rejected_units(self):
        self.fails_at("ingest", lambda j: j.broken.add("ingest"))

    def test_push_rejected(self):
        job = self.fails_at("push", lambda j: j.broken.add("git-push"))
        self.assertFalse(job.ran(["git", "pull", "--ff-only", "origin",
                                  "main"]))
        self.assertFalse(any("--force" in c or "-f" in c
                             for c in job.calls if c[:2] == ["git", "push"]))

    def test_failed_attempt_keeps_edits_on_branch(self):
        job = self.fails_at("probe", lambda j: j.broken.add("probe"))
        self.assertTrue(job.ran(["git", "commit", "-q", "-m",
                                 "wip: failed upgrade attempt"]))


class PostPushTest(Base):
    def test_activation_failure_blocks_at_once(self):
        job = self.job()
        job.broken.add("activate")
        self.assertEqual(job.run_once(), 1)
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("blocked", 1))
        self.assertIn("Blocked", job.sent[0])

    def test_readback_mismatch_blocks_before_pull(self):
        job = self.job()
        job.broken.add("readback")
        job.run_once()
        self.assertEqual(job.state()["status"], "blocked")
        self.assertFalse(job.ran(["git", "pull", "--ff-only", "origin",
                                  "main"]))


class RetryTest(Base):
    def test_backoff_then_blocked_after_third(self):
        job = self.job()
        job.broken.add("probe")
        job.run_once()
        self.assertEqual(job.state()["next_attempt_at"], job.clock + 3600)
        job.run_once()  # too early: nothing happens
        self.assertEqual(job.state()["attempt"], 1)
        job.clock += 3600
        job.run_once()
        self.assertEqual(job.state()["next_attempt_at"],
                         job.clock + 4 * 3600)
        job.clock += 4 * 3600
        job.run_once()
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("blocked", 3))
        self.assertIn(state["branch"], job.sent[-1])
        branches = sorted(job.branches)
        self.assertEqual(branches, ["upgrade/spec-470-a1",
                                    "upgrade/spec-470-a2",
                                    "upgrade/spec-470-a3"])
        job.clock += 10 ** 6
        calls = len(job.calls)
        job.run_once()
        self.assertEqual(len(job.calls), calls)  # blocked: no new run
        self.assertEqual(len(job.sent), 3)

    def test_clear_restarts_at_attempt_one(self):
        job = self.job()
        job.broken.add("probe")
        job.save_state({"status": "blocked", "spec": 470, "attempt": 3,
                        "reported": []})
        job.branches.add("upgrade/spec-470-a1")
        self.assertEqual(au.clear(job, 469), 1)
        self.assertEqual(au.clear(job, 470), 0)
        job.broken.discard("probe")
        job.run_once()
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("updated", 1))
        self.assertEqual(state["branch"], "upgrade/spec-470-a1-r2")

    def test_newer_spec_supersedes_block(self):
        job = self.job(live=471, clone=471)
        job.save_state({"status": "blocked", "spec": 470, "attempt": 3,
                        "reported": []})
        job.run_once()
        state = job.state()
        self.assertEqual((state["spec"], state["attempt"], state["status"]),
                         (471, 1, "updated"))


class WaitingTest(Base):
    def test_clone_lag_waits_without_an_attempt(self):
        job = self.job(clone=469)
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("waiting", 0))
        self.assertEqual(self.claude_calls(job), [])
        self.assertTrue(job.ran([sys.executable, os.path.join(
            job.root, "repotrack", "atlas_repo.py"), "update"]))
        job.clock += 1800
        job.run_once()
        self.assertEqual(len(job.sent), 1)
        self.assertIn("waiting", job.sent[0])

    def test_clone_catches_up(self):
        job = self.job(clone=469)
        job.run_once()
        write(os.path.join(job.clone, "runtime", "src", "lib.rs"),
              "spec_version: 470,\n")
        job.run_once()
        self.assertEqual(job.state()["status"], "updated")


class InterruptTest(Base):
    def test_interrupted_run_reports_stalled_once(self):
        job = self.job()
        job.save_state({"status": "running", "spec": 470, "attempt": 1,
                        "step": "edit", "reported": []})
        self.assertEqual(job.run_once(), 0)  # too early for attempt 2
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]),
                         ("retrying", 1))
        self.assertIn("interrupted", state["last_error"])
        self.assertEqual(len(job.sent), 1)
        self.assertIn("stalled", job.sent[0])
        self.assertNotIn("retrying:", job.sent[0])

    def test_interrupted_last_attempt_blocks_as_stalled(self):
        job = self.job()
        job.save_state({"status": "running", "spec": 470, "attempt": 3,
                        "step": "test", "reported": []})
        job.run_once()
        self.assertEqual(job.state()["status"], "blocked")
        self.assertEqual(len(job.sent), 1)
        self.assertIn("stalled", job.sent[0])


class ReportTest(Base):
    def test_undelivered_report_is_retried_once(self):
        job = self.job()
        job.broken.add("probe")
        job.deliver = False
        job.run_once()
        self.assertIn("pending_report", job.state())
        job.deliver = True
        job.run_once()  # before the backoff: only the pending report
        self.assertEqual(len(job.sent), 1)
        self.assertNotIn("pending_report", job.state())
        job.run_once()
        self.assertEqual(len(job.sent), 1)


class DryRunTest(Base):
    def test_machinery_check_without_edit_push_or_activate(self):
        job = self.job(live=469)
        job.dry_run = True
        job.state_path = os.path.join(job.var, "dry-run-state.json")
        self.assertEqual(job.run_once(), 0)
        self.assertEqual(self.claude_calls(job), [])
        self.assertFalse(job.ran(["git", "push", "origin", "HEAD:main"]))
        self.assertTrue(any(c[1:3] == ["-m", "unittest"] for c in job.calls))
        self.assertFalse(os.path.exists(os.path.join(job.var,
                                                     "state.json")))


class HelpersTest(unittest.TestCase):
    def test_allowed_paths(self):
        for path in ("knowledge/corpus/ground-truth.md",
                     "knowledge/corpus/hashes.json",
                     "knowledge/supersession-markers.json",
                     "docs/decisions.md", "livedata/atlas_live.py",
                     "livedata/config.json"):
            self.assertTrue(ap.is_allowed(path), path)
        for path in ("livedata/atlas_probe.py", "livedata/scale_meta.py",
                     "livedata/tests/test_gate.py", "knowledge/atlas_kb.py",
                     "docs/runtime-upgrade.md", "AGENTS.md",
                     "upgrade/allowed_paths.py", "upgrade/prompt.md",
                     "livedata/systemd/atlas-probe.service", ".env",
                     "livedata/sub/x.py", "livedata/schemas/a.json",
                     "fleet/atlas_fleet.py"):
            self.assertFalse(ap.is_allowed(path), path)

    def test_tool_rules_mirror_lists(self):
        self.assertIn("Edit(docs/decisions.md)", ap.tool_rules())
        self.assertIn("Write(livedata/atlas_probe.py)", ap.tool_denials())

    def test_status_paths_rename(self):
        out = " M a.md\0R  new.py\0old.py\0?? dir/u.txt\0"
        self.assertEqual(au.status_paths(out),
                         ["a.md", "new.py", "old.py", "dir/u.txt"])

    def test_test_dirs_outermost_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "a", "tests", "test_a.py"), "")
            write(os.path.join(tmp, "a", "tests", "sub", "test_b.py"), "")
            write(os.path.join(tmp, "b", "tests", "test_lib.sh"), "")
            write(os.path.join(tmp, "var", "tests", "test_v.py"), "")
            self.assertEqual(au.test_dirs(tmp),
                             [os.path.join(tmp, "a", "tests")])

    def test_repo_suites_are_all_found(self):
        repo = os.path.dirname(os.path.dirname(_HERE))
        found = {os.path.relpath(p, repo) for p in au.test_dirs(repo)}
        for suite in ("fleet/tests", "subnt/tests", "livedata/tests",
                      "knowledge/tests", "upgrade/tests", "telegram/tests"):
            self.assertIn(suite, found)


if __name__ == "__main__":
    unittest.main()
