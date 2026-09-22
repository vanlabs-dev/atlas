import hashlib
import subprocess

import pytest

from maintenance import validate as v

KEY = b'validation-only-secret-key-32-bytes'


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c',
        'user.name=vaNlabs', '-c', 'user.email=vanlabs@pm.me', '-C', str(repo), *args],
        text=True).strip()


@pytest.fixture
def candidate(tmp_path):
    repo = tmp_path / 'candidate'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    (repo / 'README.md').write_text('baseline\n')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'docs: establish baseline')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'README.md').write_text('reviewed update\n')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'docs: update runtime')
    return repo, base


def report(repo):
    return {
        'reviewer': 'independent-reviewer', 'worker': 'coding-worker',
        'approved': True, 'tree': git(repo, 'rev-parse', 'HEAD^{tree}'),
        'evidence_sha256': hashlib.sha256(b'evidence').hexdigest(),
        'upstream': {'runtime/src/lib.rs': {'disposition': 'no_impact', 'evidence': 'packet:runtime/src/lib.rs'}},
        'subsystems': {name: {'disposition': 'no_impact', 'evidence': 'packet:analysis'} for name in v.SUBSYSTEMS},
        'checks': {name: 'passed' for name in v.REQUIRED_CHECKS},
    }


def validate(repo, base, review=None):
    return v.validate_candidate(repo, base, evidence=b'evidence',
        upstream_paths=['runtime/src/lib.rs'], review=report(repo) if review is None else review,
        worker_id='coding-worker', reviewer_id='independent-reviewer',
        checks={name: 'passed' for name in v.REQUIRED_CHECKS}, signing_key=KEY)


@pytest.mark.parametrize('path', ['.env', 'config/.env.prod', 'var/out.json', '.gitmodules',
    'AGENTS.md', 'maintenance/worker.py', 'maintenance/config.json', 'private/results.json',
    'output/private.json', 'keys/deploy.key', 'credentials.json', 'docs/link'])
def test_rejects_unsafe_changed_paths(candidate, path):
    repo, base = candidate
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if path == 'docs/link':
        target.symlink_to('/etc/passwd')
    else:
        target.write_text('unsafe\n')
    git(repo, 'add', path)
    git(repo, 'commit', '-m', 'docs: propose unsafe path')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


@pytest.mark.parametrize('path', [
    'conftest.py', 'inventory/tests/conftest.py', 'pytest.ini', '.pytest.ini',
    'pyproject.toml', 'inventory/pyproject.toml', 'setup.cfg', 'tox.ini',
    'pytest.py', 'pytest/__init__.py', 'pytest/__main__.py', '_pytest/config.py',
    'sitecustomize.py', 'usercustomize.py', 'nested/sitecustomize/__init__.py',
    'nested/usercustomize/__init__.py', 'pytest.toml', '.pytest.toml',
])
def test_test_harness_changes_require_operator_route(candidate, path):
    repo, base = candidate
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# candidate-controlled harness\n')
    git(repo, 'add', path)
    git(repo, 'commit', '-m', 'test: change harness')
    with pytest.raises(v.ValidationError, match='operator review'):
        validate(repo, base)


@pytest.mark.parametrize('bad', ['empty', 'none', 'list', 'self', 'unapproved', 'tree',
    'evidence', 'upstream_missing', 'subsystem_missing', 'blocked', 'blank_evidence', 'check_skipped'])
def test_rejects_incomplete_or_unbound_review(candidate, bad):
    repo, base = candidate
    r = report(repo)
    if bad == 'empty': r = {}
    elif bad == 'none': r = None
    elif bad == 'list': r = []
    elif bad == 'self': r['reviewer'] = r['worker']
    elif bad == 'unapproved': r['approved'] = 'true'
    elif bad == 'tree': r['tree'] = '0' * 40
    elif bad == 'evidence': r['evidence_sha256'] = '0' * 64
    elif bad == 'upstream_missing': r['upstream'] = {}
    elif bad == 'subsystem_missing': r['subsystems'].pop('fleet')
    elif bad == 'blocked': r['subsystems']['fleet']['disposition'] = 'blocked'
    elif bad == 'blank_evidence': r['subsystems']['fleet']['evidence'] = ' '
    elif bad == 'check_skipped': r['checks']['fleet'] = 'skipped'
    with pytest.raises(v.ValidationError):
        v.validate_candidate(repo, base, evidence=b'evidence', upstream_paths=['runtime/src/lib.rs'],
            review=r, worker_id='coding-worker', reviewer_id='independent-reviewer',
            checks={name: 'passed' for name in v.REQUIRED_CHECKS}, signing_key=KEY)


