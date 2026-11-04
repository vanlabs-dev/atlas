#!/usr/bin/env python3
"""Nightly encrypted backup of the Pi's Atlas stores and Hermes state
(change: pi-offsite-backup).

    atlas_backup.py run            stage, upload, prune, check, write status
    atlas_backup.py stage          stage and check the SQLite copies only
    atlas_backup.py restore-check  restore the latest snapshot's store
                                   copies to scratch and check each one

Every SQLite file under the include roots is copied with the SQLite
online backup API into the staging dir, which sits under an include
root, so restic picks the copies up while the live files (and their
-wal/-shm) are excluded. restic encrypts on the device and writes to the
repository named by RESTIC_REPOSITORY, with the password read from
RESTIC_PASSWORD_FILE. Neither value is ever printed.
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")
SQLITE_MAGIC = b"SQLite format 3\x00"
REQUIRED_KEYS = ("include", "exclude_paths", "exclude_globs",
                 "required_stores", "staging", "status_file", "keep_daily",
                 "min_free_bytes")
REQUIRED_ENV = ("RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE")
STDERR_TAIL = 20


class BackupError(Exception):
    """A run must stop. The message is fixed text plus paths, never a
    secret."""


def log(msg: str) -> None:
    print(f"atlas-backup: {msg}", flush=True)


# ---------------------------------------------------------------------------
# Config and paths


def load_config(path: str) -> Dict:
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise BackupError(f"config {path} is missing {', '.join(missing)}")
    if not isinstance(cfg["keep_daily"], int) or cfg["keep_daily"] < 1:
        raise BackupError("config keep_daily must be a positive integer")
    return cfg


class Layout:
    """Absolute paths resolved against one home directory."""

    def __init__(self, cfg: Dict, home: str):
        self.home = os.path.abspath(home)
        self.cfg = cfg
        self.include = [self.abs(p) for p in cfg["include"]]
        self.exclude_paths = [self.abs(p) for p in cfg["exclude_paths"]]
        self.exclude_globs = list(cfg["exclude_globs"])
        self.required = [self.abs(p) for p in cfg["required_stores"]]
        self.staging = self.abs(cfg["staging"])
        self.status_file = self.abs(cfg["status_file"])
        self.scratch = os.path.join(os.path.dirname(self.staging),
                                    "restore-check")
        if not any(_under(self.staging, root) for root in self.include):
            raise BackupError("staging dir must sit under an include root")
        if self.is_excluded(self.staging):
            raise BackupError("staging dir must not be excluded")

    def abs(self, rel: str) -> str:
        return os.path.join(self.home, rel)

    def rel(self, path: str) -> str:
        return os.path.relpath(path, self.home)

    def is_excluded(self, path: str) -> bool:
        name = os.path.basename(path)
        if any(fnmatch.fnmatchcase(name, g) for g in self.exclude_globs):
            return True
        for pat in self.exclude_paths:
            if fnmatch.fnmatchcase(path, pat) or any(
                    fnmatch.fnmatchcase(parent, pat)
                    for parent in _parents(path, self.home)):
                return True
        return False


def _under(path: str, root: str) -> bool:
    path, root = os.path.abspath(path), os.path.abspath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _parents(path: str, stop: str) -> List[str]:
    out = []
    cur = os.path.dirname(path)
    while _under(cur, stop) and cur != stop:
        out.append(cur)
        cur = os.path.dirname(cur)
    return out


def _restic_escape(path: str) -> str:
    """Escape glob metacharacters so restic matches the path literally."""
    return "".join("\\" + c if c in "*?[]\\" else c for c in path)


# ---------------------------------------------------------------------------
# Staging


def is_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def find_databases(layout: Layout) -> List[str]:
    found = []
    for root in layout.include:
        if os.path.isfile(root):
            candidates = [root]
        elif os.path.isdir(root):
            candidates = []
            for dirpath, dirnames, filenames in os.walk(root):
                if _under(dirpath, layout.staging) or _under(
                        dirpath, layout.scratch):
                    dirnames[:] = []
                    continue
                dirnames[:] = sorted(
                    d for d in dirnames
                    if not os.path.islink(os.path.join(dirpath, d))
                    and not layout.is_excluded(os.path.join(dirpath, d)))
                candidates.extend(os.path.join(dirpath, f)
                                  for f in sorted(filenames))
        else:
            continue
        for path in candidates:
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if layout.is_excluded(path):
                continue
            if is_sqlite(path):
                found.append(path)
    return found


def quick_check(path: str) -> Optional[str]:
    """None when the database is sound, else the first problem line."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"{type(exc).__name__}: {exc}"
    if rows == [("ok",)]:
        return None
    return str(rows[0][0]) if rows else "no result"


