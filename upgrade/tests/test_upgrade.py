"""Runtime upgrade job (change: runtime-upgrade-pipeline). Every gate,
retry, and report path runs against fakes for git, claude, RPC, and
Telegram; nothing here reaches the network or a real repository."""

import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import allowed_paths as ap  # noqa: E402
import atlas_upgrade as au  # noqa: E402

sys.path.insert(0, os.path.join(au.ROOT, "knowledge"))
import atlas_kb as akb  # noqa: E402
tg = au.tg

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
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
    # The edit prompt lists the tested corpus facts from the live tree
    # (change: kb-battery-honesty): copy the real sources of that list.
    for rel in ("knowledge/benchmark/atlas_kb_battery.py",
                "knowledge/benchmark/retrieval_eval.json",
                "knowledge/polarity-rules.json"):
        target = os.path.join(root, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(os.path.join(REPO, rel), target)


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
        self.timeouts = []
        self.late = []  # files that appear after the scope gate
        self.edit_seconds = self.ingest_seconds = 0
        self.broken = set()
        self.changed = []
        self.branches = set()
        self.edit = self.default_edit
        self.deliver = True
        self.pushed = False
        self.repo_ident = au.AUTHOR_IDENT + " 1 +0000"
        self.live_head = BASE
        self.code_log = ""
        self.gateway = "active"
        self.restarts = 0
        self.activated = []
        self.hermes_home = os.path.join(tmp, "hermes")
        self.added = []  # paths the edit creates (porcelain ??)
        # Release anchors in the clone: tag commits and spec-bump commits.
        self.tags = {live: "a%d" % live, corpus: "a%d" % corpus}
        self.bumps = {}
        self.anchor_spec = {"a%d" % live: live, "a%d" % corpus: corpus}
        self.canary_checks = {name: True for name in au.sandbox.CANARY_CHECKS}
        self.set_gateway()
        self.make_kb()

    # -- world builders ------------------------------------------------------

    def set_gateway(self, age=0.0, **fields):
        state = {"gateway_state": "running", "active_agents": 0,
                 "active_work": None,
                 "updated_at": datetime.datetime.fromtimestamp(
                     self.clock - age, tz=datetime.timezone.utc).isoformat()}
        state.update(fields)
        write(os.path.join(self.hermes_home, "gateway_state.json"),
              json.dumps(state))

    def make_kb(self):
        """A real store with the atlas_kb schema; run R0 (operator) serves
        the corpus the live tree carries."""
        os.makedirs(os.path.dirname(self.kb_db), exist_ok=True)
        connection = sqlite3.connect(self.kb_db)
        connection.executescript(akb.SCHEMA_SQL)
        connection.commit()
        connection.close()
        self.add_run("R0", self.corpus_hashes(), actor="operator")
        self.kb_activate("R0")

    def add_run(self, run_id, files, actor="atlas-upgrade", clean=True):
        connection = sqlite3.connect(self.kb_db)
        connection.execute("DELETE FROM units WHERE run_id = ?", (run_id,))
        connection.execute(
            "INSERT OR REPLACE INTO intake_runs VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "2026-11-%02d" % (len(self.activated) + 1),
             "2026-11-01", "p", "k", json.dumps(
                 {name: {"bytes": 1, "sha256": digest}
                  for name, digest in files.items()})))
        connection.execute(
            "INSERT INTO units (unit_id, run_id, source_file, source_sha256,"
            " heading_path, line_start, line_end, coverage_date, "
            "evidence_state, content) VALUES ('u', ?, 'f', 's', 'h', 1, 1, "
            "'2026-11-01', 'confirmed', 'c')", (run_id,))
        connection.execute(
            "INSERT INTO audit (timestamp, actor, action, detail) VALUES "
            "('t', ?, 'ingest', ?)", (actor, "run %s staged 1 units"
                                      % run_id))
        connection.commit()
        connection.close()
        write(os.path.join(self.root, "var", "knowledge",
                           "validation-report-%s.json" % run_id),
              json.dumps({"secret_scan_findings": [],
                          "duplicate_unit_ids": [] if clean else ["dup"]}))

    def kb_activate(self, run_id):
        connection = sqlite3.connect(self.kb_db)
        connection.execute("UPDATE units SET active = 0")
        connection.execute("UPDATE units SET active = 1 WHERE run_id = ?",
                           (run_id,))
        connection.commit()
        connection.close()
        self.activated.append(run_id)

    def set_corpus(self, digest=None, grounded=None):
        path = os.path.join(self.root, "knowledge", "corpus", "hashes.json")
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if digest is not None:
            manifest["files"] = {"ground-truth.md": digest}
        if grounded is not None:
            manifest["grounded_spec"] = grounded
        write(path, json.dumps(manifest))

    def sleep(self, seconds):
        pass

    def now(self):
        return self.clock

    def live_spec(self):
        if "rpc" in self.broken:
            return {"ok": False, "error": "down"}
        return {"ok": True, "spec_version": self.live}

    def send(self, msg):
        if self.deliver:
            self.sent.append(msg.plain())
        return self.deliver

    def default_edit(self, wt):
        write(os.path.join(wt, "knowledge", "corpus", "SOURCES.md"),
              SOURCES % self.live)
        self.changed.append("knowledge/corpus/SOURCES.md")

    def bwrap_present(self):
        return "bwrap" not in self.broken

    def run(self, cmd, cwd, timeout, env=None):
        self.calls.append(cmd)
        self.timeouts.append(timeout)
        ok = au.Result(0, "", "")
        if cmd[0] == au.sandbox.BWRAP:
            inner = cmd[cmd.index("--") + 1:]
            if au.sandbox.CANARY_PATH in inner:
                return au.Result(0, json.dumps({"checks": self.canary_checks}),
                                 "")
            return self.run(inner, cwd, timeout, env)
        if cmd[0] == "git" and cwd == self.clone:
            return self.clone_git_fake(cmd[1:])
        if cmd[0] == "git":
            return self.git_fake(cmd[1:], cwd, env)
        if cmd[0] == "systemctl":
            if cmd[2] == "is-active":
                return au.Result(0 if self.gateway == "active" else 3,
                                 self.gateway + "\n", "")
            if "restart" in self.broken:
                return au.Result(1, "", "failed")
            self.restarts += 1
            return ok
        if cmd[0] == self.claude:
            if cmd[-1] == "reply ok":
                return au.Result(1, "", "OAuth session expired") \
                    if "smoke" in self.broken \
                    else au.Result(0, "ok", "")
            if "claude" in self.broken:
                return au.Result(124, "", "timed out")
            self.clock += self.edit_seconds
            self.edit(cwd)
            return au.Result(0, "summary of edits", "")
        script = os.path.basename(cmd[1]) if len(cmd) > 1 else ""
        if cmd[1:3] == ["-m", "unittest"]:
            if "late-write" in self.broken:
                self.added.append("livedata/json.py")
            return au.Result(1, "", "FAILED") if "suite" in self.broken else ok
        if script == "atlas_probe.py" and cwd == self.root:
            if "readers" in self.broken:
                return au.Result(1, json.dumps({"ok": False, "failures": [
                    {"item": "Tempo", "reason": "missing"}]}), "")
            if "probe-rpc" in self.broken:
                return au.Result(1, json.dumps({"ok": False, "failures": [],
                                                "error": "down"}), "")
            return au.Result(0, json.dumps({"ok": True, "block": 9000002,
                                            "spec": self.live}), "")
        if script == "atlas_probe.py":
            return au.Result(1, '{"ok": false}', "") \
                if "probe" in self.broken else au.Result(0, '{"ok": true}', "")
        if script == "atlas_live.py":
            return au.Result(0, json.dumps({"block_number": 9000001}), "")
        if script == "atlas_kb.py" and cmd[2] == "ingest":
            self.clock += self.ingest_seconds
            report = {"secret_scan_findings": [],
                      "duplicate_unit_ids": ["dup"] if "ingest" in self.broken
                      else []}
            with open(os.path.join(cwd, "knowledge", "corpus",
                                   "hashes.json"), "r",
                      encoding="utf-8") as handle:
                self.add_run("R1", json.load(handle)["files"])
            write(os.path.join(self.root, "var", "knowledge",
                               "validation-report-R1.json"),
                  json.dumps(report))
            return au.Result(0, "Ingest run R1: 3 units staged", "")
        if script == "atlas_kb.py" and cmd[2] == "activate":
            if "activate" in self.broken:
                return au.Result(1, "", "no")
            self.kb_activate(cmd[cmd.index("--run") + 1])
            return ok
        return ok  # repotrack update, read-knobs

    def clone_git_fake(self, args):
        ok = au.Result(0, "", "")
        if args[0] == "rev-parse":
            spec = int(args[-1][len("refs/tags/v"):].split("^")[0])
            sha = self.tags.get(spec)
            return au.Result(0, sha + "\n", "") if sha else \
                au.Result(1, "", "")
        if args[0] == "log" and "-S" in args:
            spec = int(args[args.index("-S") + 1].split()[1].rstrip(","))
            sha = self.bumps.get(spec)
            return au.Result(0, sha + "\n" if sha else "", "")
        if args[0] == "show":
            sha = args[1].split(":")[0]
            return au.Result(0, "spec_version: %s,\n" % self.anchor_spec.get(
                sha), "")
        if args[0] == "merge-base":
            return au.Result(1 if "anchor-off-head" in self.broken else 0,
                             "", "")
        if args[0] == "log":
            return au.Result(0, "abc1234 bump spec\n", "")
        if args[0] == "diff":
            return au.Result(0, "diff --git a/x b/x\n", "")
        return ok  # archive

    def git_fake(self, args, cwd, env=None):
        ok = au.Result(0, "", "")
        if "git-" + args[0] in self.broken:
            return au.Result(1, "", "%s failed" % args[0])
        if args[0] == "var":
            # The job's own overrides always win; only a bare env shows the
            # repo's identity.
            if env and env.get("GIT_AUTHOR_NAME"):
                return au.Result(0, au.AUTHOR_IDENT + " 1 +0000", "")
            return au.Result(0, self.repo_ident, "")
        if args[0] == "merge-base":
            older, newer = args[2], args[3]
            if (older, newer) == ("HEAD", "origin/main"):
                late = "diverged-late" in self.broken and any(
                    len(c) > 2 and c[2] == "ingest" for c in self.calls)
                return au.Result(1 if "diverged" in self.broken or late
                                 else 0, "", "")
            return au.Result(0 if older in (self.live_head, BASE) else 1,
                             "", "")
        if args[0] == "log" and "--format=%h %s" in args:
            return au.Result(0, self.code_log, "")
        if args[0] == "pull":
            if self.pushed:
                self.live_head = COMMIT
                shutil.copy(os.path.join(self.worktree, "knowledge",
                                         "corpus", "hashes.json"),
                            os.path.join(self.root, "knowledge", "corpus",
                                         "hashes.json"))
            return ok
        if args[0] == "status":
            if cwd == self.root:
                return au.Result(0, " M x" if "dirty" in self.broken else "",
                                 "")
            return au.Result(0, "".join(" M %s\0" % p for p in self.changed)
                             + "".join("?? %s\0" % p for p in self.added),
                             "")
        if args[0] == "diff" and "--cached" in args:
            return au.Result(0, "\0".join(self.changed + self.added
                                          + self.late), "")
        if args[0] == "rev-parse" and args[1] == "--verify":
            return ok if args[-1][len("refs/heads/"):] in self.branches \
                else au.Result(1, "", "")
        if args[0] == "rev-parse":
            if cwd == self.worktree:
                if "moved" in self.broken:
                    return au.Result(0, "d" * 40, "")
                return au.Result(0, COMMIT if "commit" in self.calls_flat()
                                 else BASE, "")
            if args[1] == "HEAD":
                return au.Result(0, self.live_head, "")
            return au.Result(0, COMMIT if self.pushed else BASE, "")
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
        self.assertIn("Atlas updated itself for runtime spec 470",
                      job.sent[0])
        self.assertTrue(job.sent[0].startswith("✅ "))
        self.assertTrue(job.ran(["git", "push", "origin", "HEAD:main"]))

    def test_corpus_equals_live_does_nothing(self):
        job = self.job(live=469)
        self.assertEqual(job.run_once(), 0)
        # Only the read-only live-tree checks of the recovery pass run.
        self.assertEqual({tuple(c[:2]) for c in job.calls},
                         {("git", "status"), ("git", "merge-base")})
        self.assertEqual(job.sent, [])
        self.assertFalse(os.path.exists(job.state_path))

    def test_only_repo_moved_does_nothing(self):
        job = self.job(live=469, clone=470)
        job.run_once()
        self.assertEqual(self.claude_calls(job), [])

    def test_live_spec_unavailable(self):
        # An RPC blip is a handled outcome: exit 0, no page, no OnFailure=
        # (change: alert-delivery-reliability).
        job = self.job()
        job.broken.add("rpc")
        self.assertEqual(job.run_once(), 0)
        self.assertEqual(job.sent, [])

    def test_unexpected_error_exits_non_zero(self):
        job = self.job()

        def crash():
            raise RuntimeError("bug")
        job.corpus_spec = crash
        with self.assertRaises(RuntimeError):
            job.run_once()  # propagates: python exits non-zero

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
        # The model reads the source exported at the live release, never
        # the clone (change: upgrade-sandbox-scope).
        self.assertNotIn(job.clone, cmd)
        self.assertIn(os.path.join(job.var, "source-470"), cmd)
        self.assertEqual(job.calls[-1][0], sys.executable)  # activate last


