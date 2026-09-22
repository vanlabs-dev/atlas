"""Trusted deployment primitives; never run from a candidate worker process."""
from pathlib import Path
import os
import sqlite3
import json
import re
import subprocess
import time
from dataclasses import dataclass


SYSTEM_TIMERS = ('atlas-repotrack-update.timer', 'atlas-fleet.timer', 'atlas-subnt.timer')


@dataclass(frozen=True)
class SystemdWindow:
    """Fail-closed, operator-audited migration/reader maintenance window.

    Original system timers MUST already be disabled and inactive; this class
    never changes system units. It stops only the user replacements, waits
    (never kills) producers, then invokes trusted reader suspension/checks.
    Checks must cover non-systemd/manual writers and ALL code readers including
    MCP. This is an operational exclusion contract, not a magic global lock.
    Commands are policy-owned argv tuples, never worker/candidate output.
    Reload commands must load the selected checkout while keeping public
    traffic suspended; check commands must verify that suspension still holds.
    On any failure producers remain paused for explicit operator recovery.
    """
    systemctl: str = '/usr/bin/systemctl'
    system_timers: tuple = SYSTEM_TIMERS
    user_timers: tuple = SYSTEM_TIMERS
    reader_pause_commands: tuple = ()
    reader_check_commands: tuple = ()
    reload_commands: tuple = ()
    timeout: float = 120

    def _ctl(self, user, *args):
        argv = [self.systemctl, '--no-ask-password']
        if user:
            argv.append('--user')
        return _run([*argv, *args], '/', max(self.timeout, 1))

    def _state(self, user, unit):
        return dict(line.split('=', 1) for line in self._ctl(
            user, 'show', unit, '-p', 'LoadState', '-p', 'ActiveState',
            '-p', 'UnitFileState', '-p', 'Job').splitlines() if '=' in line)

    def _inactive(self, state):
        return (state.get('LoadState') == 'loaded' and
                state.get('ActiveState') == 'inactive' and state.get('Job') == '')

    def _system_gate(self):
        if not self.system_timers or not self.user_timers:
            raise DeployBlocked('system timer inventory and user replacements required')
        for timer in self.system_timers:
            state = self._state(False, timer)
            if not self._inactive(state) or state.get('UnitFileState') not in ('disabled', 'masked'):
                raise DeployBlocked(f'system timer {timer} must be inactive and disabled by operator')
            if not self._inactive(self._state(False, timer.removesuffix('.timer') + '.service')):
                raise DeployBlocked(f'system jobs still active for {timer}')
        # This installed legacy writer is not part of the migrated producer set.
        # Never silently enable, stop, or ignore it if the operator reactivates it.
        for unit in ('atlas-poll-chain-head.timer', 'atlas-poll-chain-head.service'):
            state = self._state(True, unit)
            if state.get('LoadState') == 'not-found' and state.get('ActiveState') == 'inactive' and state.get('Job') == '':
                continue
            if (not self._inactive(state) or (unit.endswith('.timer') and
                    state.get('UnitFileState') not in ('disabled', 'masked'))):
                raise DeployBlocked(f'unmanaged writer jobs must remain inactive: {unit}')

    def _commands(self, commands):
        for command in commands:
            if not command or isinstance(command, str) or not Path(command[0]).is_absolute():
                raise DeployBlocked('audited absolute argv commands required')
            _run(command, '/', self.timeout)

    def pause(self):
        self._system_gate()
        if not self.reader_pause_commands or not self.reader_check_commands:
            raise DeployBlocked('reader/MCP pause and verification commands not configured')
        if not self.reload_commands:
            raise DeployBlocked('explicit reader/MCP reload method not configured')
        self._ctl(True, 'stop', *self.user_timers)
        deadline = time.monotonic() + self.timeout
        while True:
            states = [self._state(True, timer.removesuffix('.timer') + '.service')
                      for timer in self.user_timers]
            if all(self._inactive(state) for state in states):
                break
            if time.monotonic() >= deadline:
                raise DeployBlocked('user jobs did not become inactive within maintenance timeout')
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        self._commands(self.reader_pause_commands)
        self.check()

    def check(self):
        self._system_gate()
        if not self.reader_check_commands:
            raise DeployBlocked('reader/MCP verification not configured')
        for timer in self.user_timers:
            for unit in (timer, timer.removesuffix('.timer') + '.service'):
                if not self._inactive(self._state(True, unit)):
                    raise DeployBlocked(f'user jobs or timer active: {unit}')
        self._commands(self.reader_check_commands)

    def reload(self):
        if not self.reload_commands:
            raise DeployBlocked('explicit reader/MCP reload method not configured')
        self._commands(self.reload_commands)



class DeployBlocked(RuntimeError):
    """No safe deployment is currently possible."""


@dataclass(frozen=True)
class DeployConfig:
    repo: Path
    baseline: str
    commit: str
    kb_db: Path
    state_dir: Path
    python: str
    remote: str = 'origin'
    branch: str = 'main'
    timeout: float = 120
    databases: tuple = ()


