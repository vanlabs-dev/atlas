"""Worker, mechanical citation check and critic for stale claims (change:
chain-grounding).

- The worker is one headless `claude -p` per section. It reads only the
  subtensor source exported at the live tag (plus the corpus, as leads)
  and returns JSON: the section's claims, each with cited line ranges.
- Code then checks every citation: the file exists in the export, the
  range is inside it, every number and every backticked identifier in the
  statement appears in the cited lines, and a hyperparameter claim's
  default equals the runtime metadata default in the snapshot.
- The critic is a separate `claude -p` with no tools. It sees each claim
  and the text of its cited lines, and nothing of the worker's reasoning.

The model never writes a file. Code applies agreed claims to the ledger.
"""

from __future__ import annotations

import json
import os
import re
import string
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
ACTIONS = ("keep", "rewrite", "new", "deprecate", "remove")
Runner = Callable[[List[str], str, int], Tuple[int, str, str]]

_SPEC_REF = re.compile(r"(?i)\b(?:spec(?:_version)?s?|runtime)\s+\d+"
                       r"(?:\s*(?:to|-|and|,)\s*\d+)*|\bv\d{3,}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?\b")
_PR = re.compile(r"#\d+")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,_]*(?:\.\d+)?(?![\w])")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*"
                    r"(?:\(\))?$")


class ModelError(Exception):
    """A model run failed or returned no usable JSON."""


LIMIT_RE = re.compile(r"hit your (.{1,40}?) limit[^\n]*?resets ([^.()\n]{3,60})")


def usage_limit(text: str) -> Optional[str]:
    """'<model> limit, resets <when>' when a claude failure is a plan
    usage limit, else None. A limit is not an expired login."""
    match = LIMIT_RE.search(text or "")
    return "%s limit, resets %s" % (match.group(1), match.group(2).strip()) \
        if match else None


# -- model runs -------------------------------------------------------------

def extract_json(text: str) -> Dict[str, Any]:
    """The JSON object in a model reply: a ```json fence, else the span
    from the first `{` to the last `}`."""
    fence = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = fence[::-1] + [text[text.find("{"):text.rfind("}") + 1]]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ModelError("no JSON object in the reply")