class GateTest(Base):
    def fails_at(self, gate, prepare):
        job = self.job()
        prepare(job)
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual(state["status"], "retrying")
        self.assertTrue(state["last_error"].startswith(gate + ":"),
                        state["last_error"])
        self.assertFalse(job.pushed)
        self.assertFalse(any(len(c) > 2 and c[2] == "activate"
                             for c in job.calls))
        self.assertEqual(len(job.sent), 1)
        self.assertIn("retrying", job.sent[0])
        self.assertIn("(attempt 1 of 3)", job.sent[0].split("\n")[0])
        # Fixed wording only (change: alert-delivery-reliability).
        self.assertIn(au.GATE_PHRASES[gate], job.sent[0])
        raw = state["last_error"].split(": ", 1)[1].splitlines()[0]
        self.assertNotIn(raw, job.sent[0])
        return job

    def test_raw_auth_error_never_reaches_the_report(self):
        job = self.job()
        state = {"spec": 470, "attempt": 1, "status": "running"}
        job.fail(state, "edit", "Failed to authenticate: OAuth token has "
                                "expired. Authorization: Bearer abcdefgh123")
        self.assertEqual(len(job.sent), 1)
        self.assertNotIn("OAuth", job.sent[0])
        self.assertNotIn("Bearer", job.sent[0])
        tg.assert_sendable(job.sent[0])
        self.assertIn("OAuth", state["last_error"])

    def test_unknown_gate_uses_generic_phrase(self):
        job = self.job()
        state = {"spec": 470, "attempt": 1, "status": "running"}
        job.fail(state, "mystery", "boom")
        self.assertIn("The mystery step failed.", job.sent[0])

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
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("blocked", 1))
        self.assertIn("blocked after the push", job.sent[0])
        self.assertTrue(job.sent[0].startswith("🔴 "))
        self.assertEqual(state["post_push"],
                         {"commit": COMMIT, "run_id": "R1",
                          "gate": "activate"})
        last = job.sent[0].split("\n")[-1]
        self.assertIn("atlas_kb.py activate --run R1", last)
        self.assertNotIn("pull", last)

    def test_readback_mismatch_blocks_before_pull(self):
        job = self.job()
        job.broken.add("readback")
        job.run_once()
        self.assertEqual(job.state()["status"], "blocked")
        self.assertFalse(job.ran(["git", "pull", "--ff-only", "origin",
                                  "main"]))


