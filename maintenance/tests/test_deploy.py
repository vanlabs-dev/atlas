"""Deployment tests use disposable repositories and real SQLite/KB CLI."""
import importlib
import sqlite3
import shutil
import json
from dataclasses import replace

import subprocess
import sys
from pathlib import Path

import pytest


def module():
    try:
        return importlib.import_module('maintenance.deploy')
    except ModuleNotFoundError:
        pytest.fail('maintenance.deploy is not implemented')


def test_sqlite_backup_captures_wal_without_overwriting(tmp_path):
    d = module()
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE data (value)')
        db.execute('INSERT INTO data VALUES (42)')
        db.commit()
        dest = tmp_path / 'backup.db'
        d.backup_sqlite(source, dest)
        with sqlite3.connect(dest) as copied:
            assert copied.execute('SELECT value FROM data').fetchone() == (42,)
        with pytest.raises(FileExistsError):
            d.backup_sqlite(source, dest)


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'user.name=Test', '-c',
                                    'user.email=test@example.invalid', *args],
                                   cwd=repo, text=True).strip()


def kb(repo, db, *args):
    return subprocess.run([sys.executable, 'knowledge/atlas_kb.py', *args,
                           '--db', str(db)], cwd=repo, text=True,
                          capture_output=True, check=True)


class HeldWindow:
    """Test-only external ownership assertion, never a production lock."""
    def pause(self):
        pass

    def check(self):
        pass

    def reload(self):
        pass


