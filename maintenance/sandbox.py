"""Execute candidate tests without host home, credentials or network access.

Trusted harness code must be imported from the operator installation, never the
candidate. Session receipts reject stdout spoofing, not arbitrary same-process
Python tampering: independent review is still a mandatory trust boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


TEST_VENV = '/home/pi/.cache/atlas-maintenance-venv'
TRUSTED_LAUNCHER = '/trusted/pytest_launcher.py'
DEFAULT_SUITES = [
    {'name': name, 'cwd': '.', 'argv': [TEST_VENV + '/bin/python', '-I', TRUSTED_LAUNCHER,
                                     '-p', 'no:cacheprovider', '--color=no', '-q', f'{name}/tests']}
    for name in ('inventory', 'hardening', 'hermes', 'knowledge', 'repotrack', 'livedata', 'telegram', 'fleet', 'subnt', 'maintenance')
]


def sandbox_command(root, argv, cwd='.', *, extra_readonly=(), receipt_path=None):
    root = Path(root).resolve(strict=True)
    work = (root / cwd).resolve(strict=True)
    work.relative_to(root)
    cmd = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
           '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
           '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
           '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/home/test',
           '--ro-bind', str(root), '/repo',
           '--ro-bind', str(Path(__file__).resolve().with_name('pytest_launcher.py')), TRUSTED_LAUNCHER,
           '--chdir', '/repo/' + str(work.relative_to(root))]
    if receipt_path is not None:
        cmd.extend(['--bind', str(receipt_path), '/trusted/test-receipt.json'])
    if Path('/etc/ld.so.cache').is_file():
        cmd.extend(['--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache'])
    if (root / '.git').is_dir():
        cmd.extend(['--tmpfs', '/repo/.git'])
    elif (root / '.git').exists():
        cmd.extend(['--ro-bind', '/dev/null', '/repo/.git'])
    for hidden in ('.env', 'var'):
        target = root / hidden
        if target.is_dir():
            cmd.extend(['--tmpfs', '/repo/' + hidden])
        elif target.exists():
            cmd.extend(['--ro-bind', '/dev/null', '/repo/' + hidden])
    # Only explicit trusted test dependencies may be mounted; never mount HOME.
    for path in (TEST_VENV, *extra_readonly):
        p = str(Path(path).resolve(strict=True))
        cmd.extend(['--ro-bind', p, p])
    return cmd + ['--'] + list(argv)


def _receipt_counts(handle, exit_code):
    """Fail closed on missing, malformed, oversized or incomplete receipts."""
    empty = dict.fromkeys(('passed', 'failed', 'errors', 'skipped', 'deselected', 'xfailed', 'xpassed'), 0)
    if os.fstat(handle.fileno()).st_size > 4096:
        return empty
    handle.seek(0)
    try:
        receipt = json.load(handle)
        counts = receipt['counts']
        if (receipt['version'] != 1 or receipt['event'] != 'sessionfinish' or
                type(receipt['exit_code']) is not int or receipt['exit_code'] != exit_code or
                type(receipt['collected']) is not int or receipt['collected'] < 0 or
                not isinstance(counts, dict) or set(counts) != set(empty) or
                any(type(value) is not int or value < 0 for value in counts.values())):
            return empty
        return counts
    except (ValueError, KeyError, TypeError, UnicodeError):
        return empty


def run_tests(root, suites=None, *, timeout=300, extra_readonly=()):
    suites = DEFAULT_SUITES if suites is None else suites
    if not suites:
        raise ValueError('No mandatory test suites configured')
    results = []
    for suite in suites:
        argv = list(suite['argv'])
        # Preserve legacy caller argv while never resolving pytest in /repo.
        if argv[:3] == [TEST_VENV + '/bin/python', '-m', 'pytest']:
            argv[:3] = [TEST_VENV + '/bin/python', '-I', TRUSTED_LAUNCHER]
        trusted_pytest = argv[:3] == [TEST_VENV + '/bin/python', '-I', TRUSTED_LAUNCHER]
        # Apply limits *inside* the new user namespace, not against all host-UID
        # processes. Children (including nested bwrap tests) inherit hard limits.
        bounded = ['/usr/bin/prlimit', '--as=2147483648',
                   '--cpu=' + str(max(1, int(timeout))), '--nproc=128',
                   '--nofile=128', '--fsize=2000000', '--', *argv]
        started = time.monotonic()
        # Host-controlled files bound both output memory and receipt reads.
        with tempfile.TemporaryFile() as log, tempfile.NamedTemporaryFile() as receipt:
            cmd = sandbox_command(root, bounded, suite.get('cwd', '.'),
                                  extra_readonly=extra_readonly, receipt_path=receipt.name)
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    env={'PATH': TEST_VENV + '/bin:/usr/bin:/bin', 'HOME': '/home/test',
                                         'PYTHONNOUSERSITE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
                                         'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
                                         'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_COUNT': '1',
                                         'GIT_CONFIG_KEY_0': 'init.defaultBranch',
                                         'GIT_CONFIG_VALUE_0': 'main'}, start_new_session=True)
            timed_out = False
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                code = proc.wait()
            output_limited = os.fstat(log.fileno()).st_size >= 2_000_000
            log.seek(0)
            output = log.read(2_000_000).decode('utf-8', 'replace')
            counts = _receipt_counts(receipt, code)
            if not trusted_pytest:
                counts = dict.fromkeys(counts, 0)
        results.append({'name': suite['name'], 'exit_code': code, 'timed_out': timed_out,
                        'output_limited': output_limited,
                        'duration_seconds': round(time.monotonic()-started, 3), 'output': output,
                        'counts': counts})
    return {'passed': all(r['exit_code'] == 0 and not r['timed_out'] and not r['output_limited']
                          and r['counts']['passed'] > 0
                          and not any(value for key, value in r['counts'].items() if key != 'passed')
                          for r in results), 'suites': results}
