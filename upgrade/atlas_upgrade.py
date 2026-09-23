#!/usr/bin/env python3
"""Atlas runtime upgrade job (change: runtime-upgrade-pipeline).

When the live Finney runtime spec moves past the corpus spec, this job
brings Atlas up to date on the Pi without an operator:

    detect, preflight, prepare, edit, goal, scope, test, probe, ingest,
    push, activate, report

It runs from the live tree (~/atlas, trusted origin/main code) on a timer.
The model step is one headless `claude -p` session in a separate worktree
(~/atlas-upgrade); it only edits files. Every gate is enforced here, in
code. Nothing reaches main unless every gate passes, and the corpus is
activated only after the push is confirmed on the remote.

    python3 upgrade/atlas_upgrade.py run [--dry-run]
    python3 upgrade/atlas_upgrade.py clear --spec <n>
    python3 upgrade/atlas_upgrade.py status

State lives in var/upgrade/state.json (atomic writes); one run at a time
holds an exclusive flock on var/upgrade/lock.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import fcntl
import hashlib
import json
import os
import re
import string
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_UPGRADE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_UPGRADE_DIR)
sys.path.insert(0, _UPGRADE_DIR)
sys.path.insert(0, os.path.join(ROOT, "livedata"))

import allowed_paths  # noqa: E402
import atlas_live as al  # noqa: E402
import atlas_probe  # noqa: E402

AUTHOR_NAME = "vaNlabs"
AUTHOR_EMAIL = "vanlabs@pm.me"
AUTHOR_IDENT = "%s <%s>" % (AUTHOR_NAME, AUTHOR_EMAIL)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (3600, 4 * 3600)  # after attempt 1, after attempt 2
MAX_TURNS = 60
TIMEOUT = {"git": 120, "rpc": 120, "repotrack": 600, "smoke": 120,
           "claude": 25 * 60, "suite": 5 * 60, "probe": 180, "ingest": 300}
# A failure after the push has landed cannot be fixed by another attempt:
# main already carries the grounded corpus. It blocks at once.
POST_PUSH_GATES = ("readback", "pull", "activate")
MODEL_TOOLS = "Read,Grep,Glob,Edit,Write"

SPEC_RE = re.compile(r"spec_version:\s*(\d+)")
GROUNDED_RE = re.compile(r"Grounded at\s*\|\s*Finney `spec_version` "
                         r"\*\*(\d+)\*\*")
INGEST_RUN_RE = re.compile(r"Ingest run (\S+):")

Result = collections.namedtuple("Result", "rc out err")


class StepFailed(Exception):
    def __init__(self, gate: str, detail: str) -> None:
        super().__init__("%s: %s" % (gate, detail))
        self.gate = gate
        self.detail = detail


def _tail(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _utc(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def status_paths(porcelain_z: str) -> List[str]:
    """Paths from `git status --porcelain=v1 -z -uall`. A rename or copy
    reports both the new and the old path."""
    paths: List[str] = []
    tokens = porcelain_z.split("\0")
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            paths.append(tokens[index])
            index += 1
    return paths


def test_dirs(tree: str) -> List[str]:
    """Every `tests` directory that holds Python tests, outermost only."""
    found: List[str] = []
    for current, dirs, files in os.walk(tree):
        rel = os.path.relpath(current, tree)
        if rel.split(os.sep)[0] in (".git", "var", "openspec", "triage"):
            dirs[:] = []
            continue
        if os.path.basename(current) == "tests":
            dirs[:] = []
            if any(name.startswith("test_") and name.endswith(".py")
                   for name in files):
                found.append(current)
    return sorted(found)


def regenerate_hashes(corpus_dir: str, grounded_spec: int,
                      today: str) -> None:
    """Rewrite hashes.json: sha256 per manifest file over LF-normalized
    bytes (the rule load_corpus verifies), dates, and grounded_spec."""
    path = os.path.join(corpus_dir, "hashes.json")
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for name in manifest["files"]:
        with open(os.path.join(corpus_dir, name), "rb") as handle:
            raw = handle.read().replace(b"\r\n", b"\n")
        manifest["files"][name] = hashlib.sha256(raw).hexdigest()
    manifest.update(sync_date=today, coverage_date=today,
                    grounded_spec=grounded_spec)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")


class Job:
    """One upgrade job. `run`, `live_spec`, `send`, and `now` are the seams
    the tests replace; everything else is the real logic."""

    def __init__(self, root: str = ROOT, worktree: Optional[str] = None,
                 dry_run: bool = False) -> None:
        self.root = root
        self.worktree = (worktree or os.environ.get("ATLAS_UPGRADE_WORKTREE")
                         or os.path.join(os.path.dirname(root),
                                         "atlas-upgrade"))
        self.var = os.path.join(root, "var", "upgrade")
        self.clone = os.path.join(root, "var", "repotrack", "subtensor")
        self.kb_db = os.path.join(root, "var", "knowledge", "knowledge.db")
        self.claude = os.environ.get("ATLAS_CLAUDE_BIN", "claude")
        self.dry_run = dry_run
        self.state_path = os.path.join(
            self.var, "dry-run-state.json" if dry_run else "state.json")
        self.git_env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR_NAME,
                            GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
                            GIT_COMMITTER_NAME=AUTHOR_NAME,
                            GIT_COMMITTER_EMAIL=AUTHOR_EMAIL)

    # -- seams --------------------------------------------------------------

    def now(self) -> float:
        return time.time()

    def run(self, cmd: List[str], cwd: str, timeout: int,
            env: Optional[Dict[str, str]] = None) -> Result:
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Result(124, "", "timed out after %ds" % timeout)
        except OSError as exc:
            return Result(127, "", str(exc))
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def live_spec(self) -> Dict[str, Any]:
        return al.read_live_spec(al.load_config())

    def send(self, text: str) -> bool:
        if self.dry_run:
            print("[dry-run report] " + text)
            return True
        return atlas_probe.telegram_send(text)

    # -- helpers ------------------------------------------------------------

    def git(self, gate: str, cwd: str, *args: str) -> str:
        result = self.run(["git"] + list(args), cwd, TIMEOUT["git"],
                          self.git_env)
        if result.rc != 0:
            raise StepFailed(gate, "git %s: %s" % (
                args[0], _tail(result.err or result.out)))
        return result.out.rstrip("\n")  # porcelain lines lead with a space

    def py(self, gate: str, cwd: str, script: str, *args: str,
           timeout: int, ok: Tuple[int, ...] = (0,)) -> Result:
        result = self.run([sys.executable, script] + list(args), cwd,
                          timeout)
        if result.rc not in ok:
            raise StepFailed(gate, "%s: %s" % (
                os.path.basename(script), _tail(result.err or result.out)))
        return result

    def load_state(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {"status": "idle"}

    def save_state(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = self.now()
        os.makedirs(self.var, exist_ok=True)
        tmp = self.state_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, self.state_path)

    def corpus_spec(self) -> Optional[int]:
        path = os.path.join(self.root, "knowledge", "corpus", "hashes.json")
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle).get("grounded_spec")
        return value if isinstance(value, int) else None

    def clone_spec(self) -> Optional[int]:
        try:
            with open(os.path.join(self.clone, "runtime", "src", "lib.rs"),
                      "r", encoding="utf-8") as handle:
                match = SPEC_RE.search(handle.read(20000))
        except OSError:
            return None
        return int(match.group(1)) if match else None

    # -- reporting ----------------------------------------------------------

    def report(self, state: Dict[str, Any], kind: str, text: str) -> None:
        """Exactly one delivery per (spec, attempt, outcome). An undelivered
        report is kept and retried at the start of the next run."""
        key = "%s:%s:%s" % (state.get("spec"), state.get("attempt", 0), kind)
        reported = state.setdefault("reported", [])
        if key in reported:
            return
        if self.send(text):
            reported.append(key)
            del reported[:-20]
        else:
            state["pending_report"] = {"key": key, "text": text}

    def flush_pending(self, state: Dict[str, Any]) -> None:
        pending = state.get("pending_report")
        if pending and self.send(pending["text"]):
            state.setdefault("reported", []).append(pending["key"])
            state.pop("pending_report")

    def fail(self, state: Dict[str, Any], gate: str, detail: str,
             stalled: bool = False) -> None:
        """Record a failed attempt: retry with backoff, or block after the
        last attempt. An interrupted run reports `stalled` in place of the
        `retrying` or `blocked` report for that attempt."""
        attempt = int(state.get("attempt", 0))
        spec = state.get("spec")
        blocked = gate in POST_PUSH_GATES or attempt >= MAX_ATTEMPTS
        state.update(status="blocked" if blocked else "retrying",
                     last_error="%s: %s" % (gate, _tail(detail, 600)),
                     step=None)
        lines = ["Atlas • runtime upgrade %s: spec %s, attempt %d failed "
                 "at %s" % ("stalled" if stalled else state["status"],
                            spec, attempt, gate), _tail(detail, 600)]
        if blocked:
            lines.append("Blocked. Branch %s kept. Release with: python3 "
                         "upgrade/atlas_upgrade.py clear --spec %s"
                         % (state.get("branch"), spec))
        else:
            state["next_attempt_at"] = (
                self.now() + BACKOFF_SECONDS[attempt - 1])
            lines.append("Next attempt %s." % _utc(state["next_attempt_at"]))
        self.report(state, "stalled" if stalled else state["status"],
                    "\n".join(lines))

    # -- the run ------------------------------------------------------------

    def run_once(self) -> int:
        os.makedirs(self.var, exist_ok=True)
        with open(os.path.join(self.var, "lock"), "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("another upgrade run holds the lock")
                return 0
            return self._run_locked()

    def _run_locked(self) -> int:
        state = self.load_state()
        self.flush_pending(state)
        if state.get("status") == "running":
            # We hold the lock, so no live run owns this state.
            self.keep_branch()
            self.fail(state, "interrupted", "run interrupted at step %s"
                      % state.get("step"), stalled=True)
            self.save_state(state)

        live = self.live_spec()
        if not live.get("ok"):
            print("live spec unavailable: %s" % live.get("error"))
            return 1
        spec = live["spec_version"]
        corpus = self.corpus_spec()
        machinery_check = self.dry_run and spec == corpus
        if spec == corpus and not machinery_check:
            if state.get("spec") == spec and state.get("status") != "idle":
                state["status"] = "idle"
                self.save_state(state)
            return 0

        if state.get("spec") != spec:
            # A newer live spec supersedes; old branches are kept.
            state = {"status": "idle", "spec": spec, "attempt": 0,
                     "reported": state.get("reported", []),
                     **({"pending_report": state["pending_report"]}
                        if "pending_report" in state else {})}
        if state["status"] == "blocked":
            self.save_state(state)
            return 0
        if (state["status"] == "retrying"
                and self.now() < state.get("next_attempt_at", 0)):
            self.save_state(state)
            return 0
        return self._attempt(state, spec, corpus, machinery_check)

    def _attempt(self, state: Dict[str, Any], spec: int,
                 corpus: Optional[int], machinery_check: bool) -> int:
        # The clone must cover the live spec before any attempt is used.
        self.run([sys.executable, os.path.join(
            self.root, "repotrack", "atlas_repo.py"), "update"],
            self.root, TIMEOUT["repotrack"])
        clone = self.clone_spec()
        if clone is None or clone < spec:
            state.update(status="waiting", clone_spec=clone)
            self.report(state, "waiting",
                        "Atlas • runtime upgrade waiting: live spec %d, "
                        "subtensor clone at spec %s. No attempt used; "
                        "checking again each run." % (spec, clone))
            self.save_state(state)
            return 0

        state.update(status="running", attempt=int(state["attempt"]) + 1,
                     started_at=self.now(), last_error=None, step=None,
                     clone_spec=clone)
        ctx: Dict[str, Any] = {"spec": spec, "corpus": corpus,
                               "clone": clone}
        steps = [("preflight", self.step_preflight),
                 ("prepare", self.step_prepare)]
        if not machinery_check:
            steps += [("edit", self.step_edit), ("goal", self.step_goal),
                      ("scope", self.step_scope)]
        steps += [("test", self.step_test), ("probe", self.step_probe)]
        if not self.dry_run:
            steps += [("ingest", self.step_ingest),
                      ("push", self.step_push),
                      ("activate", self.step_activate)]
        try:
            for name, step in steps:
                state["step"] = name
                self.save_state(state)
                step(state, ctx)
        except StepFailed as exc:
            self.keep_branch()
            self.fail(state, exc.gate, exc.detail)
            self.save_state(state)
            return 1

        state.update(status="updated", step=None, commit=ctx.get("commit"))
        if self.dry_run:
            self.report(state, "updated", "Atlas • runtime upgrade dry run "
                        "passed every gate for spec %d (no push, no "
                        "activate)." % spec)
        else:
            self.report(state, "updated",
                        "Atlas • runtime upgrade: updated to spec %d\n"
                        "commit %s on main, corpus run %s active\n%s"
                        % (spec, ctx["commit"][:12], ctx["run_id"],
                           _tail(ctx.get("summary", ""), 1200)))
        self.save_state(state)
        return 0

    # -- steps --------------------------------------------------------------

    def step_preflight(self, state: Dict[str, Any],
                       ctx: Dict[str, Any]) -> None:
        ident = self.git("preflight", self.root, "var", "GIT_AUTHOR_IDENT")
        if not ident.startswith(AUTHOR_IDENT + " "):
            raise StepFailed("preflight", "author is %r, not %s"
                             % (ident.rsplit(">", 1)[0] + ">", AUTHOR_IDENT))
        dirty = self.git("preflight", self.root, "status", "--porcelain")
        if dirty:
            raise StepFailed("preflight", "live tree has uncommitted "
                             "changes: %s" % _tail(dirty, 200))
        smoke = self.run([self.claude, "-p", "--restricted",
                          "--strict-mcp-config", "--max-turns", "1",
                          "--tools", "", "--", "reply ok"],
                         self.root, TIMEOUT["smoke"])
        if smoke.rc != 0:
            raise StepFailed("preflight", "claude auth: %s"
                             % _tail(smoke.err or smoke.out, 200))

    def branch_name(self, spec: int, attempt: int) -> str:
        base = "upgrade/spec-%d-a%d" % (spec, attempt)
        name, n = base, 1
        while self.run(["git", "rev-parse", "--verify", "--quiet",
                        "refs/heads/" + name], self.root,
                       TIMEOUT["git"]).rc == 0:
            n += 1
            name = "%s-r%d" % (base, n)  # a cleared spec reuses a number
        return name

    def step_prepare(self, state: Dict[str, Any],
                     ctx: Dict[str, Any]) -> None:
        self.git("prepare", self.root, "fetch", "origin")
        ctx["base"] = self.git("prepare", self.root, "rev-parse",
                               "origin/main")
        if os.path.exists(self.worktree):
            # The old attempt's edits were committed to its branch.
            self.git("prepare", self.root, "worktree", "remove", "--force",
                     self.worktree)
        self.git("prepare", self.root, "worktree", "prune")
        branch = self.branch_name(ctx["spec"], state["attempt"])
        state["branch"] = branch
        self.git("prepare", self.root, "worktree", "add", "-b", branch,
                 self.worktree, ctx["base"])

    def keep_branch(self) -> None:
        """Commit a failed attempt's edits to its branch (never pushed)."""
        if not os.path.isdir(self.worktree):
            return
        try:
            if self.git("keep", self.worktree, "status", "--porcelain"):
                self.git("keep", self.worktree, "add", "-A")
                self.git("keep", self.worktree, "commit", "-q", "-m",
                         "wip: failed upgrade attempt")
        except StepFailed as exc:
            print("could not keep the attempt's edits: %s" % exc)

    def spec_bump(self, ctx: Dict[str, Any]) -> Tuple[str, str]:
        """(commit log, diff file) for the spec bump in the clone. The range
        runs from the commit that introduced the corpus spec to HEAD; the
        last 50 commits when that commit cannot be found."""
        found = self.run(["git", "log", "--reverse", "--format=%H", "-S",
                          "spec_version: %s," % ctx["corpus"], "--",
                          "runtime/src/lib.rs"], self.clone, TIMEOUT["git"])
        start = found.out.split()[0] if found.rc == 0 and found.out else None
        span = ["%s..HEAD" % start] if start else ["-n", "50"]
        log = self.run(["git", "log", "--oneline", "--no-decorate"] + span,
                       self.clone, TIMEOUT["git"])
        diff = self.run(["git", "diff", start, "HEAD"] if start else
                        ["git", "log", "-p", "-n", "50"],
                        self.clone, TIMEOUT["git"])
        path = os.path.join(self.var, "spec-%d.diff" % ctx["spec"])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(diff.out)
        return _tail(log.out, 6000), path

    def step_edit(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        live_py = os.path.join(self.root, "livedata", "atlas_live.py")
        probe_py = os.path.join(self.root, "livedata", "atlas_probe.py")
        knobs = self.py("edit", self.root, live_py, "read-knobs",
                        timeout=TIMEOUT["rpc"])
        probe = self.py("edit", self.root, probe_py, "check",
                        timeout=TIMEOUT["probe"], ok=(0, 1))
        bump_log, diff_file = self.spec_bump(ctx)
        with open(os.path.join(_UPGRADE_DIR, "prompt.md"), "r",
                  encoding="utf-8") as handle:
            template = string.Template(handle.read())
        prompt = template.substitute(
            live_spec=ctx["spec"], corpus_spec=ctx["corpus"],
            clone_dir=self.clone, clone_spec=ctx["clone"],
            bump_log=bump_log, diff_file=diff_file,
            knobs=knobs.out.strip(), probe=probe.out.strip(),
            allowed="\n".join("- `%s`" % p for p in allowed_paths.ALLOWED))
        cmd = ([self.claude, "-p", "--restricted", "--strict-mcp-config",
                "--max-turns", str(MAX_TURNS), "--tools", MODEL_TOOLS,
                "--add-dir", self.clone, self.var,
                "--allowedTools", "Read", "Grep", "Glob"]
               + allowed_paths.tool_rules()
               + ["--disallowedTools", "WebFetch", "WebSearch"]
               + allowed_paths.tool_denials() + ["--", prompt])
        result = self.run(cmd, self.worktree, TIMEOUT["claude"])
        if result.rc != 0:
            raise StepFailed("edit", "claude exited %d: %s" % (
                result.rc, _tail(result.err or result.out)))
        ctx["summary"] = result.out.strip()

    def changed_paths(self, gate: str) -> List[str]:
        return status_paths(self.git(gate, self.worktree, "status",
                                     "--porcelain=v1", "-z", "-uall"))

    def step_goal(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        if not self.changed_paths("goal"):
            raise StepFailed("goal", "the session changed no file")
        corpus_dir = os.path.join(self.worktree, "knowledge", "corpus")
        with open(os.path.join(corpus_dir, "SOURCES.md"), "r",
                  encoding="utf-8") as handle:
            match = GROUNDED_RE.search(handle.read())
        grounded = int(match.group(1)) if match else None
        if grounded != ctx["spec"]:
            raise StepFailed("goal", "SOURCES.md grounds spec %s, live spec "
                             "is %d" % (grounded, ctx["spec"]))
        regenerate_hashes(corpus_dir, grounded, datetime.datetime.now(
            tz=datetime.timezone.utc).strftime("%Y-%m-%d"))

    def step_scope(self, state: Dict[str, Any],
                   ctx: Dict[str, Any]) -> None:
        head = self.git("scope", self.worktree, "rev-parse", "HEAD")
        if head != ctx["base"]:
            raise StepFailed("scope", "the session moved HEAD")
        outside = allowed_paths.out_of_scope(self.changed_paths("scope"))
        if outside:
            raise StepFailed("scope", "changed outside the allowed scope: %s"
                             % ", ".join(outside))
        if self.git("scope", self.root, "status", "--porcelain"):
            raise StepFailed("scope", "the live tree changed during the edit")

    def step_test(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        dirs = test_dirs(self.worktree)
        if not dirs:
            raise StepFailed("test", "no test suites found")
        for path in dirs:
            result = self.run([sys.executable, "-m", "unittest", "discover",
                               "-s", "."], path, TIMEOUT["suite"])
            if result.rc != 0:
                raise StepFailed("test", "%s failed: %s" % (
                    os.path.relpath(path, self.worktree),
                    _tail(result.err or result.out, 300)))

    def step_probe(self, state: Dict[str, Any],
                   ctx: Dict[str, Any]) -> None:
        result = self.run([sys.executable, os.path.join(
            self.worktree, "livedata", "atlas_probe.py"), "check"],
            self.worktree, TIMEOUT["probe"])
        if result.rc != 0:
            raise StepFailed("probe", _tail(result.out or result.err, 600))

    def step_ingest(self, state: Dict[str, Any],
                    ctx: Dict[str, Any]) -> None:
        output_dir = os.path.join(self.root, "var", "knowledge")
        result = self.py("ingest", self.worktree, os.path.join(
            self.worktree, "knowledge", "atlas_kb.py"), "ingest",
            "--db", self.kb_db, "--output-dir", output_dir,
            "--corpus-dir", os.path.join(self.worktree, "knowledge",
                                         "corpus"),
            "--actor", "atlas-upgrade", timeout=TIMEOUT["ingest"])
        match = INGEST_RUN_RE.search(result.out)
        if not match:
            raise StepFailed("ingest", "no run id in ingest output")
        run_id = match.group(1)
        with open(os.path.join(output_dir, "validation-report-%s.json"
                               % run_id), "r", encoding="utf-8") as handle:
            report = json.load(handle)
        rejected = (report["secret_scan_findings"]
                    + report["duplicate_unit_ids"])
        if rejected:
            raise StepFailed("ingest", "run %s has rejected units: %s"
                             % (run_id, "; ".join(rejected[:5])))
        ctx["run_id"] = run_id

    def step_push(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        wt = self.worktree
        self.git("push", wt, "add", "-A")
        self.git("push", wt, "commit", "-q", "-m",
                 "chore: ground Atlas at runtime spec %d" % ctx["spec"])
        author = self.git("push", wt, "log", "-1", "--format=%an <%ae>")
        if author != AUTHOR_IDENT:
            raise StepFailed("push", "commit author is %r" % author)
        ctx["commit"] = self.git("push", wt, "rev-parse", "HEAD")
        self.git("push", wt, "push", "origin", "HEAD:main")  # never forced
        remote = self.git("readback", self.root, "ls-remote", "origin",
                          "refs/heads/main").split()
        if not remote or remote[0] != ctx["commit"]:
            raise StepFailed("readback", "remote main is %s, pushed %s"
                             % (remote[:1], ctx["commit"]))
        self.git("pull", self.root, "pull", "--ff-only", "origin", "main")
        if self.git("pull", self.root, "rev-parse", "HEAD") != ctx["commit"]:
            raise StepFailed("pull", "live tree did not reach %s"
                             % ctx["commit"])

    def step_activate(self, state: Dict[str, Any],
                      ctx: Dict[str, Any]) -> None:
        self.py("activate", self.root, os.path.join(
            self.root, "knowledge", "atlas_kb.py"), "activate",
            "--db", self.kb_db, "--run", ctx["run_id"],
            "--actor", "atlas-upgrade", timeout=TIMEOUT["ingest"])


def clear(job: Job, spec: int) -> int:
    """Operator release of a blocked spec: the next run starts it at
    attempt 1."""
    with open(os.path.join(job.var, "lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = job.load_state()
        if state.get("spec") != spec or state.get("status") != "blocked":
            print("spec %d is not blocked (state: spec %s, %s)"
                  % (spec, state.get("spec"), state.get("status")))
            return 1
        state.update(status="idle", attempt=0, last_error=None)
        job.save_state(state)
    print("spec %d cleared; the next run starts at attempt 1" % spec)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas runtime upgrade job")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="one timer run")
    run.add_argument("--dry-run", action="store_true",
                     help="no push, no activation, reports printed; with "
                          "corpus equal to live, checks the machinery on "
                          "an unedited worktree")
    clr = sub.add_parser("clear", help="release a blocked spec")
    clr.add_argument("--spec", type=int, required=True)
    sub.add_parser("status", help="print the saved state")
    args = parser.parse_args(argv)
    if args.command == "run":
        return Job(dry_run=args.dry_run).run_once()
    job = Job()
    os.makedirs(job.var, exist_ok=True)
    if args.command == "clear":
        return clear(job, args.spec)
    print(json.dumps(job.load_state(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