def copy_database(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.unlink(dst)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
            # A copy of a WAL store is itself in WAL mode, and opening it
            # later would leave -wal/-shm beside it (excluded from the
            # snapshot). Rollback mode makes the copy one complete file.
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
    finally:
        source.close()


def clear_staging(layout: Layout) -> None:
    shutil.rmtree(layout.staging, ignore_errors=True)


def stage(layout: Layout, min_free_bytes: int) -> Tuple[int, int]:
    """Copy and check every database. Returns (count, bytes)."""
    missing = [layout.rel(p) for p in layout.required
               if not os.path.isfile(p)]
    if missing:
        raise BackupError(f"required store missing: {', '.join(missing)}")
    clear_staging(layout)
    os.makedirs(layout.staging, exist_ok=True)
    free = shutil.disk_usage(layout.staging).free
    if free < min_free_bytes:
        raise BackupError(
            f"free space {free} bytes is under the {min_free_bytes} minimum")
    databases = find_databases(layout)
    staged = set()
    total = 0
    for src in databases:
        dst = os.path.join(layout.staging, layout.rel(src))
        try:
            copy_database(src, dst)
        except sqlite3.Error as exc:
            raise BackupError(
                f"copy failed for {layout.rel(src)}: {type(exc).__name__}")
        problem = quick_check(dst)
        if problem is not None:
            raise BackupError(
                f"staged copy of {layout.rel(src)} failed quick_check: "
                f"{problem}")
        staged.add(src)
        total += os.path.getsize(dst)
    not_staged = [layout.rel(p) for p in layout.required if p not in staged]
    if not_staged:
        raise BackupError(
            f"required store not staged: {', '.join(not_staged)}")
    return len(staged), total


# ---------------------------------------------------------------------------
# restic


def check_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise BackupError(f"environment missing {', '.join(missing)}")


def restic(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["restic", *args], capture_output=True, text=True)


def _fail(step: str, proc: subprocess.CompletedProcess) -> BackupError:
    tail = (proc.stderr or "").strip().splitlines()[-STDERR_TAIL:]
    for line in tail:
        log(f"restic {step}: {line}")
    return BackupError(f"restic {step} exited {proc.returncode}")


def exclude_lines(layout: Layout, databases: Sequence[str]) -> List[str]:
    lines = [_restic_escape(p) if "*" not in p else p
             for p in layout.exclude_paths]
    lines += layout.exclude_globs
    lines += [_restic_escape(p) for p in databases]
    return lines


def upload(layout: Layout, databases: Sequence[str]) -> Dict:
    exclude_file = os.path.join(layout.staging, ".exclude")
    with open(exclude_file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(exclude_lines(layout, databases)) + "\n")
    paths = [p for p in layout.include if os.path.exists(p)]
    proc = restic(["backup", "--json", "--quiet", "--tag", "atlas",
                   "--exclude-file", exclude_file, *paths])
    # Exit 3: the snapshot was written but some files could not be read
    # (a log rotated mid-run). The stores are already staged and checked,
    # so the snapshot is kept and the status file records it.
    if proc.returncode not in (0, 3):
        raise _fail("backup", proc)
    summary = None
    for line in (proc.stdout or "").splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("message_type") == "summary":
            summary = msg
    if not summary or not summary.get("snapshot_id"):
        raise BackupError("restic backup gave no snapshot summary")
    return {"snapshot_id": summary["snapshot_id"],
            "data_added": summary.get("data_added"),
            "incomplete": proc.returncode == 3}


def prune(keep_daily: int) -> None:
    proc = restic(["forget", "--quiet", "--keep-daily", str(keep_daily),
                   "--prune"])
    if proc.returncode != 0:
        raise _fail("forget", proc)


def check_repo() -> None:
    proc = restic(["check", "--quiet"])
    if proc.returncode != 0:
        raise _fail("check", proc)


def repo_size() -> Optional[int]:
    proc = restic(["stats", "--json", "--quiet", "--mode", "raw-data"])
    if proc.returncode != 0:
        raise _fail("stats", proc)
    try:
        return int(json.loads(proc.stdout).get("total_size"))
    except (ValueError, TypeError, AttributeError):
        return None


def write_status(layout: Layout, status: Dict) -> None:
    os.makedirs(os.path.dirname(layout.status_file), exist_ok=True)
    tmp = layout.status_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, layout.status_file)