class DeployKeyTest(Base):
    def test_only_the_push_carries_the_deploy_key(self):
        job = self.job()
        seen = []
        real = job.run

        def spy(cmd, cwd, timeout, env=None):
            seen.append((cmd, (env or {}).get("GIT_SSH_COMMAND")))
            return real(cmd, cwd, timeout, env)

        job.run = spy
        self.assertEqual(job.run_once(), 0)
        keyed = [cmd for cmd, ssh in seen if ssh]
        self.assertEqual(keyed, [["git", "push", "origin", "HEAD:main"]])
        ssh = [s for cmd, s in seen if s][0]
        self.assertIn("-i " + au.DEPLOY_KEY, ssh)
        self.assertIn("IdentitiesOnly=yes", ssh)
        self.assertNotIn("GIT_SSH_COMMAND", job.git_env)


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
        self.assertFalse(any(c[0] in (job.claude, sys.executable)
                             or c[:2] in (["git", "fetch"], ["git", "push"])
                             for c in job.calls[calls:]))  # blocked: no run
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


class FlushTest(Base):
    """C16: a delivered pending report is saved on every path."""

    def test_pending_delivered_on_idle_run_is_saved(self):
        job = self.job(live=469)
        job.save_state({"status": "idle", "spec": 469, "attempt": 1,
                        "reported": [], "pending_report": {
                            "key": "469:1:retrying",
                            "message": {"headline": "late news"}}})
        job.run_once()
        self.assertEqual(len(job.sent), 1)
        state = job.state()
        self.assertNotIn("pending_report", state)
        self.assertIn("469:1:retrying", state["reported"])
        job.run_once()
        self.assertEqual(len(job.sent), 1)

    def test_stale_pending_report_dropped(self):
        job = self.job(live=469)
        job.save_state({"status": "idle", "spec": 469, "attempt": 1,
                        "reported": [], "pending_report": {
                            "key": "468:2:retrying",
                            "message": {"headline": "old news"}}})
        job.run_once()
        self.assertEqual(job.sent, [])
        self.assertNotIn("pending_report", job.state())


