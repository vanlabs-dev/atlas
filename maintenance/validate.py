"""Deterministic gates; call only in the trusted validator, never the worker.

Signing keys and externally executed check results must originate outside the
worker's writable scope. This module is NOT an OS sandbox or a test runner.
The caller must stop/freeze the worker and protect Git administration files
against concurrent changes before validation/publication. Pattern-based secret
scanning is conservative, not proof that arbitrary encoded secrets are absent.
Restricted changes have no automated override: they need a separate operator
review/publication route. Candidate and publisher checkouts must have no
ignored/untracked state (run tests elsewhere, with external cache directories).
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
import re
import subprocess

SECRET = re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|'
                    rb'github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|'
                    rb'(?:api[_-]?key|secret|password|access[_-]?token)\s*[=:]\s*[\"\']?[^\s\"\']{8,}|'
                    rb'https?://[^\s/:]+:[^\s/@]+@', re.I)


def require_oid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValidationError('exact full SHA-1 object ID required')


def require_clean(repo):
    entries = git(repo, 'ls-files', '-v', '-z').split(b'\0')
    if any(entry and not entry.startswith(b'H ') for entry in entries):
        raise ValidationError('index flags or sparse entries can conceal changes')
    if git(repo, 'status', '--porcelain=v1', '--untracked-files=all', '--ignored'):
        raise ValidationError('candidate must be clean, including ignored files')

SUBSYSTEMS = ('inventory', 'hardening', 'hermes', 'knowledge', 'repotrack',
              'livedata', 'telegram', 'fleet', 'subnt', 'specs', 'operator_docs')
REQUIRED_CHECKS = SUBSYSTEMS[:9] + ('diff_check', 'provenance', 'pinned_rpc', 'mcp_contracts')


class ValidationError(ValueError):
    pass


def bounded_run(command, **kwargs):
    try:
        return subprocess.run(command, timeout=120, **kwargs)
    except (subprocess.TimeoutExpired, OSError):
        raise ValidationError('git execution failed or timed out; publication may require reconciliation') from None


def git(repo, *args, input=None):
    """No inherited credentials, hooks, global config, or replacement refs."""
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}
    # Enumerate names only: never read or log repository SSH commands/keys.
    # Reject executable filters and config indirection before even `status`.
    config = bounded_run(['git', '-C', str(repo), 'config', '--no-includes',
        '--name-only', '--list'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if config.returncode or any(name.startswith((b'filter.', b'include.', b'includeif.')) or
                               name in (b'core.worktree', b'core.alternaterefscommand')
                               for name in config.stdout.lower().splitlines()):
        raise ValidationError('unsafe repository config; trusted git administration required')
    result = bounded_run(['git', '-c', 'core.hooksPath=/dev/null', '-c',
        'core.fsmonitor=false', '-C', str(repo), *args], input=input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        raise ValidationError('git operation failed: ' + args[0])
    return result.stdout


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@dataclass(frozen=True)
class ValidationReceipt:
    baseline: str
    candidate: str
    tree: str
    paths: tuple[str, ...]
    evidence_sha256: str
    review_sha256: str
    signature: str = ''


def _signature(receipt, key):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValidationError('a trusted signing key of at least 32 bytes is required')
    return hmac.new(key, _canonical(asdict(replace(receipt, signature=''))), hashlib.sha256).hexdigest()


def verify_receipt(receipt, signing_key):
    return isinstance(receipt, ValidationReceipt) and hmac.compare_digest(
        receipt.signature, _signature(receipt, signing_key))


def validate_candidate(repo, baseline, *, evidence, upstream_paths, review,
                       worker_id, reviewer_id, checks, signing_key):
    """Return an HMAC-signed ValidationReceipt, or raise ValidationError.

    Candidate HEAD must already contain the complete proposed tree, descending
    from the exact baseline SHA. The publisher will NOT push worker commits.
    `evidence` is the exact nonempty serialized evidence packet (bytes).
    `upstream_paths` is its complete, trusted changed-path manifest.
    `review` is an independently obtained JSON-compatible dict with:
      worker, reviewer, approved=True, tree, evidence_sha256;
      upstream={each_path: {disposition: updated|no_impact, evidence: citation}};
      subsystems={each SUBSYSTEMS entry: same disposition structure};
      checks={each REQUIRED_CHECKS entry: passed}.
    `checks` separately supplies trusted runner results in the same mapping
    format; the caller must execute those checks on THIS tree/evidence. A
    worker-produced assertion is never a test receipt. Reviewer identity and
    citations are authenticated/evaluated by the trusted review orchestrator;
    this gate validates structure, coverage, hashes, and acceptance, not prose.
    """
    require_oid(baseline)
    if not isinstance(evidence, bytes) or not evidence:
        raise ValidationError('nonempty exact evidence bytes required')
    if (not isinstance(upstream_paths, (list, tuple)) or not upstream_paths or
            any(not isinstance(p, str) or not p.strip() for p in upstream_paths) or
            len(set(upstream_paths)) != len(upstream_paths)):
        raise ValidationError('complete nonempty unique upstream manifest required')
    require_clean(repo)
    candidate = git(repo, 'rev-parse', 'HEAD').decode().strip()
    tree = git(repo, 'rev-parse', candidate + '^{tree}').decode().strip()
    git(repo, 'merge-base', '--is-ancestor', baseline, candidate)
    git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--check', baseline, candidate)
    if (not isinstance(review, dict) or not worker_id or not reviewer_id or
            worker_id == reviewer_id or review.get('worker') != worker_id or
            review.get('reviewer') != reviewer_id or review.get('approved') is not True or
            review.get('tree') != tree or
            review.get('evidence_sha256') != hashlib.sha256(evidence).hexdigest()):
        raise ValidationError('missing, nonindependent, or unbound review')
    for name, expected in (('upstream', set(upstream_paths)), ('subsystems', set(SUBSYSTEMS))):
        records = review.get(name)
        if not isinstance(records, dict) or set(records) != expected:
            raise ValidationError('incomplete review coverage')
        for record in records.values():
            if (not isinstance(record, dict) or record.get('disposition') not in
                    ('updated', 'no_impact') or not isinstance(record.get('evidence'), str) or
                    not record['evidence'].strip()):
                raise ValidationError('blocked or unsupported disposition')
    for results in (checks, review.get('checks')):
        if not isinstance(results, dict) or any(results.get(c) != 'passed' for c in REQUIRED_CHECKS):
            raise ValidationError('mandatory checks incomplete')
    paths = tuple(p.decode() for p in git(repo, 'diff', '--no-renames', '--name-only', '-z', baseline, candidate).split(b'\0') if p)
    for path in paths:
        parts = path.lower().split('/')
        if (any(p in {'var', '.git', '.ssh', 'private', 'output', 'outputs', 'keys', 'secrets',
                      'maintenance', 'agents.md', '.gitmodules', '.gitattributes', '.github',
                      'auth.json', 'id_ed25519', 'id_rsa', '.aws', '.gnupg', '.hermes', '__pycache__',
                      'conftest.py', 'conftest.pyc', 'pytest.ini', '.pytest.ini',
                      'pytest.toml', '.pytest.toml', 'pyproject.toml', 'setup.cfg', 'tox.ini',
                      'pytest', 'pytest.py', 'pytest.pyc', '_pytest',
                      'sitecustomize', 'sitecustomize.py', 'sitecustomize.pyc',
                      'usercustomize', 'usercustomize.py', 'usercustomize.pyc'} or
                p.startswith('.env') or p.startswith('credentials') or
                p.endswith(('.key', '.pem', '.p12', '.pfx', '.db', '.sqlite', '.sqlite3')) for p in parts)):
            raise ValidationError('restricted path requires operator review')
        for ref in (baseline, candidate):
            entry = git(repo, 'ls-tree', ref, '--', path)
            if entry and not entry.startswith((b'100644 blob ', b'100755 blob ')):
                raise ValidationError('symlinks and nonregular entries are forbidden')
            if entry:
                content = git(repo, 'cat-file', 'blob', ref + ':' + path)
                if b'\0' in content:
                    raise ValidationError('binary artifacts require operator review')
                if SECRET.search(content):
                    raise ValidationError('potential secret in changed content; operator review required')
    require_clean(repo)
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != candidate:
        raise ValidationError('candidate changed during validation')
    receipt = ValidationReceipt(baseline, candidate, tree, paths,
        hashlib.sha256(evidence).hexdigest(), hashlib.sha256(_canonical(review)).hexdigest())
    return replace(receipt, signature=_signature(receipt, signing_key))
