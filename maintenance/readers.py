"""Cooperative Atlas stdio reader gate (Linux, stdlib only).

Install this trusted module OUTSIDE the checkout being updated. Operator must
first stop the old Atlas MCP children through their owning client's lifecycle,
then explicitly replace ALL four Hermes MCP commands with::

  /absolute/python -m maintenance.readers --config /trusted/readers.json wrap kb

Use the corresponding server key for each entry, retaining its original env.
Do not signal/restart the gateway from this facility. Run `bootstrap` only after
migration; existing unmanaged servers cause refusal. Configuration example::

  {"state_dir":"/home/pi/.local/state/atlas-readers",
   "python":"/home/pi/atlas/.venv/bin/python",
   "managed_launches_only":true}

The explicit managed_launches_only attestation means ALL future launches use
this gate: no /proc snapshot can exclude a future unmanaged launch. Production
server paths are fixed below. Config and state must be private to this UID.

Wire SystemdWindow pause/check/reload argv to this CLI's `pause`, `check`, and
`reload`. Reload performs isolated MCP initialize + tools/list probes, not public
traffic. It leaves the durable pause marker in place. Call `resume` ONLY after
acceptance has committed (or an explicitly verified rollback). Never put resume
in finally. Failure leaves the marker closed. Bootstrap initially opens the gate.

A short gate flock serializes spawn+registration against pause publication.
Each reader holds a shared lifetime flock, inherited by its child. Pause persists
across command exits and reboots; check acquires exclusive lifetime flock only
while checking, NOT pretending that this ephemeral lock spans CLI invocations.
A wrapper observes pause and signals ONLY its own pidfd-bound child. There is no
controller PID kill, process-group kill, or gateway signal. Orphaned children or
forked descendants retaining the lock cause a fail-closed timeout, not broad kills.
An interrupted pause must be retried before any checkout mutation.

Active wrappers EXIT on pause to force MCP EOF and a new initialize handshake;
reconnecting wrappers wait behind the gate. Reusing an old initialized stream
with a new server is invalid MCP. Reconnect after resume is a client/operator
responsibility; the probe proves server readiness, not client reconnection.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

SERVERS = {
    'kb': '/home/pi/atlas/knowledge/atlas_kb_server.py',
    'repo': '/home/pi/atlas/repotrack/atlas_repo_server.py',
    'fleet': '/home/pi/atlas/fleet/atlas_fleet_server.py',
    'live': '/home/pi/atlas/livedata/atlas_live_server.py',
}


class Blocked(RuntimeError):
    pass


def identity(pid):
    """Kernel start tick plus UID; None only if process vanished."""
    try:
        path = Path('/proc') / str(pid)
        fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
        return [path.stat().st_uid, fields[19]]
    except (FileNotFoundError, ProcessLookupError):
        return None


class Readers:
    def __init__(self, config):
        self.config = Path(config)
        info = self.config.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise Blocked('config must be owner-controlled, not group/world writable')
        cfg = json.loads(self.config.read_text())
        if cfg.get('managed_launches_only') is not True:
            raise Blocked('explicit exclusive managed-launch operator attestation required')
        self.servers = dict(SERVERS)
        if cfg.get('test_mode'):
            if os.environ.get('ATLAS_READERS_TEST_MODE') != '1':
                raise Blocked('test mode requires explicit isolated-test environment')
            self.servers = cfg['servers']
        elif 'servers' in cfg and cfg['servers'] != SERVERS:
            raise Blocked('production server allowlist is fixed')
        self.python = cfg['python']
        if not Path(self.python).is_absolute() or not self.servers:
            raise Blocked('absolute Python and nonempty allowlist required')
        for script in self.servers.values():
            if not Path(script).is_absolute():
                raise Blocked('absolute script paths required')
        self.state = Path(cfg['state_dir'])
        if not self.state.is_absolute():
            raise Blocked('absolute state path required')
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.state.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Blocked('state must be a private, owned nonsymlink directory')
        self.paused = self.state / 'paused'

    @contextmanager
    def lock(self, name, mode=fcntl.LOCK_EX):
        fd = os.open(self.state / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, mode)
            yield fd
        finally:
            os.close(fd)

    def durable(self, name, value='1'):
        target = self.state / name
        temporary = self.state / (name + '.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        self.sync()

    def sync(self):
        fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def ready(self):
        if not (self.state / 'bootstrapped').exists():
            raise Blocked('operator bootstrap required before reader management')

    def unmanaged(self):
        registered = {}
        for file in self.state.glob('child-*.json'):
            try:
                record = json.loads(file.read_text())
            except FileNotFoundError:
                continue  # wrapper reaped its child between glob and read
            if identity(record['pid']) == record['identity']:
                registered[record['pid']] = record
        names = {Path(s).name for s in self.servers.values()}
        found = []
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                args = (proc / 'cmdline').read_bytes().split(b'\0')
                matching = any(Path(os.fsdecode(a)).name in names for a in args if a)
                if matching and int(proc.name) not in registered:
                    found.append(int(proc.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError as exc:
                raise Blocked('cannot audit /proc; refusing incomplete reader inventory') from exc
        if found:
            raise Blocked(f'unmanaged Atlas readers: {found}; migrate through owning client')

    def preflight(self):
        """Read-only audit; requires prior explicit operator bootstrap."""
        with self.lock('gate'):
            self.unmanaged()
            self.ready()

    def bootstrap(self):
        with self.lock('gate'):
            self.unmanaged()
            if (self.state / 'bootstrapped').exists():
                raise Blocked('already bootstrapped; bootstrap never clears pause')
            self.durable('bootstrapped')

    def _check(self):
        self.ready()
        if not self.paused.exists():
            raise Blocked('readers are not paused')
        self.unmanaged()
        try:
            with self.lock('readers', fcntl.LOCK_EX | fcntl.LOCK_NB):
                pass
        except BlockingIOError as exc:
            raise Blocked('reader lifetime locks still held') from exc

    def check(self):
        with self.lock('gate'):
            self._check()

    def pause(self, timeout=30):
        self.ready()
        with self.lock('gate'):
            self.durable('paused')  # before audit: failure must stay closed
            self.unmanaged()
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.check()
                return
            except Blocked:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)

    def resume(self):
        with self.lock('gate'):
            self._check()
            self.paused.unlink()
            self.sync()

    def _spawn(self, key, fd, **kwargs):
        child = subprocess.Popen([self.python, self.servers[key]],
                                 pass_fds=(fd,), start_new_session=True, **kwargs)
        pidfd = os.pidfd_open(child.pid)
        record = {'pid': child.pid, 'identity': identity(child.pid), 'key': key}
        self.durable(f'child-{child.pid}.json', json.dumps(record))
        return child, pidfd

    def _stop(self, child, pidfd):
        # pidfd cannot be redirected to a reused PID or to the parent/gateway.
        try:
            if child.poll() is None:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                    child.wait(timeout=2)
        finally:
            os.close(pidfd)
            (self.state / f'child-{child.pid}.json').unlink(missing_ok=True)

    def wrap(self, key):
        self.ready()
        if key not in self.servers:
            raise Blocked('unknown server key')
        while True:
            with self.lock('gate'):
                if not self.paused.exists():
                    fd = os.open(self.state / 'readers', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    try:
                        child, pidfd = self._spawn(key, fd)
                    except BaseException:
                        os.close(fd)
                        raise
                    break
            time.sleep(.05)
        try:
            while child.poll() is None and not self.paused.exists():
                time.sleep(.05)
            return child.returncode if child.returncode is not None else 75
        finally:
            self._stop(child, pidfd)
            os.close(fd)

    def reload(self, timeout=15):
        """Probe fresh exact servers, no inherited client stdin/stdout traffic."""
        with self.lock('gate'):
            self._check()
            for key in self.servers:
                with self.lock('readers', fcntl.LOCK_SH) as fd:
                    child, pidfd = self._spawn(key, fd, stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    try:
                        self._probe(child, timeout)
                    finally:
                        self._stop(child, pidfd)
            self._check()

    @staticmethod
    def _probe(child, timeout):
        deadline = time.monotonic() + timeout
        buffer = b''
        def send(message):
            child.stdin.write(json.dumps(message).encode() + b'\n')
            child.stdin.flush()
        def receive(request_id):
            nonlocal buffer
            while time.monotonic() < deadline:
                if b'\n' not in buffer:
                    if not select.select([child.stdout], [], [], max(0, deadline-time.monotonic()))[0]:
                        break
                    data = os.read(child.stdout.fileno(), 65536)
                    if not data:
                        raise Blocked('MCP probe ended before response')
                    buffer += data
                    if len(buffer) > 4 * 1024 * 1024:
                        raise Blocked('oversized MCP response')
                    continue
                line, buffer = buffer.split(b'\n', 1)
                message = json.loads(line)
                if message.get('id') == request_id:
                    if 'error' in message or 'result' not in message:
                        raise Blocked('MCP probe returned error')
                    return message['result']
            raise Blocked('MCP readiness probe timed out')
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'atlas-maintenance-probe', 'version': '1'}}})
        result = receive(1)
        if not result.get('protocolVersion') or 'serverInfo' not in result:
            raise Blocked('invalid MCP initialize response')
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        if not isinstance(receive(2).get('tools'), list):
            raise Blocked('invalid MCP tools/list response')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('action', choices=['bootstrap', 'preflight', 'pause', 'check', 'reload', 'resume', 'wrap'])
    parser.add_argument('server', nargs='?')
    args = parser.parse_args(argv)
    try:
        readers = Readers(args.config)
        if args.action == 'wrap':
            return readers.wrap(args.server)
        if args.action in ('pause', 'reload'):
            getattr(readers, args.action)(timeout=args.timeout)
        else:
            getattr(readers, args.action)()
        return 0
    except (Blocked, OSError, ValueError, KeyError) as exc:
        print(f'atlas-readers: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
