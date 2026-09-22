from dataclasses import replace
import subprocess
import json

import pytest

from maintenance import publish as p
from maintenance import validate as v
from maintenance.tests.test_validate import KEY, candidate, git, validate


@pytest.fixture
def publication(candidate, tmp_path):
    repo, base = candidate
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'init', '--bare', str(remote)], check=True, capture_output=True)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', 'origin', base + ':refs/heads/main')
    trusted = tmp_path / 'publisher'
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '-b', 'main', str(remote), str(trusted)], check=True, capture_output=True)
    return repo, base, remote, trusted


def publish(publication, receipt=None, **kwargs):
    repo, base, remote, trusted = publication
    return p.publish_candidate(trusted, repo, receipt or validate(repo, base),
        signing_key=KEY, remote=str(remote), local_test=True,
        message='docs: audit runtime upgrade', **kwargs)


@pytest.mark.parametrize('state', ['forged', 'dirty_candidate', 'dirty_trusted', 'candidate_advanced',
    'trusted_advanced', 'remote_advanced', 'wrong_remote', 'multiple_remote', 'wrong_branch'])
def test_publication_rejects_stale_or_untrusted_inputs(publication, state):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    if state == 'forged': receipt = replace(receipt, tree='0' * 40)
    elif state == 'dirty_candidate': (repo / 'README.md').write_text('dirty\n')
    elif state == 'dirty_trusted': (trusted / 'new.txt').write_text('dirty\n')
    elif state in ('candidate_advanced', 'trusted_advanced'):
        target = repo if state == 'candidate_advanced' else trusted
        (target / 'new.txt').write_text('new\n')
        git(target, 'add', 'new.txt')
        git(target, 'commit', '-m', 'docs: newer update')
    elif state == 'remote_advanced': git(repo, 'push', 'origin', 'HEAD:refs/heads/main')
    elif state == 'wrong_remote': git(trusted, 'remote', 'set-url', 'origin', '/wrong/destination')
    elif state == 'multiple_remote': git(trusted, 'config', '--add', 'remote.origin.pushurl', '/wrong/destination')
    elif state == 'wrong_branch': git(trusted, 'checkout', '-b', 'other')
    before = git(remote, 'rev-parse', 'refs/heads/main')
    with pytest.raises(v.ValidationError):
        publish(publication, receipt)
    assert git(remote, 'rev-parse', 'refs/heads/main') == before


@pytest.mark.parametrize('fault', ['candidate_race', 'unapproved_transport', 'message', 'credential_identity'])
def test_publication_boundaries(publication, monkeypatch, fault):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    if fault == 'candidate_race':
        original = p._run
        def race(scratch, *args, **kwargs):
            result = original(scratch, *args, **kwargs)
            if args[0] == 'index-pack':
                (repo / 'README.md').write_text('raced\n')
            return result
        monkeypatch.setattr(p, '_run', race)
    with pytest.raises(v.ValidationError):
        if fault == 'unapproved_transport':
            p.publish_candidate(trusted, repo, receipt, signing_key=KEY, remote=str(remote),
                message='docs: runtime audit')  # local bypass must be explicit
        elif fault == 'message':
            p.publish_candidate(trusted, repo, receipt, signing_key=KEY, remote=str(remote),
                local_test=True, message='docs: update\n\nCo-Authored-By: bot <bot@test>')
        elif fault == 'credential_identity':
            publish(publication, receipt, credential_env={'GIT_AUTHOR_EMAIL': 'work@example.org'})
        else:
            publish(publication, receipt)
    assert git(remote, 'rev-parse', 'refs/heads/main') == base


def test_credentials_never_reach_candidate_commands_or_worker_environment(publication, monkeypatch):
    repo, base, remote, trusted = publication
    monkeypatch.setenv('GH_TOKEN', 'publisher-only-token')
    monkeypatch.setenv('SSH_AUTH_SOCK', '/publisher-only-agent')
    monkeypatch.setenv('GIT_AUTHOR_EMAIL', 'work@example.org')
    marker = 'ssh -i /publisher-only-key'
    original = subprocess.run
    observations = []
    def observe(command, **kwargs):
        env = kwargs.get('env', {})
        if command[0] == 'git' and '-C' in command:
            cwd = str(command[command.index('-C') + 1])
            if cwd in (str(repo), str(trusted)):
                assert marker not in env.values()
                assert 'GH_TOKEN' not in env
                assert 'SSH_AUTH_SOCK' not in env
            if env.get('GIT_SSH_COMMAND') == marker:
                assert cwd not in (str(repo), str(trusted))
                observations.append(command)
        return original(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observe)
    publish(publication, credential_env={'GIT_SSH_COMMAND': marker})
    assert observations
    assert not {'GH_TOKEN', 'GIT_SSH_COMMAND', 'SSH_AUTH_SOCK'} & p.worker_environment().keys()


