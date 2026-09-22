"""Sandbox-only installation contracts; never contact the user service manager."""
import json
import os
from pathlib import Path
import shlex

import pytest

from maintenance import install

REPO = Path(__file__).resolve().parents[2]


def test_prepare_runtime_copies_all_defaults_privately_without_mutating_checkout(tmp_path):
    source = REPO / 'maintenance/config.json'
    before = source.read_bytes()
    config = tmp_path / 'private/runtime.json'
    assert install.prepare_runtime_config(REPO, config) == config
    assert config.read_bytes() == before
    assert json.loads(config.read_text())['publication_enabled'] is False
    assert json.loads(config.read_text())['activation_enabled'] is False
    assert config.stat().st_mode & 0o777 == 0o600
    assert config.parent.stat().st_mode & 0o777 == 0o700
    assert config.stat().st_uid == os.getuid()
    assert source.read_bytes() == before
    original = config.stat()
    install.prepare_runtime_config(REPO, config)
    assert config.stat().st_ino == original.st_ino
    assert config.stat().st_mtime_ns == original.st_mtime_ns


@pytest.mark.parametrize('kind', ['file-link', 'dangling-link', 'parent-link', 'enabled',
                                  'whitespace', 'public-mode', 'directory', 'hardlink'])
def test_runtime_refuses_unsafe_or_conflicting_existing_paths(tmp_path, kind):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    config = private / 'runtime.json'
    defaults = (REPO / 'maintenance/config.json').read_bytes()
    target = tmp_path / 'target'
    target.write_bytes(defaults)
    target.chmod(0o600)
    if kind in ('file-link', 'dangling-link'):
        config.symlink_to(target if kind == 'file-link' else tmp_path / 'missing')
    elif kind == 'parent-link':
        link = tmp_path / 'link'
        link.symlink_to(private, target_is_directory=True)
        config = link / 'runtime.json'
    elif kind == 'directory':
        config.mkdir()
    elif kind == 'hardlink':
        os.link(target, config)
    else:
        body = json.loads(defaults)
        if kind == 'enabled':
            body['activation_enabled'] = body['publication_enabled'] = True
        config.write_bytes(defaults if kind == 'public-mode' else json.dumps(body).encode())
        config.chmod(0o644 if kind == 'public-mode' else 0o600)
    before = config.read_bytes() if config.is_file() else None
    with pytest.raises(ValueError):
        install.prepare_runtime_config(REPO, config)
    if before is not None:
        assert config.read_bytes() == before
    assert target.read_bytes() == defaults


def test_runtime_rejects_enabled_trusted_defaults_before_writing(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'maintenance').mkdir(parents=True)
    (repo / 'maintenance/config.json').write_text('{"publication_enabled":true,"activation_enabled":false}')
    config = tmp_path / 'private/runtime.json'
    with pytest.raises(ValueError):
        install.prepare_runtime_config(repo, config)
    assert not config.exists()


@pytest.mark.parametrize('custom', [False, True])
def test_cli_prepare_wires_effective_units_to_inert_external_config(tmp_path, monkeypatch, custom):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    calls = []
    monkeypatch.setattr(install.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    config = tmp_path / ('custom/runtime.json' if custom else '.config/atlas-maintenance/runtime.json')
    argv = ['prepare', '--repo', str(REPO)]
    if custom:
        argv += ['--runtime-config', str(config)]
    tracked = (REPO / 'maintenance/config.json').read_bytes()
    assert install.main(argv) == 0
    destination = tmp_path / '.config/systemd/user'
    units = {p.name: p.read_bytes() for p in destination.iterdir()}
    for service, action in [('scan', 'scan'), ('worker', 'process')]:
        text = (destination / f'atlas-maintenance-{service}.service').read_text()
        command = next(line.removeprefix('ExecStart=') for line in text.splitlines() if line.startswith('ExecStart='))
        assert shlex.split(command) == ['/home/pi/.cache/atlas-maintenance-venv/bin/python',
            '-m', 'maintenance.atlas_maintenance', '--config', str(config), action]
    for timer in destination.glob('*.timer'):
        module = next((k for k, v in install.PRODUCERS.items() if timer.name == v + '.timer'), 'maintenance')
        assert timer.read_bytes() == (REPO / module / 'systemd' / timer.name).read_bytes()
    assert config.read_bytes() == tracked
    assert install.main(argv) == 0
    assert units == {p.name: p.read_bytes() for p in destination.iterdir()}
    assert calls == [['/usr/bin/systemctl', '--user', 'daemon-reload']] * 2
    body = json.loads(config.read_text())
    body['publication_enabled'] = True
    config.write_text(json.dumps(body))
    calls.clear()
    with pytest.raises(ValueError):
        install.main(argv)
    assert not calls
    assert json.loads(config.read_text())['publication_enabled'] is True
    assert units == {p.name: p.read_bytes() for p in destination.iterdir()}
    assert (REPO / 'maintenance/config.json').read_bytes() == tracked


def test_shipped_units_explicitly_select_same_absolute_runtime_config():
    for service, action in [('scan', 'scan'), ('worker', 'process')]:
        text = (REPO / f'maintenance/systemd/atlas-maintenance-{service}.service').read_text()
        command = next(line[10:] for line in text.splitlines() if line.startswith('ExecStart='))
        assert shlex.split(command)[-3:] == ['--config', '/home/pi/.config/atlas-maintenance/runtime.json', action]


@pytest.mark.parametrize('path', ['relative.json', '/tmp/a/../runtime.json',
                                  '/tmp/$(touch injected)/runtime.json', '/tmp/%h/runtime.json',
                                  '/tmp/bad\nExecStart=/bin/true', '/tmp/space name/runtime.json'])
def test_cli_rejects_unsafe_config_argument_before_side_effects(tmp_path, monkeypatch, path):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    calls = []
    monkeypatch.setattr(install.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    with pytest.raises(ValueError):
        install.main(['prepare', '--repo', str(REPO), '--runtime-config', path])
    assert not calls
    assert not (tmp_path / '.config/systemd/user').exists()


def test_runtime_must_live_outside_checkout(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'maintenance').mkdir(parents=True)
    (repo / 'maintenance/config.json').write_bytes((REPO / 'maintenance/config.json').read_bytes())
    with pytest.raises(ValueError, match='outside'):
        install.prepare_runtime_config(repo, repo / 'private/runtime.json')
    assert not (repo / 'private').exists()


def test_double_slash_alias_cannot_create_runtime_config_inside_checkout(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'maintenance').mkdir(parents=True)
    (repo / 'maintenance/config.json').write_bytes((REPO / 'maintenance/config.json').read_bytes())
    alias = Path('/' + str(repo / 'private/runtime.json'))
    with pytest.raises(ValueError):
        install.prepare_runtime_config(repo, alias)
    assert not (repo / 'private').exists()