class WaitReasonTest(Base):
    """C12, A2: environment preflight uses no attempt."""

    def waits(self, reason, prepare):
        job = self.job()
        prepare(job)
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual((state["status"], state["wait_reason"],
                          state["attempt"]), ("waiting", reason, 0))
        self.assertEqual(self.claude_calls(job), [])
        self.assertFalse(job.pushed)
        self.assertEqual(len(job.sent), 1)
        headline, _meaning, _action = au.WAIT_REASONS[reason]
        self.assertIn(headline, job.sent[0])
        job.clock += 1800
        job.run_once()
        self.assertEqual(len(job.sent), 1)  # one report per reason
        return job

    def test_claude_login_expired(self):
        job = self.waits("auth", lambda j: j.broken.add("smoke"))
        self.assertNotIn("OAuth", job.sent[0])  # fixed wording only

    def test_dirty_live_tree(self):
        self.waits("dirty", lambda j: j.broken.add("dirty"))

    def test_local_commit_in_live_tree(self):
        job = self.waits("diverged", lambda j: j.broken.add("diverged"))
        self.assertTrue(job.ran(["git", "fetch", "origin"]))

    def test_identity_checked_without_overrides(self):
        def wrong(job):
            job.repo_ident = "Atlas <atlas@localhost> 1 +0000"
        self.waits("identity", wrong)

    def test_fetch_failure_is_not_reported_as_divergence(self):
        job = self.job()
        job.broken.add("git-fetch")
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertTrue(state["last_error"].startswith("prepare:"))
        self.assertNotIn(au.WAIT_REASONS["diverged"][0], "".join(job.sent))

    def test_code_pathspec_excludes_corpus_and_docs(self):
        job = self.job()
        job.code_commits(BASE, COMMIT)
        call = [c for c in job.calls if c[:2] == ["git", "log"]][-1]
        for path in ("knowledge/corpus", "docs",
                     "knowledge/supersession-markers.json"):
            self.assertIn(":!" + path, call)

    def test_recovers_and_uses_attempt_one(self):
        job = self.waits("auth", lambda j: j.broken.add("smoke"))
        job.broken.discard("smoke")
        job.run_once()
        state = job.state()
        self.assertEqual((state["status"], state["attempt"]), ("updated", 1))
        self.assertNotIn("wait_reason", state)

    def test_divergence_before_push_fails_at_push(self):
        job = self.job()
        job.broken.add("diverged-late")
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual(state["status"], "retrying")
        self.assertTrue(state["last_error"].startswith("push:"))
        self.assertFalse(job.ran(["git", "push", "origin", "HEAD:main"]))
        self.assertNotIn("post_push", state)


