"""Deterministic policy tests; fixtures are synthetic, never chain receipts."""
import copy
import importlib
import pytest
from maintenance.acceptance import activation_checks, storage_key

H = '0x' + '22'*32
A = '0x' + '11'*32


def test_one_passing_row_cannot_verify_failed_same_obligation():
    requirement = [{'id': 'both', 'paths': [], 'required': True}]
    proof = {'obligation': 'both', 'block_hash': H, 'key': '0x12',
             'expected_raw': '0x01', 'evidence': 'trusted fixture'}
    result = activation_checks([], requirement, [proof, {**proof, 'expected_raw': '0x00'}],
                               lambda *args: '0x01')
    assert not result['passed']
    assert result['unverified'] == ['both']


def metadata():
    defs = [{'primitive': 'u8'}, {'primitive': 'u16'}, {'primitive': 'u64'},
            {'primitive': 'bool'}, {'sequence': {'type': 0}},
            {'composite': {'fields': [{'type': 1}]}},
            {'composite': {'fields': [{'type': 2}]}}]
    def entry(name, value, key=None):
        return {'name': name, 'modifier': 'Default',
                'default': '0x' + ('00'*8 if value == 6 else '00'),
                'type': {'Plain': value} if key is None else
                        {'Map': {'key': key, 'value': value, 'hashers': ['Identity']}}}
    return {'types': {'types': [{'id': i, 'type': {'def': d}} for i, d in enumerate(defs)]},
            'pallets': [{'name': 'SubtensorModule', 'storage': {'prefix': 'SubtensorModule', 'entries': [
                entry('HasMigrationRun', 3, 4), entry('NetworksAdded', 3, 5),
                entry('SubnetTAO', 6, 5), entry('TotalStake', 6), entry('BasketTradingEnabled', 3)]}}]}


def aggregate_fixture(monkeypatch):
    from maintenance import metadata as decoder
    m = metadata()
    monkeypatch.setattr(decoder, 'decode_metadata', lambda raw: copy.deepcopy(m))
    prefix = storage_key('SubtensorModule', 'NetworksAdded')
    subnet = storage_key('SubtensorModule', 'SubnetTAO')
    total = storage_key('SubtensorModule', 'TotalStake')
    values = {prefix+'0000': '0x01', prefix+'0100': '0x00', prefix+'0200': '0x01',
              subnet+'0000': '0x0300000000000000', subnet+'0200': None,
              total: '0x0300000000000000'}
    def rpc(method, params):
        assert params[-1] == H
        if method == 'state_getMetadata': return '0x00'
        if method == 'state_getKeysPaged':
            return sorted(k for k in values if k.startswith(prefix) and (params[2] is None or k > params[2]))
        if method == 'state_queryStorageAt':
            return [{'block': H, 'changes': [[k, values[k]] for k in params[0]]}]
        if method == 'state_getStorage': return values[params[0]]
        raise AssertionError(method)
    proof = {'op': 'sum_live_subnet_tao_v1', 'obligation': 'sum', 'block_hash': H,
             'activation_hash': A, 'evidence': 'reviewed source'}
    requirement = [{'id': 'sum', 'paths': [], 'required': True}]
    return m, values, rpc, proof, requirement


def test_aggregate_rereads_complete_enumeration_and_actual_values(monkeypatch):
    m, values, rpc, proof, requirement = aggregate_fixture(monkeypatch)
    result = activation_checks([], requirement, [proof], rpc)
    assert result['passed']
    row = result['checks'][0]
    assert row['pagination_exhausted'] and row['enumerated_keys'] == 3
    assert row['live_network_count'] == 2 and row['sum_live_subnet_tao_rao'] == 3
    assert row['rpc_observations'][-1]['method'] == 'state_getStorage'
    values[storage_key('SubtensorModule', 'TotalStake')] = '0x0400000000000000'
    assert not activation_checks([], requirement, [proof], rpc)['passed']


@pytest.mark.parametrize('extra', [{'op': 'execute'}, {'callback': 'eval'}, {'expected_raw': '0x03'},
                                 {'schema_version': 99}, {'op': []}])
def test_aggregate_unknown_operation_or_schema_fails_closed(monkeypatch, extra):
    _, _, rpc, proof, requirement = aggregate_fixture(monkeypatch)
    with pytest.raises(ValueError):
        activation_checks([], requirement, [{**proof, **extra}], rpc)


@pytest.mark.parametrize('fault', ['hasher', 'key_type', 'value_type', 'unknown_type', 'unknown_map_schema'])
def test_aggregate_metadata_types_fail_closed(monkeypatch, fault):
    m, _, rpc, proof, requirement = aggregate_fixture(monkeypatch)
    entry = m['pallets'][0]['storage']['entries'][1]['type']['Map']
    if fault == 'hasher': entry['hashers'] = ['Blake2_128Concat']
    if fault == 'key_type': entry['key'] = 0
    if fault == 'value_type': entry['value'] = 0
    if fault == 'unknown_type': m['types']['types'][1]['type']['def'] = {'future': {}}
    if fault == 'unknown_map_schema': entry['future'] = True
    with pytest.raises(ValueError):
        activation_checks([], requirement, [proof], rpc)


