"""Offline protocol tests: actual payloads, never real inference."""
import copy
from typing import Any
import pytest
from maintenance import worker as w
from maintenance.tests.test_worker import repo, digest, packet, answer


def large_packet(chunk_count=5, repeats=3500):
    chunks = [{'id': f'chunk-{i}', 'path': f'runtime/{i}.rs',
               'text': (f'raw-source-{i}\n' * repeats)} for i in range(chunk_count)]
    for chunk in chunks:
        chunk['sha256'] = digest(chunk['text'])
    return {'complete': True, 'chunks': chunks,
            'chunk_ids': [c['id'] for c in chunks],
            'upstream_paths': [c['path'] for c in chunks]}


def dispositions(payload, evidence):
    result = answer(payload)
    result['covered_chunks'] = evidence['chunk_ids']
    result['upstream'] = {p: {'disposition': 'no_impact', 'evidence': 'audited'}
                          for p in evidence['upstream_paths']}
    return result


def audit_answer(payload, label):
    return {'action': 'source_audit', 'covered_chunks': [
        {'id': c['id'], 'sha256': c['sha256']} for c in payload['chunks']],
        'summary': label + ': migration and consumer findings'}


def test_hash_bound_replacements_materialize_large_files_without_large_output(repo):
    texts = {'README.md': 'before-marker\n' + 'x\n' * 73000,
             'consumer.py': 'before-marker\n' + 'y\n' * 63500}
    for path, text in texts.items():
        (repo / path).write_text(text)
    def model(payload):
        result = answer(payload)
        result['edits'] = [{'path': p, 'before_sha256': digest(text),
            'replacements': [{'old': 'before-marker', 'new': 'after-marker'}]}
            for p, text in texts.items()]
        return result
    proposal = w.propose(repo, packet(), model, selected_paths=list(texts), max_edit_bytes=1000)
    assert all(set(e) == {'path', 'before_sha256', 'content'} for e in proposal['edits'])
    w.apply_proposal(repo, proposal)
    for path, text in texts.items():
        assert (repo / path).read_text() == text.replace('before-marker', 'after-marker')


