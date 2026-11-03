"""Upgrade job sandbox and scope (change: upgrade-sandbox-scope). One
regression test per audit defect: B2 (scope, sandbox, edit reads), A4
(release anchor, citation gate), C17 (run deadline). Fakes come from
test_upgrade; the anchor and canary integration tests use real git and,
when it can start, real bwrap."""

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_upgrade import SOURCES, Base, FakeJob, write  # noqa: F401

import allowed_paths as ap
import atlas_upgrade as au
import sandbox as sb

_HERE = os.path.dirname(os.path.abspath(__file__))
UPGRADE = os.path.dirname(_HERE)


def option(cmd, flag):
    """Values after `flag` up to the next `--` flag."""
    start = cmd.index(flag) + 1
    values = []
    for part in cmd[start:]:
        if part.startswith("--"):
            break
        values.append(part)
    return values


class ScopeTest(Base):
    def fails_at(self, gate, prepare):
        job = self.job()
        prepare(job)
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual(state["status"], "retrying", state)
        self.assertTrue(state["last_error"].startswith(gate + ":"),
                        state["last_error"])
        self.assertFalse(job.pushed)
        self.assertIn(au.GATE_PHRASES[gate], job.sent[0])
        return job

    def test_chain_reader_edit_fails(self):
        def edit(job):
            def change(wt):
                job.default_edit(wt)
                job.changed.append("livedata/atlas_live.py")
            job.edit = change
        job = self.fails_at("scope", edit)
        self.assertIn("livedata/atlas_live.py", job.state()["last_error"])

    def test_new_file_under_an_allowed_path_fails(self):
        def edit(job):
            def change(wt):
                job.default_edit(wt)
                job.added.append("knowledge/corpus/new.md")
            job.edit = change
        job = self.fails_at("scope", edit)
        self.assertIn("only modifications", job.state()["last_error"])

    def test_file_written_after_the_scope_gate_blocks_the_push(self):
        # A gate that writes into the worktree (here: a test run creating
        # livedata/json.py) must not reach the commit.
        job = self.fails_at("scope", lambda j: j.broken.add("late-write"))
        self.assertIn("livedata/json.py", job.state()["last_error"])
        # Only the failed attempt's branch commit, never the upgrade one.
        self.assertFalse(any("chore: ground" in " ".join(c)
                             for c in job.calls))

    def test_staged_file_not_checked_blocks_the_push(self):
        def late(job):
            job.late.append("knowledge/corpus/sneaky.md")
        job = self.fails_at("scope", late)
        self.assertIn("staged files not checked", job.state()["last_error"])

    def test_scope_violations_by_code(self):
        bad = ap.scope_violations([
            (" M", "knowledge/corpus/ground-truth.md"),
            ("??", "knowledge/corpus/x.md"),
            ("R ", "knowledge/corpus/fact-patterns.md"),
            (" D", "docs/decisions.md"),
            (" M", "livedata/config.json")])
        self.assertEqual(len(bad), 4)
        self.assertEqual(ap.scope_violations(
            [(" M", "knowledge/corpus/SOURCES.md"), ("M ", "docs/decisions.md"),
             ("MM", "knowledge/supersession-markers.json")]), [])

    def test_status_entries_keep_codes_and_both_rename_paths(self):
        self.assertEqual(au.status_entries(
            "R  new.md\0old.md\0?? x.py\0 M y.md\0"),
            [("R ", "new.md"), ("R ", "old.md"), ("??", "x.py"),
             (" M", "y.md")])

    def test_import_closure_is_out_of_scope(self):
        # Every repo module the job or the probe imports is outside the
        # edit scope, so the job never runs model-written code.
        script = ("import sys, json; sys.path.insert(0, %r); "
                  "sys.path.insert(0, %r); import atlas_upgrade, "
                  "atlas_probe; print(json.dumps([m.__file__ for m in "
                  "list(sys.modules.values()) if getattr(m, '__file__', "
                  "None)]))" % (UPGRADE, os.path.join(au.ROOT, "livedata")))
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True, check=True)
        repo = [os.path.relpath(path, au.ROOT) for path in json.loads(
            out.stdout) if os.path.abspath(path).startswith(au.ROOT + os.sep)]
        self.assertIn("livedata/atlas_live.py", repo)
        self.assertIn("repotrack/atlas_repo.py", repo)
        for path in repo:
            self.assertFalse(ap.is_allowed(path), path)
        # The check has teeth: the old scope admitted the chain readers.
        old = ap._regex("livedata/*.py")
        self.assertTrue(any(old.match(path) for path in repo))

    def test_prompt_names_no_livedata_path_as_editable(self):
        self.assertFalse(any("livedata" in p for p in ap.ALLOWED))
        with open(os.path.join(UPGRADE, "prompt.md"), "r",
                  encoding="utf-8") as handle:
            prompt = handle.read()
        self.assertNotIn("Fix `livedata/`", prompt)
        self.assertIn("out of scope", prompt)


