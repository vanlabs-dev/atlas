"""The retired shortcut must not provide a second publication route."""
import importlib.util
from pathlib import Path


def test_retired_publisher_refuses_without_git_or_network(monkeypatch, capsys):
    path = Path(__file__).resolve().parents[1] / 'atlas_spec_publish.py'
    spec = importlib.util.spec_from_file_location('retired_publisher', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError('Retired publisher attempted an external operation')

    import subprocess
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert module.main() == 2
    assert 'retired' in capsys.readouterr().err.lower()