def test_review_serves_original_and_current_files_on_request(repo):
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []
    def reviewer(payload):
        calls.append(payload)
        if len(calls) == 1:
            assert payload['files'] == {}
            return {'action': 'request_files', 'paths': ['README.md'], 'version': 'original'}
        if len(calls) == 2:
            assert payload['files']['README.md'] == proposal['before_files']['README.md']
            assert payload['file_version'] == 'original'
            return {'action': 'request_files', 'paths': ['README.md']}
        assert payload['files']['README.md']['content'] == 'new\n'
        assert payload['file_version'] == 'current'
        return {**answer(payload), 'action': 'review', 'approved': True,
                'manifest_sha256': payload['manifest_sha256'],
                'checks': payload['checks'], 'tree': payload['tree']}
    w.review_proposal(repo, packet(), proposal, reviewer, tree='tree',
        checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')


@pytest.mark.parametrize('path', ['conftest.py', 'nested/conftest.py', 'pytest.ini',
    'pyproject.toml', 'setup.cfg', 'tox.ini', 'sitecustomize.py', 'usercustomize.py',
    'pytest.py', 'pytest/__init__.py', 'nested/pytest/plugin.py'])
def test_harness_policy_paths_readable_but_never_writable(repo, path):
    assert w.safe_path(repo, path) == repo / path
    for new in (False, True):
        with pytest.raises(w.WorkerBlocked, match='policy'):
            w.safe_path(repo, path, writable=True, new=new)


def test_file_windows_do_not_accumulate_but_keep_inspected_hashes(repo):
    for path in ('README.md', 'consumer.py'):
        (repo / path).write_text(path + '\n' + 'x' * 150000)
    calls = []
    def model(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['README.md']}
        if len(calls) == 2:
            return {'action': 'request_files', 'paths': ['consumer.py']}
        assert set(payload['files']) == {'consumer.py'}
        assert set(payload['inspected_files']) == {'README.md', 'consumer.py'}
        result = answer(payload)
        result['edits'] = [{'path': 'README.md',
            'before_sha256': payload['inspected_files']['README.md'],
            'replacements': [{'old': 'README.md', 'new': 'renamed header'}]}]
        return result
    proposal = w.propose(repo, packet(), model, max_context_bytes=200000)
    assert proposal['edits'][0]['content'].startswith('renamed header\n')


def test_compact_inventory_keeps_complete_path_manifest_and_binding(repo):
    evidence = large_packet()
    records = [{'path': f'consumer/{i}.py', 'oid': str(i), 'mode': '100644'} for i in range(20)]
    evidence['atlas_inventory'] = {'commit': 'abc', 'files': records,
        'subsystems': {'consumer': {'paths': [r['path'] for r in records], 'disposition': 'pending'}}}
    def model(payload):
        context = payload.get('evidence_context', payload.get('evidence'))
        compact = context['atlas_inventory']
        assert compact['full_path_manifest'] == [r['path'] for r in records]
        assert compact['sha256'] == w.sha256(w.canonical(evidence['atlas_inventory']))
        assert 'files' not in compact
        assert compact['subsystems']['consumer']['path_indices'] == list(range(20))
        if payload.get('phase') == 'source-audit':
            return audit_answer(payload, 'coder')
        return dispositions(payload, evidence)
    w.propose(repo, evidence, model, selected_paths=['README.md'])


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'hash', 'extra', 'schema', 'summary'])
@pytest.mark.parametrize('role', ['coding-worker', 'independent-reviewer'])
def test_bad_audit_never_reaches_final_gate(repo, failure, role):
    evidence = large_packet()
    def good(payload):
        if payload.get('phase') == 'source-audit':
            return audit_answer(payload, 'coder')
        return dispositions(payload, evidence)
    def bad(payload):
        assert payload['phase'] == 'source-audit'
        response = audit_answer(payload, role)
        if failure == 'missing': response['covered_chunks'].pop()
        if failure == 'duplicate': response['covered_chunks'].append(response['covered_chunks'][0])
        if failure == 'hash': response['covered_chunks'][0]['sha256'] = '0' * 64
        if failure == 'extra': response['covered_chunks'].append({'id': 'extra', 'sha256': '0' * 64})
        if failure == 'schema': response['coverage_count'] = 999
        if failure == 'summary': response['summary'] = 'x' * 16001
        return response
    with pytest.raises(w.WorkerBlocked, match='audit'):
        if role == 'coding-worker':
            w.propose(repo, evidence, bad)
        else:
            proposal = w.propose(repo, evidence, good, selected_paths=['README.md'])
            proposal['source_audit_receipts'] = [{'summary': 'forged coder approval'}]
            w.apply_proposal(repo, proposal)
            w.review_proposal(repo, evidence, proposal, bad, tree='tree',
                checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')


@pytest.mark.parametrize('failure', ['missing', 'nonunique', 'empty', 'overlap', 'stale',
    'unread', 'new', 'wire_budget', 'per_file', 'overall', 'binary', 'both'])
def test_replacement_edits_fail_closed(repo, failure):
    (repo / 'README.md').write_text('old old unique\n')
    edit = {'path': 'README.md', 'before_sha256': digest('old old unique\n'),
            'replacements': [{'old': 'unique', 'new': 'new'}]}
    kwargs: dict[str, Any] = {'selected_paths': ['README.md']}
    if failure == 'missing': edit['replacements'][0]['old'] = 'absent'
    if failure == 'nonunique': edit['replacements'][0]['old'] = 'old'
    if failure == 'empty': edit['replacements'][0]['old'] = ''
    if failure == 'overlap': edit['replacements'].append({'old': 'nique', 'new': 'other'})
    if failure == 'stale': edit['before_sha256'] = '0' * 64
    if failure == 'unread': kwargs['selected_paths'] = []
    if failure == 'new': edit.update(path='new.py', before_sha256=None)
    if failure == 'wire_budget': kwargs['max_edit_bytes'] = 100
    if failure == 'per_file': edit['replacements'][0]['new'] = 'x' * 199999
    if failure == 'overall': kwargs['max_materialized_bytes'] = 1
    if failure == 'binary': edit['replacements'][0]['new'] = '\0'
    if failure == 'both': edit['content'] = 'conflicting'
    with pytest.raises(w.WorkerBlocked):
        w.propose(repo, packet(), lambda p: {**answer(p), 'edits': [edit]}, **kwargs)


def test_real_historical_packet_offline_covers_every_chunk_twice(repo):
    import json
    from pathlib import Path
    path = Path('/home/pi/.cache/atlas-maintenance-historical-model-packet.json')
    # Sandboxed acceptance suites deliberately cannot access host caches. Keep
    # exercising the same 146-chunk protocol there with an explicit test fixture.
    evidence = json.loads(path.read_text()) if path.exists() else large_packet(146, 200)
    seen = {'coding-worker': [], 'independent-reviewer': []}
    sizes = []
    (repo / 'README.md').write_text('old\n' + 'a' * 146000)
    (repo / 'consumer.py').write_text('original\n' + 'b' * 127000)
    rounds = {'coding-worker': 0, 'independent-reviewer': 0}
    def model(payload):
        sizes.append(len(w.canonical(payload)))
        role = payload['role']
        if payload.get('phase') == 'source-audit':
            seen[role].extend(payload['chunks'])
            return audit_answer(payload, role)
        assert seen[role] == evidence['chunks']
        rounds[role] += 1
        if rounds[role] == 1:
            return {'action': 'request_files', 'paths': ['README.md', 'consumer.py']}
        result = dispositions(payload, evidence)
        if role == 'coding-worker':
            result['edits'] = [{'path': 'README.md',
                'before_sha256': payload['files']['README.md']['sha256'],
                'replacements': [{'old': 'old\n', 'new': 'new\n'}]}]
            return result
        return {**result, 'action': 'review', 'approved': True,
            'manifest_sha256': payload['manifest_sha256'], 'tree': payload['tree'], 'checks': payload['checks']}
    original_bytes = w.canonical(evidence)
    proposal = w.propose(repo, evidence, model)
    w.apply_proposal(repo, proposal)
    review = w.review_proposal(repo, evidence, proposal, model, tree='tree',
        checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')
    assert len(evidence['chunks']) == 146
    assert w.canonical(evidence) == original_bytes
    assert max(sizes) <= 800000
    assert review['source_audit_coverage_count'] == proposal['source_audit_coverage_count'] == 146
    print('offline protocol:', 'real historical packet' if path.exists() else 'synthetic test fixture',
          'calls=', len(sizes), 'max_request_bytes=', max(sizes))


def test_replacement_old_must_not_have_overlapping_occurrences(repo):
    (repo / 'README.md').write_text('aaa')
    def model(payload):
        return {**answer(payload), 'edits': [{'path': 'README.md', 'before_sha256': digest('aaa'),
            'replacements': [{'old': 'aa', 'new': 'new'}]}]}
    with pytest.raises(w.WorkerBlocked, match='unique'):
        w.propose(repo, packet(), model, selected_paths=['README.md'])


def test_review_diff_preserves_missing_newlines(repo):
    (repo / 'README.md').write_text('old')
    proposal = w.propose(repo, packet(), lambda p: {**answer(p), 'edits': [
        {'path': 'README.md', 'before_sha256': digest('old'), 'content': 'new'}]},
        selected_paths=['README.md'])
    assert w.proposal_diffs(proposal)['README.md'] == (
        '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n'
        '-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n')


def test_replacement_budget_counts_serialized_list_envelope(repo):
    edit = {'path': 'README.md', 'before_sha256': digest('old\n'),
            'replacements': [{'old': 'old', 'new': 'new'}]}
    with pytest.raises(w.WorkerBlocked, match='budget'):
        w.propose(repo, packet(), lambda p: {**answer(p), 'edits': [edit]},
            selected_paths=['README.md'], max_edit_bytes=len(w.canonical(edit)))


def test_separate_raw_audits_precede_compact_final_gates(repo):
    evidence = large_packet()
    evidence_hash = w.sha256(w.canonical(evidence))
    calls = {'coding-worker': [], 'independent-reviewer': []}
    def model(payload):
        role = payload['role']
        calls[role].append(copy.deepcopy(payload))
        if payload.get('phase') == 'source-audit':
            assert len(w.canonical(payload)) < 180000
            assert sum(len(c['text'].encode()) for c in payload['chunks']) <= 120000
            return audit_answer(payload, role)
        audits = [p for p in calls[role] if p.get('phase') == 'source-audit']
        assert [c for p in audits for c in p['chunks']] == evidence['chunks']
        assert payload['evidence']['original_packet_sha256'] == evidence_hash
        assert payload['evidence']['view'] == 'source-audit-summaries'
        assert all('text' not in c for c in payload['evidence']['chunks'])
        assert all(role in r['summary'] for r in payload['evidence']['source_audits'])
        result = dispositions(payload, evidence)
        if role == 'coding-worker':
            return result
        assert 'edits' not in payload and 'before_files' not in payload
        assert '-old\n+new\n' in payload['diffs']['README.md']
        return {**result, 'action': 'review', 'approved': True,
                'manifest_sha256': payload['manifest_sha256'],
                'checks': payload['checks'], 'tree': payload['tree']}
    proposal = w.propose(repo, evidence, model, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    review = w.review_proposal(repo, evidence, proposal, model, tree='tree',
        checks={'tests': 'passed'}, worker_id='coder', reviewer_id='reviewer')
    for result, role in [(proposal, 'coding-worker'), (review, 'independent-reviewer')]:
        receipts = result['source_audit_receipts']
        assert result['evidence_sha256'] == evidence_hash
        assert result['source_audit_coverage_count'] == len(evidence['chunks'])
        raw_calls = [p for p in calls[role] if p.get('phase') == 'source-audit']
        assert len(receipts) == len(raw_calls)
        for receipt, payload in zip(receipts, raw_calls):
            assert receipt['request_sha256'] == w.sha256(w.canonical(payload))
            assert receipt['response_sha256'] == w.sha256(w.canonical(audit_answer(payload, role)))
            assert receipt['original_packet_sha256'] == evidence_hash
            assert receipt['covered_chunks'] == audit_answer(payload, role)['covered_chunks']
