"""Prepare user units, then migrate producers after explicit system shutdown.

Never invokes sudo or modifies system units. The operator owns the one-time
privileged disable step. Prepare writes inactive user units and verifies them.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

DEFAULT_RUNTIME_CONFIG = Path('/home/pi/.config/atlas-maintenance/runtime.json')


def runtime_config_path(config):
    """Restrict unit arguments to literal absolute paths, not shell/systemd syntax."""
    config = Path(config)
    if (not config.is_absolute() or str(config).startswith('//') or '..' in config.parts or
            not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(config))):
        raise ValueError('runtime config requires a literal absolute path (letters, digits, _ . / -)')
    return config


def runtime_service(text, config):
    config = runtime_config_path(config)
    old = ' --config ' + str(DEFAULT_RUNTIME_CONFIG) + ' '
    lines = text.splitlines()
    starts = [line for line in lines if line.startswith('ExecStart=')]
    if len(starts) != 1 or starts[0].count(old) != 1:
        raise ValueError('maintenance unit must select the trusted runtime config explicitly')
    return '\n'.join(line.replace(old, ' --config ' + str(config) + ' ')
                     if line.startswith('ExecStart=') else line for line in lines) + '\n'


def prepare_runtime_config(repo, config):
    """Copy byte-identical inert defaults; refuse links or operator changes.

    Walk directory descriptors with O_NOFOLLOW, including every ancestor.
    Never chmod or overwrite an existing operator file.
    """
    config = runtime_config_path(config)
    if config.is_relative_to(Path(repo).resolve()):
        raise ValueError('runtime config must be outside the checkout')
    content = (Path(repo) / 'maintenance/config.json').read_bytes()
    defaults = json.loads(content)
    if any(defaults.get(flag) is not False for flag in
           ('publication_enabled', 'activation_enabled')):
        raise ValueError('trusted runtime defaults must disable publication and activation')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in config.parts[1:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        parent = os.fstat(directory)
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError('runtime config directory must be operator-owned mode 0700')
        try:
            fd = os.open(config.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
        fd = os.open(config.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('runtime config must be a private operator-owned regular file')
            if stream.read() != content:
                raise ValueError('preserve existing runtime config: ' + str(config))
    except OSError as exc:
        raise ValueError('unsafe runtime config path: ' + str(config)) from exc
    finally:
        os.close(directory)
    return config

PRODUCERS={'repotrack':'atlas-repotrack-update','fleet':'atlas-fleet','subnt':'atlas-subnt'}


def user_service(text):
    lines=[]
    for line in text.splitlines():
        if line.startswith(('User=','Group=')):
            if line.split('=',1)[1]!='pi':raise ValueError('unexpected system identity')
        else:lines.append(line)
    return '\n'.join(lines)+'\n'


def write_unit(path,content):
    path=Path(path)
    if path.is_symlink():raise ValueError('refuse unit symlink')
    if path.exists() and path.read_text()!=content:
        raise ValueError('existing user unit differs; preserve operator work: '+path.name)
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with path.open('x') as stream:stream.write(content)
    if path.read_text()!=content:raise ValueError('unit readback mismatch')


def system_state(unit):
    result=subprocess.check_output(['/usr/bin/systemctl','--no-ask-password','show',unit,
        '-p','ActiveState','-p','UnitFileState','-p','Job'],text=True,timeout=20)
    return dict(line.split('=',1) for line in result.splitlines() if '=' in line)


def prepare_readers(repo, control, config, state):
    """Install inert, operator-controlled reader code; print—not apply—MCP changes."""
    import json
    import os
    from .readers import SERVERS
    repo,control,config,state=map(Path,(repo,control,config,state))
    payload={'state_dir':str(state),'python':'/usr/bin/python3','managed_launches_only':False}
    config_text=json.dumps(payload,indent=2)+'\n'
    targets={control/'maintenance/__init__.py':'',
             control/'maintenance/readers.py':(repo/'maintenance/readers.py').read_text(),
             config:config_text}
    for path,content in targets.items():
        if any(parent.is_symlink() for parent in path.parents):
            raise ValueError('symlinked reader control/config parent: '+str(path))
        if path.is_symlink() or (path.exists() and path.read_text()!=content):
            raise ValueError('preserve existing reader control/config: '+str(path))
    for path,content in targets.items():
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not path.exists():
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(content)
        if path.read_text()!=content:raise ValueError('reader installation readback failed')
    commands=[]
    for name in SERVERS:
        commands.append(['hermes','config','set',f'mcp_servers.atlas-{name}.command','/usr/bin/python3'])
        commands.append(['hermes','config','set',f'mcp_servers.atlas-{name}.args',json.dumps([
            str(control/'maintenance/readers.py'),'--config',str(config),'wrap',name])])
    return commands


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','prepare-readers','enable'))
    parser.add_argument('--repo',type=Path,default=Path('/home/pi/atlas'))
    parser.add_argument('--runtime-config', type=Path,
                        default=Path.home()/'.config/atlas-maintenance/runtime.json',
                        help='external runtime config to prepare and wire into both maintenance services')
    args=parser.parse_args(argv)
    destination=Path.home()/'.config/systemd/user'
    if args.action=='prepare-readers':
        import shlex
        home=Path.home()
        commands=prepare_readers(args.repo,home/'.local/lib/atlas-maintenance-control',
                    home/'.config/atlas-maintenance/readers.json',home/'.local/state/atlas-readers')
        print('Reader control installed INERT. No Hermes configuration changed. Managed-only attestation is false.')
        print('\n'.join(shlex.join(c) for c in commands))
        return 0
    if args.action=='prepare':
        config = prepare_runtime_config(args.repo, args.runtime_config)
        for module,name in PRODUCERS.items():
            for suffix in ('.service','.timer'):
                content=(args.repo/module/'systemd'/(name+suffix)).read_text()
                write_unit(destination/(name+suffix),user_service(content) if suffix=='.service' else content)
        for file in (args.repo/'maintenance/systemd').glob('atlas-maintenance-*.*'):
            content = file.read_text()
            if file.name in ('atlas-maintenance-scan.service', 'atlas-maintenance-worker.service'):
                content = runtime_service(content, config)
            write_unit(destination/file.name,content)
        subprocess.run(['/usr/bin/systemctl','--user','daemon-reload'],check=True,timeout=30)
        print(f'Prepared inactive user units and inert runtime config: {config}. No timers enabled; publication and activation remain false.')
        return 0
    # Timer and service states are checked, not assumed from disable exit status.
    for name in PRODUCERS.values():
        timer=system_state(name+'.timer')
        if timer.get('ActiveState')!='inactive' or timer.get('UnitFileState') not in ('disabled','masked') or timer.get('Job'):
            raise ValueError('operator must disable and stop system timer '+name+'.timer')
        service=system_state(name+'.service')
        if service.get('ActiveState')!='inactive' or service.get('Job'):
            raise ValueError('wait for system job to finish: '+name+'.service')
    timers=[name+'.timer' for name in PRODUCERS.values()]
    timers+=['atlas-maintenance-scan.timer','atlas-maintenance-worker.timer']
    subprocess.run(['/usr/bin/systemctl','--user','enable','--now',*timers],check=True,timeout=30)
    for timer in timers:
        subprocess.run(['/usr/bin/systemctl','--user','is-enabled',timer],check=True,timeout=10)
        subprocess.run(['/usr/bin/systemctl','--user','is-active',timer],check=True,timeout=10)
    print('Verified user timer enablement and active state. Publication remains separately gated.')
    return 0


if __name__=='__main__':raise SystemExit(main())
