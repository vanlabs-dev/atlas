"""Real local Git + production sandbox; only remote RPC/model are fixtures."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from maintenance import pipeline as p
from maintenance.tests.test_worker import answer, packet
from maintenance.tests.test_acceptance import metadata
from maintenance.tests.test_deploy import release, config as deploy_config, HeldWindow


class Store:
    def __init__(self, jobs): self.rows = jobs
    def jobs(self, genesis): return self.rows


class RPC:
    def __init__(self): self.calls = []
    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'chain_getFinalizedHead': return '0x'+'22'*32
        if method == 'state_getStorage': return None
        if method == 'state_getBlockHash': return '0x'+'11'*32
        if method == 'state_getRuntimeVersion': return {'specVersion': 468}
        raise AssertionError(method)


def local_git(repo, *args):
    return subprocess.check_output(['git', '-c', 'user.name=vaNlabs', '-c',
        'user.email=vanlabs@pm.me', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def integration(tmp_path, request):
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path/'repo'
    shutil.copytree(source, repo, ignore=shutil.ignore_patterns('.git', 'var', '.venv', '__pycache__', '.pytest_cache', '*.pyc'))
    # A copied integration suite must not recursively clone and execute itself.
    (repo/'maintenance/tests/test_pipeline_integration.py').unlink()
    (repo/'README.md').write_text('old\n')
    if 'bounded_repair' in request.node.name:
        (repo/'inventory/tests/test_runtime_repair.py').write_text(
            'from pathlib import Path\ndef test_runtime_document():\n'
            '    assert Path("README.md").read_text() == "fixed\\n"\n')
    local_git(repo, 'init', '-q', '-b', 'main')
    local_git(repo, 'add', '.')
    local_git(repo, 'commit', '-qm', 'isolated baseline fixture')
    config = json.loads((source/'maintenance/config.json').read_text())
    config.update(repo=str(repo), state_dir=str(tmp_path/'state'), semantic_requirements=[], semantic_proofs=[])
    job = {'number': 2, 'genesis': config['genesis'], 'activation_hash': '0x'+'22'*32,
           'code_hash': '0x'+'aa'*32, 'state': 'editing'}
    calls = []
    def model(payload):
        calls.append(payload)
        result = answer(payload)
        if 'repair_feedback' in payload:
            assert 'test_runtime_document' in json.dumps(payload['repair_feedback'])
            result['edits'][0].update(before_sha256=payload['files']['README.md']['sha256'],content='fixed\n')
        if 'manifest_sha256' in payload:
            reports = [path for path in payload['manifest'] if path.startswith('docs/runtime-upgrades/')]
            assert len(reports) == 1
            report = reports[0]
            assert payload['manifest'][report]['before_sha256'] is None
            assert set(payload['diffs']) == set(payload['manifest'])
            assert '+# Runtime deployment audit\n' in payload['diffs'][report]
            assert payload['manifest'][report]['after_sha256'] == hashlib.sha256(
                (pipe.candidate/report).read_bytes()).hexdigest()
            return {**result, 'action': 'review', 'approved': True,
                    'manifest_sha256': payload['manifest_sha256'],
                    'checks': payload['checks'], 'tree': payload['tree']}
        return result
    rpc = RPC()
    pipe = p.Pipeline(config, Store([job]), job, rpc=rpc, broker=model)
    evidence = {**packet(), 'status': 'ready',
        'atlas_inventory': {'commit': local_git(repo, 'rev-parse', 'HEAD'), 'files': [], 'subsystems': {}},
        'deployments': {side: {'block_hash': '0x'+byte*32, 'code_hash': job['code_hash'],
                              'mapping': {'source_verified': True}}
                        for side, byte in [('old', '11'), ('new', '22')]},
        'source_commits': {'old': 'a'*40, 'new': 'b'*40}}
    p.save_json(pipe.root/'model-packet.json', evidence)
    directory = pipe.root/'evidence-2'
    directory.mkdir()
    p.save_json(directory/'old.decoded-metadata.json', metadata())
    p.save_json(directory/'new.decoded-metadata.json', metadata('0x01'))
    p.save_json(directory/'semantic-pins.json', {side: evidence['deployments'][side]['block_hash'] for side in ('old', 'new')})
    p.save_json(directory/'packet.json', {**evidence,
        'source_diff': {'changed_paths': evidence['upstream_paths'],
                        'old_commit': 'a'*40, 'new_commit': 'b'*40}})
    bound={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in
           ('packet.json','semantic-pins.json','old.decoded-metadata.json','new.decoded-metadata.json')}
    p.save_json(pipe.root/'evidence-receipt.json', {'evidence_receipts': [{'key': [job['genesis'], job['activation_hash'], job['code_hash']], 'packet_dir': str(directory), 'complete': True, 'semantic_files':bound}]})
    return pipe, rpc, calls


@pytest.mark.parametrize('inventory', [None, {}, {'commit': 'a'*40}])
def test_edit_rejects_missing_or_stale_inventory_before_model(integration, inventory):
    pipe, _, calls = integration
    evidence = pipe.load('model-packet.json')
    if inventory is None:
        del evidence['atlas_inventory']
    else:
        evidence['atlas_inventory'] = inventory
    p.save_json(pipe.root/'model-packet.json', evidence)
    with pytest.raises(ValueError, match='inventory.*baseline'):
        pipe.edit(pipe.job)
    assert calls == []
    assert not pipe.candidate.exists()


def test_real_edit_validate_report_and_actual_acceptance_receipts(integration):
    pipe, rpc, calls = integration
    edited = pipe.edit(pipe.job)
    validated = pipe.validate(pipe.job)
    assert validated['candidate'] == edited['candidate']
    assert edited['report'] in validated['paths']
    acceptance = pipe.load('acceptance-receipt.json')
    assert acceptance['pinned_rpc']['transitions'][0]['storage']['count'] == 1
    assert acceptance['mcp_contracts']['count'] > 0
    assert ('state_getStorage', [acceptance['pinned_rpc']['transitions'][0]['storage']['checks'][0]['after']['key'], '0x'+'22'*32]) in rpc.calls
    assert pipe.load('test-results.json')['passed'] is True
    assert len(calls) == 2


def test_bounded_repair_uses_real_failures_and_reviews_original_baseline(integration):
    pipe, _, calls = integration
    pipe.config['max_implementation_passes']=1
    original=pipe.edit(pipe.job)
    receipt=pipe.validate(pipe.job)
    assert receipt['baseline']==original['baseline']
    assert receipt['candidate']!=original['candidate']
    proposal=pipe.load('proposal.json')
    assert proposal['before_files']['README.md']['content']=='old\n'
    assert proposal['manifest']['README.md']['before_sha256']==hashlib.sha256(b'old\n').hexdigest()
    assert (pipe.candidate/'README.md').read_text()=='fixed\n'
    assert original['report'] in receipt['paths']
    assert pipe.load('repair-progress.json')['attempts']==1
    correction = pipe.load('repair-proposal-1.json')
    assert pipe.load('repair-progress.json')['proposal_sha256'] == hashlib.sha256(p.canonical(correction)).hexdigest()
    assert correction['manifest_sha256'] == hashlib.sha256(p.canonical(correction['manifest'])).hexdigest()
    assert correction['evidence_sha256'] == hashlib.sha256(p.canonical(pipe.load('model-packet.json'))).hexdigest()
    assert correction['edits'][0]['content'] == 'fixed\n'
    assert 'source_audit_receipts' in correction
    assert 'source_audit_coverage_count' in correction
    assert len(calls)==3


def test_config_keeps_rollout_disabled_and_reader_controller_external():
    config = json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text())
    assert config['publication_enabled'] is config['activation_enabled'] is False
    for name, action in [('pause', 'pause'), ('check', 'check'), ('reload', 'reload'), ('resume', 'resume')]:
        assert config['reader_'+name+'_commands'] == [[
            '/usr/bin/python3', '/home/pi/.local/lib/atlas-maintenance-control/maintenance/readers.py',
            '--config', '/home/pi/.config/atlas-maintenance/readers.json', action]]


def test_semantics_missing_evidence_blocks_not_inferred_from_runtime(integration):
    pipe, _, _ = integration
    (pipe.root/'evidence-receipt.json').unlink()
    with pytest.raises(FileNotFoundError):
        pipe.semantic_acceptance(pipe.load('model-packet.json'))


def test_semantics_rejects_changed_decoded_metadata(integration):
    pipe, _, _ = integration
    p.save_json(pipe.root/'evidence-2/new.decoded-metadata.json', metadata('0x42'))
    with pytest.raises(ValueError, match='semantic evidence changed'):
        pipe.semantic_acceptance(pipe.load('model-packet.json'))


@pytest.mark.parametrize('violation',['unbound','pre-execution','wrong-code','valid'])
@pytest.mark.parametrize('origin', ['config', 'policy'])
def test_semantic_proof_cannot_reuse_unrelated_runtime_observation(integration,violation,origin,monkeypatch):
    pipe, _, _ = integration
    pipe.config['semantic_requirements']=[{'id':'migration','paths':['runtime/lib.rs']}]
    proof={'obligation':'migration','evidence':'trusted test fixture', 'activation_hash':pipe.job['activation_hash'],
           'block_hash':'0x'+'33'*32,'key':'0x1234','expected_raw':None}
    if violation=='unbound': proof['activation_hash']='0x'+'11'*32
    if violation=='pre-execution': proof['block_hash']=pipe.job['activation_hash']
    pipe.config['semantic_proofs']=[proof]
    if origin == 'policy':
        from maintenance import semantic_policy
        policy = {'matched': True, 'requirements': pipe.config['semantic_requirements'], 'proofs': [proof]}
        monkeypatch.setattr(semantic_policy, 'resolve_policy', lambda **kwargs: policy)
        pipe.config['semantic_requirements'] = []
        pipe.config['semantic_proofs'] = []
    class ProofRPC(RPC):
        def call(self,method,params):
            if method=='chain_getFinalizedHead': return '0x'+'44'*32
            if method=='chain_getHeader': return {'number':hex(int(params[0][2:4],16)//17)}
            if method=='chain_getBlockHash': return pipe.job['genesis'] if params==[0] else '0x'+f'{params[0]*17:02x}'*32
            if method=='state_getStorageHash': return '0x'+('bb' if violation=='wrong-code' else 'aa')*32
            if method=='state_getMetadata': return '0x00'
            return super().call(method,params)
    pipe.rpc=ProofRPC()
    pipe.detector.rpc=pipe.rpc
    if violation=='valid':
        actual=pipe.semantic_acceptance(pipe.load('model-packet.json'))
        assert actual['passed'] is True
        assert actual['transitions'][0]['activation_proofs']['execution_pins'][0]['block_hash']==proof['block_hash']
    else:
        with pytest.raises(ValueError,match='proof'):
            pipe.semantic_acceptance(pipe.load('model-packet.json'))


def test_exact_policy_uses_bound_raw_packet_and_preserves_receipt(integration, monkeypatch):
    from maintenance import semantic_policy
    pipe, _, _ = integration
    raw = json.loads((pipe.root/'evidence-2/packet.json').read_text())
    policy = {'matched': True, 'policy_id': 'fixture-exact-policy',
              'requirements': [{'id': 'historical', 'paths': [], 'required': True}],
              'proofs': [], 'source_receipts': [{'sha256': 'fixture'}],
              'rpc_observations': [{'method': 'fixture', 'result': 'retained'}]}
    observed = []
    def resolve(**kwargs):
        observed.append(kwargs)
        assert kwargs['packet'] == raw
        assert kwargs['activation_hash'] == pipe.job['activation_hash']
        assert kwargs['code_hash'] == pipe.job['code_hash']
        assert kwargs['source_repo'] == pipe.config['source_repo']
        return policy
    monkeypatch.setattr(semantic_policy, 'resolve_policy', resolve)
    actual = pipe.semantic_acceptance(pipe.load('model-packet.json'))
    assert len(observed) == 1
    assert actual['passed'] is False  # A matched policy is not a passed proof.
    transition = actual['transitions'][0]
    assert transition['policy'] == policy
    assert transition['activation_proofs']['unverified'] == ['historical']


@pytest.mark.parametrize('tamper', ['changed', 'missing-receipt'])
def test_semantics_rejects_unbound_raw_policy_packet(integration, tamper):
    pipe, _, _ = integration
    if tamper == 'changed':
        p.save_json(pipe.root/'evidence-2/packet.json', {'status': 'ready'})
    else:
        receipt = pipe.load('evidence-receipt.json')
        del receipt['evidence_receipts'][0]['semantic_files']['packet.json']
        p.save_json(pipe.root/'evidence-receipt.json', receipt)
    with pytest.raises(ValueError, match='semantic evidence changed'):
        pipe.semantic_acceptance(pipe.load('model-packet.json'))


def test_unknown_future_migration_remains_blocked(integration):
    pipe, _, _ = integration
    path = 'pallets/subtensor/src/migrations/unknown_future.rs'
    raw = json.loads((pipe.root/'evidence-2/packet.json').read_text())
    raw['source_diff']['changed_paths'] = [path]
    p.save_json(pipe.root/'evidence-2/packet.json', raw)
    receipt = pipe.load('evidence-receipt.json')
    receipt['evidence_receipts'][0]['semantic_files']['packet.json'] = hashlib.sha256(
        (pipe.root/'evidence-2/packet.json').read_bytes()).hexdigest()
    p.save_json(pipe.root/'evidence-receipt.json', receipt)
    model = pipe.load('model-packet.json')
    model['upstream_paths'] = [path]
    actual = pipe.semantic_acceptance(model)
    assert actual['passed'] is False
    assert actual['transitions'][0]['policy']['matched'] is False
    assert actual['transitions'][0]['activation_proofs']['unmapped_changed_paths'] == [path]


def test_live_acceptance_requires_actual_json_receipt(integration):
    pipe, _, _ = integration
    pipe.edit(pipe.job)
    pipe.repo=pipe.candidate
    pipe.config['repotrack_config']=str(pipe.root/'missing-repotrack.json')
    assert pipe.live_acceptance({'commit':'a'*40, 'run_id':'missing'}) is False
    receipt=pipe.load('live-acceptance-receipt.json')
    assert receipt['passed'] is False
    assert receipt['expected_run']=='missing'


def test_activation_refuses_empty_benchmark_before_window(integration):
    pipe, _, _ = integration
    pipe.config['activation_enabled']=True
    pipe.config['kb_benchmark_cases']=[]
    with pytest.raises(ValueError, match='benchmark'):
        pipe.activate(pipe.job)


def test_pipeline_staged_callback_executes_real_benchmark_before_activation(integration, release, tmp_path):
    from maintenance.deploy import deploy
    pipe, _, _ = integration
    cfg=deploy_config(release,tmp_path)
    pipe.repo=cfg.repo
    receipt=deploy(cfg,window=HeldWindow(),acceptance=lambda receipt: True,
                   staged_validation=lambda report:pipe.staged_acceptance(report,cfg,{'commit':cfg.commit}))
    actual=pipe.load('staged-acceptance-receipt.json')
    assert actual['passed'] is True
    assert actual['active_before']==actual['active_after']==[release[-1]]
    assert actual['run_id']==receipt['run_id']
    assert actual['benchmark']['count']==2


def test_freshness_refuses_superseding_ledger_even_same_code(integration):
    pipe, rpc, _ = integration
    pipe.detector.snapshot = lambda block: {'code_hash': pipe.job['code_hash']}
    pipe.store.rows.append({**pipe.job, 'number': 3, 'activation_hash': '0x'+'33'*32})
    with pytest.raises(ValueError, match='superseding'):
        pipe.fresh_runtime()
