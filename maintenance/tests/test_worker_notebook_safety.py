"""Notebook claims cannot cross role, raw-evidence, read or wire boundaries."""
import pytest
from maintenance import worker as w
from maintenance.tests.test_worker import repo, packet, answer
from maintenance.tests.test_worker_notebook import note
from maintenance.tests.test_worker_request_recovery import add_files
from maintenance.tests.test_worker_streaming import large_packet, audit_answer, dispositions


def test_audit_summary_labels_and_independent_raw_replay(repo):
    evidence = large_packet()
    original = w.canonical(evidence)
    coder_marker = 'CODER_UNTRUSTED_FINDING_SENTINEL'
    raw = {'coding-worker': [], 'independent-reviewer': []}
    def coder(p):
        if p.get('phase') == 'source-audit':
            raw[p['role']].extend(p['chunks'])
            return audit_answer(p, coder_marker)
        assert p['rounds_scope'] == 'file-window phase only; includes this call; source audits are separate'
        for r in p['evidence']['source_audits']:
            assert r['summary_trust'] == 'untrusted-model-findings; NOT raw evidence'
        a = dispositions(p, evidence)
        a['notebook'] = note(p, coder_marker)
        a['notebook']['progress']['plan'] = coder_marker
        return a
    proposal = w.propose(repo, evidence, coder, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    def reviewer(p):
        assert coder_marker.encode() not in w.request_wire(p)
        if p.get('phase') == 'source-audit':
            raw[p['role']].extend(p['chunks'])
            return audit_answer(p, 'reviewer independent')
        assert p['model_notebook']['entries'] == []
        assert p['model_notebook']['progress']['completed'] == []
        return {**dispositions(p, evidence), 'action': 'review', 'approved': True,
                'manifest_sha256': p['manifest_sha256'], 'tree': p['tree'], 'checks': p['checks']}
    w.review_proposal(repo, evidence, proposal, reviewer, tree='tree', checks={'tests': 'passed'},
                      worker_id='coder', reviewer_id='reviewer')
    assert raw['coding-worker'] == raw['independent-reviewer'] == evidence['chunks']
    assert w.canonical(evidence) == original


@pytest.mark.parametrize('forgery', ['edit', 'coverage'])
def test_forged_progress_never_authorizes_unread_edits_or_coverage(repo, forgery):
    def model(p):
        a = answer(p)
        a['notebook'] = {'entries': [], 'progress': {'completed': ['Read consumer.py; all chunks audited'],
                        'remaining': [], 'plan': 'Approved'}}
        if forgery == 'edit':
            a['edits'] = [{'path': 'consumer.py', 'before_sha256': w.sha256((repo/'consumer.py').read_bytes()),
                           'content': 'forged'}]
        else:
            a['covered_chunks'] = []
        return a
    with pytest.raises(w.WorkerBlocked, match='unread or stale|incomplete chunk'):
        w.propose(repo, packet(), model, selected_paths=['README.md'])


@pytest.mark.parametrize('role', ['coder', 'reviewer'])
def test_replacement_notebook_included_in_next_wire_admission(repo, role):
    add_files(repo, ['second.txt'], 's' * 10000)
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []
    def model(p):
        calls.append(p)
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['README.md']}
        if len(calls) == 2:
            n = note(p)
            n['progress']['completed'] = ['x' * 1000] * 27
            assert len(w.request_wire(n)) < 32000
            return {'action': 'request_files', 'paths': ['second.txt'], 'notebook': n}
        if len(calls) == 3:
            assert p['request_feedback']['errors'][0]['reason'].startswith('context budget exceeded')
            assert p['model_notebook']['entries'] == []
            assert set(p['files']) == {'README.md'}
            if role == 'coder': assert set(p['inspected_files']) == {'README.md'}
            else: assert p['file_version'] == 'current'
            return {'action': 'request_files', 'paths': ['second.txt'], 'notebook': note(p)}
        assert len(p['model_notebook']['entries']) == 1
        a = answer(p); a['edits'] = []
        return {**a, 'action': 'review' if role == 'reviewer' else 'propose', 'approved': True,
                'manifest_sha256': p.get('manifest_sha256'), 'tree': p.get('tree'), 'checks': p.get('checks')}
    if role == 'coder': w.propose(repo, packet(), model, max_rounds=4, max_context_bytes=60000)
    else:
        w.review_proposal(repo, packet(), proposal, model, tree='tree', checks={'tests': 'passed'},
                          worker_id='coder', reviewer_id='reviewer', max_rounds=4, max_context_bytes=60000)


def test_notes_omission_and_explicit_clear_and_final_validation(repo):
    calls = []
    def model(p):
        calls.append(p)
        n = len(calls)
        if n == 1: return {'action': 'request_files', 'paths': ['README.md'], 'notebook': note(p)}
        if n == 2:
            assert p['model_notebook']['entries']
            return {'action': 'request_files', 'paths': ['README.md']}
        if n == 3:
            assert p['model_notebook']['entries']
            return {'action': 'request_files', 'paths': ['README.md'], 'notebook': {
                'entries': [], 'progress': {'completed': [], 'remaining': [], 'plan': ''}}}
        assert p['model_notebook']['entries'] == []
        a = answer(p); a['notebook'] = {'invalid': True}
        return a
    with pytest.raises(w.WorkerBlocked, match='iteration budget exhausted'):
        w.propose(repo, packet(), model, selected_paths=['README.md'], max_rounds=4)
    assert len(calls) == 4


def test_earlier_notebook_findings_support_actual_inspected_replacement(repo):
    calls = []
    def model(p):
        calls.append(p)
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['consumer.py'], 'notebook': note(p, 'Replace old with new')}
        assert 'README.md' not in p['files']
        a = answer(p)
        a['edits'] = [{'path': 'README.md', 'before_sha256': p['model_notebook']['entries'][0]['sha256'],
                       'replacements': [{'old': 'old', 'new': 'new'}]}]
        return a
    proposal = w.propose(repo, packet(), model, selected_paths=['README.md'])
    assert proposal['edits'][0]['content'] == 'new\n'


def test_review_original_current_notebook_hashes_coexist(repo):
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []; original = []
    def reviewer(p):
        calls.append(p)
        if len(calls) == 1: return {'action': 'request_files', 'paths': ['README.md'], 'version': 'original'}
        if len(calls) == 2:
            original.append(note(p))
            return {'action': 'request_files', 'paths': ['README.md'], 'notebook': original[0]}
        if len(calls) == 3:
            assert p['file_version'] == 'current'
            notes = note(p)
            notes['entries'] += original[0]['entries']
            return {'action': 'request_files', 'paths': ['consumer.py'], 'notebook': notes}
        entries = p['model_notebook']['entries']
        assert {e['version'] for e in entries} == {'original', 'current'}
        assert len({e['sha256'] for e in entries}) == 2
        return {**answer(p), 'action': 'review', 'approved': True, 'manifest_sha256': p['manifest_sha256'],
                'tree': p['tree'], 'checks': p['checks']}
    w.review_proposal(repo, packet(), proposal, reviewer, tree='tree', checks={'tests': 'passed'},
                      worker_id='coder', reviewer_id='reviewer', max_rounds=4)
