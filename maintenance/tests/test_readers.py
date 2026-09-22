"""Run with python -m unittest maintenance.tests.test_readers.
All actual process signaling is confined to a new bubblewrap PID namespace.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReaderTests(unittest.TestCase):
    def test_isolated_lifecycle(self):
        result = subprocess.run([
            'bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--setenv', 'ATLAS_READERS_TEST_MODE', '1',
            sys.executable, str(Path(__file__).resolve()), 'scenario'],
            cwd=ROOT, capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('lifecycle verified', result.stdout)

    def test_unmanaged_bootstrap_refuses_without_signaling(self):
        self.run_case('unmanaged')

    def test_launch_pause_race_is_serialized(self):
        self.run_case('race')

    def test_reload_probes_while_public_gate_stays_closed(self):
        self.run_case('probe')

    def test_failed_reload_leaves_gate_closed(self):
        self.run_case('badprobe')

    def test_wrapper_crash_leaves_inherited_lock_closed(self):
        self.run_case('orphan')

    def test_preflight_requires_bootstrap(self):
        self.run_case('preflight')

    def test_forged_registry_cannot_signal_parent(self):
        self.run_case('registry')

    def run_case(self, case):
        result = subprocess.run([
            'bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--setenv', 'ATLAS_READERS_TEST_MODE', '1',
            sys.executable, str(Path(__file__).resolve()), case],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def scenario():
    sys.path.insert(0, str(ROOT))
    from maintenance import readers
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = root / 'fake_reader.py'
        script.write_text('import os,sys,time\nprint(os.getpid(), flush=True)\nfor line in sys.stdin: print(line.strip(), flush=True)\n')
        cfg = root / 'config.json'
        cfg.write_text(json.dumps({'state_dir': str(root / 'state'),
            'python': sys.executable, 'servers': {'fake': str(script)},
            'managed_launches_only': True, 'test_mode': True}))
        cfg.chmod(0o600)
        control = readers.Readers(cfg)
        control.bootstrap()
        cmd = [sys.executable, '-m', 'maintenance.readers', '--config', str(cfg), 'wrap', 'fake']
        child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        first = int(child.stdout.readline())
        child.stdin.write('hello\n'); child.stdin.flush()
        assert child.stdout.readline().strip() == 'hello'
        control.pause(timeout=5)
        control.check()
        assert child.wait(timeout=5) != 0  # EOF forces a fresh MCP handshake
        assert not Path(f'/proc/{first}').exists()
        waiting = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        time.sleep(.15)
        control.check()
        assert waiting.poll() is None
        control.resume()
        second = int(waiting.stdout.readline())
        assert second != first
        control.pause(timeout=5)
        waiting.wait(timeout=5)
        assert os.getppid() > 0  # controller/test parent was never signaled
        print('lifecycle verified')


def extra_case(case):
    sys.path.insert(0, str(ROOT))
    from maintenance import readers
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = root / 'fake_reader.py'
        script.write_text('import time\ntime.sleep(60)\n')
        cfg = root / 'config.json'
        cfg.write_text(json.dumps({'state_dir': str(root / 'state'),
            'python': sys.executable, 'servers': {'fake': str(script)},
            'managed_launches_only': True, 'test_mode': True}))
        cfg.chmod(0o600)
        control = readers.Readers(cfg)
        if case == 'unmanaged':
            child = subprocess.Popen([sys.executable, str(script)])
            try:
                try:
                    control.bootstrap()
                    raise AssertionError('accepted unmanaged process')
                except readers.Blocked as exc:
                    assert 'unmanaged' in str(exc)
                assert child.poll() is None
                assert not (control.state / 'bootstrapped').exists()
            finally:
                child.terminate(); child.wait()
            return
        if case == 'preflight':
            try:
                control.preflight()
                raise AssertionError('preflight accepted absent bootstrap')
            except readers.Blocked:
                pass
            control.bootstrap()
            control.preflight()
            return
        control.bootstrap()
        if case == 'orphan':
            script.write_text('import os,time\nprint(os.getpid(),flush=True)\ntime.sleep(60)\n')
            wrapper = subprocess.Popen([sys.executable, '-m', 'maintenance.readers',
                '--config', str(cfg), 'wrap', 'fake'], stdout=subprocess.PIPE, text=True)
            assert wrapper.stdout is not None
            pid = int(wrapper.stdout.readline())
            wrapper.kill(); wrapper.wait()
            try:
                control.pause(timeout=.15)
                raise AssertionError('accepted orphan holding lifetime lock')
            except readers.Blocked:
                pass
            assert control.paused.exists()
            assert Path(f'/proc/{pid}').exists()
            # Namespace dies on test exit. Controller deliberately never signals orphan.
            return
        if case == 'registry':
            control.durable('child-forged.json', json.dumps({
                'pid': os.getpid(), 'identity': readers.identity(os.getpid()), 'key': 'fake'}))
            control.pause(timeout=1)
            control.check()
            return
        if case == 'race':
            # Hold the exact spawn/registration boundary, then race pause against it.
            hook = '''import sys,time
from pathlib import Path
from maintenance.readers import Readers
r=Readers(sys.argv[1]); original=r._spawn
root=Path(sys.argv[2])
def delayed(*a,**kw):
    (root/'entered').touch()
    while not (root/'release').exists(): time.sleep(.01)
    return original(*a,**kw)
r._spawn=delayed
sys.exit(r.wrap('fake'))
'''
            wrapper = subprocess.Popen([sys.executable, '-c', hook, str(cfg), str(root)])
            deadline = time.monotonic() + 5
            while not (root / 'entered').exists():
                assert time.monotonic() < deadline
                time.sleep(.01)
            pause = subprocess.Popen([sys.executable, '-m', 'maintenance.readers',
                '--config', str(cfg), 'pause'])
            time.sleep(.15)
            assert pause.poll() is None
            assert not control.paused.exists()  # pause cannot cross in-flight launch
            (root / 'release').touch()
            assert pause.wait(timeout=5) == 0
            assert wrapper.wait(timeout=5) == 75
            control.check()
            return
        control.pause()
        if case == 'probe':
            script.write_text('''import json,sys
for line in sys.stdin:
    msg=json.loads(line)
    if 'id' not in msg: continue
    result=({'protocolVersion':'2024-11-05','serverInfo':{'name':'fake','version':'1'}}
        if msg['method']=='initialize' else {'tools':[]})
    print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
''')
            control.reload(timeout=2)
        elif case == 'badprobe':
            try:
                control.reload(timeout=.1)
                raise AssertionError('unresponsive MCP accepted')
            except readers.Blocked:
                pass
        control.check()
        assert control.paused.exists()
        assert not list(control.state.glob('child-*.json'))


if __name__ == '__main__':
    if sys.argv[1:] == ['scenario']:
        scenario()
    elif len(sys.argv) == 2 and sys.argv[1] in ('unmanaged', 'race', 'probe', 'badprobe', 'registry', 'orphan', 'preflight'):
        extra_case(sys.argv[1])
    else:
        unittest.main()
