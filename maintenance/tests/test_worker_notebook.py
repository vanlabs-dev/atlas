"""Fresh-call continuity is untrusted, hash-bound, and role-local."""
import pytest
from maintenance import worker as w
from maintenance.tests.test_worker import repo, packet, answer
from maintenance.tests.test_worker_request_recovery import add_files


def note(payload, summary='README examined; next inspect second file'):
    return {'entries': [{'path': 'README.md', 'version': payload.get('file_version', 'current'),
                         'sha256': payload['files']['README.md']['sha256'], 'summary': summary}],
            'progress': {'completed': ['README audit'], 'remaining': ['second file'], 'plan': 'Finish dispositions'}}


@pytest.mark.parametrize('role', ['coder', 'reviewer'])
def test_fresh_calls_keep_hash_bound_notebook_independently(repo, role):
    add_files(repo, ['second.txt'])
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []
    saved = []
    def model(p):
        calls.append(p)
        assert p['rounds_remaining'] == 4 - len(calls)
        assert p['model_notebook']['trust'] == 'untrusted model summaries; NOT raw evidence or edit authorization'
        assert p['model_notebook']['evidence_sha256'] == w.sha256(w.canonical(packet()))
        assert len(w.request_wire(p)) == p['request_limits']['serialized_payload_bytes'] <= 800000
        if len(calls) == 1:
            assert p['model_notebook']['entries'] == []
            return {'action': 'request_files', 'paths': ['README.md']}
        if len(calls) == 2:
            saved.append(note(p))
            return {'action': 'request_files', 'paths': ['second.txt'], 'notebook': saved[0]}
        assert set(p['files']) == {'second.txt'}
        assert p['model_notebook']['entries'] == saved[0]['entries']
        assert p['model_notebook']['progress'] == saved[0]['progress']
        a = answer(p); a['edits'] = []
        return {**a, 'action': 'review' if role == 'reviewer' else 'propose', 'approved': True,
                'manifest_sha256': p.get('manifest_sha256'), 'tree': p.get('tree'), 'checks': p.get('checks')}
    if role == 'coder':
        w.propose(repo, packet(), model, max_rounds=3)
    else:
        w.review_proposal(repo, packet(), proposal, model, tree='tree', checks={'tests': 'passed'},
                          worker_id='coder', reviewer_id='reviewer', max_rounds=3)
    assert len(calls) == 3


@pytest.mark.parametrize('value', [None, [], 'text', {}, {'entries': [], 'progress': []},
    {'entries': 'bad', 'progress': {}},
    {'entries': [], 'progress': {'completed': [], 'remaining': [], 'plan': 1}},
    {'entries': [], 'progress': {'completed': [1], 'remaining': [], 'plan': ''}},
    {'entries': [], 'progress': {'completed': [], 'remaining': [], 'plan': '\ud800'}},
    {'entries': [{'path': [], 'version': 'current', 'sha256': None, 'summary': ''}],
     'progress': {'completed': [], 'remaining': [], 'plan': ''}}])
def test_malformed_notebook_is_sanitized(value):
    n = w.ModelNotebook(packet(), 'coding-worker')
    old = w.canonical(n.value)
    candidate, errors = n.candidate({'notebook': value})
    assert errors == [{'path': '<notebook>', 'reason':
        'invalid notebook schema, size or undelivered hash; no notebook or files accepted'}]
    assert w.canonical(candidate) == w.canonical(n.value) == old


def test_notebook_exact_wire_boundary_and_original_absence():
    n = w.ModelNotebook(packet(), 'independent-reviewer')
    p = {'files': {'new.txt': {'sha256': None, 'content': None}}, 'file_version': 'original', 'protocol': ''}
    n.annotate(p, 2)
    value = {'entries': [{'path': 'new.txt', 'version': 'original', 'sha256': None, 'summary': 'absent'}],
             'progress': {'completed': ['x' * 1000] * 28, 'remaining': [], 'plan': ''}}
    value['progress']['plan'] = 'x' * (32000 - len(w.request_wire(value)))
    assert len(w.request_wire(value)) == 32000
    assert n.candidate({'notebook': value})[1] == []
    value['progress']['plan'] += 'x'
    assert n.candidate({'notebook': value})[1]


@pytest.mark.parametrize('role', ['coder', 'reviewer'])
@pytest.mark.parametrize('bad', ['schema', 'oversize', 'unread', 'hash', 'duplicate', 'version', 'paths', 'surrogate'])
def test_invalid_update_is_atomic_and_correctable(repo, role, bad):
    add_files(repo, ['second.txt'])
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []
    def model(p):
        calls.append(p)
        n = len(calls)
        if n == 1:
            return {'action': 'request_files', 'paths': ['README.md']}
        if n == 2:
            notes = note(p)
            paths = ['second.txt']
            if bad == 'schema': notes['extra'] = True
            if bad == 'surrogate': notes['progress']['plan'] = '\ud800'
            if bad == 'oversize': notes['progress']['completed'] = ['☃' * 1000] * 12
            if bad == 'unread': notes['entries'][0]['path'] = 'second.txt'
            if bad == 'hash': notes['entries'][0]['sha256'] = '0' * 64
            if bad == 'duplicate': notes['entries'] *= 2
            if bad == 'version': notes['entries'][0]['version'] = 'original'
            if bad == 'paths': paths = ['.hidden']
            return {'action': 'request_files', 'paths': paths, 'notebook': notes}
        if n == 3:
            assert p['request_feedback']['status'] == 'rejected'
            assert p['model_notebook']['entries'] == []
            assert set(p['files']) == {'README.md'}
            return {'action': 'request_files', 'paths': ['second.txt'], 'notebook': note(p)}
        assert p['request_feedback'] is None
        assert set(p['files']) == {'second.txt'}
        assert len(p['model_notebook']['entries']) == 1
        a = answer(p); a['edits'] = []
        return {**a, 'action': 'review' if role == 'reviewer' else 'propose', 'approved': True,
                'manifest_sha256': p.get('manifest_sha256'), 'tree': p.get('tree'), 'checks': p.get('checks')}
    if role == 'coder': w.propose(repo, packet(), model, max_rounds=4)
    else:
        w.review_proposal(repo, packet(), proposal, model, tree='tree', checks={'tests': 'passed'},
                          worker_id='coder', reviewer_id='reviewer', max_rounds=4)
    assert len(calls) == 4


def test_notebook_correction_budget_is_bounded(repo):
    calls = []
    def model(p):
        calls.append(p)
        return {'action': 'request_files', 'paths': ['README.md'], 'notebook': []}
    with pytest.raises(w.WorkerBlocked, match='iteration budget exhausted'):
        w.propose(repo, packet(), model, max_rounds=3)
    assert len(calls) == 3


def test_wire_limit_cannot_be_relaxed_by_caller():
    calls = []
    with pytest.raises(w.WorkerBlocked, match='context budget exceeded'):
        w.model_call(lambda p: calls.append(p) or {}, {'text': 'x' * 800001}, 900000)
    assert calls == []
