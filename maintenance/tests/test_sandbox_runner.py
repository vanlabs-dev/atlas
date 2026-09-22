import pytest

from maintenance.sandbox import DEFAULT_SUITES, run_tests


@pytest.mark.parametrize('source,extra,expected', [
    ('', [], {'passed': 0}),
    ('import pytest\n@pytest.mark.skip(reason="mandatory")\ndef test_skip(): pass\n', [], {'skipped': 1}),
    ('def test_ok(): pass\ndef test_other(): pass\n', ['-k', 'ok'], {'passed': 1, 'deselected': 1}),
    ('def test_ok(): pass\nimport pytest\n@pytest.mark.skip(reason="mandatory")\ndef test_skip(): pass\n', [], {'passed': 1, 'skipped': 1}),
    ('import pytest\n@pytest.mark.xfail\ndef test_expected_failure(): assert False\n', [], {'xfailed': 1}),
    ('import pytest\n@pytest.mark.xfail\ndef test_unexpected_success(): pass\n', [], {'xpassed': 1}),
    ('raise RuntimeError("collection failure")\n', [], {'errors': 1}),
    ('import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError("setup")\ndef test_setup(broken): pass\n', [], {'errors': 1}),
    ('import pytest\n@pytest.fixture\ndef broken():\n    yield\n    raise RuntimeError("teardown")\ndef test_teardown(broken): pass\n', [], {'passed': 1, 'errors': 1}),
])
def test_missing_mandatory_execution_blocks(tmp_path, source, extra, expected):
    tests = tmp_path / 'maintenance' / 'tests'
    tests.mkdir(parents=True)
    (tests / 'test_example.py').write_text(source)
    default = next(suite for suite in DEFAULT_SUITES if suite['name'] == 'maintenance')
    result = run_tests(tmp_path, [{**default, 'argv': default['argv'] + extra}], timeout=30)
    assert result['passed'] is False, result
    for key, value in expected.items():
        assert result['suites'][0]['counts'][key] == value


@pytest.mark.parametrize('harness', ['conftest.py', 'maintenance/tests/conftest.py',
                                    'pytest.py', 'pytest/__main__.py',
                                    'sitecustomize.py', 'usercustomize.py'])
def test_candidate_harness_cannot_replace_mandatory_failure(tmp_path, harness):
    tests = tmp_path / 'maintenance' / 'tests'
    tests.mkdir(parents=True)
    (tests / 'test_example.py').write_text('def test_mandatory(): assert False\n')
    target = tmp_path / harness
    target.parent.mkdir(parents=True, exist_ok=True)
    if harness.startswith('pytest/'):
        (target.parent / '__init__.py').write_text('')
    spoof = "import os\nprint('1 passed in 0.01s', flush=True)\nos._exit(0)\n"
    if harness.endswith('conftest.py'):
        spoof = 'def pytest_configure(config):\n' + ''.join('    ' + line + '\n' for line in spoof.splitlines())
    target.write_text(spoof)
    suite = next(suite for suite in DEFAULT_SUITES if suite['name'] == 'maintenance')
    result = run_tests(tmp_path, [suite], timeout=30)
    assert result['passed'] is False, result
    assert result['suites'][0]['counts']['failed'] == 1, result


@pytest.mark.parametrize('command_only', [False, True])
def test_stdout_summary_without_session_finish_is_not_evidence(tmp_path, command_only):
    from maintenance.sandbox import TEST_VENV
    spoof = "import os; print('1 passed in 0.01s', flush=True); os._exit(0)"
    suite = next(suite for suite in DEFAULT_SUITES if suite['name'] == 'maintenance')
    if command_only:
        suite = {'name': 'spoof', 'argv': [TEST_VENV + '/bin/python', '-c', spoof]}
    else:
        tests = tmp_path / 'maintenance' / 'tests'
        tests.mkdir(parents=True)
        (tests / 'test_example.py').write_text('def test_early_exit():\n    ' + spoof + '\n')
        suite = {**suite, 'argv': suite['argv'] + ['-s']}
    result = run_tests(tmp_path, [suite], timeout=30)
    assert '1 passed in 0.01s' in result['suites'][0]['output']
    assert result['suites'][0]['exit_code'] == 0
    assert result['passed'] is False, result
    assert result['suites'][0]['counts']['passed'] == 0


