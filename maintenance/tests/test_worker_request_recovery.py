"""Networkless request-protocol regression tests; replay paths are public metadata."""
import json
import subprocess

import pytest
from maintenance import worker as w
from maintenance.tests.test_worker import repo, packet, answer


# Exact model-005 request from the reconciled replay (no source contents).
RECORDED_PATHS = [
    'AGENTS.md', 'prd.md', 'docs/decisions.md', 'docs/emission-metrics.md',
    'knowledge/corpus/ground-truth.md', 'knowledge/corpus/fact-patterns.md',
    'knowledge/corpus/negative-claim-rules.md', 'knowledge/corpus/hashes.json',
    'knowledge/supersession-markers.json', 'knowledge/atlas_kb.py',
    'knowledge/benchmark/atlas_kb_battery.py', 'livedata/atlas_live.py',
    'livedata/atlas_live_server.py', 'livedata/config.json',
    'livedata/tests/test_subnet_param_watch.py', 'telegram/atlas_telegram.py',
    'telegram/atlas_briefing.py', 'telegram/config.json', 'repotrack/atlas_repo.py',
    'fleet/atlas_fleet_mining.py', 'fleet/atlas_fleet_metrics.py', 'subnt/atlas_subnt.py',
    'openspec/specs/live-data/spec.md', 'openspec/specs/knowledge-base/spec.md',
    'openspec/specs/telegram-integration/spec.md', 'openspec/specs/mining-triage/spec.md',
    'inventory/README.md', 'hardening/README.md', 'hermes/README.md',
    '.claude/commands/opsx/apply.md', 'triage/miner_economics.py',
]


def add_files(root, paths, text='public\n'):
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    subprocess.run(['git', '-C', str(root), 'add', '-f', *paths], check=True)


def test_recorded_denial_recovers_atomically_with_full_inventory(repo, monkeypatch):
    add_files(repo, RECORDED_PATHS)
    reads = []
    original = w.read_text
    def read(*args, **kwargs):
        reads.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(w, 'read_text', read)
    calls = []
    def model(payload):
        calls.append(payload)
        if len(calls) == 1:
            assert '.claude/commands/opsx/apply.md' in payload['inventory']
            assert '.claude' in payload['inventory_groups']
            assert '.claude/commands/opsx/apply.md' not in payload['requestable_inventory']
            return {'action': 'request_files', 'paths': RECORDED_PATHS}
        if len(calls) == 2:
            assert reads == []  # preflight denied batch before reading any member
            assert payload['files'] == payload['inspected_files'] == {}
            assert payload['request_feedback']['status'] == 'rejected'
            assert payload['request_feedback']['errors'] == [
                {'path': '.claude/commands/opsx/apply.md', 'reason': 'hidden or escaping path'}]
            return {'action': 'request_files', 'paths': ['README.md']}
        assert payload['request_feedback'] is None
        assert payload['files']['README.md']['content'] == 'old\n'
        return answer(payload)
    result = w.propose(repo, packet(), model, max_rounds=3)
    assert len(calls) == 3
    assert result['before_files']['README.md']['content'] == 'old\n'


@pytest.mark.parametrize('role', ['coder', 'reviewer'])
def test_serialized_aggregate_budget_recovers_without_partial_delivery(repo, role):
    # Raw UTF-8 fits the limit, JSON escaping does not. 31-file replay shape.
    paths = [f'large/file{i}.txt' for i in range(31)]
    add_files(repo, paths, '\u2603' * 5000)
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    calls = []
    def model(payload):
        calls.append(payload)
        assert len(json.dumps(payload, allow_nan=False).encode()) <= 800000
        limits = payload['request_limits']
        assert limits['max_context_bytes'] == 800000
        assert limits['serialized_payload_bytes'] == len(json.dumps(payload, allow_nan=False).encode())
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': paths}
        if len(calls) == 2:
            assert payload['files'] == {}
            assert not payload.get('inspected_files')
            assert payload['request_feedback']['errors'][0]['reason'].startswith('context budget exceeded')
            return {'action': 'request_files', 'paths': [paths[0]]}
        assert payload['files'][paths[0]]['content'] == '\u2603' * 5000
        result = answer(payload)
        result['edits'] = []
        return {**result, 'action': 'review' if role == 'reviewer' else 'propose',
            'approved': True, 'manifest_sha256': payload.get('manifest_sha256'),
            'tree': payload.get('tree'), 'checks': payload.get('checks')}
    if role == 'coder':
        w.propose(repo, packet(), model, max_rounds=3)
    else:
        w.review_proposal(repo, packet(), proposal, model, tree='tree', checks={'tests': 'passed'},
            worker_id='coder', reviewer_id='reviewer', max_rounds=3)
    assert len(calls) == 3


def test_broker_wire_budget_not_compact_hash_encoding():
    payload = {'paths': ['a'] * 170000}
    assert len(w.canonical(payload)) < 800000
    assert len(json.dumps(payload, allow_nan=False).encode()) > 800000
    calls = []
    with pytest.raises(w.WorkerBlocked, match='context budget exceeded'):
        w.model_call(lambda p: calls.append(p) or {}, payload, 800000)
    assert calls == []


