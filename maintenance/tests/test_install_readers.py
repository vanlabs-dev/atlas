from pathlib import Path
import json
import pytest


def test_prepare_reader_control_is_inert_and_preserves_existing_files(tmp_path):
    from maintenance.install import prepare_readers
    root=Path(__file__).resolve().parents[2]
    lib=tmp_path/'control';config=tmp_path/'readers.json';state=tmp_path/'state'
    commands=prepare_readers(root,lib,config,state)
    assert len(commands)==8
    assert all(c[:3]==['hermes','config','set'] for c in commands)
    body=json.loads(config.read_text())
    assert body['managed_launches_only'] is False
    assert body['python']=='/usr/bin/python3'
    assert (lib/'maintenance/readers.py').read_bytes()==(root/'maintenance/readers.py').read_bytes()
    assert config.stat().st_mode & 0o077==0
    config.write_text('{"operator":"keep"}')
    with pytest.raises(ValueError):prepare_readers(root,lib,config,state)
    assert config.read_text()=='{"operator":"keep"}'