@pytest.mark.parametrize('config,content', [
    ('pytest.ini', '[pytest]\naddopts = -k safe\n'),
    ('pyproject.toml', '[tool.pytest.ini_options]\naddopts = "-k safe"\n'),
    ('setup.cfg', '[tool:pytest]\naddopts = -k safe\n'),
    ('tox.ini', '[pytest]\naddopts = -k safe\n'),
])
def test_candidate_configuration_cannot_deselect_mandatory_failure(tmp_path, config, content):
    tests = tmp_path / 'maintenance' / 'tests'
    tests.mkdir(parents=True)
    (tmp_path / config).write_text(content)
    (tests / 'test_example.py').write_text(
        'def test_mandatory(): assert False\ndef test_safe(): pass\n')
    result = run_tests(tmp_path, [DEFAULT_SUITES[-1]], timeout=30)
    assert result['passed'] is False, result
    assert result['suites'][0]['counts']['failed'] == 1, result
    assert result['suites'][0]['counts']['passed'] == 1, result
    assert result['suites'][0]['counts']['deselected'] == 0, result


@pytest.mark.parametrize('cwd', ['.', 'app'])
def test_trusted_launcher_preserves_application_imports(tmp_path, cwd):
    from maintenance.sandbox import TEST_VENV
    (tmp_path / 'app').mkdir()
    (tmp_path / 'application.py').write_text('VALUE = 7\n')
    work = tmp_path / cwd
    (work / 'test_import.py').write_text(
        'def test_import():\n    import application\n    assert application.VALUE == 7\n')
    suite = {'name': 'app-import', 'cwd': cwd,
             'argv': [TEST_VENV + '/bin/python', '-m', 'pytest', '-p', 'no:cacheprovider', '-q', 'test_import.py']}
    result = run_tests(tmp_path, [suite], timeout=30)
    assert result['passed'], result
    assert result['suites'][0]['counts']['passed'] == 1


def test_test_stdout_is_not_a_count_receipt(tmp_path):
    tests = tmp_path / 'maintenance' / 'tests'
    tests.mkdir(parents=True)
    (tests / 'test_example.py').write_text(
        "import atexit\natexit.register(print, '99 passed in 0.01s')\n"
        'def test_ok(): pass\n')
    result = run_tests(tmp_path, [DEFAULT_SUITES[-1]], timeout=30)
    assert result['passed'], result
    assert '99 passed in 0.01s' in result['suites'][0]['output']
    assert result['suites'][0]['counts']['passed'] == 1


def test_successful_command_without_test_evidence_blocks(tmp_path):
    result = run_tests(tmp_path, [{'name': 'empty', 'argv': ['/usr/bin/true']}])
    assert result['passed'] is False


def test_actual_runner_applies_limits_and_readonly_venv(tmp_path):
    import json
    from maintenance.sandbox import TEST_VENV
    source = '''import json, resource, pathlib, socket
limits = {name: resource.getrlimit(getattr(resource, 'RLIMIT_' + name)) for name in ('AS', 'CPU', 'NPROC', 'FSIZE', 'NOFILE')}
print(json.dumps(limits), flush=True)
import pytest
assert not pathlib.Path('/home/pi/.ssh').exists()
assert not pathlib.Path('/home/pi/.config').exists()
try:
    pathlib.Path(%r).write_text('bad')
except OSError: pass
else: raise AssertionError('venv writable')
sock = socket.socket()
sock.settimeout(0.2)
assert sock.connect_ex(('1.1.1.1', 443)) != 0
''' % (TEST_VENV + '/forbidden-write')
    result = run_tests(tmp_path, [{'name': 'limits', 'argv': [TEST_VENV + '/bin/python', '-c', source]}], timeout=30)
    suite = result['suites'][0]
    assert suite['exit_code'] == 0, suite
    limits = json.loads(suite['output'])
    assert 0 < limits['AS'][1] <= 2147483648
    assert 0 < limits['CPU'][1] <= 30
    assert 0 < limits['NPROC'][1] <= 128
    assert 0 < limits['FSIZE'][1] <= 2000000
    assert 0 < limits['NOFILE'][1] <= 128


def test_stdout_flood_stops_at_file_limit(tmp_path):
    source = "import os; data = b'x' * 65536\nfor _ in range(64): os.write(1, data)"
    result = run_tests(tmp_path, [{'name': 'flood', 'argv': ['/usr/bin/python3', '-c', source]}], timeout=30)
    suite = result['suites'][0]
    assert suite['exit_code'] != 0
    assert suite['output_limited'] is True
    assert len(suite['output'].encode()) <= 2000000
    assert result['passed'] is False


def test_defaults_discover_pytest_functions_with_dedicated_venv(tmp_path):
    assert 'maintenance' in {suite['name'] for suite in DEFAULT_SUITES}
    suite = next(suite for suite in DEFAULT_SUITES if suite['name'] == 'maintenance')
    tests = tmp_path / 'maintenance' / 'tests'
    tests.mkdir(parents=True)
    (tests / 'test_example.py').write_text('def test_example():\n    import pytest\n    assert True\n')
    result = run_tests(tmp_path, [suite], timeout=30)
    assert result['passed'], result
    assert result['suites'][0]['counts']['passed'] == 1
    assert result['suites'][0]['counts']['skipped'] == 0