def test_candidate_and_publisher_hooks_never_execute(publication):
    repo, base, remote, trusted = publication
    sentinel = repo.parent / 'hook-executed'
    for root in (repo, trusted):
        for name in ('pre-commit', 'pre-push', 'post-commit'):
            hook = root / '.git/hooks' / name
            hook.write_text('#!/bin/sh\ntouch ' + str(sentinel) + '\nexit 1\n')
            hook.chmod(0o755)
    publish(publication)
    assert not sentinel.exists()


def test_remote_concurrent_update_is_not_overwritten(publication, monkeypatch):
    repo, base, remote, trusted = publication
    original = p._run
    def race(scratch, *args, **kwargs):
        if args[0] == 'push':
            git(repo, 'push', 'origin', 'HEAD:refs/heads/main')
        return original(scratch, *args, **kwargs)
    monkeypatch.setattr(p, '_run', race)
    with pytest.raises(v.ValidationError):
        publish(publication)
    assert git(remote, 'rev-parse', 'refs/heads/main') == git(repo, 'rev-parse', 'HEAD')


def test_failed_readback_never_reports_publication_success(publication, monkeypatch):
    original = p._run
    pushed = False
    def readback_failure(scratch, *args, **kwargs):
        nonlocal pushed
        if args[0] == 'ls-remote' and pushed:
            return b''
        result = original(scratch, *args, **kwargs)
        if args[0] == 'push': pushed = True
        return result
    monkeypatch.setattr(p, '_run', readback_failure)
    with pytest.raises(v.ValidationError, match='readback'):
        publish(publication)
    assert pushed


def test_production_requires_explicit_publisher_transport(publication, monkeypatch):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    git(trusted, 'remote', 'set-url', 'origin', p.APPROVED_REMOTE)
    def no_transport(*args, **kwargs):
        raise AssertionError('must fail before publisher transport setup')
    monkeypatch.setattr(p, '_run', no_transport)
    with pytest.raises(v.ValidationError, match='credential'):
        p.publish_candidate(trusted, repo, receipt, signing_key=KEY,
            message='docs: runtime audit')


@pytest.mark.parametrize('runner', ['validator', 'publisher'])
def test_git_commands_are_bounded_and_errors_do_not_leak_credentials(publication, monkeypatch, runner):
    repo, _, _, _ = publication
    def timed_out(command, **kwargs):
        assert 0 < kwargs.get('timeout', 0) <= 120
        raise subprocess.TimeoutExpired(command, kwargs['timeout'], stderr=b'publisher secret')
    monkeypatch.setattr(subprocess, 'run', timed_out)
    with pytest.raises(v.ValidationError) as error:
        (v.git if runner == 'validator' else p._run)(repo, 'status')
    assert 'publisher secret' not in str(error.value)


def test_worker_history_is_not_published(publication):
    repo, base, remote, trusted = publication
    (repo / '.env').write_text('PRIVATE_HISTORY_ONLY\n')
    git(repo, 'add', '.env')
    git(repo, 'commit', '-m', 'chore: private intermediate')
    private_blob = git(repo, 'rev-parse', 'HEAD:.env')
    git(repo, 'rm', '.env')
    git(repo, 'commit', '-m', 'chore: remove private intermediate')
    candidate_commit = git(repo, 'rev-parse', 'HEAD')
    publish(publication)
    for oid in (private_blob, candidate_commit):
        assert subprocess.run(['git', '-C', str(remote), 'cat-file', '-e', oid], capture_output=True).returncode != 0


def test_local_bare_publication_exact_tree_personal_identity(publication):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    result = publish(publication, receipt)
    assert git(remote, 'rev-parse', 'refs/heads/main') == result.commit
    assert git(remote, 'rev-parse', result.commit + '^{tree}') == receipt.tree
    assert git(remote, 'show', '-s', '--format=%P', result.commit) == base
    assert git(remote, 'show', '-s', '--format=%an <%ae>|%cn <%ce>', result.commit) == 'vaNlabs <vanlabs@pm.me>|vaNlabs <vanlabs@pm.me>'
    assert git(trusted, 'rev-parse', 'HEAD') == base  # no live rollout
    assert result.remote == str(remote)
    assert result.branch == 'refs/heads/main'


