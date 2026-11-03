#!/usr/bin/env python3
"""Atlas runtime upgrade job (change: runtime-upgrade-pipeline).

When the live Finney runtime spec moves past the corpus spec, this job
brings Atlas up to date on the Pi without an operator:

    recover, detect, source, preflight, prepare, edit, goal, scope,
    citation, sandbox, test, probe, ingest, push, activate, report, restart

The model may edit data only: the corpus, the supersession markers and the
decision log (allowed_paths.py). It reads the subtensor source exported at
the live release, never the clone's newer code. The test and probe gates
run in a bubblewrap sandbox with no secrets (sandbox.py), checked from
inside by a canary on every attempt (change: upgrade-sandbox-scope).

Recovery runs first on every run: it finishes a pull or activation a
failed run left behind, and keeps the active knowledge run equal to the
live tree's corpus. A failed environment preflight waits without using an
attempt. After a pull that brings in code, the Hermes gateway restarts so
its MCP servers load it.

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
import contextlib
import datetime
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import string
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_UPGRADE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_UPGRADE_DIR)
sys.path.insert(0, _UPGRADE_DIR)
sys.path.insert(0, os.path.join(ROOT, "livedata"))
sys.path.insert(0, os.path.join(ROOT, "repotrack"))

import allowed_paths  # noqa: E402
import atlas_repo as arp  # noqa: E402
import sandbox  # noqa: E402
import atlas_live as al  # noqa: E402
import atlas_probe  # noqa: E402
import atlas_telegram as tg  # noqa: E402  (atlas_probe put it on the path)

AUTHOR_NAME = "vaNlabs"
AUTHOR_EMAIL = "vanlabs@pm.me"
AUTHOR_IDENT = "%s <%s>" % (AUTHOR_NAME, AUTHOR_EMAIL)
# The write-enabled deploy key. Only the job's push uses it; the live
# tree has no `core.sshCommand`, so other pushes from the Pi fail.
DEPLOY_KEY = os.environ.get(
    "ATLAS_DEPLOY_KEY", os.path.expanduser("~/.ssh/atlas_maintenance_ed25519"))
DEPLOY_SSH = ("ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes "
              "-o StrictHostKeyChecking=yes" % DEPLOY_KEY)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (3600, 4 * 3600)  # after attempt 1, after attempt 2
MAX_TURNS = 60
TIMEOUT = {"git": 120, "rpc": 120, "repotrack": 600, "smoke": 120,
           "claude": 25 * 60, "suite": 5 * 60, "probe": 180, "ingest": 300,
           "export": 300, "canary": 60}
# One deadline per run (change: upgrade-sandbox-scope). Every step before
# the push runs under the smaller of its own timeout and the time left,
# less PUSH_RESERVE for push, readback, pull and activation; the push does
# not start without that reserve. The unit's TimeoutStartSec (60 min) is a
# backstop above RUN_BUDGET; a test keeps it that way.
RUN_BUDGET = 50 * 60
PUSH_RESERVE = 15 * 60
MIN_STEP_SECONDS = 30
# How long a run waits for the clone lock (a repotrack update in flight).
CLONE_LOCK_WAIT = 900
# A failure after the push has landed cannot be fixed by another attempt:
# main already carries the grounded corpus. It blocks at once.
POST_PUSH_GATES = ("readback", "pull", "activate")
# Fixed wording per failing gate (change: alert-delivery-reliability).
# Reports never quote raw command, error or model output: that text stays
# in state.json and on stderr, where `status` shows it.
GATE_PHRASES = {
    "prepare": "Setting up the upgrade worktree failed.",
    "edit": "The Claude editing session failed or changed nothing usable.",
    "goal": "The edit did not bring the corpus to the live spec.",
    "scope": "The edit touched files outside the allowed scope.",
    "citation": "The edit cited a chain read this run did not make, or a "
                "spec past the live one.",
    "sandbox": "The gate sandbox failed its isolation check.",
    "deadline": "The run ran out of time before the push.",
    "test": "A test suite failed on the edited tree.",
    "probe": "The chain-read probe failed on the edited tree.",
    "ingest": "Staging the knowledge run from the edited corpus failed.",
    "push": "Pushing the upgrade commit to main failed.",
    "readback": "The pushed commit could not be read back from main.",
    "pull": "The live tree could not pull the pushed commit.",
    "activate": "Activating the staged knowledge run failed.",
    "interrupted": "The previous run stopped before it finished.",
}
GATE_PHRASE_DEFAULT = "The %s step failed."
RAW_ERROR_HINT = "The raw error is kept on the Pi: %s"
MODEL_TOOLS = "Read,Grep,Glob,Edit,Write"
GATEWAY_UNIT = "hermes-gateway"
GATEWAY_FRESH_SECONDS = 600  # Hermes rewrites its state file about once a min
RESTART_CONFIRM_TRIES, RESTART_CONFIRM_PAUSE = 6, 5
CODE_COMMITS_SHOWN = 10
CORPUS_PATH = "knowledge/corpus"
# Paths no long-lived process loads: a pull touching only these needs no
# gateway restart. Every upgrade commit edits docs/decisions.md.
NON_CODE_PATHS = (CORPUS_PATH, "knowledge/supersession-markers.json", "docs")
KB_ACTIVATE = "python3 knowledge/atlas_kb.py activate --run %s"
PULL_CMD = "git -C ~/atlas pull --ff-only origin main"

# Environment preflight failures: (headline, meaning, next action). Fixed
# wording only; raw command output can trip the scrubber and never sends.
WAIT_REASONS = {
    "identity": (
        "Atlas self-update waiting: wrong git identity in the live tree",
        "The live tree's git author is not %s. No attempt used; Atlas "
        "checks again each run." % AUTHOR_IDENT,
        "set the repo identity in ~/atlas to %s" % AUTHOR_IDENT),
    "dirty": (
        "Atlas self-update waiting: the live tree has uncommitted changes",
        "Uncommitted changes in ~/atlas would block the pull after a push. "
        "No attempt used; Atlas checks again each run.",
        "commit or discard the changes in ~/atlas"),
    "diverged": (
        "Atlas self-update waiting: the live tree has local commits",
        "~/atlas holds commits that origin/main does not, so the pull "
        "after a push would fail. No attempt used; Atlas checks again "
        "each run.",
        "move the local commits off main in ~/atlas so it matches "
        "origin/main"),
    "auth": (
        "Atlas self-update waiting: the Claude login needs renewing",
        "The Claude login check on the Pi failed. No attempt used; Atlas "
        "checks again each run.",
        "log in to Claude on the Pi"),
    "readers": (
        "Atlas self-update waiting: chain readers need an operator fix",
        "The chain-read probe fails on the live tree, so a storage item "
        "Atlas reads changed. The upgrade job may not edit chain readers. "
        "No attempt used; Atlas checks again each run.",
        "run python3 livedata/atlas_probe.py check on the Pi and fix the "
        "readers"),
    "probe": (
        "Atlas self-update waiting: the chain-read probe could not run",
        "The probe could not read live chain metadata. No attempt used; "
        "Atlas checks again each run.",
        "run python3 livedata/atlas_probe.py check on the Pi"),
    "anchor": (
        "Atlas self-update waiting: no release found for the live spec",
        "The subtensor clone has no release tag and no spec-bump commit for "
        "the live or the corpus spec, so Atlas cannot tell which code "
        "shipped. No attempt used; Atlas checks again each run.",
        "check the tags in var/repotrack/subtensor"),
}

SPEC_RE = re.compile(r"spec_version:\s*(\d+)")
GROUNDED_RE = re.compile(r"Grounded at\s*\|\s*Finney `spec_version` "
                         r"\*\*(\d+)\*\*")
INGEST_RUN_RE = re.compile(r"Ingest run (\S+):")
# Citation gate (change: upgrade-sandbox-scope). A block citation is the
# word block(s) followed by one or more 7+ digit numbers; a spec citation
# is "spec" or "spec_version" followed closely by a 3-digit number.
BLOCK_CITE_RE = re.compile(
    r"(?i)\bblocks?\b((?:[\s,#(]*(?:and\s+|or\s+)?\d[\d,]{5,}\d)+)")
BLOCK_NUM_RE = re.compile(r"\d[\d,]{5,}\d")
SPEC_CITE_RE = re.compile(r"(?i)\bspec(?:_version)?\b[^0-9\n]{0,12}?(\d{3})\b")

Result = collections.namedtuple("Result", "rc out err")


class Waiting(Exception):
    """An environment preflight check failed: no attempt is used."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__("%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


