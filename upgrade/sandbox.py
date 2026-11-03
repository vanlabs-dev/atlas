"""Sandbox for the upgrade job's gates (change: upgrade-sandbox-scope).

The test suites and the chain-read probe run on the edited worktree. They
run inside bubblewrap (`bwrap`), as the same user, with:

- system directories read-only, nothing else of the host filesystem;
- the worktree read-only;
- an empty private /tmp, /run and home (no SSH keys, no Hermes or Claude
  home, no repo .env, no user or system bus, no docker socket);
- a cleared environment with a fixed minimal set;
- new user, PID, IPC, UTS and cgroup namespaces, and no network unless the
  caller asks for it (the probe needs RPC);
- NO_NEW_PRIVS (bwrap sets it), so sudo cannot raise privileges.

`sandbox_cmd` only builds the argv. The canary (sandbox_canary.py) checks
those properties from inside, through the same builder, before the gates
run; the job fails closed when any check does not hold.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Sequence

BWRAP = "/usr/bin/bwrap"
# Read-only system directories. Each is bound only when it exists; on a
# merged-/usr system /bin, /lib and /sbin are symlinks and are recreated as
# symlinks so interpreters and shebangs resolve.
SYSTEM_DIRS = ("/usr", "/etc")
SYSTEM_LINKS = ("/bin", "/lib", "/lib64", "/sbin")
ENV_PATH = "/usr/local/bin:/usr/bin:/bin"
CANARY_PATH = "/atlas-canary.py"


def sandbox_env(home: str) -> Dict[str, str]:
    return {"PATH": ENV_PATH, "HOME": home, "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": "/tmp"}


def sandbox_cmd(worktree: str, cwd: str, argv: Sequence[str],
                network: bool = False, home: str = "",
                extra_ro: Sequence[tuple] = ()) -> List[str]:
    """The bwrap argv that runs `argv` in `cwd` (inside `worktree`).
    `extra_ro` is (host path, sandbox path) pairs bound read-only."""
    home = home or os.path.expanduser("~")
    cmd = [BWRAP, "--unshare-all"]
    if network:
        cmd.append("--share-net")
    cmd += ["--die-with-parent", "--new-session", "--clearenv"]
    for key, value in sorted(sandbox_env(home).items()):
        cmd += ["--setenv", key, value]
    for path in SYSTEM_DIRS:
        if os.path.isdir(path):
            cmd += ["--ro-bind", path, path]
    for path in SYSTEM_LINKS:
        if os.path.islink(path):
            cmd += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            cmd += ["--ro-bind", path, path]
    cmd += ["--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", "/home",
            "--dir", home,
            "--ro-bind", worktree, worktree]
    if network:
        # A resolver file linked into /run (systemd-resolved) would vanish
        # under the private /run: bind that one file back, read-only.
        real = os.path.realpath("/etc/resolv.conf")
        if real.startswith("/run/") and os.path.isfile(real):
            cmd += ["--ro-bind", real, real]
    for host, inside in extra_ro:
        cmd += ["--ro-bind", host, inside]
    cmd += ["--chdir", cwd, "--"] + list(argv)
    return cmd


def canary_cmd(python: str, canary: str, worktree: str, network: bool,
               secrets: Sequence[str], home: str = "") -> List[str]:
    """Run the canary through the same builder the gates use."""
    spec = {"network": network, "worktree": worktree,
            "secrets": list(secrets)}
    return sandbox_cmd(worktree, worktree,
                       [python, "-I", CANARY_PATH, json.dumps(spec)],
                       network=network, home=home,
                       extra_ro=[(canary, CANARY_PATH)])


# Every check the canary must report as holding. A missing name counts as
# a failure, so a canary that skips a check cannot pass.
CANARY_CHECKS = ("secrets_absent", "sockets_absent", "no_new_privs",
                 "sudo_fails", "worktree_read_only", "env_clean",
                 "network_as_asked")


def canary_failures(output: str) -> List[str]:
    """Checks that did not hold, from the canary's JSON output. Anything
    unparseable is one failure, never a pass."""
    try:
        checks = json.loads(output)["checks"]
    except (ValueError, KeyError, TypeError):
        return ["canary output unreadable"]
    if not isinstance(checks, dict):
        return ["canary output unreadable"]
    return [name for name in CANARY_CHECKS if checks.get(name) is not True]
