"""Regression coverage for the completed publisher rename and harness boundary."""
import pytest
from maintenance import worker, validate, deploy


def test_current_publisher_is_required():
    for module in (worker, validate):
        assert 'subnt' in module.SUBSYSTEMS
        assert 'shinogi' not in module.SUBSYSTEMS
    assert 'subnt' in validate.REQUIRED_CHECKS
    assert 'atlas-subnt.timer' in deploy.SYSTEM_TIMERS
    assert 'atlas-shinogi.timer' not in deploy.SYSTEM_TIMERS


@pytest.mark.parametrize('path', ['pytest.toml', 'nested/pytest.toml',
    '_pytest/__init__.py', 'pytest.pyc', 'conftest.pyc',
    'sitecustomize/__init__.py', 'usercustomize/__init__.py',
    'sitecustomize.pyc', 'usercustomize.pyc', '__pycache__/payload.pyc'])
def test_worker_rejects_all_validator_harness_paths(tmp_path, path):
    with pytest.raises(worker.WorkerBlocked):
        worker.safe_path(tmp_path, path, writable=True, new=True)
