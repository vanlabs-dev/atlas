"""Sandbox canary (change: upgrade-sandbox-scope).

Runs inside the gate sandbox (sandbox.py) and reports, as JSON on stdout,
whether each isolation property holds. It never raises: a check that
cannot be evaluated is reported as not holding.

    python3 -I sandbox_canary.py '{"network": false, "worktree": "...",
                                    "secrets": ["/home/pi/.ssh", ...]}'
"""

import errno
import json
import os
import socket
import subprocess
import sys

SOCKETS = ("/run/user/1000/bus", "/run/dbus/system_bus_socket",
           "/var/run/docker.sock", "/run/docker.sock")
SECRET_ENV = ("TELEGRAM", "ANTHROPIC", "HERMES", "GIT_SSH", "SSH_AUTH",
              "CLAUDE", "OPENAI", "TAOSTATS", "LIUM")


def check(fn):
    try:
        return fn() is True
    except Exception:  # a check that errors does not hold
        return False


def secrets_absent(spec):
    home = os.environ.get("HOME", "")
    paths = list(spec["secrets"]) + [os.path.join(home, name) for name in
                                     (".ssh", ".hermes", ".claude")]
    return not any(os.path.lexists(path) for path in paths)


def sockets_absent(spec):
    return not any(os.path.lexists(path) for path in SOCKETS)


def no_new_privs(spec):
    with open("/proc/self/status", "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("NoNewPrivs:"):
                return line.split()[1] == "1"
    return False


def sudo_fails(spec):
    try:
        result = subprocess.run(["sudo", "-n", "true"],
                                capture_output=True, timeout=10)
    except FileNotFoundError:
        return True
    return result.returncode != 0


def worktree_read_only(spec):
    path = os.path.join(spec["worktree"], ".atlas-canary-write")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
    except OSError as exc:
        return exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    os.unlink(path)
    return False


def env_clean(spec):
    return not any(word in key.upper() for key in os.environ
                   for word in SECRET_ENV)


def network_as_asked(spec):
    try:
        conn = socket.create_connection(("1.1.1.1", 443), timeout=5)
        conn.close()
        reached = True
    except OSError:
        reached = False
    if spec["network"]:
        return True  # the probe sandbox may reach the network
    return not reached


CHECKS = {"secrets_absent": secrets_absent, "sockets_absent": sockets_absent,
          "no_new_privs": no_new_privs, "sudo_fails": sudo_fails,
          "worktree_read_only": worktree_read_only, "env_clean": env_clean,
          "network_as_asked": network_as_asked}


def main(argv):
    try:
        spec = json.loads(argv[1])
    except (IndexError, ValueError):
        print(json.dumps({"checks": {}, "error": "bad spec"}))
        return 1
    checks = {name: check(lambda fn=fn: fn(spec))
              for name, fn in CHECKS.items()}
    print(json.dumps({"checks": checks}, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
