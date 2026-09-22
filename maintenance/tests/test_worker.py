import hashlib
import json
import subprocess
import pytest
from maintenance import worker as w


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'candidate'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'README.md').write_text('old\n')
    (root / 'consumer.py').write_text('VALUE = 1\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    return root


def packet():
    return {'complete': True, 'upstream_paths': ['runtime/lib.rs'],
            'chunks': [{'id': 'chunk-1', 'path': 'runtime/lib.rs', 'text': 'diff full',
                        'sha256': digest('diff full')}],
            'chunk_ids': ['chunk-1']}


def answer(payload):
    return {'action': 'propose', 'edits': [{'path': 'README.md',
        'before_sha256': digest('old\n'), 'content': 'new\n'}],
        'covered_chunks': ['chunk-1'],
        'upstream': {'runtime/lib.rs': {'disposition': 'update_required', 'evidence': 'chunk-1'}},
        'subsystems': {s: {'disposition': 'no_impact', 'evidence': 'chunk-1'} for s in w.SUBSYSTEMS},
        'inventory_groups': {s: {'disposition': 'no_impact', 'evidence': 'chunk-1'}
                             for s in payload.get('inventory_groups', {'root': []})}}


def test_git_inventory_ignores_inherited_git_overrides(repo, monkeypatch):
    monkeypatch.setenv('GIT_INDEX_FILE', str(repo.parent / 'absent-index'))
    assert w.tracked_paths(repo) == ['README.md', 'consumer.py']


def test_requests_tracked_text_then_returns_hash_bound_proposal(repo):
    calls = []
    def model(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['consumer.py']}
        assert payload['files']['consumer.py']['content'] == 'VALUE = 1\n'
        return answer(payload)
    result = w.propose(repo, packet(), model, selected_paths=['README.md'])
    assert len(calls) == 2
    assert result['manifest'] == {'README.md': {'before_sha256': digest('old\n'), 'after_sha256': digest('new\n')}}
    assert (repo / 'README.md').read_text() == 'old\n'


@pytest.mark.parametrize('path', ['auth.json', 'keys/token.txt', 'database.sqlite', 'output/log.txt'])
def test_sensitive_tracked_paths_are_denied(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('secret')
    subprocess.run(['git', '-C', str(repo), 'add', path], check=True)
    with pytest.raises(w.WorkerBlocked):
        w.read_text(repo, path)


def test_secret_contents_never_reach_inference(repo):
    (repo / 'consumer.py').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nsecret')
    with pytest.raises(w.WorkerBlocked):
        w.read_text(repo, 'consumer.py')


def test_blocked_evidence_cannot_be_promoted_by_complete_flag(repo):
    evidence = {**packet(), 'status': 'blocked', 'blocked_reasons': ['source provenance unknown']}
    with pytest.raises(w.WorkerBlocked):
        w.propose(repo, evidence, answer, selected_paths=['README.md'])


@pytest.mark.parametrize('path', ['../outside', '/etc/passwd', '.git/config', '.env',
    'var/token.txt', 'secrets.json', 'private/key.pem', 'link', 'untracked.txt'])
def test_file_requests_cannot_escape_or_read_secrets(repo, path):
    outside = repo.parent / 'outside'
    outside.write_text('SECRET')
    (repo / 'link').symlink_to(outside)
    (repo / '.env').write_text('SECRET')
    (repo / 'untracked.txt').write_text('SECRET')
    subprocess.run(['git', '-C', str(repo), 'add', '-f', 'link', '.env'], check=True)
    calls = []
    def request(payload):
        calls.append(payload)
        return {'action': 'request_files', 'paths': [path]} if len(calls) == 1 else answer(payload)
    with pytest.raises(w.WorkerBlocked):
        w.propose(repo, packet(), request, selected_paths=['README.md'])


@pytest.mark.parametrize('failure', ['incomplete', 'missing_chunk', 'hash', 'coverage',
    'subsystem', 'stale', 'duplicate', 'unread_edit', 'context', 'output', 'policy'])
def test_proposal_fails_closed(repo, failure):
    evidence = packet()
    response = answer({})
    kwargs = {}
    if failure == 'incomplete': evidence['complete'] = False
    if failure == 'missing_chunk': evidence['chunk_ids'].append('missing')
    if failure == 'hash': evidence['chunks'][0]['text'] = 'tampered'
    if failure == 'coverage': response['covered_chunks'] = []
    if failure == 'subsystem': response['subsystems'].pop('operator_docs')
    if failure == 'stale': response['edits'][0]['before_sha256'] = '0' * 64
    if failure == 'duplicate': response['edits'] *= 2
    if failure == 'unread_edit': response['edits'][0]['path'] = 'consumer.py'
    if failure == 'context': kwargs['max_context_bytes'] = 10
    if failure == 'output': kwargs['max_edit_bytes'] = 1
    if failure == 'policy':
        (repo / 'AGENTS.md').write_text('policy')
        subprocess.run(['git', '-C', str(repo), 'add', 'AGENTS.md'], check=True)
        response['edits'][0] = {'path': 'AGENTS.md', 'before_sha256': digest('policy'), 'content': 'unsafe'}
    with pytest.raises(w.WorkerBlocked):
        w.propose(repo, evidence, lambda _: response, selected_paths=['README.md'], **kwargs)


def test_worker_contract_matches_validator():
    from maintenance import validate
    assert w.SUBSYSTEMS == validate.SUBSYSTEMS


def test_apply_then_independent_manifest_review(repo):
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    assert (repo / 'README.md').read_text() == 'new\n'
    calls = []
    def reviewer(payload):
        calls.append(payload)
        assert payload['manifest'] == proposal['manifest']
        assert payload['diffs']['README.md'] == '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n'
        assert payload['files'] == {}
        result = answer(payload)
        return {**result, 'action': 'review', 'approved': True,
                'manifest_sha256': payload['manifest_sha256'],
                'checks': payload['checks'], 'tree': payload['tree']}
    review = w.review_proposal(repo, packet(), proposal, reviewer, tree='a' * 40,
        checks={'tests': 'passed'}, worker_id='coder-1', reviewer_id='reviewer-1')
    assert review['worker'] != review['reviewer']
    assert review['manifest_sha256'] == proposal['manifest_sha256']
    assert review['upstream']['runtime/lib.rs']['disposition'] == 'updated'
    with pytest.raises(w.WorkerBlocked):
        w.apply_proposal(repo, proposal)


@pytest.mark.parametrize('failure', ['manifest', 'rejected', 'identity', 'tampered', 'checks'])
def test_review_rejects_unsafe_candidate(repo, failure):
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    if failure == 'tampered': (repo / 'README.md').write_text('tamper')
    def reviewer(payload):
        return {**answer(payload), 'action': 'review', 'approved': failure != 'rejected',
            'manifest_sha256': 'wrong' if failure == 'manifest' else payload['manifest_sha256'],
            'tree': payload['tree'], 'checks': {} if failure == 'checks' else payload['checks']}
    with pytest.raises(w.WorkerBlocked):
        w.review_proposal(repo, packet(), proposal, reviewer, tree='a' * 40,
            checks={'tests': 'passed'}, worker_id='coder',
            reviewer_id='coder' if failure == 'identity' else 'reviewer')


def test_review_rejects_additional_unreviewed_file(repo):
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    (repo / 'consumer.py').write_text('VALUE = 999\n')
    def reviewer(payload):
        return {**answer(payload), 'action': 'review', 'approved': True,
            'manifest_sha256': payload['manifest_sha256'], 'tree': payload['tree'], 'checks': payload['checks']}
    with pytest.raises(w.WorkerBlocked, match='unreviewed'):
        w.review_proposal(repo, packet(), proposal, reviewer, tree='a' * 40,
            checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')


def test_dynamic_inventory_groups_cannot_be_omitted(repo):
    (repo / 'triage').mkdir()
    (repo / 'triage/consumer.py').write_text('VALUE = 1\n')
    subprocess.run(['git', '-C', str(repo), 'add', 'triage'], check=True)
    def model(payload):
        assert set(payload['inventory_groups']) == {'root', 'triage'}
        result = answer(payload)
        del result['inventory_groups']['triage']
        return result
    with pytest.raises(w.WorkerBlocked, match='inventory_groups'):
        w.propose(repo, packet(), model, selected_paths=['README.md'])


def test_new_file_edits_are_absence_bound_and_reviewable(repo):
    def model(payload):
        response = answer(payload)
        response['edits'].append({'path': 'tests/test_consumer.py', 'before_sha256': None,
                                  'content': 'def test_constant():\n    assert 2 == 2\n'})
        return response
    proposal = w.propose(repo, packet(), model, selected_paths=['README.md'])
    assert proposal['manifest']['tests/test_consumer.py']['before_sha256'] is None
    w.apply_proposal(repo, proposal)
    assert (repo / 'tests/test_consumer.py').is_file()
    tests = w.run_isolated_tests(repo, proposal=proposal,
        python_args=['-m', 'pytest', '-p', 'no:cacheprovider', 'tests', '-q'],
        venv='/home/pi/.cache/atlas-maintenance-venv', timeout=20)
    assert tests['returncode'] == 0, tests
    assert '1 passed' in tests['stdout']
    def reviewer(payload):
        return {**answer(payload), 'action': 'review', 'approved': True,
            'manifest_sha256': payload['manifest_sha256'], 'tree': payload['tree'], 'checks': payload['checks']}
    result = w.review_proposal(repo, packet(), proposal, reviewer, tree='trusted-tree',
        checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')
    assert result['approved'] is True
    with pytest.raises(w.WorkerBlocked):
        w.apply_proposal(repo, proposal)


def test_null_hash_cannot_overwrite_existing_file(repo):
    def model(payload):
        response = answer(payload)
        response['edits'][0]['before_sha256'] = None
        return response
    with pytest.raises(w.WorkerBlocked):
        w.propose(repo, packet(), model, selected_paths=['README.md'])


def test_isolated_tests_have_readonly_source_and_no_host_secrets(repo, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'secret')
    (repo / '.env').write_text('GITHUB_TOKEN=secret')
    subprocess.run(['git', '-C', str(repo), 'add', '-f', '.env'], check=True)
    code = """import os, pathlib, socket
assert 'GITHUB_TOKEN' not in os.environ
import resource
assert resource.getrlimit(resource.RLIMIT_NPROC)[0] <= 128
assert not pathlib.Path('/home/pi/.hermes/auth.json').exists()
try:
    pathlib.Path('/candidate/README.md').write_text('bad')
except OSError:
    pass
else:
    raise AssertionError('candidate writable')
assert pathlib.Path('/candidate/README.md').read_text() == 'old\\n'
print('isolated-ok')
"""
    result = w.run_isolated_tests(repo, python_args=['-c', code],
        venv='/home/pi/.cache/atlas-maintenance-venv', timeout=20)
    assert result['returncode'] == 0, result
    assert 'isolated-ok' in result['stdout']
    assert result['excluded_paths'] == ['.env']
    assert (repo / 'README.md').read_text() == 'old\n'