class RecoveryTest(Base):
    """A1: a post-push failure never goes quiet with a stale corpus."""

    def pull_blocked(self):
        job = self.job()
        job.broken.add("git-pull")
        self.assertEqual(job.run_once(), 0)
        return job

    def test_pull_failure_blocks_with_commands(self):
        job = self.pull_blocked()
        state = job.state()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["post_push"],
                         {"commit": COMMIT, "run_id": "R1", "gate": "pull"})
        self.assertIn(au.PULL_CMD, job.sent[0])
        self.assertIn("atlas_kb.py activate --run R1", job.sent[0])
        self.assertEqual(job.activated, ["R0"])

    def test_corpus_catching_up_keeps_the_block(self):
        job = self.pull_blocked()
        job.set_corpus(digest="new", grounded=470)  # rebased by hand
        job.clock += 10 ** 6
        job.run_once()
        state = job.state()
        self.assertEqual(state["status"], "blocked")
        self.assertIn("post_push", state)

    def test_repaired_tree_pulls_activates_and_clears(self):
        job = self.pull_blocked()
        job.broken.discard("git-pull")
        sent = len(job.sent)
        job.run_once()
        state = job.state()
        self.assertEqual(state["status"], "idle")
        self.assertNotIn("post_push", state)
        self.assertEqual(job.live_head, COMMIT)
        self.assertEqual(job.activated, ["R0", "R1"])
        self.assertEqual(len(job.sent), sent + 1)
        self.assertIn("activated the knowledge run", job.sent[-1])
        job.run_once()
        self.assertEqual(len(job.sent), sent + 1)

    def test_diverged_tree_is_not_pulled(self):
        job = self.pull_blocked()
        job.broken.discard("git-pull")
        job.broken.add("diverged")
        job.run_once()
        self.assertEqual(job.state()["status"], "blocked")
        self.assertEqual(job.activated, ["R0"])

    def test_activation_failure_recovers_next_run(self):
        job = self.job()
        job.broken.add("activate")
        job.run_once()
        job.broken.discard("activate")
        job.run_once()
        self.assertEqual(job.state()["status"], "idle")
        self.assertEqual(job.activated, ["R0", "R1"])


