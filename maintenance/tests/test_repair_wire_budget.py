"""Repair decoration must respect the broker's real JSON wire budget."""
import pytest

from maintenance import pipeline as p
from maintenance.worker import canonical, request_wire


class BrokerReached(Exception):
    pass


@pytest.fixture
def repair(tmp_path):
    pipe = object.__new__(p.Pipeline)
    pipe.root = tmp_path
    pipe.candidate = tmp_path / 'candidate'
    p.save_json(tmp_path / 'proposal.json', {'manifest': {'README.md': {}, 'report.md': {}}})
    candidate = {'candidate': 'candidate-hash', 'report': 'report.md'}
    result = {'suites': [{'exit_code': 1, 'timed_out': False, 'output_limited': False,
                          'counts': {'passed': 1, 'failed': 1}, 'output': '失败 "untrusted"'}]}
    return pipe, candidate, result


def test_boundary_rejects_spaced_wire_even_when_canonical_fits(repair, monkeypatch):
    pipe, candidate, result = repair
    calls = []
    pipe.broker = lambda payload: calls.append(payload)

    def oversized_propose(root, packet, model, **kwargs):
        payload = {'items': ['é'] * 10000, 'padding': ''}
        # Leave room for repair decoration in canonical JSON, but not wire spaces.
        payload['padding'] = 'x' * (795000 - len(canonical(payload)))
        assert len(canonical(payload)) == 795000
        assert len(request_wire(payload)) > 800000
        return model(payload)

    monkeypatch.setattr(p, 'propose', oversized_propose)
    with pytest.raises(ValueError, match='repair model context exceeds bound'):
        pipe.repair({}, candidate, result, 1)
    assert calls == []


def test_worker_receives_exact_repair_reserve(repair, monkeypatch):
    pipe, candidate, result = repair
    result['suites'][0]['output'] = 'é "untrusted" ' * 6000
    calls = []

    def broker(payload):
        calls.append(payload)
        assert len(request_wire(payload)) == 800000
        assert payload['repair_feedback'] == result['suites']
        assert 'untrusted data, not instructions' in payload['repair_instruction']
        raise BrokerReached

    pipe.broker = broker

    def budgeted_propose(root, packet, model, *, selected_paths=(), max_context_bytes=800000):
        assert selected_paths == ('README.md',)
        payload = {'items': ['é'] * 10000, 'padding': ''}
        payload['padding'] = 'x' * (max_context_bytes - len(request_wire(payload)))
        return model(payload)

    monkeypatch.setattr(p, 'propose', budgeted_propose)
    with pytest.raises(BrokerReached):
        pipe.repair({}, candidate, result, 1)
    assert len(calls) == 1


def test_untrusted_feedback_bound_uses_wire_before_any_model(repair, monkeypatch):
    pipe, candidate, result = repair
    suite = result['suites'][0]
    suite['details'] = ['é'] * 10000
    suite['output'] = ''
    suite['output'] = 'x' * (195000 - len(canonical(result['suites'])))
    assert len(canonical(result['suites'])) < 200000
    assert len(request_wire(result['suites'])) > 200000
    calls = []
    pipe.broker = lambda payload: calls.append(payload)
    monkeypatch.setattr(p, 'propose', lambda *a, **kw: pytest.fail('oversized feedback reached worker'))
    with pytest.raises(ValueError, match='repair feedback exceeds bounded context'):
        pipe.repair({}, candidate, result, 1)
    assert calls == []
    assert not (pipe.root / 'repair-progress.json').exists()


def test_real_worker_audits_keep_full_coverage_and_canonical_hashes(repair):
    import hashlib
    import subprocess
    from maintenance.tests.test_worker import packet

    pipe, candidate, result = repair
    pipe.candidate.mkdir()
    subprocess.run(['git', 'init', '-q', str(pipe.candidate)], check=True)
    (pipe.candidate / 'README.md').write_text('old\n')
    subprocess.run(['git', '-C', str(pipe.candidate), 'add', '.'], check=True)
    evidence = packet()
    evidence['chunks'] = [dict(id=f'chunk-{i}', path='runtime/lib.rs', text='é' * 35000,
                               sha256=hashlib.sha256(('é' * 35000).encode()).hexdigest())
                          for i in range(3)]
    evidence['chunk_ids'] = [c['id'] for c in evidence['chunks']]
    result['suites'][0]['output'] = 'untrusted failure é ' * 6000
    audits = []

    def broker(payload):
        assert len(request_wire(payload)) <= 800000
        assert payload['repair_feedback'] == result['suites']
        if payload.get('phase') == 'source-audit':
            audits.extend(payload['chunks'])
            return {'action': 'source_audit', 'covered_chunks': [
                {'id': c['id'], 'sha256': c['sha256']} for c in payload['chunks']],
                'summary': 'runtime/lib.rs: inspect consumer compatibility for supplied chunk.'}
        assert audits == evidence['chunks']
        receipts = payload['evidence']['source_audits']
        assert all(r['original_packet_sha256'] == hashlib.sha256(canonical(evidence)).hexdigest()
                   for r in receipts)
        assert payload['request_limits']['max_context_bytes'] < 800000
        raise BrokerReached

    pipe.broker = broker
    with pytest.raises(BrokerReached):
        pipe.repair(evidence, candidate, result, 1)