@pytest.mark.parametrize('fault', ['after_push', 'readback', 'before_push'])
def test_durable_intent_recovers_exact_commit(publication, monkeypatch, fault):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    journal = repo.parent / 'publication-intent.json'
    original = p._run
    pushed = False
    def interrupt(scratch, *args, **kwargs):
        nonlocal pushed
        if args[0] == 'push':
            intent = json.loads(journal.read_text())
            assert intent['baseline'] == base
            assert intent['tree'] == receipt.tree
            assert intent['receipt_signature'] == receipt.signature
            assert intent['commit'] == args[2].split(':')[0]
            assert intent['raw_commit']
            if fault == 'before_push':
                raise RuntimeError('interrupted')
        if args[0] == 'ls-remote' and pushed and fault == 'readback':
            return b''
        result = original(scratch, *args, **kwargs)
        if args[0] == 'push':
            pushed = True
            if fault == 'after_push':
                raise RuntimeError('interrupted')
        return result
    monkeypatch.setattr(p, '_run', interrupt)
    with pytest.raises((RuntimeError, v.ValidationError)):
        publish(publication, receipt, journal_path=journal)
    intended = json.loads(journal.read_text())['commit']
    monkeypatch.setattr(p, '_run', original)
    result = publish(publication, receipt, journal_path=journal)
    assert result.commit == intended
    assert git(remote, 'rev-parse', 'refs/heads/main') == intended
    assert git(trusted, 'rev-parse', 'HEAD') == base


@pytest.mark.parametrize('remote_state', ['advanced', 'deleted'])
def test_retry_preserves_unexpected_remote(publication, monkeypatch, remote_state):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    journal = repo.parent / 'publication-intent.json'
    original = p._run
    def interrupt(scratch, *args, **kwargs):
        if args[0] == 'push':
            raise RuntimeError('before push')
        return original(scratch, *args, **kwargs)
    monkeypatch.setattr(p, '_run', interrupt)
    with pytest.raises(RuntimeError):
        publish(publication, receipt, journal_path=journal)
    saved = journal.read_bytes()
    if remote_state == 'advanced':
        git(repo, 'push', 'origin', 'HEAD:refs/heads/main')
    else:
        git(remote, 'update-ref', '-d', 'refs/heads/main')
    before = git(remote, 'show-ref', '--head') if remote_state == 'advanced' else ''
    monkeypatch.setattr(p, '_run', original)
    with pytest.raises(v.ValidationError, match='baseline advanced'):
        publish(publication, receipt, journal_path=journal)
    assert journal.read_bytes() == saved
    if remote_state == 'advanced':
        assert git(remote, 'show-ref', '--head') == before
    else:
        assert subprocess.run(['git', '-C', str(remote), 'rev-parse', '--verify', 'refs/heads/main'],
                              capture_output=True).returncode != 0


@pytest.mark.parametrize('field', ['commit', 'baseline', 'tree', 'receipt_signature', 'raw_commit'])
def test_journal_tampering_rejected_before_transport(publication, monkeypatch, field):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    journal = repo.parent / 'publication-intent.json'
    publish(publication, receipt, journal_path=journal)
    intent = json.loads(journal.read_text())
    intent[field] += 'forged'
    journal.write_text(json.dumps(intent))
    def forbidden(*args, **kwargs):
        raise AssertionError('untrusted journal reached transport')
    monkeypatch.setattr(p, '_run', forbidden)
    with pytest.raises(v.ValidationError, match='journal'):
        publish(publication, receipt, journal_path=journal)


@pytest.mark.parametrize('change', ['message', 'remote', 'candidate', 'receipt_signature'])
def test_authenticated_journal_identity_is_bound(publication, monkeypatch, change):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    journal = repo.parent / 'publication-intent.json'
    publish(publication, receipt, journal_path=journal)
    intent = json.loads(journal.read_text())
    intent[change] = 'different'
    # Even a valid MAC cannot authorize a different invocation identity.
    intent['hmac'] = p._intent_mac({k: val for k, val in intent.items() if k != 'hmac'}, KEY)
    journal.write_text(json.dumps(intent))
    with pytest.raises(v.ValidationError, match='journal'):
        publish(publication, receipt, journal_path=journal)


@pytest.mark.parametrize('location', ['candidate', 'symlink'])
def test_journal_must_be_outside_candidate(publication, location):
    repo, base, remote, trusted = publication
    journal = repo / '.git/intent.json'
    if location == 'symlink':
        alias = repo.parent / 'alias'
        alias.symlink_to(repo / '.git', target_is_directory=True)
        journal = alias / 'intent.json'
    with pytest.raises(v.ValidationError, match='journal'):
        publish(publication, journal_path=journal)
    assert git(remote, 'rev-parse', 'refs/heads/main') == base


def test_production_requires_durable_journal(publication, monkeypatch):
    repo, base, remote, trusted = publication
    receipt = validate(repo, base)
    git(trusted, 'remote', 'set-url', 'origin', p.APPROVED_REMOTE)
    def forbidden(*args, **kwargs):
        raise AssertionError('must fail before transport')
    monkeypatch.setattr(p, '_run', forbidden)
    with pytest.raises(v.ValidationError, match='journal'):
        p.publish_candidate(trusted, repo, receipt, signing_key=KEY,
            message='docs: runtime audit', credential_env={'GIT_SSH_COMMAND': 'ssh'})