class KnowledgeCurrencyTest(Base):
    """A1: the active run must serve the live tree's corpus."""

    def stale(self, prepare=None):
        job = self.job(live=469)
        job.set_corpus(digest="new")
        if prepare:
            prepare(job)
        job.run_once()
        return job

    def test_matching_run_ingested_by_the_job_is_activated(self):
        job = self.stale(lambda j: j.add_run("R5", {"ground-truth.md":
                                                    "new"}))
        self.assertEqual(job.activated, ["R0", "R5"])
        self.assertEqual(len(job.sent), 1)
        self.assertIn("R5", job.sent[0])

    def test_no_candidate_reports_commands_once(self):
        job = self.stale()
        self.assertEqual(job.activated, ["R0"])
        self.assertEqual(len(job.sent), 1)
        self.assertIn("knowledge base is stale", job.sent[0])
        self.assertIn("atlas_kb.py ingest", job.sent[0])
        job.run_once()
        self.assertEqual(len(job.sent), 1)

    def test_operator_run_is_not_self_activated(self):
        job = self.stale(lambda j: j.add_run(
            "R6", {"ground-truth.md": "new"}, actor="operator"))
        self.assertEqual(job.activated, ["R0"])
        self.assertIn("stale", job.sent[0])

    def test_other_corpus_or_rejected_run_is_not_activated(self):
        def runs(job):
            job.add_run("R7", {"ground-truth.md": "other"})
            job.add_run("R8", {"ground-truth.md": "new"}, clean=False)
        job = self.stale(runs)
        self.assertEqual(job.activated, ["R0"])

    def test_dirty_tree_activates_nothing(self):
        job = self.stale(lambda j: (j.add_run("R5", {"ground-truth.md":
                                                     "new"}),
                                    j.broken.add("dirty")))
        self.assertEqual(job.activated, ["R0"])
        self.assertEqual(job.sent, [])