@pytest.mark.parametrize('content', ['-----BEGIN OPENSSH PRIVATE KEY-----',
    'ghp_' + 'a' * 36, 'api_key = "super-secret-value"', 'https://name:password@example.com'])
def test_secret_content_rejected(candidate, content):
    repo, base = candidate
    (repo / 'README.md').write_text(content + '\n')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'docs: accidental secret')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


@pytest.mark.parametrize('state', ['dirty', 'untracked', 'ignored', 'staged', 'bad_baseline', 'whitespace'])
def test_rejects_nonexact_candidate(candidate, state):
    repo, base = candidate
    if state in ('dirty', 'staged'):
        (repo / 'README.md').write_text('unreviewed\n')
        if state == 'staged': git(repo, 'add', 'README.md')
    elif state == 'untracked': (repo / 'new.txt').write_text('unreviewed')
    elif state == 'ignored':
        (repo / '.git/info/exclude').write_text('ignored.txt\n')
        (repo / 'ignored.txt').write_text('private')
    elif state == 'bad_baseline': base = 'HEAD~1'
    elif state == 'whitespace':
        (repo / 'README.md').write_text('trailing  \n')
        git(repo, 'add', 'README.md')
        git(repo, 'commit', '-m', 'docs: whitespace')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


@pytest.mark.parametrize('path', ['auth.json', 'id_ed25519', '.aws/config', '__pycache__/module.pyc'])
def test_additional_private_paths_require_operator_gate(candidate, path):
    repo, base = candidate
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('private\n')
    git(repo, 'add', path)
    git(repo, 'commit', '-m', 'docs: private output')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


def test_empty_evidence_cannot_be_self_attested(candidate):
    repo, base = candidate
    r = report(repo)
    r['evidence_sha256'] = hashlib.sha256(b'').hexdigest()
    r['upstream'] = {}
    with pytest.raises(v.ValidationError):
        v.validate_candidate(repo, base, evidence=b'', upstream_paths=[], review=r,
            worker_id='coding-worker', reviewer_id='independent-reviewer',
            checks={name: 'passed' for name in v.REQUIRED_CHECKS}, signing_key=KEY)


def test_rename_cannot_launder_protected_path(candidate):
    repo, _ = candidate
    (repo / 'maintenance').mkdir()
    (repo / 'maintenance/policy.py').write_text('trusted baseline policy\n')
    git(repo, 'add', 'maintenance/policy.py')
    git(repo, 'commit', '-m', 'chore: baseline policy')
    base = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'mv', 'maintenance/policy.py', 'ordinary.py')
    git(repo, 'commit', '-m', 'chore: move policy')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


def test_binary_content_requires_operator_review(candidate):
    repo, base = candidate
    (repo / 'README.md').write_bytes(b'archive\x00private bytes')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'docs: binary artifact')
    with pytest.raises(v.ValidationError):
        validate(repo, base)


def test_git_clean_filter_cannot_execute_candidate_code(candidate):
    repo, _ = candidate
    (repo / '.gitattributes').write_text('README.md filter=evil\n')
    git(repo, 'add', '.gitattributes')
    git(repo, 'commit', '-m', 'chore: baseline attributes')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'README.md').write_text('new reviewed text\n')
    git(repo, 'add', 'README.md')
    git(repo, 'commit', '-m', 'docs: update')
    r = report(repo)
    sentinel = repo.parent / 'filter-executed'
    git(repo, 'config', 'filter.evil.clean', 'touch ' + str(sentinel) + '; cat')
    (repo / 'README.md').write_text('new reviewed text\n')
    with pytest.raises(v.ValidationError):
        validate(repo, base, r)
    assert not sentinel.exists()


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_index_flags_cannot_hide_dirty_candidate(candidate, flag):
    repo, base = candidate
    r = report(repo)
    git(repo, 'update-index', flag, 'README.md')
    (repo / 'README.md').write_text('hidden unreviewed content\n')
    with pytest.raises(v.ValidationError):
        validate(repo, base, r)


def test_validation_binds_exact_tree_and_evidence(candidate):
    repo, base = candidate
    receipt = validate(repo, base)
    assert receipt.baseline == base
    assert receipt.tree == git(repo, 'rev-parse', 'HEAD^{tree}')
    assert receipt.paths == ('README.md',)
    assert receipt.evidence_sha256 == hashlib.sha256(b'evidence').hexdigest()
    assert v.verify_receipt(receipt, KEY)