class StepFailed(Exception):
    def __init__(self, gate: str, detail: str) -> None:
        super().__init__("%s: %s" % (gate, detail))
        self.gate = gate
        self.detail = detail


def _tail(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


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


def status_entries(porcelain_z: str) -> List[Tuple[str, str]]:
    """(XY code, path) from `git status --porcelain=v1 -z -uall`. A rename
    or copy reports both paths under its code."""
    entries: List[Tuple[str, str]] = []
    tokens = porcelain_z.split("\0")
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        entries.append((entry[:2], entry[3:]))
        if "R" in entry[:2] or "C" in entry[:2]:
            entries.append((entry[:2], tokens[index]))
            index += 1
    return entries


def cited_blocks(text: str) -> set:
    found = set()
    for match in BLOCK_CITE_RE.finditer(text):
        found |= {int(n.replace(",", ""))
                  for n in BLOCK_NUM_RE.findall(match.group(1))}
    return found


def citation_violations(added: List[str], live: int, run_blocks: set,
                        base_blocks: set) -> List[str]:
    """Added corpus lines that cite a block this run did not read and the
    base corpus does not cite, or name a spec past the live one."""
    found: List[str] = []
    for line in added:
        bad = sorted(cited_blocks(line) - run_blocks - base_blocks)
        if bad:
            found.append("block %s not read: %s" % (
                ", ".join(map(str, bad)), _tail(line.strip(), 160)))
        future = sorted({int(n) for n in SPEC_CITE_RE.findall(line)
                         if int(n) > live})
        if future:
            found.append("spec %s is past live %d: %s" % (
                ", ".join(map(str, future)), live, _tail(line.strip(), 160)))
    return found


def corpus_texts(corpus_dir: str) -> Dict[str, str]:
    """Every text file under the corpus, by path relative to it."""
    texts: Dict[str, str] = {}
    for current, _, files in os.walk(corpus_dir):
        for name in files:
            path = os.path.join(current, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    texts[os.path.relpath(path, corpus_dir)] = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
    return texts


def added_lines(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    lines: List[str] = []
    for name in sorted(after):
        for line in difflib.unified_diff(
                before.get(name, "").splitlines(),
                after[name].splitlines(), lineterm="", n=0):
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
    return lines


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
        self.hermes_home = (os.environ.get("HERMES_HOME")
                            or os.path.expanduser("~/.hermes"))
        self.dry_run = dry_run
        self.state_path = os.path.join(
            self.var, "dry-run-state.json" if dry_run else "state.json")
        self.git_env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR_NAME,
                            GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
                            GIT_COMMITTER_NAME=AUTHOR_NAME,
                            GIT_COMMITTER_EMAIL=AUTHOR_EMAIL)
        self.deadline: Optional[float] = None
        self.pre_push = False  # True while pre-push steps run
        self.preflight_probe = ""  # the live tree's probe JSON
        self.canary = os.path.join(_UPGRADE_DIR, "sandbox_canary.py")
        # Paths the gate sandbox must hide; the canary checks each.
        self.secret_paths = [
            os.path.expanduser("~/.ssh"), os.path.expanduser("~/.hermes"),
            os.path.expanduser("~/.claude"), self.hermes_home, DEPLOY_KEY,
            os.path.join(root, ".env"), os.path.join(root, "var")]

    # -- seams --------------------------------------------------------------

    def now(self) -> float:
        return time.time()

    def run(self, cmd: List[str], cwd: str, timeout: int,
            env: Optional[Dict[str, str]] = None) -> Result:
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                                  text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return Result(124, "", "timed out after %ds" % timeout)
        except OSError as exc:
            return Result(127, "", str(exc))
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def bwrap_present(self) -> bool:
        return os.access(sandbox.BWRAP, os.X_OK)

    def live_spec(self) -> Dict[str, Any]:
        return al.read_live_spec(al.load_config())

    def send(self, msg: "tg.Message") -> bool:
        if self.dry_run:
            print("[dry-run report] " + msg.plain())
            return True
        try:
            return tg.send_alert(msg, "upgrade-report")
        except tg.FatalTelegramError as exc:
            print("telegram: %s" % tg.redact(str(exc)), file=sys.stderr)
            return False

    # -- helpers ------------------------------------------------------------

    def timeout(self, name: str) -> int:
        """A step's timeout. Before the push it is capped by the run
        deadline, less the push reserve; a step that would get under
        MIN_STEP_SECONDS fails the attempt at the `deadline` gate."""
        limit = TIMEOUT[name]
        if not self.pre_push or self.deadline is None:
            return limit
        left = int(self.deadline - PUSH_RESERVE - self.now())
        if left < MIN_STEP_SECONDS:
            raise StepFailed("deadline", "%ds left before the push reserve "
                             "at a %s step" % (max(left, 0), name))
        return min(limit, left)

    def git(self, gate: str, cwd: str, *args: str,
            env: Optional[Dict[str, str]] = None) -> str:
        result = self.run(["git"] + list(args), cwd, self.timeout("git"),
                          env or self.git_env)
        if result.rc != 0:
            raise StepFailed(gate, "git %s: %s" % (
                args[0], _tail(result.err or result.out)))
        return result.out.rstrip("\n")  # porcelain lines lead with a space

    def py(self, gate: str, cwd: str, script: str, *args: str,
           timeout: str, ok: Tuple[int, ...] = (0,)) -> Result:
        result = self.run([sys.executable, script] + list(args), cwd,
                          self.timeout(timeout))
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

    def corpus_hashes(self) -> Dict[str, str]:
        path = os.path.join(self.root, CORPUS_PATH, "hashes.json")
        with open(path, "r", encoding="utf-8") as handle:
            return dict(json.load(handle).get("files") or {})

    def clone_spec(self) -> Optional[int]:
        try:
            with open(os.path.join(self.clone, "runtime", "src", "lib.rs"),
                      "r", encoding="utf-8") as handle:
                match = SPEC_RE.search(handle.read(20000))
        except OSError:
            return None
        return int(match.group(1)) if match else None

    # -- reporting ----------------------------------------------------------

    def report(self, state: Dict[str, Any], kind: str,
               msg: "tg.Message", key: Optional[str] = None) -> None:
        """Exactly one delivery per (spec, attempt, outcome), or per explicit
        key. An undelivered report is kept and retried at the start of the
        next run."""
        key = key or "%s:%s:%s" % (state.get("spec"),
                                   state.get("attempt", 0), kind)
        reported = state.setdefault("reported", [])
        if key in reported:
            return
        if self.send(msg):
            reported.append(key)
            del reported[:-20]
        else:
            state["pending_report"] = {"key": key,
                                       "message": msg.to_dict()}

    def flush_pending(self, state: Dict[str, Any]) -> bool:
        """Retry the undelivered report. True when state changed, so the
        caller saves it. A report for an older spec is dropped unsent."""
        pending = state.get("pending_report")
        if not pending:
            return False
        head = str(pending.get("key", "")).split(":", 1)[0]
        if (head.isdigit() and isinstance(state.get("spec"), int)
                and int(head) < state["spec"]):
            print("dropped stale pending report %s" % pending["key"],
                  file=sys.stderr)
            state.pop("pending_report")
            return True
        if "message" in pending:
            msg = tg.Message.from_dict(pending["message"])
        else:  # a report saved before the house layout (plain text)
            msg = tg.Message(severity=None, headline=str(pending["text"]))
        if self.send(msg):
            state.setdefault("reported", []).append(pending["key"])
            state.pop("pending_report")
            return True
        return False

    def fail(self, state: Dict[str, Any], gate: str, detail: str,
             stalled: bool = False) -> None:
        """Record a failed attempt: retry with backoff, or block after the
        last attempt. An interrupted run reports `stalled` in place of the
        `retrying` or `blocked` report for that attempt."""
        print("failed at %s: %s" % (gate, _tail(detail, 600)),
              file=sys.stderr)
        attempt = int(state.get("attempt", 0))
        spec = state.get("spec")
        post_push = state.get("post_push")
        if (gate == "interrupted" and post_push
                and state.get("step") == "activate"):
            gate = "activate"  # the push and pull were done
        if post_push and gate not in POST_PUSH_GATES:
            state.pop("post_push")  # the commit never reached main
            post_push = None
        blocked = gate in POST_PUSH_GATES or attempt >= MAX_ATTEMPTS
        state.update(status="blocked" if blocked else "retrying",
                     last_error="%s: %s" % (gate, _tail(detail, 600)),
                     step=None)
        of = "attempt %d of %d" % (attempt, MAX_ATTEMPTS)
        details = [GATE_PHRASES.get(gate, GATE_PHRASE_DEFAULT % gate),
                   RAW_ERROR_HINT % tg.mono(
                       "python3 upgrade/atlas_upgrade.py status")]
        if blocked and post_push:
            post_push["gate"] = gate
            msg = tg.Message(
                severity=tg.severity_for("upgrade-blocked"),
                headline="Atlas self-update for spec %s is %s after the push"
                         % (spec, "stalled and blocked" if stalled
                            else "blocked"),
                meaning="Commit %s is on main, but %s failed, so corpus run "
                        "%s is not active. Atlas retries each run and "
                        "clears this block once the live tree has the "
                        "commit and the run is active." % (
                            tg.mono(post_push["commit"][:8]), gate,
                            tg.mono(post_push["run_id"])),
                details=details,
                next_action=("in ~/atlas run %s" % tg.mono(
                    KB_ACTIVATE % post_push["run_id"])
                    if gate == "activate" else
                    "in ~/atlas run %s, then %s" % (
                        tg.mono(PULL_CMD),
                        tg.mono(KB_ACTIVATE % post_push["run_id"]))))
        elif blocked:
            why = ("this gate runs after the push, so another attempt "
                   "cannot fix it" if gate in POST_PUSH_GATES
                   else "all %d attempts are used" % MAX_ATTEMPTS)
            msg = tg.Message(
                severity=tg.severity_for("upgrade-blocked"),
                headline="Atlas self-update for spec %s is %s" % (
                    spec, "stalled and blocked" if stalled else "blocked"),
                meaning="Blocked after %s failed at %s: %s. Branch %s is "
                        "kept for you." % (of, gate, why,
                                           tg.mono(state.get("branch"))),
                details=details,
                next_action="fix the branch, then run %s" % tg.mono(
                    "python3 upgrade/atlas_upgrade.py clear --spec %s"
                    % spec))
        else:
            state["next_attempt_at"] = (
                self.now() + BACKOFF_SECONDS[attempt - 1])
            msg = tg.Message(
                severity=tg.severity_for("upgrade-stalled" if stalled
                                         else "upgrade-retrying"),
                headline=("Atlas self-update for spec %s stalled (%s)"
                          % (spec, of) if stalled else
                          "Atlas self-update for spec %s failed, retrying "
                          "(%s)" % (spec, of)),
                meaning="Failed at %s. The next attempt runs %s." % (
                    gate, tg.fmt_time(state["next_attempt_at"])),
                details=details)
        self.report(state, "stalled" if stalled else state["status"], msg)

    # -- the run ------------------------------------------------------------

    def run_once(self) -> int:
        self.deadline = self.now() + RUN_BUDGET
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
        changed = self.flush_pending(state)
        if state.get("status") == "running":
            # We hold the lock, so no live run owns this state.
            self.keep_branch()
            self.fail(state, "interrupted", "run interrupted at step %s"
                      % state.get("step"), stalled=True)
            self.save_state(state)
        if not self.dry_run and self.reconcile(state):
            changed = True

        live = self.live_spec()
        if not live.get("ok"):
            # An RPC blip is not a job failure: the chain-head poll and the
            # fail-closed page already cover a real outage, and a non-zero
            # exit would page through OnFailure= (change:
            # alert-delivery-reliability).
            print("live spec unavailable: %s" % live.get("error"))
            if changed:
                self.save_state(state)
            return 0
        spec = live["spec_version"]
        corpus = self.corpus_spec()
        machinery_check = self.dry_run and spec == corpus
        if spec == corpus and not machinery_check:
            # A pre-push wait or retry is moot once the corpus is current.
            # A block is not: a post-push block clears only in reconcile,
            # a pre-push one only through `clear`.
            if (state.get("spec") == spec
                    and state.get("status") in ("waiting", "retrying")):
                state["status"] = "idle"
                changed = True
            if changed:
                self.save_state(state)
            return 0

        if state.get("spec") != spec:
            # A newer live spec supersedes; old branches are kept.
            state = {"status": "idle", "spec": spec, "attempt": 0,
                     "reported": state.get("reported", []),
                     **{key: state[key] for key in ("pending_report",
                                                    "restart")
                        if key in state}}
        if state["status"] == "blocked":
            self.save_state(state)
            return 0
        if (state["status"] == "retrying"
                and self.now() < state.get("next_attempt_at", 0)):
            self.save_state(state)
            return 0
        return self._attempt(state, spec, corpus, machinery_check)

    # -- recovery (every run) -----------------------------------------------

    def tree_ok(self) -> bool:
        """The live tree is clean and holds no commit origin/main lacks."""
        status = self.run(["git", "status", "--porcelain"], self.root,
                          TIMEOUT["git"])
        if status.rc != 0 or status.out.strip():
            return False
        return self.is_ancestor("HEAD", "origin/main")

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self.run(["git", "merge-base", "--is-ancestor", older, newer],
                        self.root, TIMEOUT["git"]).rc == 0

    def head(self) -> Optional[str]:
        result = self.run(["git", "rev-parse", "HEAD"], self.root,
                          TIMEOUT["git"])
        return result.out.strip() if result.rc == 0 else None

    def code_commits(self, old: str, new: str) -> List[str]:
        """`old..new` commits that touch code, not just corpus or docs."""
        result = self.run(["git", "log", "--format=%h %s", "%s..%s"
                           % (old, new), "--", "."]
                          + [":!" + path for path in NON_CODE_PATHS],
                          self.root, TIMEOUT["git"])
        return result.out.splitlines() if result.rc == 0 else []

    def kb_read(self) -> Tuple[Optional[str], Optional[Dict[str, str]],
                               List[Tuple[str, Dict[str, str]]]]:
        """(active run, its file hashes, staged runs this job ingested
        newest first with their hashes). Read-only; writes go through
        atlas_kb.py."""
        def hashes(files_json: str) -> Dict[str, str]:
            return {name: info.get("sha256")
                    for name, info in json.loads(files_json).items()}
        connection = sqlite3.connect("file:%s?mode=ro" % self.kb_db,
                                     uri=True)
        try:
            row = connection.execute(
                "SELECT u.run_id, r.files_json FROM units u LEFT JOIN "
                "intake_runs r ON r.run_id = u.run_id WHERE u.active = 1 "
                "LIMIT 1").fetchone()
            ours = connection.execute(
                "SELECT r.run_id, r.files_json FROM intake_runs r WHERE "
                "EXISTS (SELECT 1 FROM audit a WHERE a.actor = ? AND "
                "a.action = 'ingest' AND a.detail LIKE 'run ' || r.run_id "
                "|| ' staged %') ORDER BY r.intake_date DESC",
                ("atlas-upgrade",)).fetchall()
        finally:
            connection.close()
        active = row[0] if row else None
        active_files = hashes(row[1]) if row and row[1] else None
        return active, active_files, [(run, hashes(files))
                                      for run, files in ours]

    def run_is_clean(self, run_id: str) -> bool:
        path = os.path.join(self.root, "var", "knowledge",
                            "validation-report-%s.json" % run_id)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            return False
        return not (report.get("secret_scan_findings")
                    or report.get("duplicate_unit_ids"))

    def reconcile(self, state: Dict[str, Any]) -> bool:
        """Recover what a run left undone after the push, on every timer
        run and before the "corpus equals live" exit. True when state
        changed."""
        changed = False
        post_push = state.get("post_push")
        blocked = post_push and state.get("status") == "blocked"
        tree_ok = self.tree_ok()
        if blocked and tree_ok and not self.is_ancestor(
                post_push["commit"], "HEAD"):
            before = self.head()
            pull = self.run(["git", "pull", "--ff-only", "origin", "main"],
                            self.root, TIMEOUT["git"], self.git_env)
            if pull.rc == 0 and before:
                print("live tree pulled to %s" % self.head())
                if self.code_commits(before, "HEAD"):
                    state["restart"] = {"commit": self.head() or ""}
                    changed = True
        try:
            if tree_ok and os.path.exists(self.kb_db):
                changed = self.check_kb(state) or changed
            current = (os.path.exists(self.kb_db)
                       and self.kb_read()[1] == self.corpus_hashes())
        except sqlite3.Error as exc:
            print("knowledge store unreadable: %s" % exc, file=sys.stderr)
            current = False
        if blocked and current and self.is_ancestor(post_push["commit"],
                                                    "HEAD"):
            print("post-push block for spec %s cleared" % state.get("spec"))
            state.update(status="idle", last_error=None)
            state.pop("post_push")
            changed = True
        if state.get("restart"):
            self.try_restart(state)
            changed = True
        return changed

    def check_kb(self, state: Dict[str, Any]) -> bool:
        """The active run must serve the corpus the live tree carries.
        Activate a clean run this job ingested for exactly that corpus, or
        report once with the commands."""
        want = self.corpus_hashes()
        active, active_files, ours = self.kb_read()
        if active_files == want:
            return False
        digest = hashlib.sha256(json.dumps(
            want, sort_keys=True).encode("utf-8")).hexdigest()[:8]
        for run_id, files in ours:
            if files != want or not self.run_is_clean(run_id):
                continue
            result = self.run([sys.executable, os.path.join(
                self.root, "knowledge", "atlas_kb.py"), "activate",
                "--db", self.kb_db, "--run", run_id,
                "--actor", "atlas-upgrade"], self.root, TIMEOUT["ingest"])
            if result.rc != 0:
                print("activate %s failed: %s" % (
                    run_id, _tail(result.err or result.out)),
                    file=sys.stderr)
                break
            self.report(state, "kb", tg.Message(
                severity=tg.severity_for("upgrade-updated"),
                headline="Atlas activated the knowledge run for its corpus",
                meaning="The active run %s did not match the corpus in the "
                        "live tree. Atlas activated run %s, which it "
                        "ingested from that corpus." % (
                            tg.mono(active), tg.mono(run_id))),
                key="kb:%s:activated" % digest)
            return True
        self.report(state, "kb", tg.Message(
            severity=tg.severity_for("upgrade-blocked"),
            headline="Atlas knowledge base is stale",
            meaning="The active run %s does not match the corpus in the live "
                    "tree, and no clean run ingested by Atlas matches it."
                    % tg.mono(active),
            next_action="in ~/atlas run %s, then %s with the run id it "
                        "prints" % (
                            tg.mono("python3 knowledge/atlas_kb.py ingest"),
                            tg.mono(KB_ACTIVATE % "<run>"))),
            key="kb:%s:stale" % digest)
        return True

    def gateway_unsafe(self) -> Optional[str]:
        """Why a gateway restart is unsafe now, or None. Hermes owns the
        state file's schema, so anything unexpected counts as unsafe."""
        active = self.run(["systemctl", "--user", "is-active",
                           GATEWAY_UNIT], self.root, TIMEOUT["git"])
        if active.out.strip() != "active":
            return "the gateway is not running"
        try:
            with open(os.path.join(self.hermes_home, "gateway_state.json"),
                      "r", encoding="utf-8") as handle:
                gateway = json.load(handle)
            updated = datetime.datetime.fromisoformat(
                gateway["updated_at"]).timestamp()
        except (OSError, ValueError, KeyError, TypeError):
            return "the gateway state is unreadable"
        if self.now() - updated > GATEWAY_FRESH_SECONDS:
            return "the gateway state is stale"
        if (gateway.get("gateway_state") != "running"
                or gateway.get("active_agents") != 0
                or gateway.get("active_work") is not None):
            return "the gateway is busy"
        return None

    def try_restart(self, state: Dict[str, Any]) -> None:
        """Restart the gateway so its MCP servers load the pulled code.
        Never fails the run; an unsafe or failed restart reports once and
        is retried on later runs."""
        commit = str(state["restart"].get("commit") or "")
        why = self.gateway_unsafe()
        if why is None:
            result = self.run(["systemctl", "--user", "restart",
                               GATEWAY_UNIT], self.root, TIMEOUT["git"])
            if result.rc == 0:
                for _ in range(RESTART_CONFIRM_TRIES):
                    if self.run(["systemctl", "--user", "is-active",
                                 GATEWAY_UNIT], self.root,
                                TIMEOUT["git"]).out.strip() == "active":
                        print("%s restarted" % GATEWAY_UNIT)
                        state.pop("restart")
                        return
                    self.sleep(RESTART_CONFIRM_PAUSE)
            why = "the restart did not bring the gateway back"
        self.report(state, "restart", tg.Message(
            severity=tg.severity_for("upgrade-blocked"),
            headline="Atlas needs a Hermes gateway restart",
            meaning="New code was pulled into the live tree, but %s, so the "
                    "Hermes tools still run the old code. Atlas tries again "
                    "each run." % why,
            next_action="run %s on the Pi" % tg.mono(
                "systemctl --user restart %s" % GATEWAY_UNIT)),
            key="restart:%s" % commit[:8])

    # -- the attempt --------------------------------------------------------

    def _attempt(self, state: Dict[str, Any], spec: int,
                 corpus: Optional[int], machinery_check: bool) -> int:
        # The clone must cover the live spec before any attempt is used.
        # Update, spec read, release anchors, diff and source export all
        # happen under the clone lock, so the tree cannot move between them.
        ctx: Dict[str, Any] = {"spec": spec, "corpus": corpus}
        try:
            with arp.clone_lock(self.clone, CLONE_LOCK_WAIT,
                                sleep=self.sleep):
                self.run([sys.executable, os.path.join(
                    self.root, "repotrack", "atlas_repo.py"), "update"],
                    self.root, TIMEOUT["repotrack"],
                    dict(os.environ, **{arp.LOCK_HELD_ENV:
                                        os.path.abspath(self.clone)}))
                clone = self.clone_spec()
                if clone is not None and clone >= spec:
                    try:
                        self.prepare_source(ctx)
                    except Waiting as exc:
                        return self.wait(state, spec, exc)
        except arp.LockBusy as exc:
            print("clone busy: %s" % exc, file=sys.stderr)
            return 0
        if clone is None or clone < spec:
            state.update(status="waiting", clone_spec=clone)
            self.report(state, "waiting", tg.Message(
                severity=tg.severity_for("upgrade-waiting"),
                headline="Atlas self-update waiting for subtensor code",
                meaning="The live chain is on spec %d. The tracked subtensor "
                        "code is at spec %s. No attempt used; Atlas checks "
                        "again each run." % (spec, clone)))
            self.save_state(state)
            return 0

        try:
            self.check_environment()
        except Waiting as exc:
            return self.wait(state, spec, exc)
        state.pop("wait_reason", None)

        state.update(status="running", attempt=int(state["attempt"]) + 1,
                     started_at=self.now(), last_error=None, step=None,
                     clone_spec=clone)
        ctx["clone"] = clone
        steps = [("prepare", self.step_prepare)]
        if not machinery_check:
            steps += [("edit", self.step_edit), ("goal", self.step_goal),
                      ("scope", self.step_scope),
                      ("citation", self.step_citation)]
        steps += [("sandbox", self.step_sandbox), ("test", self.step_test),
                  ("probe", self.step_probe)]
        if not self.dry_run:
            steps += [("ingest", self.step_ingest),
                      ("push", self.step_push),
                      ("activate", self.step_activate)]
        try:
            self.pre_push = True
            for name, step in steps:
                if name == "push":
                    self.pre_push = False
                    self.check_push_reserve()
                state["step"] = name
                self.save_state(state)
                step(state, ctx)
        except StepFailed as exc:
            self.pre_push = False
            self.keep_branch()
            self.fail(state, exc.gate, exc.detail)
            self.save_state(state)
            return 0  # reported (or queued): a handled outcome, not a crash
        self.pre_push = False

        state.update(status="updated", step=None, commit=ctx.get("commit"))
        if self.dry_run:
            self.report(state, "updated", tg.Message(
                severity=tg.severity_for("upgrade-dry-run"),
                headline="Atlas self-update dry run passed for spec %d"
                         % spec,
                meaning="Every gate passed. No push, no activation."))
        else:
            summary = (ctx.get("summary") or "").strip().splitlines()
            self.report(state, "updated", tg.Message(
                severity=tg.severity_for("upgrade-updated"),
                headline="Atlas updated itself for runtime spec %d" % spec,
                meaning="Every check passed: edit scope, all test suites, "
                        "live chain probe. Pushed to main and the new "
                        "knowledge corpus is active.",
                facts=[("Commit", tg.mono(ctx["commit"][:8])),
                       ("Corpus run", tg.mono(ctx["run_id"]))],
                details=((["What changed:"] + summary) if summary else [])
                + self.code_lines(ctx.get("code_commits") or []),
                buttons=tg.button(None, "View commit", "atlas_commit",
                                  sha=ctx["commit"])))
        state.pop("post_push", None)
        if ctx.get("code_commits"):
            state["restart"] = {"commit": ctx["commit"]}
        # Saved before the restart: a job killed while the gateway stops
        # must not read as an interrupted activation.
        self.save_state(state)
        if state.get("restart"):
            self.try_restart(state)
            self.save_state(state)
        return 0

    def wait(self, state: Dict[str, Any], spec: int, exc: Waiting) -> int:
        """A failed environment or source check: `waiting`, no attempt
        used, one report per spec and reason, in fixed wording."""
        print("preflight %s: %s" % (exc.reason, exc.detail),
              file=sys.stderr)
        headline, meaning, action = WAIT_REASONS[exc.reason]
        state.update(status="waiting", wait_reason=exc.reason)
        self.report(state, "waiting-" + exc.reason, tg.Message(
            severity=tg.severity_for("upgrade-waiting"),
            headline=headline, meaning=meaning, next_action=action),
            key="%s:waiting-%s" % (spec, exc.reason))
        self.save_state(state)
        return 0

    def check_push_reserve(self) -> None:
        if self.deadline is None:
            return
        left = self.deadline - self.now()
        if left < PUSH_RESERVE:
            raise StepFailed("deadline", "%ds left, the push needs %ds"
                             % (max(int(left), 0), PUSH_RESERVE))

    @staticmethod
    def code_lines(commits: List[str]) -> List[str]:
        if not commits:
            return []
        lines = ["Code pulled into the live tree:"]
        lines += commits[:CODE_COMMITS_SHOWN]
        if len(commits) > CODE_COMMITS_SHOWN:
            lines.append("and %d more" % (len(commits) - CODE_COMMITS_SHOWN))
        return lines

    # -- steps --------------------------------------------------------------

    def check_environment(self) -> None:
        """Preflight before an attempt is counted. Raises Waiting."""
        # The repo's own identity: the job's overrides would always pass.
        bare = {key: value for key, value in os.environ.items()
                if not key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
        ident = self.run(["git", "var", "GIT_AUTHOR_IDENT"], self.root,
                         TIMEOUT["git"], bare)
        if ident.rc != 0 or not ident.out.startswith(AUTHOR_IDENT + " "):
            raise Waiting("identity", "author is %r" % (
                ident.out.rsplit(">", 1)[0] + ">"))
        dirty = self.run(["git", "status", "--porcelain"], self.root,
                         TIMEOUT["git"])
        if dirty.rc != 0 or dirty.out.strip():
            raise Waiting("dirty", _tail(dirty.out or dirty.err, 200))
        # A failed fetch leaves origin/main stale, and a stale ref still
        # exposes local commits; prepare's own fetch then fails the attempt.
        self.run(["git", "fetch", "origin"], self.root, TIMEOUT["git"],
                 self.git_env)
        if not self.is_ancestor("HEAD", "origin/main"):
            raise Waiting("diverged", "HEAD is not an ancestor of "
                          "origin/main")
        smoke = self.run([self.claude, "-p", "--restricted",
                          "--strict-mcp-config", "--max-turns", "1",
                          "--tools", "", "--", "reply ok"],
                         self.root, TIMEOUT["smoke"])
        if smoke.rc != 0:
            raise Waiting("auth", _tail(smoke.err or smoke.out, 200))
        # The chain readers are out of the model's scope, so a probe failure
        # on the live tree is an operator fix, not an attempt.
        probe = self.run([sys.executable, os.path.join(
            self.root, "livedata", "atlas_probe.py"), "check"], self.root,
            TIMEOUT["probe"])
        try:
            result = json.loads(probe.out)
        except ValueError:
            raise Waiting("probe", _tail(probe.err or probe.out, 200))
        if probe.rc == 0 and result.get("ok") is True:
            self.preflight_probe = probe.out.strip()
            return
        if result.get("error") or not result.get("failures"):
            raise Waiting("probe", _tail(str(result.get("error")), 200))
        raise Waiting("readers", "; ".join(
            "%s: %s" % (f.get("item"), f.get("reason"))
            for f in result["failures"][:5]))

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

    def clone_git(self, *args: str) -> Result:
        return self.run(["git"] + list(args), self.clone, TIMEOUT["git"])

    def anchor(self, spec: int) -> Tuple[str, str]:
        """(commit, kind) of a spec's release in the clone: the `v<spec>`
        tag, else the commit that introduced `spec_version: <spec>,` in the
        runtime. The runtime at the anchor must state that spec and the
        anchor must be on the clone's HEAD history. Raises Waiting."""
        tag = self.clone_git("rev-parse", "--verify", "--quiet",
                             "refs/tags/v%d^{commit}" % spec)
        if tag.rc == 0 and tag.out.strip():
            commit, kind = tag.out.strip(), "tag v%d" % spec
        else:
            found = self.clone_git("log", "--reverse", "--format=%H", "-S",
                                   "spec_version: %d," % spec, "--",
                                   "runtime/src/lib.rs")
            first = found.out.split()[:1] if found.rc == 0 else []
            if not first:
                raise Waiting("anchor", "no tag or spec-bump commit for "
                              "spec %d" % spec)
            commit, kind = first[0], "spec-bump commit (no v%d tag)" % spec
        shown = self.clone_git("show", "%s:runtime/src/lib.rs" % commit)
        match = SPEC_RE.search(shown.out[:20000]) if shown.rc == 0 else None
        if not match or int(match.group(1)) != spec:
            raise Waiting("anchor", "anchor %s for spec %d states %s" % (
                commit[:9], spec, match.group(1) if match else None))
        if self.clone_git("merge-base", "--is-ancestor", commit,
                          "HEAD").rc != 0:
            raise Waiting("anchor", "anchor %s for spec %d is not on HEAD"
                          % (commit[:9], spec))
        return commit, kind

    def prepare_source(self, ctx: Dict[str, Any]) -> None:
        """Release anchors, the spec diff and log between them, and the
        subtensor source exported at the live anchor (the only source the
        model reads). Runs under the clone lock. Raises Waiting."""
        if ctx["corpus"] is None:
            raise Waiting("anchor", "the corpus states no grounded spec")
        live, live_kind = self.anchor(ctx["spec"])
        base, _ = self.anchor(ctx["corpus"])
        log = self.clone_git("log", "--oneline", "--no-decorate",
                             "%s..%s" % (base, live))
        diff = self.clone_git("diff", base, live)
        if log.rc != 0 or diff.rc != 0:
            raise Waiting("anchor", "git log or diff failed between %s and "
                          "%s" % (base[:9], live[:9]))
        os.makedirs(self.var, exist_ok=True)
        path = os.path.join(self.var, "spec-%d.diff" % ctx["spec"])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(diff.out)
        ctx.update(anchor=live, anchor_kind=live_kind, base_anchor=base,
                   bump_log=_tail(log.out, 6000), diff_file=path,
                   source_dir=self.export_source(ctx["spec"], live))

    def export_source(self, spec: int, commit: str) -> str:
        """`git archive` of the anchor into var/upgrade/source-<spec>,
        reused while the anchor is unchanged."""
        target = os.path.join(self.var, "source-%d" % spec)
        marker = os.path.join(target, ".atlas-anchor")
        try:
            with open(marker, "r", encoding="utf-8") as handle:
                if handle.read().strip() == commit:
                    return target
        except OSError:
            pass
        shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target)
        tar = target + ".tar"
        steps = (["git", "archive", "--format=tar", "-o", tar, commit],
                 ["tar", "-xf", tar, "-C", target])
        try:
            for cmd in steps:
                result = self.run(cmd, self.clone, TIMEOUT["export"])
                if result.rc != 0:
                    raise Waiting("anchor", "export of %s failed: %s" % (
                        commit[:9], _tail(result.err or result.out, 200)))
        finally:
            if os.path.exists(tar):
                os.unlink(tar)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(commit + "\n")
        return target

    def read_rules(self, ctx: Dict[str, Any]) -> List[str]:
        """Read, Grep and Glob limited to the worktree, the source export
        and the job's directory. Absolute paths use the `//` rule form."""
        dirs = [self.worktree, ctx["source_dir"], self.var]
        return ["%s(/%s/**)" % (tool, os.path.abspath(d))
                for d in dirs for tool in ("Read", "Grep", "Glob")]

    def read_denials(self) -> List[str]:
        patterns = ["//%s/**" % os.path.abspath(p).lstrip("/") for p in (
            os.path.expanduser("~/.ssh"), os.path.expanduser("~/.hermes"),
            os.path.expanduser("~/.claude"), self.hermes_home)]
        patterns += ["~/.ssh/**", "~/.hermes/**", "~/.claude/**",
                     "//**/.env", "//**/.env.*", "**/.env*"]
        return ["%s(%s)" % (tool, p) for p in patterns
                for tool in ("Read", "Grep", "Glob")]

    def step_edit(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        live_py = os.path.join(self.root, "livedata", "atlas_live.py")
        knobs = self.py("edit", self.root, live_py, "read-knobs",
                        timeout="rpc")
        ctx["knobs"] = knobs.out
        # The corpus as it stood at the base, for the citation gate.
        ctx["base_corpus"] = corpus_texts(os.path.join(
            self.worktree, CORPUS_PATH))
        with open(os.path.join(_UPGRADE_DIR, "prompt.md"), "r",
                  encoding="utf-8") as handle:
            template = string.Template(handle.read())
        prompt = template.substitute(
            live_spec=ctx["spec"], corpus_spec=ctx["corpus"],
            source_dir=ctx["source_dir"], anchor=ctx["anchor"][:12],
            anchor_kind=ctx["anchor_kind"],
            bump_log=ctx["bump_log"], diff_file=ctx["diff_file"],
            knobs=knobs.out.strip(), probe=self.preflight_probe,
            allowed="\n".join("- `%s`" % p for p in allowed_paths.ALLOWED))
        cmd = ([self.claude, "-p", "--restricted", "--strict-mcp-config",
                "--max-turns", str(MAX_TURNS), "--tools", MODEL_TOOLS,
                "--add-dir", ctx["source_dir"], self.var,
                "--allowedTools"] + self.read_rules(ctx)
               + allowed_paths.tool_rules()
               + ["--disallowedTools", "WebFetch", "WebSearch", "Bash"]
               + allowed_paths.tool_denials() + self.read_denials()
               + ["--", prompt])
        result = self.run(cmd, self.worktree, self.timeout("claude"))
        if result.rc != 0:
            raise StepFailed("edit", "claude exited %d: %s" % (
                result.rc, _tail(result.err or result.out)))
        ctx["summary"] = result.out.strip()

    def changed_entries(self, gate: str) -> List[Tuple[str, str]]:
        return status_entries(self.git(gate, self.worktree, "status",
                                       "--porcelain=v1", "-z", "-uall"))

    def changed_paths(self, gate: str) -> List[str]:
        return [path for _, path in self.changed_entries(gate)]

    def check_scope(self) -> List[str]:
        """Scope violations of the worktree as it is now. Returns the
        checked paths; raises StepFailed on any violation."""
        entries = self.changed_entries("scope")
        bad = allowed_paths.scope_violations(entries)
        if bad:
            raise StepFailed("scope", "changed outside the allowed scope: %s"
                             % ", ".join(bad))
        return [path for _, path in entries]

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
        self.check_scope()
        if self.git("scope", self.root, "status", "--porcelain"):
            raise StepFailed("scope", "the live tree changed during the edit")

    def step_citation(self, state: Dict[str, Any],
                      ctx: Dict[str, Any]) -> None:
        """Added corpus lines may cite only blocks this run read (knobs and
        probe) or the base corpus cites, and no spec past live."""
        run_blocks = set()
        for raw, key in ((ctx.get("knobs"), "block_number"),
                         (self.preflight_probe, "block")):
            try:
                value = json.loads(raw or "{}").get(key)
            except ValueError:
                value = None
            if isinstance(value, int):
                run_blocks.add(value)
        before = ctx.get("base_corpus") or {}
        base_blocks = set()
        for text in before.values():
            base_blocks |= cited_blocks(text)
        after = corpus_texts(os.path.join(self.worktree, CORPUS_PATH))
        bad = citation_violations(added_lines(before, after), ctx["spec"],
                                  run_blocks, base_blocks)
        if bad:
            raise StepFailed("citation", "; ".join(bad[:5]))

    def sandboxed(self, cwd: str, argv: List[str],
                  network: bool = False) -> List[str]:
        return sandbox.sandbox_cmd(self.worktree, cwd, argv, network=network)

    def step_sandbox(self, state: Dict[str, Any],
                     ctx: Dict[str, Any]) -> None:
        """Prove the gate sandbox from inside, through the same builder,
        with and without network. Fails closed."""
        if not self.bwrap_present():
            raise StepFailed("sandbox", "%s is missing" % sandbox.BWRAP)
        for network in (False, True):
            cmd = sandbox.canary_cmd(sys.executable, self.canary,
                                     self.worktree, network,
                                     self.secret_paths)
            result = self.run(cmd, self.worktree, self.timeout("canary"))
            bad = sandbox.canary_failures(result.out)
            if bad:
                raise StepFailed("sandbox", "canary (network %s) failed: %s"
                                 " %s" % (network, ", ".join(bad),
                                          _tail(result.err, 200)))

    def step_test(self, state: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        dirs = test_dirs(self.worktree)
        if not dirs:
            raise StepFailed("test", "no test suites found")
        for path in dirs:
            result = self.run(self.sandboxed(path, [
                sys.executable, "-m", "unittest", "discover", "-s", "."]),
                path, self.timeout("suite"))
            if result.rc != 0:
                raise StepFailed("test", "%s failed: %s" % (
                    os.path.relpath(path, self.worktree),
                    _tail(result.err or result.out, 300)))

    def step_probe(self, state: Dict[str, Any],
                   ctx: Dict[str, Any]) -> None:
        result = self.run(self.sandboxed(self.worktree, [
            sys.executable, os.path.join(self.worktree, "livedata",
                                         "atlas_probe.py"), "check"],
            network=True), self.worktree, self.timeout("probe"))
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
            "--actor", "atlas-upgrade", timeout="ingest")
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
        # Scope again on the exact tree being committed: anything written
        # after the scope gate (by a gate or ingest) blocks the push.
        checked = set(self.check_scope())
        self.git("push", wt, "add", "-A")
        staged = set(filter(None, self.git(
            "push", wt, "diff", "--cached", "--name-only", "-z").split("\0")))
        if staged - checked:
            raise StepFailed("scope", "staged files not checked: %s"
                             % ", ".join(sorted(staged - checked)))
        self.git("push", wt, "commit", "-q", "-m",
                 "chore: ground Atlas at runtime spec %d" % ctx["spec"])
        author = self.git("push", wt, "log", "-1", "--format=%an <%ae>")
        if author != AUTHOR_IDENT:
            raise StepFailed("push", "commit author is %r" % author)
        ctx["commit"] = self.git("push", wt, "rev-parse", "HEAD")
        # The pull after the push must fast-forward: no local commits.
        if self.git("push", self.root, "status", "--porcelain"):
            raise StepFailed("push", "the live tree has uncommitted changes")
        if not self.is_ancestor("HEAD", "origin/main"):
            raise StepFailed("push", "the live tree has local commits")
        before = self.git("push", self.root, "rev-parse", "HEAD")
        state["post_push"] = {"commit": ctx["commit"],
                              "run_id": ctx["run_id"], "gate": None}
        self.save_state(state)
        self.git("push", wt, "push", "origin", "HEAD:main",  # never forced
                 env=dict(self.git_env, GIT_SSH_COMMAND=DEPLOY_SSH))
        remote = self.git("readback", self.root, "ls-remote", "origin",
                          "refs/heads/main").split()
        if not remote or remote[0] != ctx["commit"]:
            raise StepFailed("readback", "remote main is %s, pushed %s"
                             % (remote[:1], ctx["commit"]))
        self.git("pull", self.root, "pull", "--ff-only", "origin", "main")
        if self.git("pull", self.root, "rev-parse", "HEAD") != ctx["commit"]:
            raise StepFailed("pull", "live tree did not reach %s"
                             % ctx["commit"])
        # Code the pull brought in: others' commits since the last pull,
        # and the upgrade commit itself when it touched chain readers.
        ctx["code_commits"] = self.code_commits(before, ctx["commit"])

    def step_activate(self, state: Dict[str, Any],
                      ctx: Dict[str, Any]) -> None:
        self.py("activate", self.root, os.path.join(
            self.root, "knowledge", "atlas_kb.py"), "activate",
            "--db", self.kb_db, "--run", ctx["run_id"],
            "--actor", "atlas-upgrade", timeout="ingest")


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
        state.pop("post_push", None)
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
