from pathlib import Path
import pytest


def test_user_unit_render_removes_only_identity_directives():
    from maintenance.install import user_service
    text='[Service]\nUser=pi\nGroup=pi\nExecStart=/usr/bin/python3 /home/pi/atlas/fleet/atlas_fleet.py reconcile\nNice=10\n'
    result=user_service(text)
    assert 'User=' not in result and 'Group=' not in result
    assert 'ExecStart=/usr/bin/python3 /home/pi/atlas/fleet/atlas_fleet.py reconcile' in result
    assert 'Nice=10' in result
    with pytest.raises(ValueError):user_service('[Service]\nUser=root\nExecStart=/bin/true\n')


def test_install_preserves_conflicting_user_units(tmp_path):
    from maintenance.install import write_unit
    p=tmp_path/'existing.service';p.write_text('user owned')
    with pytest.raises(ValueError):write_unit(p,'replacement')
    assert p.read_text()=='user owned'
    write_unit(tmp_path/'new.service','content')
    assert (tmp_path/'new.service').read_text()=='content'


def test_prepare_uses_current_subnt_units_without_changing_renderer(tmp_path, monkeypatch):
    from maintenance import install
    repo = Path(__file__).resolve().parents[2]
    calls = []
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(install.subprocess, 'run', lambda argv, **kwargs: calls.append(argv))
    assert install.main(['prepare', '--repo', str(repo)]) == 0
    destination = tmp_path / '.config/systemd/user'
    service = (destination / 'atlas-subnt.service').read_text()
    assert service == install.user_service((repo / 'subnt/systemd/atlas-subnt.service').read_text())
    assert 'ExecStart=/usr/bin/python3 /home/pi/atlas/subnt/atlas_subnt.py publish' in service
    assert (destination / 'atlas-subnt.timer').read_text() == (repo / 'subnt/systemd/atlas-subnt.timer').read_text()
    assert not list(destination.glob('*shinogi*'))
    assert calls == [['/usr/bin/systemctl', '--user', 'daemon-reload']]


def test_mandatory_suites_include_current_subnt_contract():
    from maintenance.sandbox import DEFAULT_SUITES
    suites = {suite['name']: suite for suite in DEFAULT_SUITES}
    assert 'subnt' in suites
    assert suites['subnt']['argv'][-1] == 'subnt/tests'
    assert 'shinogi' not in suites
    assert all('shinogi/tests' not in suite['argv'] for suite in DEFAULT_SUITES)


@pytest.mark.parametrize('active_unit', ['atlas-subnt.timer', 'atlas-subnt.service'])
def test_enable_blocks_active_subnt_producer(active_unit, monkeypatch):
    from maintenance import install
    checked, calls = [], []
    def state(unit):
        checked.append(unit)
        return {'ActiveState': 'active' if unit == active_unit else 'inactive',
                'UnitFileState': 'disabled', 'Job': ''}
    monkeypatch.setattr(install, 'system_state', state)
    monkeypatch.setattr(install.subprocess, 'run', lambda argv, **kwargs: calls.append(argv))
    with pytest.raises(ValueError, match=active_unit):
        install.main(['enable'])
    assert active_unit in checked
    assert not calls