class RestartTest(Base):
    """F2, F3: pulled code reaches the Hermes tools."""

    def upgraded(self, prepare=None, commits=3):
        job = self.job()
        job.code_log = "\n".join("a%03d fix thing %d" % (n, n)
                                 for n in range(commits))
        if prepare:
            prepare(job)
        self.assertEqual(job.run_once(), 0)
        self.assertEqual(job.state()["status"], "updated")
        return job

    def test_updated_lists_code_commits(self):
        job = self.upgraded(commits=12)
        self.assertIn("Code pulled into the live tree:", job.sent[0])
        self.assertIn("a009 fix thing 9", job.sent[0])
        self.assertNotIn("a010 fix thing 10", job.sent[0])
        self.assertIn("and 2 more", job.sent[0])

    def test_idle_gateway_is_restarted(self):
        job = self.upgraded()
        self.assertEqual(job.restarts, 1)
        self.assertNotIn("restart", job.state())
        self.assertEqual(len(job.sent), 1)

    def test_corpus_only_pull_does_not_restart(self):
        job = self.upgraded(commits=0)
        self.assertEqual(job.restarts, 0)
        self.assertNotIn("Code pulled", job.sent[0])
        self.assertFalse(job.ran(["systemctl", "--user", "is-active"]))

    def test_busy_gateway_reports_once_then_restarts_later(self):
        job = self.upgraded(lambda j: j.set_gateway(active_agents=1))
        self.assertEqual(job.restarts, 0)
        self.assertEqual(len(job.sent), 2)
        self.assertIn("needs a Hermes gateway restart", job.sent[1])
        self.assertIn("busy", job.sent[1])
        job.clock += 1800
        job.set_gateway(active_agents=1)
        job.run_once()
        self.assertEqual((job.restarts, len(job.sent)), (0, 2))
        job.set_gateway()
        job.run_once()
        self.assertEqual(job.restarts, 1)
        self.assertNotIn("restart", job.state())
        self.assertEqual(len(job.sent), 2)

    def test_stale_or_missing_gateway_state_is_unsafe(self):
        job = self.upgraded(lambda j: j.set_gateway(age=3600))
        self.assertEqual(job.restarts, 0)
        self.assertIn("stale", job.sent[1])
        os.remove(os.path.join(job.hermes_home, "gateway_state.json"))
        job.state_path = job.state_path  # same state, next run
        job.run_once()
        self.assertEqual(job.restarts, 0)
        self.assertIn("restart", job.state())

    def test_stopped_gateway_is_not_started(self):
        job = self.upgraded(lambda j: setattr(j, "gateway", "inactive"))
        self.assertEqual(job.restarts, 0)
        self.assertIn("not running", job.sent[1])

    def test_restart_failure_keeps_updated(self):
        job = self.upgraded(lambda j: j.broken.add("restart"))
        self.assertEqual(job.state()["status"], "updated")
        self.assertIn("did not bring the gateway back", job.sent[1])
        self.assertIn("restart", job.state())


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
                     "docs/decisions.md"):
            self.assertTrue(ap.is_allowed(path), path)
        for path in ("livedata/atlas_probe.py", "livedata/scale_meta.py",
                     "livedata/atlas_live.py", "livedata/config.json",
                     "livedata/json.py", "livedata/atlas_live_server.py",
                     "livedata/tests/test_gate.py", "knowledge/atlas_kb.py",
                     "docs/runtime-upgrade.md", "AGENTS.md",
                     "upgrade/allowed_paths.py", "upgrade/prompt.md",
                     "livedata/systemd/atlas-probe.service", ".env",
                     "livedata/sub/x.py", "livedata/schemas/a.json",
                     "fleet/atlas_fleet.py"):
            self.assertFalse(ap.is_allowed(path), path)

    def test_site_paths_out_of_scope(self):
        # The upgrade job must never edit the subnt.dev site.
        paths = ["web/package.json", "web/src/app/page.tsx"]
        self.assertEqual(ap.out_of_scope(paths), sorted(paths))

    def test_tool_rules_mirror_lists(self):
        self.assertIn("Edit(docs/decisions.md)", ap.tool_rules())
        self.assertIn("Edit(livedata/**)", ap.tool_denials())
        self.assertFalse(any("livedata" in rule for rule in ap.tool_rules()))
        # Claude Code ignores Write(path) rules; Edit(path) covers Write.
        self.assertFalse([r for r in ap.tool_rules() + ap.tool_denials()
                          if not r.startswith("Edit(")])

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


class TestedFactsPromptTest(Base):
    """change: kb-battery-honesty. The edit session is told which corpus
    facts the knowledge suite tests."""

    def test_lists_every_tested_fact(self):
        sys.path.insert(0, os.path.join(REPO, "knowledge", "benchmark"))
        import atlas_kb_battery as kbb
        text = au.tested_facts(REPO)
        for exchange in kbb.battery():
            if exchange["set"] in kbb.GROUNDED_SETS:
                self.assertIn(exchange["tag"], text)
                for group in exchange["expected"]:
                    for alternate in group:
                        self.assertIn('"%s"' % alternate, text)
        with open(os.path.join(REPO, "knowledge", "benchmark",
                               "retrieval_eval.json"),
                  encoding="utf-8") as handle:
            for item in json.load(handle)["queries"]:
                self.assertIn('"%s"' % item["marker"], text)
        self.assertIn("subnet-lock-not-recycled", text)

    def test_prompt_carries_the_list(self):
        job = self.job()
        job.run_once()
        prompts = [call[-1] for call in self.claude_calls(job)]
        self.assertTrue(prompts)
        self.assertIn("Facts the test suite checks", prompts[0])
        self.assertIn("KB-EX-15", prompts[0])
        self.assertNotIn("$tested_facts", prompts[0])
