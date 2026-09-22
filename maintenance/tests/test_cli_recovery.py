import hashlib
import json
from pathlib import Path

import pytest
from maintenance import atlas_maintenance as cli
from maintenance.store import Store
from maintenance.controller import advance_job, STAGES
from maintenance.worker import canonical


def setup(tmp_path, **options):
    state = tmp_path/'state'
    state.mkdir()
    config = {'state_dir': str(state), 'genesis': 'g', **options}
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config))
    with Store(state/'maintenance.db') as store:
        store.initialize('g', 0, '0x0', {'metadata': 'huge', 'number': 0})
        for n in (1, 2):
            store.accept_block('g', n, f'0x{n}', f'0x{n-1}', {
                'activation_number': n, 'activation_hash': f'0x{n}',
                'code_hash': f'0xc{n}', 'current': {'runtime': {'specVersion': n}}})
    return config, path


def run(path, capsys, command='process'):
    code = cli.main(['--config', str(path), command])
    return code, json.loads(capsys.readouterr().out)


def fake_pipeline(monkeypatch, calls, fail='evidence-ready', evidence_hash=None):
    import maintenance.pipeline as pipeline
    class Fake:
        def __init__(self, config, store, job):
            self.job = job
        def steps(self):
            def step(stage):
                def call(job):
                    calls.append((job['number'], stage))
                    if stage == fail:
                        raise ValueError('bounded fake failure')
                    return {'commit': 'commit', 'stage': stage, 'evidence_sha256': evidence_hash}
                return call
            return {stage: step(stage) for stage in STAGES[1:]}
    monkeypatch.setattr(pipeline, 'Pipeline', Fake)


def test_process_selects_latest_pending(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path)
    calls = []
    fake_pipeline(monkeypatch, calls)
    assert run(path, capsys)[0] == 2
    assert calls == [(2, 'evidence-ready')]
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[0]['state'] == 'detected'


def test_process_retries_checkpoint_with_bounded_config(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path, max_job_attempts=2, retry_delay_seconds=10)
    import maintenance.controller as controller
    clock = [100]
    monkeypatch.setattr(controller.time, 'time', lambda: clock[0])
    calls = []
    fake_pipeline(monkeypatch, calls, fail='editing')
    assert run(path, capsys)[1]['state'] == 'blocked'
    assert run(path, capsys)[1]['retry_status'] == 'retry-delayed'
    clock[0] = 111
    assert run(path, capsys)[1]['state'] == 'blocked'
    clock[0] = 122
    assert run(path, capsys)[1]['retry_status'] == 'retry-exhausted'
    assert calls == [(2, 'evidence-ready'), (2, 'editing'), (2, 'editing')]
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[-1]['attempts'] == 2


def checkpoint(config, number, stage, blocked=False, evidence_hash=None):
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        job = store.jobs('g')[number-1]
        key = (job['genesis'], job['activation_hash'], job['code_hash'])
        store.claim(key, 'setup', now=1, ttl=100)
        previous = 'detected'
        receipt = None
        for target in STAGES[1:STAGES.index(stage)+1]:
            receipt = {'commit': 'commit', 'stage': target, 'evidence_sha256': evidence_hash}
            store.transition(key, 'setup', previous, target, receipt, now=2)
            previous = target
        if blocked:
            store.transition(key, 'setup', stage, 'blocked', {
                'failed_gate_after': stage, 'last_receipt': receipt, 'reason': 'interrupted'}, now=3)
        store.release(key, 'setup')


@pytest.mark.parametrize('blocked', [False, True])
def test_old_publication_blocks_new_target_until_recovered(tmp_path, monkeypatch, capsys, blocked):
    config, path = setup(tmp_path)
    checkpoint(config, 1, 'published', blocked)
    calls = []
    fake_pipeline(monkeypatch, calls, fail=None)
    code, result = run(path, capsys)
    assert code == 2
    assert result['retry_status'] == 'publication-recovery-required'
    assert calls == []
    assert run(path, capsys, 'recover')[1]['state'] == 'activated'
    assert calls == [(1, 'activated')]
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[1]['state'] == 'detected'


