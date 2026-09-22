"""Credential-separated publication of an immutable, signed candidate tree.

Call from a trusted publisher process after terminating/freezing the worker.
The worker must not have access to this process, its signing key, credential
files, trusted checkout, or temporary directory. Environment scrubbing is NOT
filesystem/process isolation. No worker or candidate scripts run here.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import json
import os
import hmac
import hashlib
import subprocess
import tempfile

from .validate import ValidationError, bounded_run, git, require_clean, verify_receipt

APPROVED_REMOTE = 'git@github.com:vanlabs-dev/atlas.git'
BRANCH = 'refs/heads/main'


@dataclass(frozen=True)
class PublishReceipt:
    commit: str
    tree: str
    baseline: str
    remote: str
    branch: str = BRANCH


def worker_environment():
    """Minimal subprocess environment, not a sandbox or worker launcher."""
    return {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}


def _run(repo, *args, input=None, credential_env=None):
    env = worker_environment()
    env.update({'GIT_AUTHOR_NAME': 'vaNlabs', 'GIT_AUTHOR_EMAIL': 'vanlabs@pm.me',
                'GIT_COMMITTER_NAME': 'vaNlabs', 'GIT_COMMITTER_EMAIL': 'vanlabs@pm.me'})
    if credential_env:
        env.update(credential_env)
    result = bounded_run(['git', '-c', 'core.hooksPath=/dev/null', '-c',
        'core.fsmonitor=false', '-c', 'commit.gpgsign=false', '-C', str(repo), *args],
        input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        # Never expose transport output which may contain credential material.
        raise ValidationError('publication git operation failed: ' + args[0])
    return result.stdout


def _intent_mac(intent, key):
    payload = json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(key, b'atlas-publication-intent-v1\0' + payload, hashlib.sha256).hexdigest()


def _load_intent(path, identity, key):
    try:
        intent = json.loads(path.read_text(encoding='utf-8'))
        signature = intent.pop('hmac')
        if not isinstance(signature, str) or not hmac.compare_digest(signature, _intent_mac(intent, key)):
            raise ValueError('invalid MAC')
        if set(intent) != set(identity) | {'commit', 'raw_commit'}:
            raise ValueError('invalid fields')
        if any(intent.get(k) != value for k, value in identity.items()):
            raise ValueError('identity mismatch')
        raw = intent['raw_commit'].encode()
        oid = hashlib.sha1(b'commit ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if oid != intent['commit']:
            raise ValueError('commit mismatch')
        return intent
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValidationError('invalid publication journal') from exc


def _save_intent(path, intent):
    """Persist before network side effects, including the directory entry."""
    fd, temporary = tempfile.mkstemp(prefix='.publication-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(intent, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_candidate(trusted_repo, candidate_repo, receipt, *, signing_key,
                      remote=APPROVED_REMOTE, message, credential_env=None, local_test=False,
                      journal_path=None):
    """Push only a new single-parent commit; return exact remote readback.

    trusted_repo remains at its baseline; activation is a separate operation.
    local_test is exclusively for absolute-path local bare repository fixtures.
    credential_env is trusted operator configuration, never worker input.
    journal_path must be in durable publisher-owned state, inaccessible to the
    worker (not merely outside its checkout). It is mandatory in production.
    Keep the journal for retries with the identical receipt and message; rotate
    it only after trusted orchestration has recorded publication/activation.
    Publication calls for one journal must be serialized by that orchestration.
    No journal flags authorize recovery: its identity and keyed MAC do.
    """
    if local_test:
        if not isinstance(remote, str) or not Path(remote).is_absolute() or not Path(remote).is_dir():
            raise ValidationError('local test destination must be an existing absolute directory')
        if git(remote, 'rev-parse', '--is-bare-repository').strip() != b'true':
            raise ValidationError('local test destination must be bare')
    elif remote != APPROVED_REMOTE:
        raise ValidationError('destination is not the exact approved Atlas SSH remote')
    if (not isinstance(message, str) or '\n' in message or len(message) > 50 or
            not re.fullmatch(r'(?:fix|feat|docs|test|refactor|chore)(?:\([a-z0-9_-]+\))?: [^\r\n]+', message)):
        raise ValidationError('single Conventional Commit subject required, maximum 50 characters')
    if not local_test and not credential_env:
        raise ValidationError('explicit repository-only publisher credential transport required')
    if credential_env and (not isinstance(credential_env, dict) or
                           set(credential_env) != {'GIT_SSH_COMMAND'} or
                           not isinstance(credential_env['GIT_SSH_COMMAND'], str)):
        raise ValidationError('only trusted SSH transport configuration is permitted')
    if not verify_receipt(receipt, signing_key):
        raise ValidationError('untrusted validation receipt')
    def check_inputs():
        require_clean(candidate_repo)
        require_clean(trusted_repo)
        if git(candidate_repo, 'rev-parse', 'HEAD').decode().strip() != receipt.candidate:
            raise ValidationError('candidate tip changed')
        if git(trusted_repo, 'rev-parse', 'HEAD').decode().strip() != receipt.baseline:
            raise ValidationError('publisher baseline changed')
        if git(trusted_repo, 'symbolic-ref', 'HEAD').decode().strip() != BRANCH:
            raise ValidationError('publisher is not on approved main branch')
        for direction in ((), ('--push',)):
            if git(trusted_repo, 'remote', 'get-url', *direction, '--all', 'origin').decode().splitlines() != [remote]:
                raise ValidationError('remote differs from exact approved destination')
    check_inputs()
    intent = None
    identity = {'version': 1, 'baseline': receipt.baseline, 'tree': receipt.tree,
                'candidate': receipt.candidate, 'receipt_signature': receipt.signature,
                'remote': remote, 'branch': BRANCH, 'message': message}
    if journal_path is None and not local_test:
        raise ValidationError('durable publication journal required')
    if journal_path is not None:
        journal_path = Path(journal_path)
        if (journal_path.is_symlink() or
                journal_path.resolve().is_relative_to(Path(candidate_repo).resolve())):
            raise ValidationError('publication journal must be trusted state outside candidate')
        journal_path = journal_path.resolve()
        if journal_path.exists():
            intent = _load_intent(journal_path, identity, signing_key)
    with tempfile.TemporaryDirectory(prefix='atlas-publisher-') as scratch:
        _run(scratch, 'init', '--bare')
        observed = _run(scratch, 'ls-remote', '--refs', remote, BRANCH,
                        credential_env=credential_env).decode().split()
        if intent and observed == [intent['commit'], BRANCH]:
            return PublishReceipt(intent['commit'], receipt.tree, receipt.baseline, remote)
        if observed != [receipt.baseline, BRANCH]:
            raise ValidationError('remote baseline advanced; revalidation required')
        packed = git(candidate_repo, 'pack-objects', '--stdout', '--revs',
                     input=(receipt.candidate + '\n').encode())
        _run(scratch, 'index-pack', '--stdin', input=packed)
        if _run(scratch, 'rev-parse', receipt.candidate + '^{tree}').decode().strip() != receipt.tree:
            raise ValidationError('candidate objects do not match signed tree')
        if intent:
            commit = _run(scratch, 'hash-object', '-t', 'commit', '-w', '--stdin',
                          input=intent['raw_commit'].encode()).decode().strip()
            if commit != intent['commit']:
                raise ValidationError('publication journal commit mismatch')
        else:
            commit = _run(scratch, 'commit-tree', receipt.tree, '-p', receipt.baseline,
                          input=(message + '\n').encode()).decode().strip()
            intent = {**identity, 'commit': commit,
                      'raw_commit': _run(scratch, 'cat-file', 'commit', commit).decode()}
            if journal_path is not None:
                _save_intent(journal_path, {**intent, 'hmac': _intent_mac(intent, signing_key)})
        check_inputs()
        if _run(scratch, 'ls-remote', '--refs', remote, BRANCH,
                credential_env=credential_env).decode().split() != [receipt.baseline, BRANCH]:
            raise ValidationError('remote moved during publication')
        _run(scratch, 'push', remote, commit + ':' + BRANCH, credential_env=credential_env)
        observed = _run(scratch, 'ls-remote', '--refs', remote, BRANCH,
                        credential_env=credential_env).decode().split()
        if observed != [commit, BRANCH]:
            raise ValidationError('push may have succeeded but exact readback failed')
        return PublishReceipt(commit, receipt.tree, receipt.baseline, remote)
