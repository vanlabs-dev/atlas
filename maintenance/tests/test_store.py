import sqlite3
import pytest


def test_interrupted_cursor_transaction_rolls_back_inserted_job(tmp_path):
    path = tmp_path / 'db'
    with store.Store(path) as db:
        db.initialize('g', 1, 'h1', {})
        db.db.execute("CREATE TRIGGER fail_cursor BEFORE UPDATE ON chains BEGIN SELECT RAISE(ABORT, 'injected crash'); END")
        with pytest.raises(sqlite3.IntegrityError):
            db.accept_block('g', 2, 'h2', 'h1', {'activation_number': 2, 'activation_hash': 'h2', 'code_hash': 'c'})
    with store.Store(path) as db:
        assert db.cursor('g') == {'number': 1, 'hash': 'h1'}
        assert db.jobs('g') == []
        db.db.execute('DROP TRIGGER fail_cursor')
        db.accept_block('g', 2, 'h2', 'h1', {'activation_number': 2, 'activation_hash': 'h2', 'code_hash': 'c'})
        assert len(db.jobs('g')) == 1



def test_atomic_cursor_jobs_and_duplicate_recovery(tmp_path):
    with store.Store(tmp_path / 'db') as db:
        db.initialize('g', 1, 'h1', {})
        event = {'activation_number': 2, 'activation_hash': 'h2', 'code_hash': 'c2'}
        db.accept_block('g', 2, 'h2', 'h1', event)
        db.accept_block('g', 2, 'h2', 'h1', event)
        assert len(db.jobs('g')) == 1
        assert db.jobs('g')[0]['state'] == 'detected'
        with pytest.raises(ValueError):
            db.accept_block('g', 4, 'h4', 'h2', None)
        with pytest.raises(ValueError):
            db.accept_block('g', 3, 'h3', 'h2', {'activation_number': 3})
        assert db.cursor('g')['number'] == 2
        assert len(db.jobs('g')) == 1

from maintenance import store


def test_leases_recover_and_receipts_remain_separate(tmp_path):
    with store.Store(tmp_path / 'db') as db:
        db.initialize('g', 1, 'h1', {})
        db.accept_block('g', 2, 'h2', 'h1', {'activation_number': 2, 'activation_hash': 'h2', 'code_hash': 'c'})
        key = ('g', 'h2', 'c')
        assert db.claim(key, 'worker1', now=10, ttl=20)
        assert not db.claim(key, 'worker2', now=11, ttl=20)
        assert db.claim(key, 'worker2', now=31, ttl=20)
        with pytest.raises(ValueError): db.transition(key, 'worker1', 'detected', 'evidence-ready', {}, now=32)
        db.transition(key, 'worker2', 'detected', 'evidence-ready', {'packet': 'sha'}, now=32)
        db.transition(key, 'worker2', 'evidence-ready', 'editing', {}, now=32)
        db.transition(key, 'worker2', 'editing', 'validated', {'audit': 'ok'}, now=32)
        db.transition(key, 'worker2', 'validated', 'published', {'commit': 'abc'}, now=32)
        assert db.progress('g')['published']['commit'] == 'abc'
        assert 'activated' not in db.progress('g')
        db.transition(key, 'worker2', 'published', 'activated', {'commit': 'abc'}, now=32)
        assert db.progress('g')['activated']['commit'] == 'abc'
        assert len(db.history(key)) == 5


def test_terminal_states_cannot_be_downgraded(tmp_path):
    with store.Store(tmp_path/'db') as db:
        db.initialize('g', 0, 'h0', {})
        db.accept_block('g', 1, 'h1', 'h0', {'activation_number':1, 'activation_hash':'h1', 'code_hash':'c'})
        key = ('g','h1','c')
        db.claim(key, 'worker', now=10, ttl=20)
        previous = 'detected'
        for state in ('evidence-ready','editing','validated','published','activated'):
            db.transition(key, 'worker', previous, state, {'commit':'abc'}, now=11)
            previous = state
        with pytest.raises(ValueError, match='invalid state'):
            db.transition(key, 'worker', 'activated', 'blocked', {}, now=12)
        assert db.get_job(key)['state'] == 'activated'


