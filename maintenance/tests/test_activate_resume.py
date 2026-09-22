"""Activation resume readback and recovery; no live services or publication."""
import pytest

from maintenance import pipeline as p


@pytest.fixture
def activation(tmp_path, monkeypatch):
    pipe = object.__new__(p.Pipeline)
    pipe.root = tmp_path / 'job'
    pipe.repo = tmp_path / 'repo'
    pipe.repo.mkdir()
    pipe.config = dict(activation_enabled=True, kb_benchmark_cases=['trusted'],
                       reader_pause_commands=[['/trusted/pause']],
                       reader_check_commands=[['/trusted/check']],
                       reader_reload_commands=[['/trusted/reload']],
                       reader_resume_commands=[['/trusted/resume']], deployment_python='/usr/bin/python3')
    publication = dict(baseline='a'*40, commit='b'*40)
    p.save_json(pipe.root / 'publication-receipt.json', publication)
    events = []

    class Window:
        user_timers = ('one.timer', 'two.timer')
        fail = False
        cleanup_fail = False
        def _state(self, user, timer):
            assert user is True
            events.append(('read', timer))
            return dict(LoadState='loaded', ActiveState='failed' if self.fail else 'active',
                        UnitFileState='disabled', Job='')
        def pause(self):
            events.append('pause')
            if self.cleanup_fail:
                raise RuntimeError('writer did not finish')
        def check(self):
            events.append('check')

    window = Window()
    monkeypatch.setattr(p, 'SystemdWindow', lambda **kw: window)
    def deploy(cfg, **kw):
        path = cfg.state_dir / 'receipt.json'
        if path.exists():
            events.append('accepted-retry')
        else:
            events.append('deploy-once')
            p.save_json(path, dict(status='accepted', run_id='run', **publication))
        return pipe.load('deployment/receipt.json')
    monkeypatch.setattr(p, 'deploy', deploy)
    monkeypatch.setattr(p, 'acceptance_commands', lambda commands, repo: events.append('resume-readers'))
    monkeypatch.setattr(p.subprocess, 'run', lambda argv, **kw: events.append(tuple(argv)))
    return pipe, window, events


def test_resume_records_disabled_but_active_supervised_timers(activation):
    pipe, window, events = activation
    result = pipe.activate({})
    assert result['status'] == 'accepted'
    receipt = pipe.load('resume-receipt.json')
    assert receipt['status'] == 'resumed'
    assert receipt['commit'] == result['commit']
    assert receipt['run_id'] == result['run_id']
    assert set(receipt['timers']) == set(window.user_timers)
    assert all(state == dict(LoadState='loaded', ActiveState='active', UnitFileState='disabled', Job='')
               for state in receipt['timers'].values())
    assert not any(isinstance(e, tuple) and 'enable' in e for e in events)


@pytest.mark.parametrize('cleanup_fail', [False, True])
def test_partial_resume_failure_requiesces_or_records_operator_recovery_then_retries(activation, cleanup_fail):
    pipe, window, events = activation
    window.fail = True
    window.cleanup_fail = cleanup_fail
    with pytest.raises(ValueError, match='resume'):
        pipe.activate({})
    receipt = pipe.load('resume-receipt.json')
    assert receipt['status'] == ('operator-recovery-required' if cleanup_fail else 'paused')
    assert receipt['timers']['one.timer']['ActiveState'] == 'failed'
    assert receipt['requiescence']['passed'] is (not cleanup_fail)
    assert 'resume-readers' in events and 'pause' in events
    assert pipe.load('deployment/receipt.json')['status'] == 'accepted'
    if cleanup_fail:
        assert 'writer did not finish' in receipt['requiescence']['error']
    else:
        assert events[-1] == 'check'
    window.fail = window.cleanup_fail = False
    assert pipe.activate({})['status'] == 'accepted'
    assert pipe.load('resume-receipt.json')['status'] == 'resumed'
    assert events.count('deploy-once') == events.count('accepted-retry') == 1
    assert pipe.load('resume-attempt-1.json') == receipt


@pytest.mark.parametrize('change', [dict(LoadState='not-found'), dict(Job='123'), dict(ActiveState='inactive')])
def test_resume_rejects_incomplete_timer_readback(activation, monkeypatch, change):
    pipe, window, events = activation
    monkeypatch.setattr(window, '_state', lambda *a: dict(
        dict(LoadState='loaded', ActiveState='active', UnitFileState='disabled', Job=''), **change))
    with pytest.raises(ValueError, match='resume'):
        pipe.activate({})
    assert pipe.load('resume-receipt.json')['status'] == 'paused'


@pytest.mark.parametrize('stage', ['reader', 'start', 'readback'])
def test_resume_command_or_readback_exception_requiesces(activation, monkeypatch, stage):
    pipe, window, events = activation
    def fail(*a, **kw):
        raise RuntimeError('partial resume failure')
    if stage == 'reader':
        monkeypatch.setattr(p, 'acceptance_commands', fail)
    elif stage == 'start':
        monkeypatch.setattr(p.subprocess, 'run', fail)
    else:
        monkeypatch.setattr(window, '_state', fail)
    with pytest.raises(ValueError, match='resume'):
        pipe.activate({})
    receipt = pipe.load('resume-receipt.json')
    assert receipt['status'] == 'paused'
    assert receipt['requiescence']['passed'] is True
    assert 'partial resume failure' in receipt['error']