@pytest.fixture
def release(tmp_path):
    root = Path(__file__).resolve().parents[2]
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    git(upstream, 'init', '-b', 'main')
    for folder in ('knowledge', 'hermes', 'inventory'):
        shutil.copytree(root / folder, upstream / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (upstream / '.gitignore').write_text('__pycache__/\nvar/\n')
    (upstream / 'release.txt').write_text('old\n')
    git(upstream, 'add', '.')
    git(upstream, 'commit', '-qm', 'baseline')
    baseline = git(upstream, 'rev-parse', 'HEAD')
    live = tmp_path / 'live'
    git(tmp_path, 'clone', '-q', str(upstream), str(live))
    (upstream / 'release.txt').write_text('new\n')
    git(upstream, 'commit', '-qam', 'candidate')
    candidate = git(upstream, 'rev-parse', 'HEAD')
    db = tmp_path / 'kb.db'
    reports = tmp_path / 'old-reports'
    kb(live, db, 'ingest', '--output-dir', str(reports))
    old = json.loads(next(reports.glob('*.json')).read_text())['run_id']
    kb(live, db, 'activate', '--run', old)
    return live, upstream, db, baseline, candidate, old


def config(release, tmp_path):
    live, upstream, db, baseline, candidate, old = release
    return module().DeployConfig(repo=live, baseline=baseline, commit=candidate,
                                 kb_db=db, state_dir=tmp_path / 'deployment',
                                 python=sys.executable, remote='origin', branch='main')


def active(db):
    with sqlite3.connect(db) as connection:
        return connection.execute('SELECT DISTINCT run_id FROM units WHERE active=1').fetchall()


def test_exact_release_stages_validates_activates_and_records_previous(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    receipt = d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.commit
    assert receipt['previous_run'] == release[-1]
    assert receipt['status'] == 'accepted'
    assert receipt['commit'] == cfg.commit
    assert active(cfg.kb_db) == [(receipt['run_id'],)]
    assert active(Path(receipt['backups'][str(cfg.kb_db)])) == [(release[-1],)]
    assert json.loads((cfg.state_dir / 'receipt.json').read_text()) == receipt


@pytest.mark.parametrize('violation', ['dirty', 'baseline', 'remote', 'malformed', 'branch', 'no-active'])
def test_preflight_refuses_unsafe_baseline_without_mutation(release, tmp_path, violation):
    d = module()
    cfg = config(release, tmp_path)
    if violation == 'dirty':
        (cfg.repo / 'external.txt').write_text('keep me')
    elif violation == 'baseline':
        cfg = replace(cfg, baseline='0' * 40)
    elif violation == 'remote':
        cfg = replace(cfg, commit=cfg.baseline)
    elif violation == 'malformed':
        cfg = replace(cfg, commit='HEAD')
    elif violation == 'branch':
        git(cfg.repo, 'checkout', '-qb', 'other')
    else:
        with sqlite3.connect(cfg.kb_db) as db:
            db.execute('UPDATE units SET active=0')
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == release[3]
    assert not cfg.state_dir.exists()


def test_acceptance_failure_restores_release_and_exact_previous_run(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    with pytest.raises(d.DeployBlocked, match='acceptance'):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: False)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline
    assert active(cfg.kb_db) == [(release[-1],)]
    assert git(release[1], 'rev-parse', 'HEAD') == cfg.commit
    receipt = json.loads((cfg.state_dir / 'receipt.json').read_text())
    assert receipt['status'] == 'rolled_back'
    with sqlite3.connect(cfg.kb_db) as db:
        assert db.execute('SELECT count(*) FROM intake_runs').fetchone()[0] == 2


@pytest.mark.parametrize('external', ['file', 'commit', 'kb'])
def test_never_overwrites_external_work_during_failed_acceptance(release, tmp_path, external):
    d = module()
    cfg = config(release, tmp_path)
    def acceptance(receipt):
        if external == 'file':
            (cfg.repo / 'release.txt').write_text('external edit')
        elif external == 'commit':
            (cfg.repo / 'release.txt').write_text('external commit')
            git(cfg.repo, 'commit', '-qam', 'external work')
        else:
            kb(cfg.repo, cfg.kb_db, 'ingest', '--output-dir', str(tmp_path / 'foreign'))
            run = json.loads(next((tmp_path / 'foreign').glob('*.json')).read_text())['run_id']
            kb(cfg.repo, cfg.kb_db, 'activate', '--run', run)
        return False
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=HeldWindow(), acceptance=acceptance)
    receipt = json.loads((cfg.state_dir / 'receipt.json').read_text())
    assert receipt['status'] == 'recovery_required'
    if external == 'kb':
        assert active(cfg.kb_db) not in [[(receipt['run_id'],)], [(receipt['previous_run'],)]]
    else:
        assert (cfg.repo / 'release.txt').read_text().startswith('external')


def test_report_findings_block_activation(release, tmp_path):
    d = module()
    reports = tmp_path / 'validation'
    kb(release[0], release[2], 'ingest', '--output-dir', str(reports))
    report = json.loads(next(reports.glob('*.json')).read_text())
    for key, bad in [('secret_scan_findings', ['secret']),
                     ('duplicate_unit_ids', ['duplicate']), ('total_units', 0),
                     ('unit_counts_by_state', {}), ('run_id', 'absent')]:
        altered = {**report, key: bad}
        with pytest.raises(d.DeployBlocked):
            d.validate_report(altered, release[2])
    d.validate_report(report, release[2])


def test_failed_staged_benchmark_never_activates_candidate(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    observed = []
    def validation(report):
        observed.append(active(cfg.kb_db))
        return False
    with pytest.raises(d.DeployBlocked, match='staged validation'):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True,
                 staged_validation=validation)
    assert observed == [[(release[-1],)]]
    assert active(cfg.kb_db) == [(release[-1],)]
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline


def test_remote_advance_during_pause_blocks_before_ingest(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    class Window(HeldWindow):
        def pause(self):
            (release[1] / 'release.txt').write_text('newer upstream')
            git(release[1], 'commit', '-qam', 'newer')
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=Window(), acceptance=lambda receipt: True)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline
    with sqlite3.connect(cfg.kb_db) as db:
        assert db.execute('SELECT count(*) FROM intake_runs').fetchone()[0] == 1


@pytest.mark.parametrize('failure', ['ingest', 'activate'])
def test_kb_subprocess_failure_rolls_back_code_and_kb(release, tmp_path, failure):
    d = module()
    script = release[1] / 'knowledge/atlas_kb.py'
    text = script.read_text()
    text = text.replace('    args = parser.parse_args(argv)',
                        '    args = parser.parse_args(argv)\n'
                        f'    if args.subcommand == {failure!r}:\n        return 19')
    script.write_text(text)
    git(release[1], 'commit', '-qam', 'candidate failure fixture')
    cfg = replace(config(release, tmp_path), commit=git(release[1], 'rev-parse', 'HEAD'))
    with pytest.raises(d.DeployBlocked, match='rolled_back'):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline
    assert active(cfg.kb_db) == [(release[-1],)]


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_hidden_tracked_edits_fail_clean_checkout_gate(release, tmp_path, flag):
    d = module()
    cfg = config(release, tmp_path)
    git(cfg.repo, 'update-index', flag, 'release.txt')
    (cfg.repo / 'release.txt').write_text('hidden external edit')
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert not cfg.state_dir.exists()
    assert (cfg.repo / 'release.txt').read_text() == 'hidden external edit'


def test_kb_activation_drift_during_pause_blocks_before_code_update(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    class Window(HeldWindow):
        def pause(self):
            kb(cfg.repo, cfg.kb_db, 'ingest', '--output-dir', str(tmp_path / 'foreign'))
            report = json.loads(next((tmp_path / 'foreign').glob('*.json')).read_text())
            kb(cfg.repo, cfg.kb_db, 'activate', '--run', report['run_id'])
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=Window(), acceptance=lambda receipt: True)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline
    assert not cfg.state_dir.exists()


def test_recovery_can_finish_after_code_was_already_restored(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    class Window(HeldWindow):
        def reload(self):
            raise RuntimeError('restart temporarily unavailable')
    with pytest.raises(d.DeployBlocked, match='recovery_required'):
        d.deploy(cfg, window=Window(), acceptance=lambda receipt: False)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline
    receipt = d.recover(cfg, window=HeldWindow())
    assert receipt['status'] == 'rolled_back'


def test_recover_interrupted_activation_from_durable_receipt(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    def interrupted(receipt):
        raise KeyboardInterrupt('simulated termination')
    with pytest.raises(KeyboardInterrupt):
        d.deploy(cfg, window=HeldWindow(), acceptance=interrupted)
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.commit
    receipt = d.recover(cfg, window=HeldWindow())
    assert receipt['status'] == 'rolled_back'
    assert active(cfg.kb_db) == [(release[-1],)]
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline


def test_reloads_candidate_then_previous_on_failed_acceptance(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    observed = []
    class Window(HeldWindow):
        def reload(self):
            observed.append(git(cfg.repo, 'rev-parse', 'HEAD'))
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=Window(), acceptance=lambda receipt: False)
    assert observed == [cfg.commit, cfg.baseline]


@pytest.mark.parametrize('when', ['window', 'kb'])
def test_freshness_gate_runs_after_pause_and_immediately_before_activation(release, tmp_path, when):
    d = module()
    cfg = config(release, tmp_path)
    calls = []
    class Window(HeldWindow):
        def pause(self): calls.append('pause')
    def guard():
        calls.append('fresh')
        if when == 'window' or calls.count('fresh') == 2:
            raise ValueError('superseding runtime')
        return {'code_hash': 'verified fixture'}
    with pytest.raises((ValueError, d.DeployBlocked), match='superseding'):
        d.deploy(cfg, window=Window(), acceptance=lambda receipt: True, preactivation=guard)
    assert calls[0:2] == ['pause', 'fresh']
    assert calls.count('fresh') == (1 if when == 'window' else 2)
    assert active(cfg.kb_db) == [(release[-1],)]
    assert git(cfg.repo, 'rev-parse', 'HEAD') == cfg.baseline


def test_deploy_resumes_interruption_via_verified_rollback_and_retry(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    def interrupted(receipt): raise KeyboardInterrupt('termination')
    with pytest.raises(KeyboardInterrupt):
        d.deploy(cfg, window=HeldWindow(), acceptance=interrupted)
    result = d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert result['status'] == 'accepted'
    histories = list(tmp_path.glob('deployment-recovered-*/receipt.json'))
    assert len(histories) == 1
    history=json.loads(histories[0].read_text())
    assert history['status'] == 'rolled_back'
    assert all(Path(path).is_relative_to(histories[0].parent) and Path(path).is_file()
               for path in history['backups'].values())
    assert active(cfg.kb_db) == [(result['run_id'],)]


def test_accepted_resume_rechecks_drift_after_acceptance(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    d.deploy(cfg,window=HeldWindow(),acceptance=lambda receipt: True)
    def changed(receipt):
        (cfg.repo/'release.txt').write_text('external resumed edit')
        return True
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg,window=HeldWindow(),acceptance=changed)
    assert (cfg.repo/'release.txt').read_text()=='external resumed edit'


def test_deploy_resume_preserves_external_edits(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    def interrupted(receipt): raise KeyboardInterrupt('termination')
    with pytest.raises(KeyboardInterrupt):
        d.deploy(cfg, window=HeldWindow(), acceptance=interrupted)
    (cfg.repo/'release.txt').write_text('external edit')
    with pytest.raises(d.DeployBlocked, match='recovery_required'):
        d.deploy(cfg, window=HeldWindow(), acceptance=lambda receipt: True)
    assert (cfg.repo/'release.txt').read_text() == 'external edit'


def test_system_window_refuses_enabled_originals_before_any_stop(tmp_path):
    d = module()
    executable, _ = fake_systemctl(tmp_path, system_enabled=True)
    with pytest.raises(d.DeployBlocked, match='system timer'):
        d.SystemdWindow(systemctl=executable).pause()


def fake_systemctl(tmp_path, *, user_active=False, system_enabled=False):
    script = tmp_path / 'systemctl'
    log = tmp_path / 'calls.jsonl'
    script.write_text('''#!/usr/bin/python3
import json, sys
from pathlib import Path
log = Path(__file__).with_name('calls.jsonl')
with log.open('a') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')
a = sys.argv[1:]
if 'show' in a:
    active = '--user' in a and a[a.index('show')+1].endswith('.service') and ACTIVE
    enabled = '--user' not in a and ENABLED
    print('LoadState=loaded\\nActiveState='+('active' if active else 'inactive')+'\\nUnitFileState='+('enabled' if enabled else 'disabled')+'\\nJob=')
'''.replace('ACTIVE', repr(user_active)).replace('ENABLED', repr(system_enabled)))
    script.chmod(0o700)
    return str(script), log


def test_system_window_stops_only_user_timers_and_requires_reader_gate(tmp_path):
    d = module()
    executable, log = fake_systemctl(tmp_path)
    window = d.SystemdWindow(systemctl=executable)
    with pytest.raises(d.DeployBlocked, match='reader'):
        window.pause()
    command = (sys.executable, '-c', 'pass')
    window = d.SystemdWindow(systemctl=executable, reader_pause_commands=(command,),
                            reader_check_commands=(command,), reload_commands=(command,))
    window.pause()
    window.check()
    window.reload()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    stop = [args for args in calls if 'stop' in args]
    assert stop
    assert all('--user' in args for args in stop)
    assert not any('disable' in args or 'enable' in args for args in calls)


def test_window_wait_is_bounded_and_does_not_kill_running_jobs(tmp_path):
    d = module()
    executable, log = fake_systemctl(tmp_path, user_active=True)
    command = (sys.executable, '-c', 'pass')
    window = d.SystemdWindow(systemctl=executable, timeout=0.05,
                            reader_pause_commands=(command,), reader_check_commands=(command,),
                            reload_commands=(command,))
    with pytest.raises(d.DeployBlocked, match='jobs'):
        window.pause()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any('stop' in args and any(x.endswith('.service') for x in args) for args in calls)


def test_acceptance_cannot_claim_success_after_checkout_changes(release, tmp_path):
    d = module()
    cfg = config(release, tmp_path)
    def acceptance(receipt):
        (cfg.repo / 'release.txt').write_text('external edit')
        return True
    with pytest.raises(d.DeployBlocked):
        d.deploy(cfg, window=HeldWindow(), acceptance=acceptance)
