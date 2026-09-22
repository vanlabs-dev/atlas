import time
import pytest
from maintenance.store import Store


def job(store):
    store.initialize('g',0,'h0',{})
    store.accept_block('g',1,'h1','h0',{'activation_number':1,'activation_hash':'h1','code_hash':'c'})
    return store.jobs('g')[0]


def test_notification_failure_never_downgrades_activation(tmp_path):
    from maintenance.controller import advance_job, STAGES
    with Store(tmp_path/'state.db') as store:
        current = job(store)
        def notify(*args): raise OSError('outbox unavailable')
        result = advance_job(store, current, dict.fromkeys(STAGES[1:], lambda j: {'commit': 'abc'}), notify=notify)
        assert result['state'] == 'activated'
        saved = store.jobs('g')[0]
        assert saved['state'] == 'activated'
        assert saved['notification_error']['exception'] == 'OSError'
        assert [h['state'] for h in store.history(('g', 'h1', 'c'))] == list(STAGES[1:])


def test_resume_retries_only_failed_gate_with_durable_bounds(tmp_path, monkeypatch):
    from maintenance import controller
    clock = [100.0]
    monkeypatch.setattr(controller.time, 'time', lambda: clock[0])
    path = tmp_path/'state.db'
    calls = []
    def accepted(j):
        calls.append(j['state'])
        return {'commit': 'abc', 'packet': 'preserved'}
    def activation(j):
        calls.append('activation')
        assert j['receipt']['packet'] == 'preserved'
        raise RuntimeError('busy')
    steps = dict.fromkeys(controller.STAGES[1:-1], accepted) | {'activated': activation}
    with Store(path) as store:
        original = job(store)
        controller.advance_job(store, original, steps, max_attempts=2, retry_delay=10)
    with Store(path) as store:
        saved = store.jobs('g')[0]
        assert saved['attempts'] == 1
        assert saved['receipt']['failed_gate_after'] == 'published'
        assert saved['next_retry_at'] == 110
        before = list(calls)
        assert controller.resume_job(store, original, steps, max_attempts=2, retry_delay=10)['retry_status'] == 'retry-delayed'
        assert calls == before
        clock[0] = 110
        result = controller.resume_job(store, original, steps, max_attempts=2, retry_delay=10)
        assert result['state'] == 'blocked'
        assert calls == before + ['activation']
        assert store.jobs('g')[0]['attempts'] == 2
        clock[0] = 200
        assert controller.resume_job(store, original, steps, max_attempts=2, retry_delay=10)['retry_status'] == 'retry-exhausted'
        assert calls == before + ['activation']
        assert [h['state'] for h in store.history(('g','h1','c'))].count('published') == 1


@pytest.mark.parametrize('checkpoint', ['editing', 'validated', 'published'])
def test_interrupted_stage_respects_lease_and_recovers_receipts(tmp_path, monkeypatch, checkpoint):
    from maintenance import controller
    clock = [100.0]
    monkeypatch.setattr(controller.time, 'time', lambda: clock[0])
    path = tmp_path/'state.db'
    key = ('g','h1','c')
    with Store(path) as store:
        current = job(store)
        store.claim(key, 'crashed', now=90, ttl=20)
        previous = 'detected'
        for state in controller.STAGES[1:controller.STAGES.index(checkpoint)+1]:
            store.transition(key, 'crashed', previous, state, {'commit': 'abc', 'checkpoint': state}, now=91)
            previous = state
    with Store(path) as store:
        assert controller.advance_job(store, current, {})['state'] == 'leased'
        assert store.get_job(key)['attempts'] == 0
        clock[0] = 111
        calls = []
        def accepted(j):
            calls.append(j['state'])
            assert j['receipt']['checkpoint'] == checkpoint
            return j['receipt']
        result = controller.advance_job(store, current, dict.fromkeys(controller.STAGES[1:], accepted))
        assert result['state'] == 'activated'
        assert calls == list(controller.STAGES[controller.STAGES.index(checkpoint):-1])
        assert controller.advance_job(store, current, {})['state'] == 'activated'
        assert [h['state'] for h in store.history(key)] == list(controller.STAGES[1:])


