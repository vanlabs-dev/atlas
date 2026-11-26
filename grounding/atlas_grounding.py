#!/usr/bin/env python3
"""Atlas chain grounding job (change: chain-grounding).

Publishes GROUNDING.md, a short, machine-checked summary of how the
Bittensor chain works on mainnet, for cloud sessions that cannot reach
the Pi. Runs hourly on the Pi:

    detect    git ls-remote (v* tags, main) and the live spec_version.
              Nothing moved and nothing queued: exit.
    snapshot  On a new live spec: snapshots/<spec>/ and DIFF.md.
    stale     The tag diff against every claim's watched paths.
    verify    Per section with stale claims: a worker `claude -p`, a code
              check of every citation, a critic `claude -p` with no tools.
    render    GROUNDING.md from grounding/claims.yaml.
    push      Scope, size and render checks, the sandbox canary and every
              test suite, then a vaNlabs commit pushed with the Atlas
              deploy key (never forced) and read back.

It holds the upgrade job's lock (var/upgrade/lock), so the two jobs never
run at once and never push at the same time. It works in its own worktree
(~/atlas-grounding, branch grounding/work) and never pulls the live tree:
the upgrade job's pull brings the generated files in with everything else.

    python3 grounding/atlas_grounding.py run
    python3 grounding/atlas_grounding.py status
    python3 grounding/atlas_grounding.py force --from v495 --to v497
    python3 grounding/atlas_grounding.py bootstrap [--no-push]
    python3 grounding/atlas_grounding.py review list|accept|reject|recheck
    python3 grounding/atlas_grounding.py render [--check]
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(ROOT, "upgrade"))
sys.path.insert(2, os.path.join(ROOT, "livedata"))
sys.path.insert(3, os.path.join(ROOT, "repotrack"))

import atlas_upgrade as up  # noqa: E402
import atlas_live as al  # noqa: E402
import atlas_repo as arp  # noqa: E402
import atlas_telegram as tg  # noqa: E402
import grounding_scope  # noqa: E402
import history  # noqa: E402
import ledger  # noqa: E402
import render  # noqa: E402
import snapshot  # noqa: E402
import verify  # noqa: E402

CONFIG_FILE = os.path.join(_HERE, "config.json")
CLAIMS = "grounding/claims.yaml"
GROUNDING = "GROUNDING.md"
BRANCH = "grounding/work"
RAW_URL = ("https://raw.githubusercontent.com/vanlabs-dev/atlas/main/"
           "GROUNDING.md")
DETECT_FAIL_PAGE = 3  # consecutive failed detections before a page
WORKER_FAIL_LIMIT = 3  # worker failures on one section before UNVERIFIED
PUSH_RESERVE = 15 * 60
TIMEOUT = {"git": 120, "ls-remote": 60, "repotrack": 600, "smoke": 120,
           "history": 90}
GATE_PHRASES = {
    "prepare": "Setting up the grounding worktree failed.",
    "snapshot": "Reading the chain snapshot failed.",
    "scope": "The grounding commit touched files outside its scope.",
    "size": "GROUNDING.md came out over the size limit.",
    "render": "GROUNDING.md does not match the claims ledger.",
    "sandbox": "The gate sandbox failed its isolation check.",
    "test": "A test suite failed on the grounding tree.",
    "push": "Pushing the grounding commit to main failed.",
    "readback": "The pushed grounding commit could not be read back.",
    "rebase": "Unpushed grounding commits no longer apply to main and "
              "were dropped.",
}


def utc(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def load_config() -> Dict[str, Any]:
    with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _plain(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return None  # undecodable (hex): never shown as a value
    return value if isinstance(value, str) else json.dumps(value)


def live_value(item: str, chain: Dict[str, Any],
               subnets: Dict[str, Any]) -> Optional[str]:
    """What mainnet holds for a storage item at the snapshot block: the
    chain-wide value, or the most common per-subnet value with its count
    over the non-root subnets. None when the snapshot lacks the item."""
    if item in chain:
        text = _plain(chain[item]["value"])
        if text is None:
            return None
        return text + (" (unset, default)" if chain[item]["state"] == "unset"
                       else "")
    entry = subnets["items"].get(item) or subnets["items"].get("Swap." + item)
    if entry is None:
        return None
    netuids = [str(n) for n in subnets["netuids"] if int(n) != 0]
    counts: Dict[str, int] = {}
    for netuid in netuids:
        text = _plain(entry["values"].get(netuid, entry.get("default")))
        if text is not None:
            counts[text] = counts.get(text, 0) + 1
    if not counts:
        return None
    top = max(sorted(counts), key=lambda k: counts[k])
    if counts[top] == len(netuids):
        return "%s on all %d subnets" % (top, len(netuids))
    return "%s on %d of %d subnets" % (top, counts[top], len(netuids))


class Gate(Exception):
    def __init__(self, gate: str, detail: str) -> None:
        super().__init__("%s: %s" % (gate, detail))
        self.gate = gate
        self.detail = detail


class Job:
    """`run`, `now`, `send`, `live_spec`, `ls_remote` and `take_snapshot`
    are the seams the tests replace."""

    def __init__(self, root: str = ROOT, no_push: bool = False,
                 target: Optional[str] = None) -> None:
        self.root = root
        self.config = load_config()
        self.no_push = no_push
        self.var = os.environ.get("ATLAS_GROUNDING_VAR") or os.path.join(
            root, "var", "grounding")
        self.lock_path = os.environ.get("ATLAS_GROUNDING_LOCK") or \
            os.path.join(root, "var", "upgrade", "lock")
        self.clone = os.environ.get("ATLAS_SUBTENSOR_CLONE") or \
            os.path.join(root, "var", "repotrack", "subtensor")
        self.worktree = target or os.environ.get(
            "ATLAS_GROUNDING_WORKTREE") or os.path.join(
                os.path.dirname(root), "atlas-grounding")
        self.uses_worktree = target is None
        self.claude = os.environ.get("ATLAS_CLAUDE_BIN", "claude")
        self.model = up.MODEL  # tools/claude-model.json
        self.livedata_db = os.path.join(root, "var", "livedata",
                                        "livedata.db")
        self.spec_history_file = os.environ.get("ATLAS_SPEC_HISTORY")
        self.state_path = os.path.join(self.var, "state.json")
        self.deadline: Optional[float] = None
        self.git_env = dict(os.environ, GIT_AUTHOR_NAME=up.AUTHOR_NAME,
                            GIT_AUTHOR_EMAIL=up.AUTHOR_EMAIL,
                            GIT_COMMITTER_NAME=up.AUTHOR_NAME,
                            GIT_COMMITTER_EMAIL=up.AUTHOR_EMAIL)
        # The upgrade job's helpers: release anchors, the source export,
        # the gate sandbox and the test suites.
        self.up = up.Job(root=root, worktree=self.worktree)
        self.up.clone = self.clone
        self.up.var = os.environ.get("ATLAS_SOURCE_VAR") or self.up.var
        self.usage: List[Dict[str, Any]] = []

    # -- seams --------------------------------------------------------------

    def now(self) -> float:
        return time.time()

    def run(self, cmd: List[str], cwd: str, timeout: int,
            env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                                  text=True, errors="replace",
                                  timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, "", "timed out after %ds" % timeout
        except OSError as exc:
            return 127, "", str(exc)
        return proc.returncode, proc.stdout, proc.stderr

    def send(self, msg: "tg.Message") -> bool:
        if self.no_push:
            print("[report] " + msg.plain())
            return True
        try:
            return tg.send_alert(msg, "grounding-report")
        except tg.FatalTelegramError as exc:
            print("telegram: %s" % tg.redact(str(exc)), file=sys.stderr)
            return False

    def live_spec(self) -> Dict[str, Any]:
        return al.read_live_spec(al.load_config())

    def ls_remote(self) -> Optional[Dict[str, str]]:
        rc, out, err = self.run(["git", "ls-remote", self.config["remote"],
                                 "refs/tags/v*", "refs/heads/main"],
                                self.root, TIMEOUT["ls-remote"])
        if rc != 0:
            print("ls-remote failed: %s" % up._tail(err), file=sys.stderr)
            return None
        return history.parse_ls_remote(out)

    def take_snapshot(self) -> Dict[str, Any]:
        return snapshot.take(self.config, al.load_config())

    # -- helpers ------------------------------------------------------------

    def git(self, cwd: str, *args: str, gate: str = "prepare",
            env: Optional[Dict[str, str]] = None) -> str:
        rc, out, err = self.run(["git"] + list(args), cwd, TIMEOUT["git"],
                                env or self.git_env)
        if rc != 0:
            raise Gate(gate, "git %s: %s" % (args[0], up._tail(err or out)))
        return out.rstrip("\n")

    def clone_git(self, *args: str) -> Tuple[int, str]:
        rc, out, _ = self.run(["git"] + list(args), self.clone,
                              TIMEOUT["history"])
        return rc, out

    def load_state(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        os.makedirs(self.var, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, self.state_path)

    def path(self, rel: str) -> str:
        return os.path.join(self.worktree, rel)

    def report(self, state: Dict[str, Any], key: str,
               msg: "tg.Message") -> None:
        """One delivery per key; an undelivered report is retried first
        thing next run."""
        reported = state.setdefault("reported", [])
        if key in reported:
            return
        if self.send(msg):
            reported.append(key)
            del reported[:-40]
        else:
            state["pending_report"] = {"key": key, "message": msg.to_dict()}

    def flush_pending(self, state: Dict[str, Any]) -> None:
        pending = state.get("pending_report")
        if pending and self.send(tg.Message.from_dict(pending["message"])):
            state.setdefault("reported", []).append(pending["key"])
            state.pop("pending_report")

    def time_left(self) -> float:
        return float("inf") if self.deadline is None else \
            self.deadline - self.now()

    # -- the run ------------------------------------------------------------

    def locked(self, body: Any) -> int:
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        with open(self.lock_path, "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("the upgrade lock is held; trying again next run")
                return 0
            return body()

    def run_once(self) -> int:
        self.deadline = self.now() + self.config["run_budget_seconds"]
        return self.locked(self._run)

    def _run(self, force: Optional[Tuple[str, str]] = None,
             bootstrap: Optional[List[str]] = None,
             recheck: Optional[List[str]] = None) -> int:
        state = self.load_state()
        self.flush_pending(state)
        state["last_run"] = utc(self.now())
        detected = self.detect(state)
        if detected is None:
            self.save_state(state)
            return 0
        spec, refs, newest = detected
        digest = "%d|%s|%s" % (spec, refs.get("refs/heads/main"), newest)
        heartbeat_due = (self.now() - float(state.get("last_commit_at") or 0)
                         >= self.config["heartbeat_seconds"])
        quiet = (force is None and bootstrap is None and not recheck
                 and digest == state.get("digest")
                 and not state.get("backlog") and not heartbeat_due
                 and not state.get("unpushed"))
        if quiet:
            state["last_success"] = utc(self.now())
            self.save_state(state)
            print("no change (spec %d, %s)" % (spec, newest))
            return 0
        try:
            outcome = self.work(state, spec, refs, newest, force, bootstrap,
                                recheck)
        except Gate as exc:
            print("failed at %s: %s" % (exc.gate, exc.detail),
                  file=sys.stderr)
            state["last_error"] = "%s: %s" % (exc.gate, up._tail(exc.detail,
                                                                  600))
            self.report(state, "fail:%s:%s" % (exc.gate, digest), tg.Message(
                severity="act",
                headline="Chain grounding stopped at the %s step" % exc.gate,
                meaning=GATE_PHRASES.get(exc.gate, "The %s step failed."
                                         % exc.gate) +
                " GROUNDING.md on main is unchanged. Atlas tries again "
                "next run.",
                details=[up.RAW_ERROR_HINT % tg.mono(
                    "python3 grounding/atlas_grounding.py status")]))
            self.save_state(state)
            return 0
        state["digest"] = digest
        state["last_success"] = utc(self.now())
        state["last_error"] = None
        state.update(outcome)
        self.save_state(state)
        return 0

    def detect(self, state: Dict[str, Any]
               ) -> Optional[Tuple[int, Dict[str, str], str]]:
        refs = self.ls_remote()
        live = self.live_spec()
        if refs is None or not live.get("ok"):
            failures = int(state.get("detect_failures") or 0) + 1
            state["detect_failures"] = failures
            print("detection failed (%d in a row): %s" % (
                failures, "ls-remote" if refs is None else live.get("error")))
            if failures == DETECT_FAIL_PAGE:
                self.report(state, "detect:%s" % state["last_run"][:13],
                            tg.Message(
                                severity="act",
                                headline="Chain grounding cannot read the "
                                         "chain or GitHub",
                                meaning="%d checks in a row failed. "
                                        "GROUNDING.md is not being "
                                        "refreshed and will look stale "
                                        "after 7 days." % failures))
            return None
        state["detect_failures"] = 0
        tags = history.release_tags(refs)
        if not tags:
            print("no v<spec> tags in ls-remote output")
            return None
        newest = "v%d" % max(tags)
        return live["spec_version"], refs, newest

    def work(self, state: Dict[str, Any], spec: int, refs: Dict[str, str],
             newest: str, force: Optional[Tuple[str, str]],
             bootstrap: Optional[List[str]],
             recheck: Optional[List[str]] = None) -> Dict[str, Any]:
        self.prepare(state)
        self.refresh_clone(spec, refs)
        try:
            anchor, _ = self.up.anchor(spec)
        except up.Waiting as exc:
            self.report(state, "anchor:%d" % spec, tg.Message(
                severity="info",
                headline="Chain grounding waiting for the spec %d release"
                         % spec,
                meaning="The subtensor clone has no release for the live "
                        "spec yet: %s. Atlas checks again each run."
                        % exc.detail))
            return {"backlog": True}
        tag = "v%d" % spec
        data = ledger.load(self.path(CLAIMS))
        meta = data["meta"]
        commits: List[str] = []

        # Snapshot (deterministic).
        snap_dir = self.path(os.path.join("snapshots", str(spec)))
        if not os.path.isfile(os.path.join(snap_dir, "meta.json")):
            self.write_snapshot(data, spec, anchor, tag)
            commits.append("Snapshot runtime spec %d" % spec)

        self.refresh_live_values(data, spec)

        # Stale claims from the release diff.
        marked: List[str] = []
        old_spec = meta.get("spec_version")
        if isinstance(old_spec, int) and old_spec != spec:
            marked += self.mark_from_diff(data, "v%d" % old_spec, tag)
        if force:
            marked += self.mark_from_diff(data, force[0], force[1])
        if recheck:
            marked += self.mark_recheck(data, recheck)
        meta.update(spec_version=spec, subtensor_tag=tag,
                    subtensor_commit=anchor, newest_tag=newest,
                    newest_tag_live=int(newest[1:]) <= spec)
        self.deterministic_meta(data, spec, anchor)
        if commits or marked:
            self.write_outputs(data, content_only=True)
            self.commit_local(commits[0] if commits else
                              "Mark grounding claims stale at spec %d"
                              % spec)

        # Verification (model), capped per run.
        source_dir = self.up.export_source(spec, anchor)
        sections = bootstrap or ledger.stale_sections(data)
        cap = len(sections) if bootstrap or force or recheck else \
            self.config["max_sections_per_run"]
        results: Dict[str, Dict[str, int]] = {}
        new_unverified: List[str] = []
        if sections and self.auth_ok(state, spec):
            for section in sections[:cap]:
                need = (self.config["worker_timeout_seconds"]
                        + self.config["critic_timeout_seconds"]
                        + PUSH_RESERVE)
                if self.time_left() < need:
                    print("out of run budget; %s waits for next run"
                          % section)
                    break
                counts, unverified = self.verify_section(
                    state, data, section, spec, tag, anchor, source_dir,
                    fresh=bool(bootstrap))
                results[section] = counts
                new_unverified += unverified
                self.write_outputs(data, content_only=True)

        # Live values again: verification may have added claims.
        self.refresh_live_values(data, spec)

        # Render, then decide whether to commit. A run that checked
        # claims, or a due heartbeat, refreshes last_updated even when the
        # rendered content is the same.
        heartbeat = (self.now() - float(state.get("last_commit_at") or 0)
                     >= self.config["heartbeat_seconds"])
        changed = self.write_outputs(data, content_only=False,
                                     heartbeat=heartbeat or bool(results))
        if results:
            self.commit_local("Ground chain claims at spec %d" % spec)
        elif changed:
            self.commit_local("Update chain grounding at spec %d" % spec)
        elif heartbeat:
            self.commit_local("Refresh the grounding heartbeat")
        outcome: Dict[str, Any] = {
            "backlog": bool(ledger.stale_sections(data)), "spec": spec}
        pushed = self.push(state)
        if pushed:
            outcome["last_commit_at"] = self.now()
            outcome["unpushed"] = False
            self.report_results(state, spec, pushed, results,
                                new_unverified, data)
        return outcome

    # -- steps --------------------------------------------------------------

    def prepare(self, state: Dict[str, Any]) -> None:
        """The worktree on branch grounding/work at origin/main. Commits a
        failed push left behind are rebased onto origin/main and pushed
        with this run's work; when they no longer apply they are dropped
        and reported."""
        if not self.uses_worktree:
            return
        self.git(self.root, "fetch", "origin")
        base = self.git(self.root, "rev-parse", "origin/main")
        if not os.path.isdir(self.worktree):
            self.git(self.root, "worktree", "prune")
            exists = self.run(["git", "rev-parse", "--verify", "--quiet",
                               "refs/heads/" + BRANCH], self.root,
                              TIMEOUT["git"])[0] == 0
            if exists:
                self.git(self.root, "worktree", "add", self.worktree, BRANCH)
            else:
                self.git(self.root, "worktree", "add", "-b", BRANCH,
                         self.worktree, base)
        wt = self.worktree
        self.git(wt, "reset", "-q", "--hard")
        self.git(wt, "clean", "-q", "-fd")
        ahead = self.git(wt, "rev-list", "--count", "%s..HEAD" % base)
        if ahead != "0":
            rc, _, err = self.run(["git", "rebase", "-q", base], wt,
                                  TIMEOUT["git"], self.git_env)
            if rc != 0:
                self.run(["git", "rebase", "--abort"], wt, TIMEOUT["git"])
                self.git(wt, "reset", "-q", "--hard", base)
                self.report(state, "rebase:%s" % base[:12], tg.Message(
                    severity="watch",
                    headline="Chain grounding dropped unpushed commits",
                    meaning=GATE_PHRASES["rebase"] + " The next runs "
                    "redo the work."))
                print("rebase failed: %s" % up._tail(err), file=sys.stderr)
        else:
            self.git(wt, "reset", "-q", "--hard", base)

    def refresh_clone(self, spec: int, refs: Dict[str, str]) -> None:
        """Update the subtensor clone when it lacks the live tag or the
        remote main moved past it. Same lock as the upgrade job."""
        head = self.clone_git("rev-parse", "HEAD")[1].strip()
        has_tag = self.clone_git("rev-parse", "--verify", "--quiet",
                                 "refs/tags/v%d" % spec)[0] == 0
        if has_tag and head == refs.get("refs/heads/main"):
            return
        if not os.path.isfile(os.path.join(self.root, "repotrack",
                                           "atlas_repo.py")) or \
                os.environ.get("ATLAS_SUBTENSOR_CLONE"):
            # A bootstrap clone outside var/: fetch it directly.
            self.run(["git", "fetch", "--tags", "origin"], self.clone,
                     TIMEOUT["repotrack"])
            self.run(["git", "merge", "--ff-only", "origin/main"],
                     self.clone, TIMEOUT["git"])
            return
        try:
            with arp.clone_lock(self.clone, up.CLONE_LOCK_WAIT,
                                sleep=time.sleep):
                self.run([sys.executable, os.path.join(
                    self.root, "repotrack", "atlas_repo.py"), "update"],
                    self.root, TIMEOUT["repotrack"],
                    dict(os.environ, **{arp.LOCK_HELD_ENV:
                                        os.path.abspath(self.clone)}))
        except arp.LockBusy as exc:
            print("clone busy: %s" % exc, file=sys.stderr)

    def write_snapshot(self, data: Dict[str, Any], spec: int, anchor: str,
                       tag: str) -> None:
        try:
            snap = self.take_snapshot()
        except snapshot.SnapshotError as exc:
            raise Gate("snapshot", str(exc))
        if snap["meta"]["spec_version"] != spec:
            raise Gate("snapshot", "the chain moved to spec %s during the "
                       "run" % snap["meta"]["spec_version"])
        snap["meta"].update(tag=tag, commit=anchor)
        snaps = self.path("snapshots")
        previous = snapshot.previous_spec(snaps, spec)
        old = snapshot.load(os.path.join(snaps, str(previous))) \
            if previous else None
        directory = os.path.join(snaps, str(spec))
        snapshot.write(snap, directory)
        d = snapshot.diff(old, snap, self.config["dynamic"])
        with open(os.path.join(directory, "DIFF.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(snapshot.diff_markdown(
                d, snap["meta"], old["meta"] if old else None))
        routed = ledger.route_items(snapshot.new_items(d),
                                    self.config["section_keywords"])
        if routed:
            queued = data["meta"].get("queued_items") or {}
            for section, names in routed.items():
                queued[section] = sorted(set(queued.get(section, []))
                                         | set(names))
            data["meta"]["queued_items"] = queued

    def refresh_live_values(self, data: Dict[str, Any], spec: int) -> None:
        """Set `live_value` on every hyperparameter claim from the live
        spec's snapshot: deterministic, read from the chain, no model."""
        directory = self.path(os.path.join("snapshots", str(spec)))
        try:
            with open(os.path.join(directory, "chain.json"), "r",
                      encoding="utf-8") as handle:
                chain = json.load(handle)
            with open(os.path.join(directory, "subnets.json"), "r",
                      encoding="utf-8") as handle:
                subnets = json.load(handle)
        except FileNotFoundError:
            return
        for claim in data["claims"]:
            if claim["section"] != "hyperparameters" or not claim.get("item"):
                continue
            claim["live_value"] = live_value(claim["item"], chain, subnets)

    def mark_recheck(self, data: Dict[str, Any],
                     sections: List[str]) -> List[str]:
        """Operator re-check: every UNVERIFIED claim in `sections` goes
        stale, and the traps section queues every seed that has no
        verified claim. Verified claims are not touched."""
        marked = []
        for claim in data["claims"]:
            if claim["section"] in sections and claim.get("review"):
                claim["stale"] = True
                marked.append(claim["id"])
        if "traps" in sections:
            verified = {c.get("seed") for c in data["claims"]
                        if c.get("seed") and not c.get("review")}
            queue = (data["meta"].get("queued_items") or {})
            wanted = ["seed:" + s["id"] for s in data.get("seeds") or []
                      if s["id"] not in verified]
            if wanted:
                queue["traps"] = sorted(set(queue.get("traps", []))
                                        | set(wanted))
                data["meta"]["queued_items"] = queue
                # A seed placeholder is replaced by the seed's real claim.
                for claim in list(data["claims"]):
                    if claim.get("seed") and not claim.get("last_verified") \
                            and not claim.get("evidence"):
                        data["claims"].remove(claim)
        print("re-check of %s: %d UNVERIFIED claims stale: %s" % (
            ", ".join(sections), len(marked), ", ".join(marked)))
        return marked

    def mark_from_diff(self, data: Dict[str, Any], old_tag: str,
                       new_tag: str) -> List[str]:
        rc, _ = self.clone_git("rev-parse", "--verify", "--quiet", old_tag)
        if rc != 0:
            print("no tag %s in the clone; nothing marked" % old_tag)
            return []
        files = history.changed_files(self.clone_git, old_tag, new_tag)
        marked = ledger.mark_stale(data, files)
        print("%s..%s changed %d files; %d claims stale: %s" % (
            old_tag, new_tag, len(files), len(marked), ", ".join(marked)))
        return marked

    def deterministic_meta(self, data: Dict[str, Any], spec: int,
                           anchor: str) -> None:
        meta = data["meta"]
        hist = self.spec_history()

        def anchor_of(n: int) -> Optional[str]:
            rc, out = self.clone_git("rev-parse", "--verify", "--quiet",
                                     "refs/tags/v%d^{commit}" % n)
            return out.strip() if rc == 0 else None

        meta["changelog"] = history.changelog(self.clone_git, hist,
                                              anchor_of)
        head = self.clone_git("rev-parse", "HEAD")[1].strip()
        head_spec = self.up.clone_spec()
        meta["pending_on_main"] = history.pending(
            self.clone_git, anchor, head, head_spec, spec)
        dates = {e["spec"]: e["date"] for e in meta.get("spec_dates") or []}
        for entry in hist:
            dates[entry["new"]] = entry["date"]
        meta["spec_dates"] = [{"spec": n, "date": dates[n]}
                              for n in sorted(dates)]

    def spec_history(self) -> List[Dict[str, Any]]:
        if self.spec_history_file:
            with open(self.spec_history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return history.spec_history(self.livedata_db)

    def auth_ok(self, state: Dict[str, Any], spec: int) -> bool:
        rc, out, err = self.run([self.claude, "-p", "--restricted",
                                 "--strict-mcp-config", "--model",
                                 self.model, "--max-turns", "1",
                                 "--tools", "", "--", "reply ok"],
                                self.root, TIMEOUT["smoke"])
        if rc == 0:
            return True
        print("claude check failed: %s" % up._tail(err or out, 200),
              file=sys.stderr)
        limit = verify.usage_limit(out + "\n" + err)
        if limit:
            self.report(state, "limit:%s" % limit, tg.Message(
                severity="watch",
                headline="Chain grounding paused: Claude usage limit",
                meaning="The %s (model %s). Stale claims show as "
                        "UNVERIFIED in GROUNDING.md until then. Snapshots "
                        "and the heartbeat continue." % (
                            limit, self.model)))
            return False
        self.report(state, "auth:%d:%s" % (spec, utc(self.now())[:10]),
                    tg.Message(
                        severity="watch",
                        headline="Chain grounding waiting: the Claude login "
                                 "needs renewing",
                        meaning="Stale claims show as UNVERIFIED in "
                                "GROUNDING.md until the login works. "
                                "Snapshots and the heartbeat continue.",
                        next_action="log in to Claude on the Pi"))
        return False

    # -- verification -------------------------------------------------------

    def section_cfg(self, section: str) -> Dict[str, Any]:
        for entry in self.config["sections"]:
            if entry["id"] == section:
                return entry
        raise KeyError(section)

    def worker_prompt(self, data: Dict[str, Any], section: str, spec: int,
                      tag: str, anchor: str, source_dir: str,
                      fresh: bool) -> str:
        cfg = self.section_cfg(section)
        claims = [{"id": c["id"], "statement": c["statement"],
                   "status": c["status"], "stale": bool(c.get("stale")),
                   "evidence": [{"path": e["path"], "lines": e["lines"]}
                                for e in c.get("evidence") or []],
                   "watched_paths": c.get("watched_paths") or [],
                   **({"last_check": (c.get("review") or {}).get("reason")}
                      if c.get("stale") and c.get("review") else {}),
                   **({"seed": c["seed"]} if c.get("seed") else {}),
                   **({"item": c.get("item"), "default": c.get("default")}
                      if section == "hyperparameters" else {})}
                  for c in ledger.by_section(data, section)]
        queued = (data["meta"].get("queued_items") or {}).get(section) or []
        rules, extra = "", ""
        if section == "hyperparameters":
            rules = ("   Each claim names one storage item in `item` and "
                     "its code default in `default`, written as the runtime "
                     "metadata decodes it: an integer, true or false, or an "
                     "enum variant name. Code compares `default` with the "
                     "metadata of the live runtime.\n")
            extra = ', "item": "Tempo", "default": "360"'
        if section == "traps":
            rules = ("   Every claim here is a `deprecate` or `new` entry "
                     "about something that no longer applies. Add "
                     "`marker`: a short literal string from the cited "
                     "current code that the change introduced. Code dates "
                     "the change from the git history of that string.\n")
            extra = ', "marker": "..."'
        seeds = ""
        if section == "traps" and data.get("seeds"):
            info = getattr(self, "seed_info", {})
            lines = []
            for seed in data["seeds"]:
                ref, since = info.get(seed["id"], (None, None))
                lines.append("  - `%s`: %s Removed string: `%s`.%s" % (
                    seed["id"], seed["topic"], seed.get("removed") or "none",
                    "" if not ref else " Old code at `%s` (the last release "
                    "before spec %s) is exported to `%s`. Cite the old "
                    "lines that call or hold the removed string, with "
                    "`\"ref\": \"%s\"`, next to the current code." % (
                        ref, since, self.sources[ref][0], ref)))
            seeds = ("\n- Seeds, the operator's list of mechanisms older "
                     "docs still describe as current. Return exactly one "
                     "claim per seed, with `\"seed\": \"<id>\"`. Code "
                     "proves, and tells the checker, that the removed string "
                     "is absent from the code at this tag; do not try to "
                     "prove absence from cited lines. Cite the old code "
                     "that used it and the current code that replaced it:\n"
                     + "\n".join(lines))
        corpus = os.path.join(self.root, "knowledge", "corpus")
        return verify.template("worker.md").substitute(
            seeds=seeds,
            title=cfg["title"], section=section, scope=cfg["scope"],
            tag=tag, commit=anchor[:12], spec=spec, source_dir=source_dir,
            corpus_dir=corpus, claims=json.dumps(claims, indent=1),
            new_items=", ".join("`%s`" % n for n in queued) or "none",
            bootstrap=("\n\nThis is the first build of this section: there "
                       "are no current claims. Return only `new` entries."
                       if fresh and not claims else ""),
            max_lines=self.config["max_evidence_lines"],
            section_rules=rules, budget=cfg["budget"],
            target=max(4, cfg["budget"] // 240), extra_fields=extra)

    def verify_section(self, state: Dict[str, Any], data: Dict[str, Any],
                       section: str, spec: int, tag: str, anchor: str,
                       source_dir: str, fresh: bool
                       ) -> Tuple[Dict[str, int], List[str]]:
        """Worker, code check and critic for one section; applies the
        outcome to the ledger. Returns (counts, ids newly UNVERIFIED)."""
        counts = {"verified": 0, "unverified": 0, "removed": 0}
        unverified: List[str] = []
        existing = {c["id"]: c for c in ledger.by_section(data, section)}
        fails = state.setdefault("worker_failures", {})
        self.sources = {tag: (source_dir, anchor)}
        if section == "traps":
            self.sources.update(self.seed_sources(data, tag))
        prompt = self.worker_prompt(data, section, spec, tag, anchor,
                                    source_dir, fresh)
        corpus = os.path.join(self.root, "knowledge", "corpus")
        old_dirs = tuple(d for ref, (d, _) in self.sources.items()
                         if ref != tag)
        try:
            reply, usage = verify.run_claude(
                self.run_model, verify.worker_cmd(
                    self.claude, self.model, prompt, source_dir,
                    corpus, self.config["worker_max_turns"], old_dirs),
                source_dir,
                int(min(self.config["worker_timeout_seconds"],
                        max(60, self.time_left() - PUSH_RESERVE))))
            self.log_usage(section, "worker", usage)
            proposals = verify.validate_worker(reply, section,
                                               list(existing))
        except verify.ModelError as exc:
            fails[section] = int(fails.get(section, 0)) + 1
            print("worker for %s failed (%d): %s" % (section, fails[section],
                                                     exc), file=sys.stderr)
            if fails[section] >= WORKER_FAIL_LIMIT:
                for claim in existing.values():
                    if claim.get("stale") and not claim.get("review"):
                        claim["review"] = {"reason": "the checking run "
                                           "failed %d times" % fails[section],
                                           "at": utc(self.now())}
                        unverified.append(claim["id"])
                        counts["unverified"] += 1
                fails[section] = 0
            return counts, unverified
        fails.pop(section, None)
        # Seed fields belong to the operator's list, not the worker.
        seed_list = {x["id"]: x for x in data.get("seeds") or []}
        for proposal in proposals:
            seed = seed_list.get(proposal.get("seed"))
            if proposal.get("seed") and seed is None:
                proposal.pop("seed")
            proposal.pop("removed", None)
            if seed is not None and seed.get("removed"):
                proposal["removed"] = seed["removed"]
        snap = os.path.join(self.path("snapshots"), str(spec),
                            "pallets.json")
        pallets = None
        if os.path.isfile(snap):
            with open(snap, "r", encoding="utf-8") as handle:
                pallets = json.load(handle)

        checked: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
        seen = set()
        if not fresh:
            # Only stale claims are re-checked. The worker sees the whole
            # section for context; a change it proposes to a claim that is
            # not stale is ignored, so a release never churns claims whose
            # watched paths it did not touch.
            ignored = [p["id"] for p in proposals if p.get("id")
                       and not existing[p["id"]].get("stale")]
            if ignored:
                print("%s: ignored proposals for claims that are not "
                      "stale: %s" % (section, ", ".join(ignored)))
            proposals = [p for p in proposals if not p.get("id")
                         or existing[p["id"]].get("stale")]
            # New claims only for new extrinsics or storage items the
            # snapshot diff queued for this section.
            queue = (data["meta"].get("queued_items") or {}).get(section) \
                or []
            seeds_q = {q[5:] for q in queue if q.startswith("seed:")}
            items_q = [q for q in queue if not q.startswith("seed:")]

            def wanted(p: Dict[str, Any]) -> bool:
                return bool(p.get("id")) or bool(items_q) or \
                    p.get("seed") in seeds_q
            extra = [p for p in proposals if not wanted(p)]
            if extra:
                print("%s: ignored %d new claims (no new item or seed "
                      "queued for them)" % (section, len(extra)))
            proposals = [p for p in proposals if wanted(p)]
        judged: List[Dict[str, Any]] = []
        for proposal in proposals:
            if proposal.get("id"):
                seen.add(proposal["id"])
            if proposal["action"] == "remove":
                claim = existing[proposal["id"]]
                claim["review"] = {"reason": "the checking run proposes "
                                   "removal: %s" % str(
                                       proposal.get("reason") or "")[:200],
                                   "proposed": None, "at": utc(self.now())}
                claim["stale"] = False
                unverified.append(claim["id"])
                counts["unverified"] += 1
                continue
            judged.append(proposal)
        for cid, claim in existing.items():
            if cid not in seen and claim.get("stale"):
                claim["review"] = {"reason": "the checking run did not "
                                   "return this claim",
                                   "at": utc(self.now())}
                claim["stale"] = False
                unverified.append(cid)
                counts["unverified"] += 1

        # Code check and critic; then one retry for the claims rejected
        # only for a missing link (a binding, constant, caller or body the
        # citation left out). A rejection on substance stays UNVERIFIED.
        agreed, failed = self.judge(section, judged, source_dir, pallets,
                                    tag)
        retry = [(p, reason) for p, reason, kind in failed
                 if kind == "missing_context"]
        final = [(p, reason) for p, reason, kind in failed
                 if kind != "missing_context"]
        if retry:
            extended = self.retry_citations(section, retry, tag, source_dir)
            agreed2, failed2 = self.judge(section, extended, source_dir,
                                          pallets, tag)
            agreed += agreed2
            final += [(p, "after one citation retry: " + reason)
                      for p, reason, _ in failed2]
            counts["retried"] = len(retry)
            counts["retry_verified"] = len(agreed2)
        for proposal in agreed:
            self.apply_agreed(data, existing, proposal, tag, anchor, section)
            counts["verified"] += 1
        for proposal, reason in final:
            unverified.append(self.mark_unverified(
                data, existing, proposal, reason, tag, anchor))
            counts["unverified"] += 1
        if section == "traps":
            unverified += self.cover_seeds(data)
        dropped = self.fit_budget(data, section, set(existing))
        counts["removed"] += len(dropped)
        unverified = [u for u in unverified if u and u not in dropped]
        counts["unverified"] = sum(1 for u in unverified)
        queued = data["meta"].get("queued_items") or {}
        queued.pop(section, None)
        data["meta"]["queued_items"] = queued
        return counts, unverified

    def judge(self, section: str, proposals: List[Dict[str, Any]],
              source_dir: str, pallets: Optional[Dict[str, Any]], tag: str
              ) -> Tuple[List[Dict[str, Any]],
                         List[Tuple[Dict[str, Any], str, str]]]:
        """(agreed, failed) for proposals: the code check, then one critic
        run. Each failure carries (proposal, reason, kind); kind is
        `missing_context` when only a link is missing, else `wrong`."""
        dirs = {ref: d for ref, (d, _) in self.sources.items()}
        checked: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
        failed: List[Tuple[Dict[str, Any], str, str]] = []
        for proposal in proposals:
            problems, cited = verify.check_claim(
                proposal, source_dir, self.config["max_evidence_lines"],
                pallets, dirs)
            if problems:
                failed.append((proposal, "; ".join(problems[:2]),
                               verify.problem_kind(problems)))
            else:
                checked.append((proposal, cited))
        agreed: List[Dict[str, Any]] = []
        if not checked:
            return agreed, failed
        facts = {i: self.seed_facts(p, tag) for i, (p, _) in
                 enumerate(checked) if p.get("removed")}
        items = verify.critic_items(checked, tag,
                                    {i: f for i, f in facts.items() if f})
        prompt = verify.template("critic.md").substitute(
            tag=tag, items=json.dumps(items, indent=1))
        try:
            reply, usage = verify.run_claude(
                self.run_model, verify.critic_cmd(self.claude, self.model,
                                                  prompt),
                self.root, self.config["critic_timeout_seconds"])
            self.log_usage(section, "critic", usage)
            verdicts = verify.parse_verdicts(reply,
                                             [i["key"] for i in items])
        except verify.ModelError as exc:
            print("critic for %s failed: %s" % (section, exc),
                  file=sys.stderr)
            verdicts = {i["key"]: ("disagree", "the critic run failed",
                                   "wrong") for i in items}
        for index, (proposal, _) in enumerate(checked):
            verdict, reason, kind = verdicts["c%d" % index]
            if verdict == "agree":
                agreed.append(proposal)
            else:
                failed.append((proposal, "critic: " + reason, kind))
        return agreed, failed

    def seed_facts(self, proposal: Dict[str, Any], tag: str) -> List[str]:
        """What git proves about a seed's removed string: absent from
        `pallets/` at the tag, and since which release."""
        removed = proposal["removed"]
        rc, out = self.clone_git("grep", "-c", "-F", removed, tag, "--",
                                 "pallets")
        if rc == 0 and out.strip():
            return []  # still present: nothing to state
        since, floor = history.marker_since(self.clone_git, self.bumps(tag),
                                            removed, False)
        facts = ["`git grep -F` finds `%s` nowhere in `pallets/` at %s."
                 % (removed, tag)]
        if since is not None:
            facts.append("It has been absent from every release %s spec %d "
                         "on, and was present in the release before."
                         % ("since at least" if floor else "from", since)
                         if not floor else
                         "It has been absent from every release back to "
                         "spec %d." % since)
        return facts

    def retry_citations(self, section: str,
                        retry: List[Tuple[Dict[str, Any], str]], tag: str,
                        source_dir: str) -> List[Dict[str, Any]]:
        """One worker run that extends the citations of claims rejected for
        a missing link. It may narrow a statement, never widen it. Returns
        the proposals with the new statement and evidence; a claim the run
        did not return keeps its first-pass form (and fails again)."""
        items = [{"key": "r%d" % i, "statement": p["statement"],
                  "evidence": p.get("evidence"), "reason": reason}
                 for i, (p, reason) in enumerate(retry)]
        prompt = verify.template("retry.md").substitute(
            tag=tag, source_dir=source_dir,
            max_lines=self.config["max_evidence_lines"],
            old_refs=", ".join("`%s` (%s)" % (ref, d) for ref, (d, _) in
                               self.sources.items() if ref != tag) or "none",
            items=json.dumps(items, indent=1))
        corpus = os.path.join(self.root, "knowledge", "corpus")
        old_dirs = tuple(d for ref, (d, _) in self.sources.items()
                         if ref != tag)
        try:
            reply, usage = verify.run_claude(
                self.run_model, verify.worker_cmd(
                    self.claude, self.model, prompt, source_dir, corpus,
                    self.config["worker_max_turns"], old_dirs), source_dir,
                self.config["worker_timeout_seconds"])
            self.log_usage(section, "retry", usage)
        except verify.ModelError as exc:
            print("citation retry for %s failed: %s" % (section, exc),
                  file=sys.stderr)
            return [p for p, _ in retry]
        by_key = {c.get("key"): c for c in reply.get("claims") or []
                  if isinstance(c, dict)}
        out = []
        for index, (proposal, _) in enumerate(retry):
            new = by_key.get("r%d" % index)
            if new and isinstance(new.get("statement"), str) and \
                    isinstance(new.get("evidence"), list):
                proposal = dict(proposal, statement=new["statement"],
                                evidence=new["evidence"])
            out.append(proposal)
        return out

    def seed_sources(self, data: Dict[str, Any],
                     tag: str) -> Dict[str, Tuple[str, str]]:
        """For each seed with a `removed` string: the files that held it,
        exported at the last release that still had it, as
        {"spec-<N>": (dir, commit)}. The worker and the critic read old
        code only from these exports."""
        out: Dict[str, Tuple[str, str]] = {}
        self.seed_info: Dict[str, Tuple[str, int]] = {}
        bumps = self.bumps(tag)
        for seed in data.get("seeds") or []:
            removed = seed.get("removed")
            if not removed:
                continue
            since, floor = history.marker_since(self.clone_git, bumps,
                                                removed, False)
            before = [b for b in bumps if since is not None and b[0] < since]
            if since is None or floor or not before:
                continue
            spec, commit = before[-1]
            ref = "spec-%d" % spec
            target = os.path.join(self.var, "old", seed["id"], ref)
            rc, names = self.clone_git("grep", "-l", "-F", removed, commit,
                                       "--", "pallets")
            for line in names.splitlines() if rc == 0 else []:
                path = line.split(":", 1)[1]
                rc2, text = self.clone_git("show", "%s:%s" % (commit, path))
                if rc2 != 0:
                    continue
                full = os.path.join(target, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as handle:
                    handle.write(text)
            if os.path.isdir(target):
                out[ref] = (target, commit)
                self.seed_info[seed["id"]] = (ref, since)
        return out

    def cover_seeds(self, data: Dict[str, Any]) -> List[str]:
        """Every seed has a claim: one the run returned, or an UNVERIFIED
        placeholder naming the seed, so a known trap never goes missing."""
        added = []
        covered = {c.get("seed") for c in data["claims"]}
        for seed in data.get("seeds") or []:
            if seed["id"] in covered:
                continue
            claim = {"id": ledger.next_id(data, "traps"), "section": "traps",
                     "statement": seed["topic"], "evidence": [],
                     "live_since_spec": None, "status": "deprecated",
                     "last_verified": None, "watched_paths": [],
                     "stale": False, "seed": seed["id"],
                     "review": {"reason": "the checking run returned no "
                                "claim for seed %s" % seed["id"],
                                "at": utc(self.now())}}
            data["claims"].append(claim)
            added.append(claim["id"])
        return added

    def fit_budget(self, data: Dict[str, Any], section: str,
                   kept: set) -> List[str]:
        """Drop this run's new claims, last first and never-verified
        before verified, until the section fits its byte budget. Claims
        that existed before the run are never dropped for space."""
        budget = self.section_cfg(section)["budget"]
        new = [c for c in data["claims"] if c["section"] == section
               and c["id"] not in kept and not c.get("seed")]
        order = ([c for c in reversed(new) if not c.get("last_verified")]
                 + [c for c in reversed(new) if c.get("last_verified")])
        dropped: List[str] = []
        for claim in order:
            if render.section_bytes(data, self.config, section) <= budget:
                break
            data["claims"].remove(claim)
            dropped.append(claim["id"])
        if dropped:
            print("%s over its %d-byte budget: dropped %s" % (
                section, budget, ", ".join(dropped)))
        return dropped

    def run_model(self, cmd: List[str], cwd: str,
                  timeout: int) -> Tuple[int, str, str]:
        return self.run(cmd, cwd, timeout)

    def log_usage(self, section: str, role: str,
                  usage: Dict[str, Any]) -> None:
        record = dict(usage, section=section, role=role, at=utc(self.now()))
        self.usage.append(record)
        os.makedirs(self.var, exist_ok=True)
        with open(os.path.join(self.var, "usage.jsonl"), "a",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def evidence(self, proposal: Dict[str, Any], tag: str,
                 anchor: str) -> List[Dict[str, Any]]:
        out = []
        sources = getattr(self, "sources", {}) or {}
        for ev in proposal.get("evidence") or []:
            ref = ev.get("ref") if ev.get("ref") in sources else tag
            commit = sources[ref][1] if ref in sources else anchor
            out.append({"path": ev["path"],
                        "lines": "%d-%d" % (ev["start"], ev["end"]),
                        "ref": ref, "commit": commit})
        return out

    def bumps(self, tag: str) -> List[Tuple[int, str]]:
        """Release list at `tag` (history.release_bumps), cached per tag
        commit in var/grounding: it takes about a minute to build."""
        if getattr(self, "_bumps_tag", None) == tag:
            return self._bumps
        rc, sha = self.clone_git("rev-parse", "%s^{commit}" % tag)
        cache = os.path.join(self.var, "bumps-%s.json" % sha.strip()[:12])
        try:
            with open(cache, "r", encoding="utf-8") as handle:
                bumps = [tuple(b) for b in json.load(handle)]
        except (FileNotFoundError, ValueError):
            bumps = history.release_bumps(self.clone_git, tag)
            if bumps:
                os.makedirs(self.var, exist_ok=True)
                with open(cache, "w", encoding="utf-8") as handle:
                    json.dump(bumps, handle)
        self._bumps, self._bumps_tag = bumps, tag
        return bumps

    def date_evidence(self, evidence: List[Dict[str, Any]],
                      tag: str) -> Optional[int]:
        """Fill `pr` and `changed_in` per live-tag evidence range; returns
        the newest release in which any cited range last changed."""
        newest = None
        bumps = self.bumps(tag)
        for ev in evidence:
            if ev["ref"] != tag:
                continue  # old code, cited for a trap
            start, end = (int(x) for x in ev["lines"].split("-"))
            sha = history.last_change(self.clone_git, tag, ev["path"],
                                      start, end)
            ev["changed_in"] = sha
            ev["pr"] = history.pr_of(self.clone_git, sha, tag) if sha \
                else None
            spec = history.release_of(self.clone_git, bumps, sha) if sha \
                else None
            if spec is not None:
                newest = spec if newest is None else max(newest, spec)
        return newest

    def oldest_release(self, tag: str) -> Optional[int]:
        bumps = self.bumps(tag)
        return bumps[0][0] if bumps else None

    def apply_agreed(self, data: Dict[str, Any],
                     existing: Dict[str, Dict[str, Any]],
                     proposal: Dict[str, Any], tag: str, anchor: str,
                     section: str) -> None:
        evidence = self.evidence(proposal, tag, anchor)
        since = self.date_evidence(evidence, tag)
        deprecated = proposal["action"] == "deprecate" or section == "traps"
        if proposal.get("id"):
            claim = existing[proposal["id"]]
        else:
            target = section
            claim = {"id": ledger.next_id(data, target), "section": target}
            data["claims"].append(claim)
        oldest = self.oldest_release(tag)
        claim.update(
            statement=proposal["statement"].strip(), evidence=evidence,
            live_since_spec=since,
            live_since_floor=since is not None and since == oldest,
            status="deprecated" if deprecated else "live",
            last_verified=utc(self.now()),
            watched_paths=sorted(set(proposal.get("watched_paths") or [])
                                 | {e["path"] for e in evidence
                                    if e["ref"] == tag}),
            stale=False, review=None)
        if section == "hyperparameters":
            claim.update(item=proposal.get("item"),
                         default=str(proposal.get("default")))
        if proposal.get("seed"):
            claim["seed"] = proposal["seed"]
        if deprecated:
            # The stop release comes from the code tree, release by
            # release: since when the removed string has been absent, or
            # the replacement string present. A change that reached main
            # twice (PR #2781 at 421, then #2769 at 423 for the tao-flow
            # switch) is dated by when the code changed, not by commit.
            bumps = self.bumps(tag)
            removed, marker = proposal.get("removed"), proposal.get("marker")
            spec, floor = None, False
            for text, present in ((removed, False), (marker, True)):
                if isinstance(text, str) and text.strip():
                    spec, floor = history.marker_since(
                        self.clone_git, bumps, text, present)
                    if spec is not None:
                        break
            if spec is None:
                spec, floor = since, since is not None and since == oldest
            claim["deprecated_since_spec"] = spec
            claim["deprecated_since_floor"] = floor
            for key in ("marker", "removed"):
                if proposal.get(key):
                    claim[key] = proposal[key]

    def mark_unverified(self, data: Dict[str, Any],
                        existing: Dict[str, Dict[str, Any]],
                        proposal: Dict[str, Any], reason: str, tag: str,
                        anchor: str) -> str:
        review = {"reason": reason[:300], "proposed":
                  proposal.get("statement"),
                  "proposed_evidence": self.evidence_safe(proposal, tag,
                                                          anchor),
                  "at": utc(self.now())}
        if proposal.get("id"):
            claim = existing[proposal["id"]]
            claim.update(review=review, stale=False)
            return claim["id"]
        seed_fields = {k: proposal[k] for k in ("seed", "removed")
                       if isinstance(proposal.get(k), str)}
        section = proposal["section"]
        claim = {"id": ledger.next_id(data, section), "section": section,
                 "statement": proposal.get("statement") or "",
                 "evidence": self.evidence_safe(proposal, tag, anchor),
                 "live_since_spec": None,
                 "status": "deprecated" if section == "traps" or
                 proposal["action"] == "deprecate" else "live",
                 "last_verified": None,
                 "watched_paths": [p for p in proposal.get("watched_paths")
                                   or [] if isinstance(p, str)],
                 "stale": False, "review": review, **seed_fields}
        data["claims"].append(claim)
        return claim["id"]

    def evidence_safe(self, proposal: Dict[str, Any], tag: str,
                      anchor: str) -> List[Dict[str, Any]]:
        out = []
        for ev in proposal.get("evidence") or []:
            if isinstance(ev, dict) and isinstance(ev.get("path"), str) and \
                    isinstance(ev.get("start"), int) and \
                    isinstance(ev.get("end"), int):
                sources = getattr(self, "sources", {}) or {}
                ref = ev.get("ref") if ev.get("ref") in sources else tag
                out.append({"path": ev["path"], "lines": "%d-%d" % (
                    ev["start"], ev["end"]), "ref": ref,
                    "commit": sources[ref][1] if ref in sources
                    else anchor})
        return out

    # -- outputs and push ---------------------------------------------------

    def write_outputs(self, data: Dict[str, Any], content_only: bool,
                      heartbeat: bool = False) -> bool:
        """Write claims.yaml and GROUNDING.md. Returns True when the
        rendered content (everything but the timestamps) changed. With
        content_only the timestamps are left alone."""
        meta = data["meta"]
        digest = render.content_hash(data, self.config)
        changed = digest != meta.get("content_hash")
        now = utc(self.now())
        if not content_only and (changed or heartbeat):
            meta["last_updated"] = now
            if changed:
                meta["content_changed"] = now
                meta["content_hash"] = digest
        os.makedirs(self.path("grounding"), exist_ok=True)
        ledger.save(self.path(CLAIMS), data)
        with open(self.path(GROUNDING), "w", encoding="utf-8") as handle:
            handle.write(render.render(data, self.config))
        return changed

    def commit_local(self, message: str) -> None:
        if not self.uses_worktree:
            return
        wt = self.worktree
        entries = up.status_entries(self.git(
            wt, "status", "--porcelain=v1", "-z", "-uall", gate="scope"))
        if not entries:
            return
        bad = grounding_scope.scope_violations(entries)
        if bad:
            raise Gate("scope", ", ".join(bad))
        self.git(wt, "add", "-A", gate="scope")
        self.git(wt, "commit", "-q", "-m", message, gate="push")
        author = self.git(wt, "log", "-1", "--format=%an <%ae>",
                          gate="push")
        if author != up.AUTHOR_IDENT:
            raise Gate("push", "commit author is %r" % author)

    def check_tree(self) -> None:
        """The checks that run on the exact tree before a push."""
        size = os.path.getsize(self.path(GROUNDING))
        if size > self.config["max_bytes"]:
            raise Gate("size", "GROUNDING.md is %d bytes, limit %d" % (
                size, self.config["max_bytes"]))
        data = ledger.load(self.path(CLAIMS))
        with open(self.path(GROUNDING), "r", encoding="utf-8") as handle:
            if handle.read() != render.render(data, self.config):
                raise Gate("render", "GROUNDING.md is not the render of "
                           "claims.yaml")
        try:
            self.up.step_sandbox({}, {})
            self.up.step_test({}, {})
        except up.StepFailed as exc:
            raise Gate(exc.gate, exc.detail)

    def push(self, state: Dict[str, Any]) -> Optional[str]:
        """Push local grounding commits. Returns the pushed head, or None
        when there was nothing to push (or no push in this mode)."""
        if not self.uses_worktree:
            return None
        wt = self.worktree
        base = self.git(self.root, "rev-parse", "origin/main")
        if self.git(wt, "rev-list", "--count", "%s..HEAD" % base) == "0":
            return None
        state["unpushed"] = True
        self.save_state(state)
        changed = self.git(wt, "diff", "--name-status", "%s..HEAD" % base,
                           gate="scope").splitlines()
        bad = [line for line in changed if not grounding_scope.is_allowed(
            line.split("\t")[-1]) or line[:1] not in ("A", "M")]
        if bad:
            raise Gate("scope", ", ".join(bad))
        self.check_tree()
        if self.no_push:
            print("no-push: commits kept on %s" % BRANCH)
            return None
        head = self.git(wt, "rev-parse", "HEAD")
        self.git(wt, "push", "origin", "HEAD:main", gate="push",
                 env=dict(self.git_env, GIT_SSH_COMMAND=up.DEPLOY_SSH))
        remote = self.git(self.root, "ls-remote", "origin",
                          "refs/heads/main", gate="readback").split()
        if not remote or remote[0] != head:
            raise Gate("readback", "remote main is %s, pushed %s" % (
                remote[:1], head))
        self.git(self.root, "fetch", "origin")
        return head

    def report_results(self, state: Dict[str, Any], spec: int, head: str,
                       results: Dict[str, Dict[str, int]],
                       new_unverified: List[str],
                       data: Dict[str, Any]) -> None:
        if not results:
            return
        verified = sum(r["verified"] for r in results.values())
        unverified = sum(r["unverified"] for r in results.values())
        self.report(state, "updated:%s" % head[:12], tg.Message(
            severity="done" if not unverified else "watch",
            headline="Chain grounding updated for spec %d" % spec,
            meaning="%d claims verified, %d UNVERIFIED, in %s." % (
                verified, unverified, ", ".join(sorted(results))),
            facts=[("Commit", tg.mono(head[:8]))],
            details=(["UNVERIFIED: " + ", ".join(new_unverified[:12])]
                     if new_unverified else []),
            next_action=("review with %s" % tg.mono(
                "python3 grounding/atlas_grounding.py review list")
                if new_unverified else None),
            buttons=tg.button(None, "View commit", "atlas_commit",
                              sha=head)))


# -- operator review ----------------------------------------------------------

def review(args: argparse.Namespace) -> int:
    config = load_config()
    path = os.path.join(args.tree, CLAIMS)
    data = ledger.load(path)
    if args.action == "list":
        rows = [c for c in data["claims"] if c.get("review")
                or c.get("stale")]
        for claim in rows:
            rev = claim.get("review") or {}
            print("%s  [%s]" % (claim["id"], rev.get("reason")
                                or "stale, re-check queued"))
            print("  verified: %s" % (claim["statement"]
                                      if claim.get("last_verified")
                                      else "(never)"))
            if rev.get("proposed"):
                print("  proposed: %s" % rev["proposed"])
            for ev in rev.get("proposed_evidence") or claim.get(
                    "evidence") or []:
                print("  cites:    %s %s:%s" % (ev["ref"], ev["path"],
                                                ev["lines"]))
        print("%d claims need review" % len(rows))
        return 0
    if args.action == "seed":
        if not args.topic:
            print("review seed needs --topic")
            return 1
        seeds = [x for x in data.get("seeds") or [] if x["id"] != args.id]
        seeds.append({"id": args.id, "topic": args.topic,
                      **({"removed": args.removed} if args.removed else {}),
                      "added": utc(time.time())[:10]})
        data["seeds"] = seeds
        ledger.save(path, data)
        print("seed %s saved; the next `recheck --sections traps` covers it"
              % args.id)
        return 0
    claim = ledger.find(data, args.id)
    if claim is None:
        print("no claim %s" % args.id)
        return 1
    now = utc(time.time())
    rev = claim.get("review") or {}
    if args.action == "accept":
        if not rev.get("proposed") and rev:
            data["claims"].remove(claim)  # an accepted removal
        else:
            claim.update(statement=rev.get("proposed") or claim["statement"],
                         evidence=rev.get("proposed_evidence")
                         or claim["evidence"], last_verified=now,
                         verified_by="operator", review=None, stale=False)
    elif args.action == "reject":
        if not claim.get("last_verified"):
            data["claims"].remove(claim)
        else:
            claim.update(review=None, stale=False)
    elif args.action == "recheck":
        claim.update(review=None, stale=True)
    elif args.action == "remove":
        data["claims"].remove(claim)
    data["meta"]["content_changed"] = now
    data["meta"]["content_hash"] = render.content_hash(data, config)
    ledger.save(path, data)
    with open(os.path.join(args.tree, GROUNDING), "w",
              encoding="utf-8") as handle:
        handle.write(render.render(data, config))
    done = {"accept": "accepted", "reject": "rejected",
            "recheck": "queued for re-check", "remove": "removed"}
    print("%s %s; commit grounding/claims.yaml and GROUNDING.md" % (
        args.id, done[args.action]))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas chain grounding")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="one timer run")
    sub.add_parser("status", help="print the saved state")
    force = sub.add_parser("force", help="mark claims stale from a tag "
                           "diff and re-check them now")
    force.add_argument("--from", dest="old", required=True)
    force.add_argument("--to", dest="new", required=True)
    force.add_argument("--no-push", action="store_true")
    boot = sub.add_parser("bootstrap", help="build sections from scratch")
    boot.add_argument("--sections", nargs="*")
    boot.add_argument("--no-push", action="store_true")
    boot.add_argument("--target", help="write into this tree, no commits")
    rec = sub.add_parser("recheck", help="re-check UNVERIFIED claims and "
                         "uncovered seeds now")
    rec.add_argument("--sections", nargs="*")
    rec.add_argument("--no-push", action="store_true")
    rec.add_argument("--target", help="write into this tree, no commits")
    rev = sub.add_parser("review", help="operator review of UNVERIFIED")
    rev.add_argument("action", choices=("list", "accept", "reject",
                                        "recheck", "remove", "seed"))
    rev.add_argument("id", nargs="?")
    rev.add_argument("--tree", default=ROOT)
    rev.add_argument("--topic", help="seed: the mechanism, in one line")
    rev.add_argument("--removed", help="seed: a literal string the old "
                     "code had and the live code lacks")
    ren = sub.add_parser("render", help="re-render GROUNDING.md")
    ren.add_argument("--tree", default=ROOT)
    ren.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "run":
        return Job().run_once()
    if args.command == "status":
        job = Job()
        state = job.load_state()
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "force":
        job = Job(no_push=args.no_push)
        return job.locked(lambda: job._run(force=(args.old, args.new)))
    if args.command == "bootstrap":
        job = Job(no_push=args.no_push or bool(args.target),
                  target=args.target)
        sections = args.sections or [s["id"] for s in job.config["sections"]
                                     if s["id"] != "changelog"]
        return job.locked(lambda: job._run(bootstrap=sections))
    if args.command == "recheck":
        job = Job(no_push=args.no_push or bool(args.target),
                  target=args.target)
        sections = args.sections or [s["id"] for s in job.config["sections"]
                                     if s["id"] != "changelog"]
        return job.locked(lambda: job._run(recheck=sections))
    if args.command == "review":
        if args.action != "list" and not args.id:
            parser.error("review %s needs a claim id" % args.action)
        return review(args)
    config = load_config()
    data = ledger.load(os.path.join(args.tree, CLAIMS))
    text = render.render(data, config)
    target = os.path.join(args.tree, GROUNDING)
    if args.check:
        with open(target, "r", encoding="utf-8") as handle:
            same = handle.read() == text
        print("GROUNDING.md is %s" % ("current" if same else "STALE"))
        return 0 if same else 1
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
