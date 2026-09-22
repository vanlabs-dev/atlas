"""Prepare user units, then migrate producers after explicit system shutdown.

Never invokes sudo or modifies system units. The operator owns the one-time
privileged disable step. Prepare writes inactive user units and verifies them.
"""
import argparse
from pathlib import Path
import subprocess
import time

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
        for module,name in PRODUCERS.items():
            for suffix in ('.service','.timer'):
                content=(args.repo/module/'systemd'/(name+suffix)).read_text()
                write_unit(destination/(name+suffix),user_service(content) if suffix=='.service' else content)
        for file in (args.repo/'maintenance/systemd').glob('atlas-maintenance-*.*'):
            write_unit(destination/file.name,file.read_text())
        subprocess.run(['/usr/bin/systemctl','--user','daemon-reload'],check=True,timeout=30)
        print('Prepared inactive user units. No system timers changed.')
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