class PreflightTest(Base):
    def waits(self, broken, reason):
        job = self.job()
        job.broken.add(broken)
        self.assertEqual(job.run_once(), 0)
        state = job.state()
        self.assertEqual((state["status"], state["attempt"],
                          state.get("wait_reason")), ("waiting", 0, reason))
        self.assertEqual(self.claude_calls(job), [])
        self.assertEqual(len(job.sent), 1)
        self.assertIn(au.WAIT_REASONS[reason][0], job.sent[0])
        job.run_once()
        self.assertEqual(len(job.sent), 1)  # once per spec and reason
        return job

    def test_drifted_readers_wait_for_the_operator(self):
        self.waits("readers", "readers")

    def test_probe_rpc_failure_waits(self):
        self.waits("probe-rpc", "probe")

    def test_probe_block_reaches_the_prompt(self):
        job = self.job()
        job.run_once()
        prompt = self.claude_calls(job)[0][-1]
        self.assertIn("9000002", prompt)


class AnchorFakeTest(Base):
    def test_diff_ends_at_the_live_tag(self):
        job = self.job()
        job.run_once()
        diffs = [c for c in job.calls if c[:2] == ["git", "diff"]
                 and "--cached" not in c]
        self.assertIn(["git", "diff", "a469", "a470"], diffs)
        self.assertFalse(any("HEAD" in c for c in diffs))
        prompt = self.claude_calls(job)[0][-1]
        self.assertIn("tag v470", prompt)

    def test_spec_bump_commit_when_no_tag(self):
        job = self.job()
        del job.tags[470]
        job.bumps[470] = "b470"
        job.anchor_spec["b470"] = 470
        job.run_once()
        self.assertEqual(job.state()["status"], "updated")
        self.assertIn("spec-bump commit", self.claude_calls(job)[0][-1])

    def test_no_anchor_waits_and_never_diffs_to_head(self):
        job = self.job()
        del job.tags[470]
        job.run_once()
        self.assertEqual(job.state()["wait_reason"], "anchor")
        self.assertEqual(job.state()["attempt"], 0)
        self.assertFalse(any(c[:2] == ["git", "diff"] for c in job.calls))
        self.assertEqual(self.claude_calls(job), [])

    def test_anchor_stating_another_spec_waits(self):
        job = self.job()
        job.anchor_spec["a470"] = 471
        job.run_once()
        self.assertEqual(job.state()["wait_reason"], "anchor")

    def test_anchor_off_head_waits(self):
        job = self.job()
        job.broken.add("anchor-off-head")
        job.run_once()
        self.assertEqual(job.state()["wait_reason"], "anchor")

    def test_job_and_repotrack_agree_on_the_clone_path(self):
        # The child update skips the lock only when LOCK_HELD_ENV equals
        # its own resolved clone path; a mismatch would make it wait on its
        # parent until killed.
        arp = au.arp
        configured = arp._resolve(au.ROOT, arp.load_config(
            arp.CONFIG_FILE)["clone_dir"])
        self.assertEqual(os.path.abspath(au.Job().clone),
                         os.path.abspath(configured))

    def test_update_runs_under_the_clone_lock(self):
        job = self.job()
        job.run_once()
        update = [i for i, c in enumerate(job.calls)
                  if c[-1:] == ["update"]][0]
        self.assertTrue(os.path.exists(au.arp.clone_lock_path(job.clone)))
        # Anchors are read after the update, inside the same lock.
        self.assertTrue(any(c[:2] == ["git", "rev-parse"] and "refs/tags"
                            in c[-1] for c in job.calls[update:]))


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c",
                           "user.email=t@t", "-c", "commit.gpgsign=false",
                           "-c", "tag.gpgsign=false"] + list(args), cwd=cwd,
                          capture_output=True, text=True, check=True
                          ).stdout.strip()