# ---------------------------------------------------------------------------
# Commands


def cmd_stage(layout: Layout) -> int:
    count, size = stage(layout, layout.cfg["min_free_bytes"])
    log(f"staged {count} databases, {size} bytes")
    return 0


def cmd_run(layout: Layout) -> int:
    check_env()
    try:
        count, size = stage(layout, layout.cfg["min_free_bytes"])
        log(f"staged {count} databases, {size} bytes")
        databases = find_databases(layout)
        result = upload(layout, databases)
        log(f"snapshot {result['snapshot_id'][:8]} written")
        if result["incomplete"]:
            log("some files could not be read; snapshot kept")
        prune(layout.cfg["keep_daily"])
        check_repo()
        status = {
            "snapshot_id": result["snapshot_id"],
            "finished_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "staged_databases": count,
            "staged_bytes": size,
            "data_added": result["data_added"],
            "repo_raw_bytes": repo_size(),
            "incomplete": result["incomplete"],
        }
        write_status(layout, status)
        log("done")
        return 0
    finally:
        clear_staging(layout)


def cmd_restore_check(layout: Layout) -> int:
    check_env()
    shutil.rmtree(layout.scratch, ignore_errors=True)
    try:
        proc = restic(["restore", "latest", "--quiet", "--target",
                       layout.scratch, "--include", layout.staging])
        if proc.returncode != 0:
            raise _fail("restore", proc)
        restored_root = os.path.join(layout.scratch,
                                     layout.staging.lstrip(os.sep))
        found: Dict[str, Optional[str]] = {}
        for dirpath, _dirs, files in os.walk(restored_root):
            for name in files:
                path = os.path.join(dirpath, name)
                if is_sqlite(path):
                    rel = os.path.relpath(path, restored_root)
                    found[rel] = quick_check(path)
        bad = {k: v for k, v in found.items() if v is not None}
        required = [layout.rel(p) for p in layout.required]
        absent = [r for r in required if r not in found]
        for rel in sorted(found):
            log(f"{'ok' if found[rel] is None else 'FAIL'} {rel}")
        if absent:
            raise BackupError(f"restore lacks {', '.join(absent)}")
        if bad:
            raise BackupError(f"{len(bad)} restored databases failed "
                              f"quick_check")
        log(f"restore check passed: {len(found)} databases ok")
        return 0
    finally:
        shutil.rmtree(layout.scratch, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "stage", "restore-check"))
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--home", default=os.path.expanduser("~"))
    args = parser.parse_args(argv)
    try:
        layout = Layout(load_config(args.config), args.home)
        if args.command == "stage":
            return cmd_stage(layout)
        if args.command == "run":
            return cmd_run(layout)
        return cmd_restore_check(layout)
    except BackupError as exc:
        log(f"FAILED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