@pytest.mark.parametrize('fault', ['duplicate', 'unordered', 'oversized', 'outside_prefix',
                                  'repeated_page', 'never_exhausted', 'batch_hash', 'batch_duplicate', 'bool', 'u64'])
def test_aggregate_malformed_actual_rpc_fails_closed(monkeypatch, fault):
    _, values, rpc, proof, requirement = aggregate_fixture(monkeypatch)
    prefix = storage_key('SubtensorModule', 'NetworksAdded')
    if fault == 'bool': values[prefix+'0000'] = '0x02'
    if fault == 'u64': values[storage_key('SubtensorModule', 'TotalStake')] = '0x03'
    count = 0
    def bad(method, params):
        nonlocal count
        result = rpc(method, params)
        if method == 'state_getKeysPaged':
            count += 1
            if fault == 'duplicate': return [prefix+'0000']*2
            if fault == 'unordered': return [prefix+'0100', prefix+'0000']
            if fault == 'oversized': return [prefix+'0000']*65
            if fault == 'outside_prefix': return ['0x1234']
            if fault == 'repeated_page': return [prefix+'0000']
            if fault == 'never_exhausted': return [prefix + count.to_bytes(2, 'big').hex()]
        if method == 'state_queryStorageAt':
            if fault == 'batch_hash': result[0]['block'] = A
            if fault == 'batch_duplicate': result[0]['changes'] = [result[0]['changes'][0]]*len(params[0])
        return result
    with pytest.raises(ValueError):
        activation_checks([], requirement, [proof], bad)


def policy_api():
    try:
        return importlib.import_module('maintenance.semantic_policy')
    except ImportError:
        pytest.fail('trusted semantic policy resolver missing')


def test_unrelated_future_transition_never_inherits_bootstrap_obligations():
    result = policy_api().resolve_policy(activation_hash=A, code_hash=H, packet={}, source_repo='/unused',
                                         rpc=lambda *args: pytest.fail('unmatched policy must not issue RPC'))
    assert result['matched'] is False
    assert result['requirements'] == [] and result['proofs'] == []
    assert not activation_checks(['runtime/migrations/future.rs'], result['requirements'], result['proofs'], None)['passed']


COMMIT = '30c70d90f8a3708d85cf95ae992b7a3fe30d2c4c'
CODE = '0x899a87a4e4610587d81d9237adeb3e420ea524cd39b397c7a9b4c811b0e7af1d'
UPDATE = '0x0a1ca38257e65f506a40ba4a44a048f4a9f161f708c60cd0f914d83c854dee9a'
GENESIS = '0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03'


def resolver_fixture(monkeypatch):
    import hashlib
    from maintenance import metadata as decoder
    module = policy_api()
    assert hasattr(module, '_load_policy'), 'bootstrap registry missing'
    policy = module._load_policy()
    # Synthetic source bytes override hashes ONLY in this test's trusted registry.
    source = b'test source\n' * max(last for citation in policy['sources'] for _, last in citation['ranges'])
    for citation in policy['sources']:
        citation['sha256'] = hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(module, '_load_policy', lambda: copy.deepcopy(policy))
    monkeypatch.setattr(module, '_source_blob', lambda *args: source)
    monkeypatch.setattr(decoder, 'decode_metadata', lambda *args: metadata())
    packet = {'status': 'ready', 'complete': True,
              'source_diff': {'new_commit': COMMIT},
              'deployments': {'new': {'code_hash': CODE, 'genesis_hash': GENESIS,
                  'mapping': {'source_verified': True, 'status': 'ready', 'source_commit': COMMIT,
                              'chain_code_hash': CODE, 'artifact_match': 'exact'}}}}
    def rpc(method, params):
        if method == 'chain_getBlockHash': return {0: GENESIS, 9117748: UPDATE, 9117749: H, 9117750: '0x'+'44'*32}[params[0]]
        if method == 'chain_getFinalizedHead': return '0x'+'44'*32
        if method == 'chain_getHeader':
            return {'number': hex({UPDATE: 9117748, H: 9117749, '0x'+'44'*32: 9117750}[params[0]]),
                    'parentHash': UPDATE if params[0] == H else A}
        if method == 'state_getStorageHash': return A if params[-1] == A else CODE
        if method == 'state_getMetadata': return '0x00'
        raise AssertionError((method, params))
    return module, packet, rpc