class AnchorGitTest(unittest.TestCase):
    """Real git: tags v1 and v3, spec 2 only as a bump commit, HEAD at 4
    with a file added after v3."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        root = os.path.join(self.tmp, "atlas")
        self.job = au.Job(root=root, worktree=os.path.join(self.tmp, "wt"))
        clone = self.job.clone
        os.makedirs(os.path.join(clone, "runtime", "src"))
        git(clone, "init", "-q", "-b", "main")
        self.sha = {}
        for spec in (1, 2, 3, 4):
            write(os.path.join(clone, "runtime", "src", "lib.rs"),
                  "spec_version: %d,\n" % spec)
            if spec == 4:
                write(os.path.join(clone, "unshipped.rs"), "fn x() {}\n")
            git(clone, "add", "-A")
            git(clone, "commit", "-q", "-m", "bump spec %d" % spec)
            self.sha[spec] = git(clone, "rev-parse", "HEAD")
            if spec in (1, 3):
                git(clone, "tag", "v%d" % spec)

    def test_tag_anchor(self):
        commit, kind = self.job.anchor(3)
        self.assertEqual((commit, kind), (self.sha[3], "tag v3"))

    def test_bump_commit_anchor(self):
        commit, kind = self.job.anchor(2)
        self.assertEqual(commit, self.sha[2])
        self.assertIn("spec-bump", kind)

    def test_missing_anchor_waits(self):
        with self.assertRaises(au.Waiting) as caught:
            self.job.anchor(9)
        self.assertEqual(caught.exception.reason, "anchor")

    def test_export_holds_nothing_after_the_anchor(self):
        ctx = {"spec": 3, "corpus": 1}
        self.job.prepare_source(ctx)
        source = ctx["source_dir"]
        with open(os.path.join(source, "runtime", "src", "lib.rs")) as fh:
            self.assertEqual(fh.read(), "spec_version: 3,\n")
        self.assertFalse(os.path.exists(os.path.join(source, "unshipped.rs")))
        self.assertNotIn("bump spec 4", ctx["bump_log"])
        with open(ctx["diff_file"]) as fh:
            self.assertNotIn("unshipped", fh.read())
        # Reused while the anchor is unchanged.
        calls = []
        real = self.job.run
        self.job.run = lambda *a, **k: calls.append(a[0]) or real(*a, **k)
        self.job.export_source(3, self.sha[3])
        self.assertFalse(any(c[:2] == ["git", "archive"] for c in calls))


class SandboxTest(Base):
    def test_gates_run_inside_the_sandbox(self):
        job = self.job()
        job.run_once()
        wrapped = [c for c in job.calls if c[0] == sb.BWRAP]
        suites = [c for c in wrapped if "unittest" in c]
        probes = [c for c in wrapped if any(p.endswith("atlas_probe.py")
                                            for p in c)]
        canaries = [c for c in wrapped if sb.CANARY_PATH in c]
        self.assertTrue(suites and probes)
        self.assertEqual(len(canaries), 2)
        for cmd in suites:
            self.assertNotIn("--share-net", cmd)
        for cmd in probes:
            self.assertIn("--share-net", cmd)
        # No suite or worktree probe ever runs outside bwrap.
        bare = [c for c in job.calls if c[0] == sys.executable and (
            "unittest" in c or any(p.startswith(job.worktree) and
                                   p.endswith("atlas_probe.py") for p in c))]
        self.assertEqual(len(bare), len(suites) + len(probes))

    def test_failed_canary_check_fails_closed(self):
        job = self.job()
        job.canary_checks["secrets_absent"] = False
        job.run_once()
        self.assertTrue(job.state()["last_error"].startswith("sandbox:"))
        self.assertIn("secrets_absent", job.state()["last_error"])
        self.assertFalse(any("unittest" in c for c in job.calls))
        self.assertFalse(job.pushed)

    def test_missing_bwrap_fails_closed(self):
        job = self.job()
        job.broken.add("bwrap")
        job.run_once()
        self.assertTrue(job.state()["last_error"].startswith("sandbox:"))
        self.assertFalse(any("unittest" in c for c in job.calls))

    def test_canary_output_must_name_every_check(self):
        self.assertEqual(sb.canary_failures("not json"),
                         ["canary output unreadable"])
        partial = {name: True for name in sb.CANARY_CHECKS[1:]}
        self.assertEqual(sb.canary_failures(json.dumps({"checks": partial})),
                         [sb.CANARY_CHECKS[0]])

    def test_builder_hides_home_run_and_env(self):
        cmd = sb.sandbox_cmd("/home/pi/atlas-upgrade", "/home/pi/atlas-upgrade",
                             ["python3", "x"], home="/home/pi")
        self.assertIn("--clearenv", cmd)
        self.assertIn("--unshare-all", cmd)
        self.assertNotIn("--share-net", cmd)
        pairs = list(zip(cmd, cmd[1:]))
        self.assertIn(("--tmpfs", "/run"), pairs)
        self.assertIn(("--tmpfs", "/home"), pairs)
        binds = [cmd[i + 1] for i, part in enumerate(cmd)
                 if part in ("--bind", "--ro-bind")]
        self.assertNotIn("--bind", cmd)  # nothing is bound writable
        for path in binds:
            self.assertFalse(path.startswith(("/home/pi/.", "/run", "/var")),
                             path)
        self.assertIn("/home/pi/atlas-upgrade", binds)
        self.assertIn("--share-net", sb.sandbox_cmd("/w", "/w", ["x"],
                                                    network=True))

    def test_real_canary_through_the_builder(self):
        # Integration: the real canary in the real sandbox, when bwrap can
        # start here (it cannot in every CI or nested sandbox).
        if not os.access(sb.BWRAP, os.X_OK):
            self.skipTest("bwrap not installed")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        worktree = os.path.join(tmp, "wt")
        os.makedirs(worktree)
        secret = os.path.join(tmp, "secret.env")  # outside the worktree
        write(secret, "x")
        cmd = sb.canary_cmd(sys.executable, os.path.join(
            UPGRADE, "sandbox_canary.py"), worktree, False, [secret])
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=60)
        if result.stderr.startswith("bwrap:"):
            self.skipTest("bwrap cannot start here: %s" % result.stderr[:80])
        self.assertEqual(sb.canary_failures(result.stdout), [], result.stdout)


class EditReadsTest(Base):
    def test_reads_are_path_scoped_with_secret_denials(self):
        job = self.job()
        job.run_once()
        cmd = self.claude_calls(job)[0]
        allowed = option(cmd, "--allowedTools")
        for bare in ("Read", "Grep", "Glob"):
            self.assertNotIn(bare, allowed)
        # Claude Code ignores Grep(path) and Glob(path) rules; Read(path)
        # rules cover every file-reading tool.
        self.assertFalse([r for r in allowed + option(cmd, "--disallowedTools")
                          if r.startswith(("Grep(", "Glob("))])
        reads = [rule for rule in allowed if rule.startswith("Read(")]
        self.assertEqual(sorted(reads), sorted(
            "Read(/%s/**)" % os.path.abspath(d) for d in (
                job.worktree, os.path.join(job.var, "source-470"), job.var)))
        denied = option(cmd, "--disallowedTools")
        for rule in ("Read(~/.hermes/**)", "Read(~/.ssh/**)",
                     "Read(~/.claude/**)", "Read(**/.env*)", "Bash",
                     "WebFetch"):
            self.assertIn(rule, denied)


class CitationTest(Base):
    def test_historical_upgrades(self):
        with open(os.path.join(_HERE, "fixtures", "citation-history.json"),
                  "r", encoding="utf-8") as handle:
            cases = json.load(handle)["cases"]
        self.assertEqual(len(cases), 12)
        for case in cases:
            bad = au.citation_violations(
                case["added"], case["live"], set(case["run_blocks"]),
                set(case["base_blocks"]))
            if case["live"] == 472:
                # It named its clone at spec 473; the new prompt gives no
                # source past live, so this is now a violation.
                self.assertTrue(bad)
                for line in bad:
                    self.assertIn("spec 473 is past live 472", line)
            else:
                self.assertEqual(bad, [], case["commit"])
            # Each run cited exactly its two reads (knobs and probe).
            self.assertEqual(len(case["run_blocks"]), 2, case["commit"])

    def edit_line(self, line):
        job = self.job()

        def edit(wt):
            job.default_edit(wt)
            path = os.path.join(wt, "knowledge", "corpus", "ground-truth.md")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            job.changed.append("knowledge/corpus/ground-truth.md")
        job.edit = edit
        job.run_once()
        return job

    def test_invented_block_fails(self):
        job = self.edit_line("Verified at finalized block 9999999.")
        self.assertTrue(job.state()["last_error"].startswith("citation:"))
        self.assertIn(au.GATE_PHRASES["citation"], job.sent[0])
        self.assertFalse(job.pushed)

    def test_future_spec_fails(self):
        job = self.edit_line("Spec 471 is live on Finney.")
        self.assertTrue(job.state()["last_error"].startswith("citation:"))

    def test_run_blocks_pass(self):
        job = self.edit_line("Knobs at finalized block 9000001; probe clean "
                             "at block 9,000,002.")
        self.assertEqual(job.state()["status"], "updated")

    def test_block_parsing(self):
        self.assertEqual(au.cited_blocks(
            "blocks 9142678, 9142723 and 9142874; 1,296,000 blocks"),
            {9142678, 9142723, 9142874})


class DeadlineTest(Base):
    def test_slow_edit_fails_before_the_push(self):
        job = self.job()
        job.edit_seconds = 36 * 60  # 50 min budget, 15 min reserve
        job.run_once()
        state = job.state()
        self.assertTrue(state["last_error"].startswith("deadline:"),
                        state["last_error"])
        self.assertIn(au.GATE_PHRASES["deadline"], job.sent[0])
        self.assertFalse(job.pushed)

    def test_push_needs_its_reserve(self):
        job = self.job()
        job.ingest_seconds = 40 * 60
        job.run_once()
        self.assertTrue(job.state()["last_error"].startswith("deadline:"))
        self.assertFalse(job.pushed)

    def test_pre_push_timeouts_are_capped(self):
        job = self.job()
        job.edit_seconds = 30 * 60
        job.run_once()
        self.assertEqual(job.state()["status"], "updated")
        # After a 30 min edit only 5 min remain before the reserve.
        claude = [i for i, c in enumerate(job.calls) if c[0] == job.claude
                  and c[-1] != "reply ok"][0]
        later = job.timeouts[claude + 1:]
        self.assertTrue(later)
        cap = au.RUN_BUDGET - au.PUSH_RESERVE - 30 * 60
        self.assertTrue(any(t <= cap for t in later))

    def test_budget_fits_the_unit_timeout(self):
        unit = configparser.ConfigParser(strict=False)
        unit.read(os.path.join(UPGRADE, "systemd", "atlas-upgrade.service"))
        value = unit["Service"]["TimeoutStartSec"]
        minutes = int(re.fullmatch(r"(\d+)min", value).group(1))
        self.assertLessEqual(au.RUN_BUDGET + 300, minutes * 60)


if __name__ == "__main__":
    unittest.main()