def invoke(role, repo, model, max_rounds=3):
    if role == 'coder':
        return w.propose(repo, packet(), model, max_rounds=max_rounds)
    proposal = w.propose(repo, packet(), answer, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    return w.review_proposal(repo, packet(), proposal, model, tree='tree', checks={'tests': 'passed'},
        worker_id='coder', reviewer_id='reviewer', max_rounds=max_rounds)


@pytest.mark.parametrize('role', ['coder', 'reviewer'])
@pytest.mark.parametrize('bad', [[], [None], ['README.md', 'README.md'], ['missing-artifact.json'],
    ['.claude/commands/opsx/apply.md'], ['secrets/token'], ['link'], ['untracked.txt'],
    ['oversize.txt'], ['binary.txt'], ['consumer.py']])
def test_repeated_invalid_requests_exhaust_existing_rounds(repo, role, bad):
    add_files(repo, ['.claude/commands/opsx/apply.md', 'secrets/token'])
    add_files(repo, ['oversize.txt'], 'x' * 200001)
    add_files(repo, ['binary.txt'], '\x00')
    (repo / 'consumer.py').write_text('sk-' + 'A' * 30)
    (repo / 'untracked.txt').write_text('PRIVATE-CONTENTS')
    (repo / 'link').symlink_to(repo / 'untracked.txt')
    subprocess.run(['git', '-C', str(repo), 'add', 'link'], check=True)
    calls = []
    def model(payload):
        calls.append(payload)
        assert 'PRIVATE-CONTENTS' not in str(payload)
        assert 'sk-' + 'A' * 30 not in str(payload)
        if len(calls) > 1:
            assert payload['request_feedback']['status'] == 'rejected'
            assert payload['files'] == {}
            assert not payload.get('inspected_files')
        return {'action': 'request_files', 'paths': bad}
    with pytest.raises(w.WorkerBlocked, match='iteration budget exhausted'):
        invoke(role, repo, model)
    assert len(calls) == 3


@pytest.mark.parametrize('path', ['consumer.py', '.claude/commands/opsx/apply.md'])
def test_recovery_cannot_authorize_unread_or_denied_edits(repo, path):
    add_files(repo, ['.claude/commands/opsx/apply.md'], 'VALUE = 1\n')
    calls = []
    def model(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['consumer.py', '.claude/commands/opsx/apply.md']}
        if len(calls) == 2:
            return {'action': 'request_files', 'paths': ['README.md']}
        assert set(payload['inspected_files']) == {'README.md'}
        result = answer(payload)
        result['edits'] = [{'path': path, 'before_sha256': w.sha256(b'VALUE = 1\n'), 'content': 'bad'}]
        return result
    with pytest.raises(w.WorkerBlocked, match='unread or stale|hidden or escaping'):
        invoke('coder', repo, model)
    assert (repo / path).read_text() == 'VALUE = 1\n'


@pytest.mark.parametrize('version', ['original', 'current'])
def test_reviewer_denial_recovers_preserving_independent_raw_audits(repo, version):
    add_files(repo, ['.claude/commands/opsx/apply.md'])
    evidence = packet()
    text = 'raw upstream source\n' * 4000
    evidence['chunks'] = [{'id': f'chunk-{i}', 'path': 'runtime/lib.rs',
        'text': text, 'sha256': w.sha256(text.encode())} for i in (1, 2)]
    evidence['chunk_ids'] = ['chunk-1', 'chunk-2']
    calls, audits = [], []
    def model(payload):
        assert 'coder-only findings' not in str(payload)
        if payload.get('phase') == 'source-audit':
            audits.extend(payload['chunks'])
            return {'action': 'source_audit', 'covered_chunks': [
                {'id': c['id'], 'sha256': c['sha256']} for c in payload['chunks']],
                'summary': 'reviewer independent findings'}
        calls.append(payload)
        assert '.claude' in payload['inventory_groups']
        if len(calls) == 1:
            return {'action': 'request_files', 'paths': ['README.md', '.claude/commands/opsx/apply.md'],
                'version': version}
        if len(calls) == 2:
            assert payload['files'] == {}
            assert payload['file_version'] == 'current'
            assert payload['request_feedback']['status'] == 'rejected'
            return {'action': 'request_files', 'paths': ['README.md'], 'version': version}
        assert payload['file_version'] == version
        assert payload['files']['README.md']['content'] == ('old\n' if version == 'original' else 'new\n')
        return {**answer(payload), 'covered_chunks': evidence['chunk_ids'], 'action': 'review',
            'approved': True, 'manifest_sha256': payload['manifest_sha256'],
            'tree': payload['tree'], 'checks': payload['checks']}
    def coder(payload):
        if payload.get('phase') == 'source-audit':
            return {'action': 'source_audit', 'covered_chunks': [
                {'id': c['id'], 'sha256': c['sha256']} for c in payload['chunks']],
                'summary': 'coder-only findings'}
        return {**answer(payload), 'covered_chunks': evidence['chunk_ids']}
    proposal = w.propose(repo, evidence, coder, selected_paths=['README.md'])
    w.apply_proposal(repo, proposal)
    result = w.review_proposal(repo, evidence, proposal, model, tree='tree', checks={'tests': 'passed'},
        worker_id='coder', reviewer_id='reviewer', max_rounds=3)
    assert audits == evidence['chunks']
    assert result['source_audit_coverage_count'] == proposal['source_audit_coverage_count'] == 2
    assert all(r['role'] == 'independent-reviewer' for r in result['source_audit_receipts'])
    assert result['source_audit_receipts'] != proposal['source_audit_receipts']