def test_failed_gate_commit_rejection_preserves_previous_receipt(tmp_path):
    from maintenance.controller import advance_job
    with Store(tmp_path/'state.db') as store:
        current = job(store)
        def accepted(j): return {'packet': 'durable'}
        result = advance_job(store, current, dict.fromkeys(('evidence-ready','editing','validated'), accepted) | {'published': lambda j: {}})
        assert result['receipt']['last_receipt'] == {'packet': 'durable'}
        assert result['receipt']['failed_gate_after'] == 'validated'


@pytest.mark.parametrize('failed_gate', ['evidence-ready', 'editing', 'validated', 'published', 'activated'])
def test_retry_success_runs_only_remaining_gates(tmp_path, failed_gate):
    from maintenance.controller import advance_job, resume_job, STAGES
    with Store(tmp_path/'state.db') as store:
        current = job(store)
        calls = []
        fail_once = [True]
        def gate(name):
            def run(j):
                calls.append(name)
                if name == failed_gate and fail_once[0]:
                    fail_once[0] = False
                    raise RuntimeError('transient')
                return {'commit':'abc', 'gate':name}
            return run
        steps = {name:gate(name) for name in STAGES[1:]}
        assert advance_job(store, current, steps)['state'] == 'blocked'
        assert resume_job(store, current, steps)['state'] == 'activated'
        assert calls.count(failed_gate) == 2
        assert all(calls.count(name) == 1 for name in STAGES[1:] if name != failed_gate)
        assert [h['state'] for h in store.history(('g','h1','c')) if h['state'] != 'blocked'] == list(STAGES[1:])
        assert store.get_job(('g','h1','c'))['lease_owner'] is None


def test_notification_error_write_failure_cannot_downgrade_activation(tmp_path):
    import sqlite3
    from maintenance.controller import advance_job, STAGES
    with Store(tmp_path/'state.db') as store:
        current = job(store)
        store.db.execute("CREATE TRIGGER fail_notification BEFORE UPDATE OF notification_error ON jobs BEGIN SELECT RAISE(ABORT, 'disk error'); END")
        def notify(*args): raise OSError('outbox unavailable')
        with pytest.raises(sqlite3.IntegrityError, match='disk error'):
            advance_job(store, current, dict.fromkeys(STAGES[1:], lambda j: {'commit':'abc'}), notify=notify)
        assert store.jobs('g')[0]['state'] == 'activated'
        assert [h['state'] for h in store.history(('g','h1','c'))] == list(STAGES[1:])


def test_pipeline_exception_keeps_blocked_receipt_and_never_publishes(tmp_path):
    from maintenance.controller import advance_job
    with Store(tmp_path/'state.db') as store:
        current=job(store)
        called=[]
        def evidence(j):raise ValueError('missing source mapping')
        def forbidden(j):called.append(True);return {}
        result=advance_job(store,current,{'evidence-ready':evidence,'editing':forbidden,'validated':forbidden,'published':forbidden,'activated':forbidden})
        assert result['state']=='blocked'
        assert not called
        assert store.progress('g')=={}
        assert 'missing source mapping' in store.jobs('g')[0]['receipt']['reason']


def test_pipeline_preserves_published_before_activation_failure(tmp_path):
    from maintenance.controller import advance_job
    with Store(tmp_path/'state.db') as store:
        current=job(store)
        def accepted(j):return {'commit':'a'*40}
        def activation(j):raise RuntimeError('producers active')
        result=advance_job(store,current,dict.fromkeys(('evidence-ready','editing','validated','published'),accepted)|{'activated':activation})
        assert result['state']=='blocked'
        assert store.progress('g')['published']['commit']=='a'*40
        assert 'activated' not in store.progress('g')


def test_pipeline_does_not_repeat_blocked_job_without_retry(tmp_path):
    from maintenance.controller import advance_job
    with Store(tmp_path/'state.db') as store:
        current=job(store)
        def fail(j):raise ValueError('blocked')
        advance_job(store,current,{'evidence-ready':fail})
        current=store.jobs('g')[0]
        history=store.history(('g','h1','c'))
        assert advance_job(store,current,{})['state']=='blocked'
        assert store.history(('g','h1','c'))==history