def test_resolver_binds_conjunctive_proofs_to_first_execution_child(monkeypatch):
    module, packet, rpc = resolver_fixture(monkeypatch)
    result = module.resolve_policy(activation_hash=UPDATE, code_hash=CODE, packet=packet, source_repo='/test', rpc=rpc)
    assert result['matched']
    assert {r['id'] for r in result['requirements']} == {'migrationMarkers', 'historicalBasketEnabled', 'totalStakeAggregate'}
    assert len(result['proofs']) == 4
    assert all(p['activation_hash'] == UPDATE and p['block_hash'] == H for p in result['proofs'])
    markers = [p for p in result['proofs'] if p['obligation'] == 'migrationMarkers']
    for p, name in zip(markers, ['enable_basket_trading_v1', 'migrate_resync_total_stake_v2']):
        assert p['key'] == storage_key('SubtensorModule', 'HasMigrationRun') + (bytes([len(name)<<2])+name.encode()).hex()
    assert result['source_receipts'] and result['rpc_observations']


def test_all_individual_required_checks_must_be_present():
    requirement = [{'id': 'markers', 'paths': [], 'required': True, 'required_checks': ['one', 'two']}]
    proof = {'obligation': 'markers', 'check_id': 'one', 'block_hash': H,
             'key': '0x12', 'expected_raw': '0x01', 'evidence': 'fixture'}
    assert not activation_checks([], requirement, [proof], lambda *args: '0x01')['passed']
    assert not activation_checks([], requirement, [proof, proof], lambda *args: '0x01')['passed']
    assert activation_checks([], requirement, [proof, {**proof, 'check_id': 'two'}], lambda *args: '0x01')['passed']


@pytest.mark.parametrize('fault', ['source_commit', 'source_hash', 'artifact', 'genesis', 'stale_child',
                                  'child_parent', 'update_poststate', 'unfinalized', 'noncanonical',
                                  'wrong_code', 'not_deployment', 'missing_parent_code'])
def test_resolver_rejects_stale_hash_and_mismatched_source(monkeypatch, fault):
    module, packet, rpc = resolver_fixture(monkeypatch)
    if fault == 'source_commit': packet['deployments']['new']['mapping']['source_commit'] = 'f'*40
    if fault == 'source_hash': monkeypatch.setattr(module, '_source_blob', lambda *args: b'tampered')
    if fault == 'artifact': packet['deployments']['new']['mapping']['source_verified'] = False
    def bad(method, params):
        result = rpc(method, params)
        if fault == 'genesis' and method == 'chain_getBlockHash' and params == [0]: return A
        if fault == 'stale_child' and method == 'chain_getBlockHash' and params == [9117749]: return '0x'+'44'*32
        if fault == 'child_parent' and method == 'chain_getHeader' and params == [H]: result['parentHash'] = A
        if fault == 'update_poststate' and method == 'chain_getBlockHash' and params == [9117749]: return UPDATE
        if fault == 'unfinalized' and method == 'chain_getFinalizedHead': return UPDATE
        if fault == 'noncanonical' and method == 'chain_getBlockHash' and params == [9117748]: return A
        if fault == 'wrong_code' and method == 'state_getStorageHash' and params[-1] == H: return A
        if fault == 'not_deployment' and method == 'state_getStorageHash': return CODE
        if fault == 'missing_parent_code' and method == 'state_getStorageHash' and params[-1] == A: return None
        return result
    with pytest.raises(ValueError):
        module.resolve_policy(activation_hash=UPDATE, code_hash=CODE, packet=packet, source_repo='/test', rpc=bad)


def test_marker_cannot_substitute_for_aggregate_operation(monkeypatch):
    module, packet, rpc = resolver_fixture(monkeypatch)
    result = module.resolve_policy(activation_hash=UPDATE, code_hash=CODE, packet=packet, source_repo='/test', rpc=rpc)
    req = [r for r in result['requirements'] if r['id'] == 'totalStakeAggregate']
    proof = {**result['proofs'][-1], 'op': 'storage_equals_v1', 'key': '0x12', 'expected_raw': '0x01'}
    assert not activation_checks([], req, [proof], lambda *args: '0x01')['passed']


@pytest.mark.parametrize('change', [{'schema_version': 2}, {'executor': 'shell'}])
def test_unknown_policy_schema_fails_closed(monkeypatch, change):
    module, packet, rpc = resolver_fixture(monkeypatch)
    policy = module._load_policy()
    policy.update(change)
    monkeypatch.setattr(module, '_load_policy', lambda: policy)
    with pytest.raises(ValueError):
        module.resolve_policy(activation_hash=UPDATE, code_hash=CODE, packet=packet, source_repo='/test', rpc=rpc)


@pytest.mark.parametrize('requirements', [
    [{'id': 'x', 'paths': [], 'required': True, 'future': True}],
    [{'id': 'x', 'paths': [], 'required': 'yes'}],
    [{'id': 'x', 'paths': [], 'required_checks': 'not-a-list'}],
    [{'id': 'x', 'paths': []}, {'id': 'x', 'paths': []}],
])
def test_requirement_schema_fail_closed(requirements):
    with pytest.raises(ValueError):
        activation_checks([], requirements, [], None)
