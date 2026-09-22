import subprocess
from pathlib import Path


def test_candidate_cannot_read_host_secrets_or_write_checkout(tmp_path):
    from maintenance.sandbox import run_tests
    root = tmp_path / 'repo'
    (root / 'tests').mkdir(parents=True)
    secret = tmp_path / 'outside-secret'
    secret.write_text('must not be visible')
    (root / 'tests' / 'test_boundary.py').write_text('''import unittest, pathlib, socket
class Boundary(unittest.TestCase):
 def test_isolation(self):
  assert not pathlib.Path(%r).exists()
  try:
   pathlib.Path('/repo/escape').write_text('bad')
  except OSError: pass
  else: raise AssertionError('checkout writable')
  assert not pathlib.Path('/home/pi/.ssh').exists()
  assert not pathlib.Path('/home/pi/atlas/.env').exists()
''' % str(secret))
    from maintenance.sandbox import TEST_VENV
    result = run_tests(root, [{'name': 'boundary', 'cwd': '.', 'argv': [TEST_VENV + '/bin/python', '-m', 'pytest', '-p', 'no:cacheprovider', '-q', 'tests']}], timeout=30)
    assert result['passed'], result
    assert not (root / 'escape').exists()


def test_failed_suite_blocks_receipt(tmp_path):
    from maintenance.sandbox import run_tests
    result = run_tests(tmp_path, [{'name':'failure','cwd':'.','argv':['/usr/bin/python3','-c','raise SystemExit(1)']}], timeout=30)
    assert result['passed'] is False


def test_empty_test_set_is_not_success(tmp_path):
    from maintenance.sandbox import run_tests
    import pytest
    with pytest.raises(ValueError):
        run_tests(tmp_path, [])
