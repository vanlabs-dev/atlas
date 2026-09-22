import copy
import importlib
import pytest


def api():
    try:
        return importlib.import_module('maintenance.acceptance')
    except ImportError:
        pytest.fail('mandatory acceptance module missing')


def metadata(default='0x00', primitive='u8'):
    return {'types': {'types': [{'id': 1, 'type': {'def': {'primitive': primitive}}}]},
            'pallets': [{'name': 'System', 'storage': {'prefix': 'System', 'entries': [
                {'name': 'Number', 'type': {'Plain': 1}, 'modifier': 'Default', 'default': default}]}}]}


def test_pinned_null_defaults_and_retirement_are_distinct():
    a = api()
    old, new = metadata(), metadata('0x01')
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        return None
    receipt = a.pinned_storage_checks(old, new, '0x'+'11'*32, '0x'+'22'*32, rpc)
    assert receipt['passed']
    row = receipt['checks'][0]
    assert row['before']['raw'] is None
    assert row['before']['effective'] == '0x00'
    assert row['after']['effective'] == '0x01'
    assert calls == [('state_getStorage', [row['before']['key'], '0x'+'11'*32]),
                     ('state_getStorage', [row['after']['key'], '0x'+'22'*32])]
    assert a.storage_key('System', 'Number') == '0x26aa394eea5630e07c48ae0c9558cef702a5c1b19ab7a04f536c519aca4983ac'
    new['pallets'] = []
    row = a.pinned_storage_checks(old, new, '0x'+'11'*32, '0x'+'22'*32, rpc)['checks'][0]
    assert row['after']['metadata_present'] is False
    assert row['after']['effective'] is None
    assert row['after']['raw'] is None
    assert a.pinned_storage_checks(old, metadata(primitive='u16'), '0x'+'11'*32, '0x'+'22'*32, rpc)['checks']
    shifted = copy.deepcopy(old)
    shifted['types']['types'][0]['id'] = 42
    shifted['pallets'][0]['storage']['entries'][0]['type']['Plain'] = 42
    assert not a.pinned_storage_checks(old, shifted, '0x'+'11'*32, '0x'+'22'*32, rpc)['checks']


def test_reads_reject_oversized_raw_and_unpinned_calls():
    a = api()
    with pytest.raises(ValueError):
        a.pinned_storage_checks(metadata(), metadata('0x01'), 'latest', '0x'+'22'*32, lambda *args: None)
    with pytest.raises(ValueError):
        a.pinned_storage_checks(metadata(), metadata('0x01'), '0x'+'11'*32, '0x'+'22'*32,
                                lambda *args: '0x'+'00'*(1024*1024+1))
    with pytest.raises(ValueError):
        a.pinned_storage_checks(metadata(), metadata('0x01'), '0x'+'11'*32, '0x'+'22'*32,
                                lambda *args: None, max_checks=0)


def test_metadata_utf8_default_roundtrips_scale_bytes():
    a = api()
    assert a._hex('\u029a') == '0xca9a'


def test_required_proof_fails_closed_without_trusted_observation():
    a = api()
    assert hasattr(a, 'activation_checks'), 'activation proof gate missing'
    changed = ['runtime/src/migrations/v468.rs']
    requirements = [{'id': 'migration-468', 'paths': changed}]
    assert a.activation_checks(changed, requirements, [], lambda *args: None)['passed'] is False
    assert a.activation_checks([], requirements, [], lambda *args: None)['passed'] is True
    proof = {'obligation': 'migration-468', 'evidence': 'operator-reviewed manifest sha256:abc',
             'block_hash': '0x'+'22'*32, 'key': '0x1234', 'expected_raw': None}
    result = a.activation_checks(changed, requirements, [proof], lambda *args: None)
    assert result['passed'] and result['checks'][0]['raw'] is None
    assert not a.activation_checks(changed, requirements, [proof], lambda *args: '0x00')['passed']
    proof['status'] = 'completed'
    del proof['expected_raw']
    with pytest.raises(ValueError):
        a.activation_checks(changed, requirements, [proof], lambda *args: None)
    assert not a.activation_checks(changed, [], [], lambda *args: None)['passed']


def test_actual_contract_nodes_run_networkless():
    a = api()
    assert hasattr(a, 'mcp_contract_checks'), 'explicit contract runner missing'
    from pathlib import Path
    receipt = a.mcp_contract_checks(Path(__file__).resolve().parents[2])
    assert receipt['passed'], receipt
    assert receipt['count'] == len(a.CONTRACT_NODES)
    assert all('::test_' in n for n in receipt['nodes'])


def test_staged_callback_benchmarks_new_run_without_activation(tmp_path):
    a = api()
    assert hasattr(a, 'staged_kb_validator'), 'mandatory staged callback missing'
    import json
    import hashlib
    import sqlite3
    from pathlib import Path
    from knowledge import atlas_kb as kb
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    text = '# Acceptance\n\nUniqueStagedTerm preserves pinned evidence.\n'
    (corpus / 'sample.md').write_text(text)
    manifest = tmp_path / 'hashes.json'
    expected = {'sample.md': hashlib.sha256(text.encode()).hexdigest()}
    manifest.write_text(json.dumps({'coverage_date': '2026-09-22', 'files': expected}))
    markers = tmp_path / 'markers.json'
    markers.write_text('[]')
    db = tmp_path / 'kb.db'
    old, _ = kb.ingest(str(db), str(tmp_path), str(corpus), str(manifest), str(markers))
    kb.activate(str(db), old)
    run, report = kb.ingest(str(db), str(tmp_path), str(corpus), str(manifest), str(markers))
    cases = [{'query': 'UniqueStagedTerm', 'expected_unit_ids': ['sample.md::Acceptance']}]
    validator = a.staged_kb_validator(Path(__file__).resolve().parents[2], db, [old], expected, cases)
    assert validator(report) is True
    assert validator.receipt['run_id'] == run
    assert validator.receipt['benchmark']['count'] == 1
    assert validator.receipt['schema_tests']['count'] > 0
    with sqlite3.connect(db) as conn:
        assert conn.execute('select distinct run_id from units where active=1').fetchall() == [(old,)]
    bad = a.staged_kb_validator(Path(__file__).resolve().parents[2], db, [old], {'missing.md': '0'*64}, cases)
    assert bad(report) is False
    bad = a.staged_kb_validator(Path(__file__).resolve().parents[2], db, [old], expected,
                                [{'query': 'UniqueStagedTerm', 'expected_unit_ids': ['missing']}])
    assert bad(report) is False


def test_live_acceptance_missing_stores_blocks_and_cli_is_read_only(tmp_path, capsys):
    a = api()
    assert hasattr(a, 'live_acceptance'), 'live acceptance missing'
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    result = a.live_acceptance(root, tmp_path/'missing.db', tmp_path/'missing.json', 'a'*40, 'missing')
    assert result['passed'] is False
    assert isinstance(result['checkout_clean'], bool)
    assert result['knowledge']['isError'] is True
    assert not list(tmp_path.iterdir())
    code = a.main(['live', '--root', str(root), '--kb-db', str(tmp_path/'missing.db'),
                   '--repo-config', str(tmp_path/'missing.json'), '--expected-head', 'a'*40,
                   '--expected-run', 'missing'])
    assert code == 1
    assert '"passed": false' in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
