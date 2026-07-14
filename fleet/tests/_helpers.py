"""Test helpers for the subnet-repo-fleet module: path wiring plus
throwaway origin repos for the clone/update tests."""

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_FLEET_DIR)
sys.path.insert(0, _FLEET_DIR)

import atlas_fleet as fleet  # noqa: E402


def git(cwd, *args):
    completed = subprocess.run(
        ["git", "-C", cwd] + list(args), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert completed.returncode == 0, "git %s failed: %s" % (
        " ".join(args), completed.stderr)
    return completed.stdout.strip()


def make_origin(tmp_dir, name="origin", files=None, branch="main"):
    """Non-bare fixture repository a fleet clone can fetch from. Enables the
    server-side partial-clone capability so `--filter=blob:none` works over
    the local transport (real GitHub advertises it)."""
    origin = os.path.join(tmp_dir, name)
    os.makedirs(origin)
    git(origin, "init", "-b", branch)
    git(origin, "config", "user.email", "test@atlas.local")
    git(origin, "config", "user.name", "Atlas Test")
    git(origin, "config", "commit.gpgsign", "false")
    git(origin, "config", "uploadpack.allowFilter", "true")
    git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    files = files or {"README.md": "# fixture subnet repo\n"}
    for rel_path, content in files.items():
        write_file(origin, rel_path, content)
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "initial fixture state")
    return origin


def write_file(root, rel_path, content):
    path = os.path.join(root, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def add_commit(origin, rel_path, content, message="update fixture"):
    write_file(origin, rel_path, content)
    git(origin, "add", "-A")
    git(origin, "commit", "-m", message)
    return git(origin, "rev-parse", "HEAD")