def _run(argv, cwd, timeout):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout,
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0',
                                 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode:
        raise DeployBlocked(f'command failed ({result.returncode}): {argv[0]}: {result.stderr[-2000:]}')
    return result.stdout.strip()


def _git(cfg, *args):
    return _run(['git', '-c', 'core.hooksPath=/dev/null', *args], cfg.repo, cfg.timeout)


def _active(db):
    with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        return [row[0] for row in conn.execute(
            'SELECT DISTINCT run_id FROM units WHERE active=1 ORDER BY run_id')]


def _save(cfg, receipt):
    temporary = cfg.state_dir / 'receipt.tmp'
    with open(temporary, 'w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, cfg.state_dir / 'receipt.json')


def _kb(cfg, *args):
    return _run([cfg.python, 'knowledge/atlas_kb.py', *args, '--db', cfg.kb_db,
                 '--actor', 'atlas-maintenance'], cfg.repo, cfg.timeout)


def _clean_head(cfg, expected):
    if any(entry and (entry[0].islower() or entry[0] == 'S')
           for entry in _git(cfg, 'ls-files', '-v', '-z').split('\0')):
        raise DeployBlocked('hidden index flags prevent clean-checkout verification')
    if _git(cfg, 'symbolic-ref', '--short', 'HEAD') != cfg.branch:
        raise DeployBlocked('checkout branch mismatch')
    if _git(cfg, 'rev-parse', 'HEAD') != expected:
        raise DeployBlocked('checkout baseline changed')
    if _git(cfg, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise DeployBlocked('checkout is not clean; preserve external work')


def _remote_exact(cfg):
    ref = f'refs/heads/{cfg.branch}'
    if _git(cfg, 'ls-remote', '--exit-code', cfg.remote, ref) != f'{cfg.commit}\t{ref}':
        raise DeployBlocked('remote exact commit mismatch')


def validate_report(report, db):
    """Reject malformed intake and findings; compare report to actual staged rows."""
    try:
        if report['secret_scan_findings'] != [] or report['duplicate_unit_ids'] != []:
            raise ValueError('secret or duplicate findings')
        total = report['total_units']
        if type(total) is not int or total <= 0:
            raise ValueError('empty intake')
        if not report['structure'] or sum(report['unit_counts_by_state'].values()) != total:
            raise ValueError('incomplete counts')
        with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as conn:
            actual = dict(conn.execute('SELECT evidence_state, count(*) FROM units '
                                       'WHERE run_id=? GROUP BY evidence_state', (report['run_id'],)))
            if actual != report['unit_counts_by_state']:
                raise ValueError('report does not match staged run')
    except (KeyError, TypeError, ValueError) as exc:
        raise DeployBlocked(f'invalid KB validation report: {exc}') from exc


def deploy(cfg, *, window, acceptance, staged_validation=None, preactivation=None):
    """Deploy one exact published commit inside an externally held window.

    `window.pause/check` and `acceptance(receipt)->bool` are trusted operator
    policy, never generated candidate instructions. The caller owns resuming
    consumers after a successful or safely rolled-back deployment.
    """
    for value in (cfg.baseline, cfg.commit):
        if not re.fullmatch('[0-9a-f]{40}', value):
            raise DeployBlocked('full lowercase commit hashes required')
    if cfg.state_dir.exists():
        path=cfg.state_dir/'receipt.json'
        if not path.is_file():
            raise DeployBlocked('interrupted deployment missing durable receipt; operator reconciliation required')
        previous_receipt=json.loads(path.read_text())
        if previous_receipt.get('commit') != cfg.commit or previous_receipt.get('baseline') != cfg.baseline:
            raise DeployBlocked('recovery receipt does not match configured commits')
        if previous_receipt.get('status') == 'accepted':
            _clean_head(cfg,cfg.commit)
            _remote_exact(cfg)
            if _active(cfg.kb_db) != [previous_receipt['run_id']]:
                raise DeployBlocked('accepted deployment has external KB drift')
            window.pause()
            window.check()
            if preactivation is not None:
                preactivation()
            window.reload()
            if acceptance(previous_receipt) is not True:
                raise DeployBlocked('accepted deployment acceptance readback failed')
            window.check()
            _clean_head(cfg,cfg.commit)
            _remote_exact(cfg)
            if _active(cfg.kb_db) != [previous_receipt['run_id']]:
                raise DeployBlocked('accepted deployment drift during acceptance')
            return previous_receipt
        recovered=recover(cfg,window=window)
        archive=cfg.state_dir.with_name(cfg.state_dir.name+'-recovered-'+str(time.time_ns()))
        recovered['backups']={db:str(archive/'backups'/Path(path).name)
                              for db,path in recovered['backups'].items()}
        recovered['archived_from']=str(cfg.state_dir)
        _save(cfg,recovered)
        cfg.state_dir.rename(archive)
    _clean_head(cfg, cfg.baseline)
    _remote_exact(cfg)
    previous = _active(cfg.kb_db)
    if len(previous) != 1:
        raise DeployBlocked('exactly one previous active KB run required')
    window.pause()
    window.check()
    fresh=preactivation() if preactivation is not None else None
    _clean_head(cfg, cfg.baseline)
    if _active(cfg.kb_db) != previous:
        raise DeployBlocked('KB active run changed while acquiring maintenance window')
    cfg.state_dir.mkdir(parents=True, mode=0o700)
    receipt = {'status': 'preparing', 'baseline': cfg.baseline,
               'commit': cfg.commit, 'previous_run': previous[0], 'backups': {},
               'fresh_after_window': fresh}
    backup_dir = cfg.state_dir / 'backups'
    backup_dir.mkdir(mode=0o700)
    for index, db in enumerate(dict.fromkeys((cfg.kb_db, *cfg.databases))):
        receipt['backups'][str(db)] = str(backup_sqlite(db, backup_dir / f'{index}.db'))
    _save(cfg, receipt)
    try:
        _git(cfg, 'fetch', '--no-tags', cfg.remote, f'refs/heads/{cfg.branch}')
        if _git(cfg, 'rev-parse', 'FETCH_HEAD') != cfg.commit:
            raise DeployBlocked('fetched remote exact commit mismatch')
        _remote_exact(cfg)
        window.check()
        _clean_head(cfg, cfg.baseline)
        _git(cfg, 'merge-base', '--is-ancestor', cfg.baseline, cfg.commit)
        _git(cfg, 'merge', '--ff-only', '--no-edit', cfg.commit)
        receipt['status'] = 'code_updated'
        _save(cfg, receipt)
        reports = cfg.state_dir / 'reports'
        _kb(cfg, 'ingest', '--output-dir', reports)
        report = json.loads(next(reports.glob('validation-report-*.json')).read_text())
        receipt['run_id'] = report['run_id']
        receipt['status'] = 'staged'
        _save(cfg, receipt)
        validate_report(report, cfg.kb_db)
        if staged_validation is not None and staged_validation(report) is not True:
            raise DeployBlocked('staged validation failed')
        window.check()
        _clean_head(cfg, cfg.commit)
        if _active(cfg.kb_db) != [receipt['previous_run']]:
            raise DeployBlocked('KB changed before activation')
        if preactivation is not None:
            receipt['fresh_before_activation']=preactivation()
            _save(cfg,receipt)
        _kb(cfg, 'activate', '--run', receipt['run_id'])
        if _active(cfg.kb_db) != [receipt['run_id']]:
            raise DeployBlocked('KB activation readback mismatch')
        window.reload()
        if acceptance(receipt) is not True:
            raise DeployBlocked('acceptance failed')
        window.check()
        _clean_head(cfg, cfg.commit)
        _remote_exact(cfg)
        if _active(cfg.kb_db) != [receipt['run_id']]:
            raise DeployBlocked('KB active run changed during acceptance')
        receipt['status'] = 'accepted'
        _save(cfg, receipt)
        return receipt
    except Exception as exc:
        receipt['error'] = str(exc)
        _rollback(cfg, receipt, window)
        _save(cfg, receipt)
        raise DeployBlocked(f'deployment failed: {exc}; {receipt["status"]}') from exc



def _rollback(cfg, receipt, window):
    try:
        window.check()
        if _active(cfg.kb_db) not in ([receipt['previous_run']], [receipt.get('run_id')]):
            raise DeployBlocked('external KB activation detected; preserve it')
        head = _git(cfg, 'rev-parse', 'HEAD')
        if head not in (cfg.commit, cfg.baseline):
            raise DeployBlocked('external release detected; preserve it')
        _clean_head(cfg, head)
        if head != cfg.baseline:
            _git(cfg, 'reset', '--keep', cfg.baseline)
        _kb(cfg, 'activate', '--run', receipt['previous_run'])
        _clean_head(cfg, cfg.baseline)
        if _active(cfg.kb_db) != [receipt['previous_run']]:
            raise DeployBlocked('KB rollback readback mismatch')
        window.reload()
        window.check()
        receipt['status'] = 'rolled_back'
    except Exception as rollback_error:
        receipt['status'] = 'recovery_required'
        receipt['rollback_error'] = str(rollback_error)


def recover(cfg, *, window):
    """Explicit retry of interrupted/failed rollback; never overwrite drift."""
    receipt = json.loads((cfg.state_dir / 'receipt.json').read_text())
    if receipt['commit'] != cfg.commit or receipt['baseline'] != cfg.baseline:
        raise DeployBlocked('recovery receipt does not match configured commits')
    if receipt['status'] == 'accepted':
        raise DeployBlocked('cannot recover an accepted deployment')
    window.pause()
    _rollback(cfg, receipt, window)
    _save(cfg, receipt)
    if receipt['status'] != 'rolled_back':
        raise DeployBlocked('recovery_required: ' + receipt['rollback_error'])
    return receipt


def backup_sqlite(source, destination):
    """Consistent backup including WAL; never replace an existing backup."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise RuntimeError('backup integrity check failed')
    return destination
