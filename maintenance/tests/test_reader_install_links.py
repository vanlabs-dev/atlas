from pathlib import Path
import pytest


def test_reader_install_refuses_symlinked_control_code(tmp_path):
    from maintenance.install import prepare_readers
    repo=Path(__file__).resolve().parents[2]
    control=tmp_path/'control';(control/'maintenance').mkdir(parents=True)
    (control/'maintenance/readers.py').symlink_to(repo/'maintenance/readers.py')
    with pytest.raises(ValueError,match='preserve'):
        prepare_readers(repo,control,tmp_path/'config/readers.json',tmp_path/'state')
    assert not (tmp_path/'config/readers.json').exists()


def test_reader_install_refuses_symlinked_parent(tmp_path):
    from maintenance.install import prepare_readers
    repo=Path(__file__).resolve().parents[2]
    backing=tmp_path/'backing';backing.mkdir()
    control=tmp_path/'control';control.mkdir()
    (control/'maintenance').symlink_to(backing,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):
        prepare_readers(repo,control,tmp_path/'config/readers.json',tmp_path/'state')
    assert not (backing/'readers.py').exists()
