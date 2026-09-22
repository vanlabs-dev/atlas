def test_git_fixtures_have_deterministic_default_branch(tmp_path):
    from maintenance.sandbox import TEST_VENV, run_tests
    (tmp_path / 'test_git.py').write_text('''import subprocess
def test_branch():
    assert subprocess.check_output(['git', 'config', 'init.defaultBranch'], text=True).strip() == 'main'
''')
    result = run_tests(tmp_path, [{'name': 'git-default', 'cwd': '.', 'argv': [TEST_VENV + '/bin/python', '-m', 'pytest', '-p', 'no:cacheprovider', '-q']}])
    assert result['passed'], result