@pytest.mark.parametrize('command', ['retry', 'recover'])
def test_manual_commands_do_not_restart_detected(tmp_path, monkeypatch, capsys, command):
    config, path = setup(tmp_path)
    calls = []
    fake_pipeline(monkeypatch, calls)
    code, result = run(path, capsys, command)
    assert code == 2
    assert result['retry_status'] == 'inappropriate-stage'
    assert calls == []


def audit_files(config, monkeypatch):
    from maintenance import pipeline
    root = Path(config['state_dir'])/'jobs'/'2'
    root.mkdir(parents=True)
    packets, receipts = [], []
    for n in (1, 2):
        model = {'complete': True, 'status': 'ready', 'chunks': [
            {'id': 'source:0', 'path': 'source', 'text': str(n)}],
            'chunk_ids': ['source:0'], 'upstream_paths': ['source'],
            'deployments': {'old': {'code_hash': f'0xc{n-1}'}, 'new': {
                'code_hash': f'0xc{n}', 'block_hash': f'0x{n}', 'genesis_hash': 'g'}},
            'atlas_inventory': {}, 'source_commits': {'old': str(n-1), 'new': str(n)},
            'metadata': {'complete': True}}
        directory = root/f'evidence-{n}'
        directory.mkdir()
        (directory/'packet.json').write_text(json.dumps(model))
        packets.append(model)
        receipts.append({'key': ['g', f'0x{n}', f'0xc{n}'], 'complete': True,
                         'packet_dir': str(directory),
                         'evidence_sha256': hashlib.sha256(canonical(model)).hexdigest()})
    # Bounded source materialization fake; orchestration hashes actual files.
    monkeypatch.setattr(pipeline, 'model_packet', lambda packet, directory, source: packet)
    model = pipeline.combine_packets(packets)
    digest = hashlib.sha256(canonical(model)).hexdigest()
    (root/'model-packet.json').write_text(json.dumps(model))
    (root/'evidence-receipt.json').write_text(json.dumps({
        'evidence_receipts': receipts, 'model_packet_sha256': digest}))
    config['source_repo'] = str(root)
    return root, digest


def test_activated_target_reconciles_history_after_crash_idempotently(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path)
    root, digest = audit_files(config, monkeypatch)
    path.write_text(json.dumps(config))
    checkpoint(config, 2, 'activated', evidence_hash=digest)
    calls = []
    fake_pipeline(monkeypatch, calls)
    code, result = run(path, capsys)
    assert code == 0
    assert result['historical_audited'] == 1
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[0]['state'] == 'historical-audited'
        assert store.progress('g')['activated']['activation_hash'] == '0x2'
        count = len(store.history(('g', '0x1', '0xc1')))
    assert run(path, capsys)[1]['state'] == 'idle'
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert len(store.history(('g', '0x1', '0xc1'))) == count
    assert calls == []


@pytest.mark.parametrize('damage', ['model', 'individual', 'missing', 'validation', 'publication', 'identity'])
def test_reconciliation_refuses_unverified_evidence(tmp_path, monkeypatch, capsys, damage):
    config, path = setup(tmp_path)
    root, digest = audit_files(config, monkeypatch)
    path.write_text(json.dumps(config))
    checkpoint(config, 2, 'activated', evidence_hash='wrong' if damage == 'validation' else digest)
    if damage == 'model':
        (root/'model-packet.json').write_text('{}')
    elif damage == 'individual':
        (root/'evidence-1'/'packet.json').write_text('{}')
    elif damage == 'missing':
        (root/'evidence-receipt.json').unlink()
    elif damage == 'identity':
        receipt_path = root/'evidence-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        items = receipt['evidence_receipts']
        items[0]['key'], items[1]['key'] = items[1]['key'], items[0]['key']
        receipt_path.write_text(json.dumps(receipt))
    elif damage == 'publication':
        checkpoint(config, 1, 'published')
    calls = []
    fake_pipeline(monkeypatch, calls)
    code, result = run(path, capsys)
    assert code == 2
    assert result['retry_status'] in ('historical-reconciliation-required', 'publication-recovery-required')
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[0]['state'] != 'historical-audited'
        assert store.jobs('g')[1]['state'] == 'activated'
    assert calls == []


