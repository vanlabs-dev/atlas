#!/usr/bin/env python3
"""Commit the spec-sync allowlist and fast-forward push it.

Uses the Atlas deploy key only. Refuses a dirty tree outside the
allowlist, a non-fast-forward, and a remote tip that does not match
the commit just pushed. Never force-pushes. Never prints the key.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.environ.get("ATLAS_ROOT", "/home/pi/atlas")
REMOTE = "git@github.com:vanlabs-dev/atlas.git"
BRANCH = "main"
AUTHOR_NAME = "vaNlabs"
AUTHOR_EMAIL = "vanlabs@pm.me"
SSH = (
    "ssh -i /home/pi/.ssh/atlas_maintenance_ed25519 "
    "-o IdentitiesOnly=yes -o BatchMode=yes "
    "-o StrictHostKeyChecking=yes"
)
ALLOW = (
    "README.md",
    "docs/decisions.md",
    "knowledge/atlas_spec_publish.py",
    "knowledge/atlas_spec_sync.py",
    "knowledge/corpus/SOURCES.md",
    "knowledge/corpus/fact-patterns.md",
    "knowledge/corpus/ground-truth.md",
    "knowledge/corpus/hashes.json",
    "knowledge/corpus/negative-claim-rules.md",
    "livedata/README.md",
    "livedata/config.json",
)
def subject() -> str:
    path = os.path.join(REPO, "knowledge", "corpus", "hashes.json")
    with open(path, "r", encoding="utf-8") as handle:
        spec = json.load(handle).get("grounded_spec")
    if not isinstance(spec, int):
        raise SystemExit("hashes.json has no grounded_spec")
    text = "docs: ground corpus at runtime spec %d" % spec
    if len(text) > 50:
        raise SystemExit("commit subject exceeds 50 characters")
    return text


def run(args, env=None, check=True):
    result = subprocess.run(
        args, cwd=REPO, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def git_env():
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = SSH
    env["GIT_AUTHOR_NAME"] = AUTHOR_NAME
    env["GIT_AUTHOR_EMAIL"] = AUTHOR_EMAIL
    env["GIT_COMMITTER_NAME"] = AUTHOR_NAME
    env["GIT_COMMITTER_EMAIL"] = AUTHOR_EMAIL
    return env


def identity_args():
    return [
        "-c", "user.name=%s" % AUTHOR_NAME,
        "-c", "user.email=%s" % AUTHOR_EMAIL,
    ]


def porcelain():
    result = run(["git", "status", "--porcelain"])
    rows = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append((line[:2], path))
    return rows


def main() -> int:
    push_url = run(
        ["git", "remote", "get-url", "--push", "origin"]).stdout.strip()
    if push_url != REMOTE:
        sys.stderr.write("push remote is not the Atlas SSH remote\n")
        return 1
    fetch = run(["git", "fetch", "origin", BRANCH], env=git_env())
    if fetch.returncode != 0:
        sys.stderr.write(fetch.stderr)
        return fetch.returncode
    local = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = run(
        ["git", "rev-parse", "origin/%s" % BRANCH]).stdout.strip()
    ahead = run(
        ["git", "merge-base", "--is-ancestor", remote, local],
        check=False)
    if ahead.returncode != 0:
        sys.stderr.write("local main is not a fast-forward of origin\n")
        return 1
    dirty = porcelain()
    outside = [path for _state, path in dirty if path not in ALLOW]
    if outside:
        sys.stderr.write("refusing dirty paths outside the allowlist:\n")
        for path in outside:
            sys.stderr.write("  %s\n" % path)
        return 1
    if dirty:
        run(["git", "add", "--"] + [path for _state, path in dirty])
        commit = run(
            ["git", *identity_args(), "commit", "-m", subject()],
            env=git_env())
        if commit.returncode != 0:
            sys.stderr.write(commit.stderr)
            return commit.returncode
        local = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        ident = run(["git", "log", "-1", "--format=%an <%ae>"]).stdout.strip()
        if ident != "%s <%s>" % (AUTHOR_NAME, AUTHOR_EMAIL):
            sys.stderr.write("commit author is not vaNlabs\n")
            return 1
    elif local == remote:
        sys.stdout.write("already published %s\n" % local)
        return 0
    push = run(
        ["git", "push", "origin", "HEAD:refs/heads/%s" % BRANCH],
        env=git_env(), check=False)
    if push.returncode != 0:
        sys.stderr.write("push refused\n")
        sys.stderr.write(push.stderr)
        return push.returncode
    shown = run(
        ["git", "ls-remote", "origin", "refs/heads/%s" % BRANCH],
        env=git_env()).stdout.split()
    if not shown or shown[0] != local:
        sys.stderr.write("remote tip does not match the commit\n")
        return 1
    sys.stdout.write("published %s\n" % local)
    return 0


if __name__ == "__main__":
    sys.exit(main())
