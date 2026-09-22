"""Trusted exact-runtime semantic policy registry (never candidate/model input).

Parent integration::

    policy = resolve_policy(activation_hash=item['key'][1], code_hash=item['key'][2],
                            packet=trusted_raw_evidence_packet,
                            source_repo=config['source_repo'], rpc=rpc.call)
    receipt = activation_checks(changed_paths, policy['requirements'], policy['proofs'], rpc.call)

Use the artifact-verified raw build_evidence packet, NOT worker/model JSON. The
caller is responsible for its durable receipt/content-hash binding. The packet
may sample the same deployed code later than deployment: canonical deployment,
parent code change and FIRST child are independently re-read here. Preserve the
returned policy receipt alongside activation_checks. A matched policy generates
proof *instructions*, not passed proofs. Unmatched policies return empty lists;
unknown changed migration/governance paths must still go through activation_checks.
No unsupported future runtime inherits bootstrap468 obligations. No writes,
publication, activation, arbitrary verifier callbacks or model-provided code.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from maintenance.acceptance import _block, runtime468_storage_schema
from maintenance.detect import CODE_KEY


def _load_policy():
    return json.loads((Path(__file__).parent / 'policies/runtime468.json').read_text())


def _source_blob(repo, commit, path):
    result = subprocess.run(['git', '-C', str(repo), 'show', commit+':'+path],
                            check=True, capture_output=True, timeout=30)
    if len(result.stdout) > 4*1024*1024:
        raise ValueError('source citation file exceeds bound')
    return result.stdout


def resolve_policy(*, activation_hash, code_hash, packet, source_repo, rpc):
    """Return {matched, requirements, proofs, source_receipts, rpc_observations}.

    Keyword-only API. ``rpc(method, params)`` is the controller's read-only RPC
    transport, not a policy-selected verifier. ``packet`` is the trusted raw
    artifact-pinned evidence packet. Raises ValueError on failed source/pin/schema
    validation. Scope is exact audited deployment468, not generic migration proof.
    """
    from maintenance.metadata import decode_metadata
    _block(activation_hash); _block(code_hash)
    policy = _load_policy()
    if (not isinstance(policy, dict) or set(policy) != {'schema_version', 'policy_id', 'source_commit',
            'code_hash', 'genesis_hash', 'activation_hash', 'activation_number', 'sources', 'requirements', 'scope'}
            or type(policy['schema_version']) is not int or policy['schema_version'] != 1):
        raise ValueError('unknown trusted policy schema')
    if policy['code_hash'] != code_hash or policy['activation_hash'] != activation_hash:
        return {'matched': False, 'requirements': [], 'proofs': [],
                'reason': 'no audited exact-runtime/deployment policy'}
    commit = policy['source_commit']
    try:
        new = packet['deployments']['new']
        mapping = new['mapping']
        if (packet['status'] != 'ready' or packet['complete'] is not True
                or new['code_hash'] != code_hash or new['genesis_hash'] != policy['genesis_hash']
                or mapping['source_verified'] is not True or mapping['status'] != 'ready'
                or mapping['chain_code_hash'] != code_hash or mapping['source_commit'] != commit
                or mapping['artifact_match'] not in ('exact', 'decompressed-equivalent')
                or packet['source_diff']['new_commit'] != commit):
            raise ValueError('policy source/artifact packet binding mismatch')
    except (KeyError, TypeError) as exc:
        raise ValueError('policy requires trusted artifact-pinned source packet') from exc
    sources = []
    for citation in policy['sources']:
        blob = _source_blob(source_repo, commit, citation['path'])
        digest = hashlib.sha256(blob).hexdigest()
        if digest != citation['sha256']:
            raise ValueError('policy source filebytes hash mismatch: '+citation['path'])
        lines = blob.decode('utf-8').splitlines()
        if any(not 1 <= first <= last <= len(lines) for first, last in citation['ranges']):
            raise ValueError('source citation range mismatch')
        sources.append({**citation, 'commit': commit, 'size': len(blob),
                        'verified_sha256': digest,
                        'citations': [{'start_line': first, 'end_line': last,
                                       'text': '\n'.join(lines[first-1:last])}
                                      for first, last in citation['ranges']]})
    observations = []
    def call(method, params):
        result = rpc(method, params)
        observations.append({'method': method, 'params': params, 'result': result})
        return result
    if call('chain_getBlockHash', [0]) != policy['genesis_hash']:
        raise ValueError('policy chain identity mismatch')
    header = call('chain_getHeader', [activation_hash])
    number = int(header['number'], 16)
    parent = header['parentHash']; _block(parent)
    if number != policy['activation_number'] or call('chain_getBlockHash', [number]) != activation_hash:
        raise ValueError('policy deployment is not canonical')
    head = call('chain_getFinalizedHead', []); _block(head)
    final = int(call('chain_getHeader', [head])['number'], 16)
    if final < number+1 or call('chain_getBlockHash', [final]) != head:
        raise ValueError('first execution child is not finalized')
    child = call('chain_getBlockHash', [number+1]); _block(child)
    child_header = call('chain_getHeader', [child])
    if child == activation_hash or child_header['parentHash'] != activation_hash or int(child_header['number'], 16) != number+1:
        raise ValueError('policy requires FIRST execution child, not update poststate')
    parent_code = call('state_getStorageHash', [CODE_KEY, parent])
    _block(parent_code)
    if parent_code == code_hash:
        raise ValueError('policy pin is not a code deployment')
    for block in (activation_hash, child):
        if call('state_getStorageHash', [CODE_KEY, block]) != code_hash:
            raise ValueError('policy post-execution code hash mismatch')
    schema = runtime468_storage_schema(decode_metadata(call('state_getMetadata', [child])))
    evidence = '; '.join(commit+':'+s['path']+' sha256:'+s['sha256'] for s in sources)
    common = {'activation_hash': activation_hash, 'block_hash': child, 'evidence': evidence}
    proofs = []
    for check, marker in [('basketMarker', 'enable_basket_trading_v1'),
                          ('stakeMarker', 'migrate_resync_total_stake_v2')]:
        encoded = marker.encode('ascii')
        # Both audited names fit SCALE's one-byte compact-length mode.
        if len(encoded) >= 64:
            raise ValueError('marker exceeds audited SCALE vector bound')
        key = schema['HasMigrationRun']['key'] + (bytes([len(encoded)<<2])+encoded).hex()
        proofs.append({**common, 'op': 'storage_equals_v1', 'obligation': 'migrationMarkers',
                       'check_id': check, 'key': key, 'expected_raw': '0x01'})
    proofs.append({**common, 'op': 'storage_equals_v1', 'obligation': 'historicalBasketEnabled',
                   'check_id': 'basketEnabled', 'key': schema['BasketTradingEnabled']['key'], 'expected_raw': '0x01'})
    proofs.append({**common, 'op': 'sum_live_subnet_tao_v1', 'obligation': 'totalStakeAggregate',
                   'check_id': 'stakeAggregate'})
    return {'matched': True, 'policy_id': policy['policy_id'], 'requirements': policy['requirements'],
            'proofs': proofs, 'activation_hash': activation_hash, 'child_hash': child,
            'code_hash': code_hash, 'source_commit': commit, 'source_receipts': sources,
            'rpc_observations': observations, 'metadata_schema': schema, 'scope': policy['scope']}