def test_activation_reconciles_only_after_success(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path, retry_delay_seconds=0)
    root, digest = audit_files(config, monkeypatch)
    path.write_text(json.dumps(config))
    calls = []
    fake_pipeline(monkeypatch, calls, fail='activated', evidence_hash=digest)
    assert run(path, capsys)[1]['state'] == 'blocked'
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        assert store.jobs('g')[0]['state'] == 'detected'
    fake_pipeline(monkeypatch, calls, fail=None, evidence_hash=digest)
    assert run(path, capsys, 'retry')[1]['historical_audited'] == 1
    assert calls == [(2, stage) for stage in STAGES[1:]] + [(2, 'activated')]


def test_status_is_compact_and_exposes_retry_progress(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path, max_job_attempts=1)
    calls = []
    fake_pipeline(monkeypatch, calls)
    run(path, capsys)
    code, result = run(path, capsys, 'status')
    assert code == 0
    assert 'metadata' not in result['baseline']
    assert 'progress' in result
    latest = result['jobs'][-1]
    assert latest['attempts'] == 1
    assert latest['retry_status'] == 'retry-exhausted'
    assert latest['reason'] == 'bounded fake failure'
    assert latest['next_retry_at'] is not None
    assert latest['last_attempt_at'] is not None
    assert 'notification_error' in latest


def test_recover_reclaims_stable_owner_only_under_worker_lock(tmp_path, monkeypatch, capsys):
    import fcntl
    import time
    config, path = setup(tmp_path)
    state = Path(config['state_dir'])
    checkpoint(config, 2, 'editing')
    with Store(state/'maintenance.db') as store:
        job = store.jobs('g')[-1]
        store.begin_attempt(('g', '0x2', '0xc2'), 'worker:' + str(state.resolve()),
                            now=time.time(), ttl=21600, max_attempts=3)
    calls = []
    fake_pipeline(monkeypatch, calls, fail='validated')
    with (state/'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(path, capsys, 'recover')[1]['state'] == 'busy'
        assert calls == []
    assert run(path, capsys, 'recover')[1]['state'] == 'blocked'
    assert calls == [(2, 'validated')]
    with Store(state/'maintenance.db') as store:
        assert store.jobs('g')[-1]['attempts'] == 2


def test_exhausted_interrupted_checkpoint_returns_failure_exit(tmp_path, monkeypatch, capsys):
    import time
    config, path = setup(tmp_path, max_job_attempts=1)
    checkpoint(config, 2, 'editing')
    with Store(Path(config['state_dir'])/'maintenance.db') as store:
        store.begin_attempt(('g', '0x2', '0xc2'), 'worker:' + str(Path(config['state_dir']).resolve()),
                            now=time.time(), ttl=21600, max_attempts=1)
    calls = []
    fake_pipeline(monkeypatch, calls)
    for command in ('process', 'recover'):
        code, result = run(path, capsys, command)
        assert code == 2
        assert result['retry_status'] == 'retry-exhausted'
    assert calls == []


def test_unfinished_publication_journal_is_not_skipped(tmp_path, monkeypatch, capsys):
    config, path = setup(tmp_path)
    root = Path(config['state_dir'])/'jobs'/'1'
    root.mkdir(parents=True)
    (root/'publication-intent.json').write_text('{}')
    calls = []
    fake_pipeline(monkeypatch, calls)
    assert run(path, capsys)[1]['retry_status'] == 'publication-recovery-required'
    assert calls == []
