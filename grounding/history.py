"""Deterministic facts from the subtensor clone's git history (change:
chain-grounding): release tags, the files a release changed, the PRs it
merged, and the release in which cited lines last changed.

Release tags are `v<spec>` (checked 2026-11-27: `runtime/src/lib.rs` at
v494 to v497 states `spec_version` equal to the tag number). Older tags
such as `v1.0.0` are not releases of a spec and are ignored.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

Git = Callable[..., Tuple[int, str]]
RELEASE_RE = re.compile(r"^v(\d+)$")
MERGE_RE = re.compile(r"^Merge pull request #(\d+) from (\S+)")
SQUASH_RE = re.compile(r"\(#(\d+)\)\s*$")


def release_tags(refs: Dict[str, str]) -> Dict[int, str]:
    """{spec: sha} from ls-remote refs like refs/tags/v497 (peeled ^{}
    entries win, so an annotated tag maps to its commit)."""
    out: Dict[int, str] = {}
    peeled: Dict[int, str] = {}
    for ref, sha in refs.items():
        name = ref.rsplit("/", 1)[-1]
        target = peeled if name.endswith("^{}") else out
        match = RELEASE_RE.match(name[:-3] if name.endswith("^{}") else name)
        if match:
            target[int(match.group(1))] = sha
    out.update(peeled)
    return out


def parse_ls_remote(text: str) -> Dict[str, str]:
    refs = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            refs[parts[1]] = parts[0]
    return refs


def changed_files(git: Git, old: str, new: str) -> List[str]:
    rc, out = git("diff", "--name-only", "%s..%s" % (old, new))
    if rc != 0:
        raise RuntimeError("git diff %s..%s failed" % (old[:9], new[:9]))
    return [line for line in out.splitlines() if line]


def merged_prs(git: Git, old: str, new: str) -> List[Tuple[int, str]]:
    """(PR number, source branch) of every PR merge in old..new, newest
    first."""
    rc, out = git("log", "--merges", "--format=%s", "%s..%s" % (old, new))
    if rc != 0:
        return []
    prs = []
    for subject in out.splitlines():
        match = MERGE_RE.match(subject)
        if match:
            prs.append((int(match.group(1)), match.group(2)))
    return prs


def first_release(git: Git, sha: str) -> Optional[int]:
    """The lowest release spec whose tag contains `sha`."""
    rc, out = git("tag", "--contains", sha)
    if rc != 0:
        return None
    specs = [int(m.group(1)) for m in
             (RELEASE_RE.match(t.strip()) for t in out.splitlines()) if m]
    return min(specs) if specs else None


def oldest_release(git: Git) -> Optional[int]:
    """The lowest release spec tagged in the clone. A change dated to it
    may be older: history before it has no release tags."""
    rc, out = git("tag", "-l", "v*")
    specs = [int(m.group(1)) for m in
             (RELEASE_RE.match(t.strip()) for t in out.splitlines()) if m] \
        if rc == 0 else []
    return min(specs) if specs else None


def pr_of(git: Git, sha: str, tag: str) -> Optional[int]:
    """The PR that brought `sha` in: its own squash subject, else the
    first PR merge on the ancestry path to the tag."""
    rc, out = git("log", "-1", "--format=%s", sha)
    if rc == 0:
        match = SQUASH_RE.search(out.strip()) or MERGE_RE.match(out.strip())
        if match:
            return int(match.group(1))
    rc, out = git("log", "--merges", "--ancestry-path", "--reverse",
                  "--format=%s", "%s..%s" % (sha, tag))
    if rc != 0:
        return None
    for subject in out.splitlines():
        match = MERGE_RE.match(subject)
        if match:
            return int(match.group(1))
    return None


def last_change(git: Git, tag: str, path: str, start: int,
                end: int) -> Optional[str]:
    """The newest commit at `tag` that changed lines start..end of path."""
    rc, out = git("log", "-1", "--format=%H", "--no-patch", "-L",
                  "%d,%d:%s" % (start, end, path), tag)
    sha = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    return sha if re.match(r"^[0-9a-f]{40}$", sha) else None


def marker_added(git: Git, tag: str, marker: str) -> Optional[str]:
    """The oldest commit at `tag` that added the literal `marker`."""
    rc, out = git("log", "--reverse", "--format=%H", "-S", marker,
                  "--no-patch", tag)
    shas = out.split() if rc == 0 else []
    return shas[0] if shas else None


def spec_history(db_path: str) -> List[Dict[str, Any]]:
    """Observed live upgrades from the livedata store, newest first:
    [{prev, new, date}]. Empty when the store is missing."""
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT prev_spec, new_spec, observed_at FROM spec_upgrades "
            "ORDER BY observed_at DESC").fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [{"prev": p, "new": n, "date": str(d)[:10]} for p, n, d in rows
            if isinstance(n, int)]


def changelog(git: Git, history: List[Dict[str, Any]],
              anchors: Callable[[int], Optional[str]],
              limit: int = 10) -> List[str]:
    """One line per live spec bump, newest first, with its PR numbers."""
    lines = []
    for entry in history[:limit]:
        old, new = anchors(entry["prev"]), anchors(entry["new"])
        prs = merged_prs(git, old, new) if old and new else []
        if not old or not new:
            what = "PRs unknown (no release tag)"
        elif not prs:
            what = "no PR merges"
        else:
            shown = " ".join("#%d" % n for n, _ in prs[:6])
            more = " (+%d more)" % (len(prs) - 6) if len(prs) > 6 else ""
            what = "%d PR%s: %s%s" % (len(prs), "" if len(prs) == 1
                                      else "s", shown, more)
        lines.append("spec %d live %s (from %s): %s" % (
            entry["new"], entry["date"], entry["prev"], what))
    return lines


def pending(git: Git, live_anchor: str, head: str, head_spec: Optional[int],
            live_spec: int, limit: int = 8) -> List[str]:
    """Short list of what `main` holds past the live release."""
    prs = merged_prs(git, live_anchor, head)
    out = []
    if head_spec is not None and head_spec > live_spec:
        out.append("main states spec %d (live is %d)" % (head_spec,
                                                         live_spec))
    out += ["#%d %s" % (n, branch) for n, branch in prs[:limit]]
    if len(prs) > limit:
        out.append("+%d more PRs" % (len(prs) - limit))
    return out