def run_claude(runner: Runner, cmd: List[str], cwd: str,
               timeout: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one `claude -p --output-format json`. Returns (parsed reply,
    usage record). Raises ModelError."""
    rc, out, err = runner(cmd, cwd, timeout)
    if rc != 0:
        raise ModelError("claude exited %d: %s" % (rc, (err or out)[-300:]))
    try:
        envelope = json.loads(out)
    except ValueError:
        raise ModelError("claude output is not JSON")
    if envelope.get("is_error"):
        raise ModelError("claude reported an error: %s" % str(
            envelope.get("result"))[-300:])
    usage = {"cost_usd": envelope.get("total_cost_usd"),
             "turns": envelope.get("num_turns"),
             "duration_ms": envelope.get("duration_ms"),
             "usage": envelope.get("usage")}
    return extract_json(str(envelope.get("result") or "")), usage


def read_denials() -> List[str]:
    home = os.path.expanduser("~")
    patterns = ["//%s/.ssh/**" % home.lstrip("/"),
                "//%s/.hermes/**" % home.lstrip("/"),
                "//%s/.claude/**" % home.lstrip("/"),
                "~/.ssh/**", "~/.hermes/**", "~/.claude/**",
                "//**/.env", "//**/.env.*", "**/.env*"]
    return ["Read(%s)" % p for p in patterns]


def worker_cmd(claude: str, model: str, prompt: str, source_dir: str,
               corpus_dir: str, max_turns: int) -> List[str]:
    reads = ["Read(/%s/**)" % os.path.abspath(d)
             for d in (source_dir, corpus_dir)]
    return ([claude, "-p", "--restricted", "--strict-mcp-config",
             "--model", model,
             "--output-format", "json", "--max-turns", str(max_turns),
             "--tools", "Read,Grep,Glob", "--add-dir", corpus_dir,
             "--allowedTools"] + reads
            + ["--disallowedTools", "WebFetch", "WebSearch", "Bash", "Edit",
               "Write"] + read_denials() + ["--", prompt])


def critic_cmd(claude: str, model: str, prompt: str) -> List[str]:
    return [claude, "-p", "--restricted", "--strict-mcp-config",
            "--model", model,
            "--output-format", "json", "--max-turns", "2", "--tools", "",
            "--", prompt]


def template(name: str) -> string.Template:
    with open(os.path.join(_HERE, "prompts", name), "r",
              encoding="utf-8") as handle:
        return string.Template(handle.read())


# -- citations --------------------------------------------------------------

def safe_path(source_dir: str, path: str) -> Optional[str]:
    """The absolute path of a cited file inside the export, or None."""
    if not isinstance(path, str) or not path or path.startswith("/"):
        return None
    root = os.path.realpath(source_dir)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    return full


def cited_lines(source_dir: str, path: str, start: int,
                end: int) -> Optional[List[str]]:
    full = safe_path(source_dir, path)
    if full is None:
        return None
    with open(full, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
    if not (isinstance(start, int) and isinstance(end, int)
            and 1 <= start <= end <= len(lines)):
        return None
    return lines[start - 1:end]


FN_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?"
                   r"(?:async\s+)?(?:unsafe\s+)?fn\s+[A-Za-z_]\w*")
SIGNATURE_REACH = 80


def enclosing_signature(source_dir: str, path: str,
                        start: int) -> Optional[Tuple[int, str]]:
    """(line number, text) of the nearest `fn` line at or above `start`,
    within SIGNATURE_REACH lines, or None. A claim about a function's body
    may cite the body only; the check and the critic then also see which
    function the lines belong to."""
    full = safe_path(source_dir, path)
    if full is None or not path.endswith(".rs"):
        return None
    with open(full, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
    for number in range(start, max(0, start - SIGNATURE_REACH), -1):
        if 1 <= number <= len(lines) and FN_RE.match(lines[number - 1]):
            return number, lines[number - 1]
    return None


def _norm_numbers(text: str) -> str:
    return re.sub(r"(?<=\d)[_,](?=\d)", "", text)


def statement_numbers(statement: str) -> List[str]:
    """Numbers a statement asserts: spec, tag, PR and date references are
    not assertions about the code and are left out."""
    text = _DATE.sub(" ", _PR.sub(" ", _SPEC_REF.sub(" ", statement)))
    text = re.sub(r"`[^`]*`", lambda m: " " if not re.search(
        r"\d", m.group(0)) else m.group(0).replace("`", " "), text)
    found = []
    for token in _NUMBER.findall(_norm_numbers(text)):
        token = token.rstrip(",")
        if token not in found:
            found.append(token)
    return found


def statement_identifiers(statement: str) -> List[str]:
    out = []
    for token in re.findall(r"`([^`]+)`", statement):
        token = token.strip()
        if _IDENT.match(token):
            out.append(token.rstrip("()").split("::")[-1])
    return out


def _normalise_default(value: Any) -> str:
    text = json.dumps(value, sort_keys=True) if not isinstance(
        value, str) else value
    return _norm_numbers(text.strip().strip('"')).lower()


def check_claim(claim: Dict[str, Any], source_dir: str, max_lines: int,
                pallets: Optional[Dict[str, Any]] = None
                ) -> Tuple[List[str], List[Dict[str, Any]]]:
    """(problems, cited) for one worker claim. `cited` holds each
    evidence range with its text, for the critic."""
    problems: List[str] = []
    cited: List[Dict[str, Any]] = []
    evidence = claim.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return ["no citation"], []
    for ev in evidence:
        path, start, end = ev.get("path"), ev.get("start"), ev.get("end")
        lines = cited_lines(source_dir, path, start, end)
        if lines is None:
            problems.append("citation %s:%s-%s is not a line range of a "
                            "file at the tag" % (path, start, end))
            continue
        if end - start + 1 > max_lines:
            problems.append("citation %s:%d-%d is over %d lines" % (
                path, start, end, max_lines))
        text = "\n".join(lines)
        signature = enclosing_signature(source_dir, path, start)
        if signature and signature[0] < start:
            # Context only: the function this range sits in.
            text = "%s\n    ...\n%s" % (signature[1], text)
        cited.append({"path": path, "start": start, "end": end,
                      "text": text,
                      "signature_line": signature[0] if signature else None})
    if problems:
        return problems, cited
    text = _norm_numbers("\n".join(c["text"] for c in cited))
    statement = claim.get("statement") or ""
    for number in statement_numbers(statement):
        if not re.search(r"(?<![\w.])%s(?![\d])" % re.escape(number), text):
            problems.append("number %s is not in the cited lines" % number)
    for ident in statement_identifiers(statement):
        if ident not in text and not any(ident in c["path"] for c in cited):
            problems.append("`%s` is not in the cited lines" % ident)
    if claim.get("section") == "hyperparameters" and pallets is not None:
        item, default = claim.get("item"), claim.get("default")
        found = None
        for inventory in pallets.values():
            if item in inventory["storage"]:
                found = inventory["storage"][item]
                break
        if found is None:
            problems.append("item %r is not a storage item in the snapshot"
                            % (item,))
        elif "default" not in found:
            problems.append("item %s has no default in the metadata" % item)
        elif _normalise_default(found["default"]) != _normalise_default(
                default):
            problems.append("default %r of %s differs from the runtime "
                            "metadata default %s" % (default, item, json.dumps(
                                found["default"])))
    return problems, cited


def validate_worker(reply: Dict[str, Any], section: str,
                    known_ids: List[str]) -> List[Dict[str, Any]]:
    """The worker's claims, shape-checked. Raises ModelError."""
    claims = reply.get("claims")
    if not isinstance(claims, list):
        raise ModelError("worker reply has no claims list")
    out = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ModelError("worker claim is not an object")
        action = claim.get("action")
        if action not in ACTIONS:
            raise ModelError("worker action %r" % (action,))
        cid = claim.get("id")
        if action == "new":
            claim["id"] = None
        elif cid not in known_ids:
            raise ModelError("worker %s of unknown id %r" % (action, cid))
        if action != "remove" and not isinstance(claim.get("statement"),
                                                 str):
            raise ModelError("worker claim without a statement")
        if not isinstance(claim.get("watched_paths", []), list):
            raise ModelError("watched_paths is not a list")
        claim["section"] = "traps" if action == "deprecate" and \
            section == "traps" else section
        out.append(claim)
    return out


def critic_items(checked: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
                 tag: str) -> List[Dict[str, Any]]:
    items = []
    for index, (claim, cited) in enumerate(checked):
        items.append({
            "key": "c%d" % index, "statement": claim["statement"],
            "kind": "deprecated" if claim.get("action") == "deprecate"
            else "current",
            "cited": [{"where": "%s %s:%d-%d%s" % (
                tag, c["path"], c["start"], c["end"],
                " (first line: the enclosing fn, line %d)"
                % c["signature_line"] if c.get("signature_line")
                and c["signature_line"] < c["start"] else ""),
                "text": c["text"]} for c in cited]})
    return items


def parse_verdicts(reply: Dict[str, Any], keys: List[str]
                   ) -> Dict[str, Tuple[str, str]]:
    """{key: (verdict, reason)}. A key the critic left out is a
    disagreement."""
    verdicts = {}
    for entry in reply.get("verdicts") or []:
        if not isinstance(entry, dict):
            continue
        key, verdict = entry.get("key"), entry.get("verdict")
        if key in keys and verdict in ("agree", "disagree"):
            verdicts[key] = (verdict, str(entry.get("reason") or "")[:300])
    for key in keys:
        verdicts.setdefault(key, ("disagree", "the critic gave no verdict"))
    return verdicts