def test_failure_checkpoint_is_enforced_and_blanket_restart_forbidden(tmp_path):
    with store.Store(tmp_path/'db') as db:
        db.initialize('g', 0, 'h0', {})
        db.accept_block('g', 1, 'h1', 'h0', {'activation_number':1, 'activation_hash':'h1', 'code_hash':'c'})
        key = ('g','h1','c')
        db.claim(key, 'worker', now=10, ttl=20)
        db.transition(key, 'worker', 'detected', 'evidence-ready', {'packet':'sha'}, now=11)
        with pytest.raises(ValueError, match='checkpoint'):
            db.transition(key, 'worker', 'evidence-ready', 'failed', {}, now=12)
        with pytest.raises(ValueError, match='checkpoint'):
            db.transition(key, 'worker', 'evidence-ready', 'failed', {'failed_gate_after':'evidence-ready', 'last_receipt':{}}, now=12)
        db.transition(key, 'worker', 'evidence-ready', 'failed', {'failed_gate_after':'evidence-ready', 'last_receipt':{'packet':'sha'}}, now=12)
        with pytest.raises(ValueError, match='invalid state'):
            db.transition(key, 'worker', 'failed', 'detected', {}, now=13)
        resumed, refusal = db.begin_attempt(key, 'worker', now=13, ttl=20, max_attempts=3, resume=True)
        assert refusal is None
        assert resumed['state'] == 'evidence-ready'
        assert resumed['receipt'] == {'packet':'sha'}


def test_historical_audit_requires_complete_bound_evidence_and_latest_target(tmp_path):
    with store.Store(tmp_path/'db') as db:
        db.initialize('g', 0, 'h0', {})
        keys = []
        for n in range(1, 4):
            db.accept_block('g', n, f'h{n}', f'h{n-1}', {'activation_number':n, 'activation_hash':f'h{n}', 'code_hash':f'c{n}'})
            keys.append(('g', f'h{n}', f'c{n}'))
        target = keys[-1]
        db.claim(target, 'worker', now=10, ttl=20)
        previous = 'detected'
        for state in ('evidence-ready','editing','validated','published','activated'):
            db.transition(target, 'worker', previous, state, {'commit':'abc'}, now=11)
            previous = state
        receipt = {'complete':True, 'audit_target':list(target), 'commit':'abc',
                   'evidence_receipts':[{'key':list(k), 'complete':True, 'evidence_sha256':'a'*64} for k in keys]}
        with pytest.raises(ValueError, match='complete'):
            db.mark_historical_audited(keys[:-1], {**receipt, 'complete':False}, now=12)
        with pytest.raises(ValueError, match='evidence'):
            db.mark_historical_audited(keys[:-1], {**receipt, 'evidence_receipts':receipt['evidence_receipts'][1:]}, now=12)
        with pytest.raises(ValueError, match='target'):
            db.mark_historical_audited(keys[:-1], {**receipt, 'audit_target':list(keys[0])}, now=12)
        assert all(db.get_job(k)['state'] == 'detected' for k in keys[:-1])
        db.claim(keys[1], 'other', now=10, ttl=10)
        with pytest.raises(ValueError, match='lease'):
            db.mark_historical_audited(keys[:-1], receipt, now=12)
        assert db.get_job(keys[0])['state'] == 'detected'  # atomic batch
        db.mark_historical_audited(keys[:-1], receipt, now=21)
        progress = db.progress('g')
        db.mark_historical_audited(keys[:-1], receipt, now=22)  # idempotent replay
        assert [j['state'] for j in db.jobs('g')] == ['historical-audited','historical-audited','activated']
        for key in keys[:-1]:
            assert len(db.history(key)) == 1
            assert db.history(key)[0]['state'] == 'historical-audited'
            assert db.get_job(key)['receipt'] == receipt
        assert db.progress('g') == progress
        assert progress['activated']['activation_hash'] == 'h3'


def test_baseline_is_explicit_and_durable(tmp_path):
    path = tmp_path / 'ledger.db'
    with store.Store(path) as db:
        assert db.cursor('g') is None
        db.initialize('g', 12, 'h12', {'code_hash': 'c'})
    with store.Store(path) as db:
        assert db.cursor('g') == {'number': 12, 'hash': 'h12'}
        assert db.baseline('g')['code_hash'] == 'c'
        with pytest.raises(ValueError):
            db.initialize('g', 13, 'h13', {})
