"""Trusted, read-only acceptance receipts; never accept model-written claims.

Runtime dependency: xxhash>=3 (installed in the dedicated maintenance venv).
The caller must bind decoded metadata to the supplied block hashes using the
existing evidence collector. These reads prove observations, not migration
completion. Operator-selected proof obligations are a separate mandatory gate.
"""
import hashlib
import json
import re
from pathlib import Path


def storage_key(prefix, name):
    import xxhash
    def twox(text):
        return b''.join(xxhash.xxh64(text.encode(), seed=i).intdigest().to_bytes(8, 'little') for i in (0, 1))
    return '0x' + (twox(prefix) + twox(name)).hex()


def _hex(value):
    if isinstance(value, str) and value.startswith('0x'):
        bytes.fromhex(value[2:])
        return value.lower()
    if isinstance(value, str):
        # scalecodec Bytes.process decodes UTF-8, falling back to 0x hex.
        return '0x' + value.encode('utf-8').hex()
    return '0x' + bytes(value).hex()


def _entries(metadata):
    types = {t['id']: t['type'] for t in metadata['types']['types']}
    def resolve(tid, stack=()):
        if tid in stack:
            return {'recursive': stack.index(tid)}
        def walk(value, key=''):
            if isinstance(value, dict):
                return {k: walk(v, k) for k, v in value.items() if k not in ('docs', 'documentation')}
            if isinstance(value, list):
                return [resolve(v, stack+(tid,)) if key == 'tuple' and isinstance(v, int) else walk(v, key) for v in value]
            if isinstance(value, int) and key in ('type', 'bitStoreType', 'bitOrderType'):
                return resolve(value, stack+(tid,))
            return value
        return walk(types[tid])
    entries = {}
    for pallet in metadata['pallets']:
        storage = pallet.get('storage')
        if not storage:
            continue
        for entry in storage['entries']:
            if 'Plain' in entry['type']:
                entries[pallet['name']+'.'+entry['name']] = {
                    'key': storage_key(storage['prefix'], entry['name']),
                    'definition': resolve(entry['type']['Plain']),
                    'default': _hex(entry['default']), 'modifier': entry['modifier']}
    return entries


def _block(value):
    if not isinstance(value, str) or not re.fullmatch('0x[0-9a-f]{64}', value):
        raise ValueError('explicit pinned block hash required')


def _read(rpc, key, block):
    value = rpc('state_getStorage', [key, block])
    if value is not None and (not isinstance(value, str) or len(value) > 2 + 2*1024*1024
                              or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', value)):
        raise ValueError('malformed storage response')
    return value.lower() if value is not None else None


def pinned_storage_checks(before, after, before_hash, after_hash, rpc, *, max_checks=256):
    """Observe changed/added/retired plain entries at BOTH explicit pins.

    Null remains raw null. Effective bytes use that snapshot's metadata default;
    retired entries have no effective metadata value, even if stale bytes remain.
    """
    _block(before_hash); _block(after_hash)
    old, new = _entries(before), _entries(after)
    changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
    if len(changed) > max_checks:
        raise ValueError('semantic storage check bound exceeded; cannot truncate')
    rows = []
    for name in changed:
        row = {'name': name}
        for side, entries, fallback, block in [('before', old, new, before_hash), ('after', new, old, after_hash)]:
            entry = entries.get(name)
            key = (entry or fallback[name])['key']
            raw = _read(rpc, key, block)
            row[side] = {'block_hash': block, 'key': key, 'raw': raw,
                         'metadata_present': entry is not None,
                         'effective': (raw if raw is not None else entry['default']) if entry else None,
                         'metadata': entry}
        rows.append(row)
    return {'passed': True, 'checks': rows, 'count': len(rows),
            'scope': 'plain storage observations, not migration/activation proof'}


def runtime468_storage_schema(metadata):
    """Allow only the audited SCALE layout; never guess encodings/hashers.

    Transparent one-field newtypes are accepted (NetUid/u16, TaoBalance/u64).
    This validator proves layout, not migration completion or runtime identity.
    """
    try:
        types = {t['id']: t['type'] for t in metadata['types']['types']}
        if len(types) != len(metadata['types']['types']):
            raise ValueError('duplicate metadata type')
        def shape(tid, seen=()):
            if tid in seen or len(seen) > 8:
                raise ValueError('recursive/oversized storage type')
            d = types[tid]['def']
            if len(d) != 1:
                raise ValueError('unknown type schema')
            if 'primitive' in d:
                return d['primitive']
            if 'sequence' in d:
                return 'Vec<' + shape(d['sequence']['type'], seen+(tid,)) + '>'
            if 'composite' in d and len(d['composite']['fields']) == 1:
                return shape(d['composite']['fields'][0]['type'], seen+(tid,))
            raise ValueError('unsupported storage type')
        pallets = [p for p in metadata['pallets'] if p['name'] == 'SubtensorModule']
        if len(pallets) != 1:
            raise ValueError('ambiguous/missing storage pallet')
        storage = pallets[0]['storage']
        if storage['prefix'] != 'SubtensorModule':
            raise ValueError('unexpected storage prefix')
        entries = {e['name']: e for e in storage['entries']}
        if len(entries) != len(storage['entries']):
            raise ValueError('duplicate storage entry')
        expected = {'HasMigrationRun': ('Vec<u8>', 'bool'), 'NetworksAdded': ('u16', 'bool'),
                    'SubnetTAO': ('u16', 'u64'), 'TotalStake': (None, 'u64'),
                    'BasketTradingEnabled': (None, 'bool')}
        result = {}
        for name, (keytype, valuetype) in expected.items():
            e = entries[name]
            t = e['type']
            if keytype is None:
                valid = set(t) == {'Plain'} and shape(t['Plain']) == valuetype
            else:
                valid = (set(t) == {'Map'} and set(t['Map']) == {'key', 'value', 'hashers'}
                         and t['Map']['hashers'] == ['Identity']
                         and shape(t['Map']['key']) == keytype and shape(t['Map']['value']) == valuetype)
            default = _hex(e['default'])
            if not valid or e['modifier'] != 'Default' or default != '0x' + '00'*(8 if valuetype == 'u64' else 1):
                raise ValueError('unsupported storage schema: ' + name)
            result[name] = {'key': storage_key(storage['prefix'], name), 'default': default,
                            'key_type': keytype, 'value_type': valuetype,
                            'hashers': ['Identity'] if keytype else [], 'metadata': e}
        return result
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('invalid storage metadata schema') from exc


def sum_live_subnet_tao(proof, rpc):
    """Fixed bounded operator: saturating u64 sum over actual live subnet values.

    Exhaustion means an EMPTY final page, not a short page. Every response is
    retained including false NetworksAdded entries and null/default values.
    No callbacks/expressions are accepted in the proof. No historical total is
    an input. This is a post-block invariant, not isolated migration replay.
    """
    from maintenance.metadata import decode_metadata
    block = proof['block_hash']
    _block(block)
    observations = []
    def call(method, params):
        value = rpc(method, params)
        observations.append({'method': method, 'params': params, 'result': value})
        return value
    schema = runtime468_storage_schema(decode_metadata(call('state_getMetadata', [block])))
    prefix = schema['NetworksAdded']['key']
    keys, start = [], None
    for _ in range(32):
        page = call('state_getKeysPaged', [prefix, 64, start, block])
        if (not isinstance(page, list) or len(page) > 64
                or any(not isinstance(k, str) or not re.fullmatch(re.escape(prefix)+'[0-9a-f]{4}', k) for k in page)
                or page != sorted(set(page)) or (start is not None and any(k <= start for k in page))):
            raise ValueError('invalid aggregate pagination: ordering/duplicates/size/key')
        if not page:
            break
        keys.extend(page)
        start = page[-1]
    else:
        raise ValueError('aggregate pagination not exhausted within bound')
    def read_many(wanted):
        values = {}
        for offset in range(0, len(wanted), 64):
            part = wanted[offset:offset+64]
            batch = call('state_queryStorageAt', [part, block])
            if (not isinstance(batch, list) or len(batch) != 1 or not isinstance(batch[0], dict)
                    or set(batch[0]) != {'block', 'changes'} or batch[0]['block'] != block):
                raise ValueError('aggregate batch block/schema mismatch')
            changes = batch[0]['changes']
            if (not isinstance(changes, list) or len(changes) != len(part)
                    or any(not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str) for row in changes)
                    or len({row[0] for row in changes}) != len(part)
                    or {row[0] for row in changes} != set(part)):
                raise ValueError('aggregate batch missing/duplicate/unexpected keys')
            values.update(changes)
        return values
    nets = read_many(keys)
    live, rows = [], []
    for key in keys:
        raw = nets[key]
        if raw not in (None, '0x00', '0x01'):
            raise ValueError('invalid NetworksAdded bool')
        effective = raw if raw is not None else schema['NetworksAdded']['default']
        row = {'netuid': int.from_bytes(bytes.fromhex(key[-4:]), 'little'),
               'networks_added_key': key, 'networks_added_raw': raw, 'networks_added_effective': effective}
        rows.append(row)
        if effective == '0x01':
            row['subnet_tao_key'] = schema['SubnetTAO']['key'] + key[-4:]
            live.append(row)
    stakes = read_many([r['subnet_tao_key'] for r in live])
    def u64(raw, name):
        effective = raw if raw is not None else schema[name]['default']
        if not isinstance(effective, str) or not re.fullmatch('0x[0-9a-fA-F]{16}', effective):
            raise ValueError('invalid aggregate u64 storage')
        return effective, int.from_bytes(bytes.fromhex(effective[2:]), 'little')
    for row in live:
        raw = stakes[row['subnet_tao_key']]
        effective, value = u64(raw, 'SubnetTAO')
        row.update(subnet_tao_raw=raw, subnet_tao_effective=effective, rao=value)
    totalraw = call('state_getStorage', [schema['TotalStake']['key'], block])
    effective, total = u64(totalraw, 'TotalStake')
    summed = min(sum(r['rao'] for r in live), 2**64-1)
    return {**proof, 'passed': total == summed, 'pagination_exhausted': True,
            'enumerated_keys': len(keys), 'live_network_count': len(live), 'rows': rows,
            'total_stake_raw': totalraw, 'total_stake_effective': effective, 'total_stake_rao': total,
            'sum_live_subnet_tao_rao': summed, 'metadata_schema': schema, 'rpc_observations': observations,
            'scope': 'first-execution child poststate invariant; not isolated migration replay'}


def activation_checks(changed_paths, requirements, trusted_proofs, rpc, *, max_reads=64):
    """Trusted policy inputs only, NEVER model/candidate JSON.

    requirements: {id, paths, required?, required_checks?, required_ops?}; exact
    changed-path intersection triggers an obligation, or required=True for an
    externally identified activation. Every required check must be present, with
    its required operation, and ALL rows for that obligation must pass. Optional
    check_id identifies conjunctive individual checks, not interchangeable claims.
    Storage proofs bind evidence, block_hash, key and exactly one expected_raw
    (including null) or expected_sha256. The only other operator is the fixed
    sum_live_subnet_tao_v1; it re-reads metadata, all pages and actual values.
    max_reads bounds proof count; each aggregate separately permits 32 pages of
    64 keys (including mandatory empty terminal page), and batches reads by 64.
    No file-name assertion can mark an obligation completed. Unknown changed
    migration/governance paths block pending explicit policy mapping. Unchanged
    migration files do not cause perpetual blocking.
    """
    if (not isinstance(requirements, list) or len(requirements) > 256
            or not isinstance(trusted_proofs, list) or type(max_reads) is not int or not 1 <= max_reads <= 256):
        raise ValueError('bounded requirement/proof lists required')
    ids = set()
    for requirement in requirements:
        if (not isinstance(requirement, dict) or not {'id', 'paths'} <= requirement.keys()
                or requirement.keys() - {'id', 'paths', 'required', 'required_checks', 'required_ops'}
                or not isinstance(requirement['id'], str) or not requirement['id'] or requirement['id'] in ids
                or type(requirement.get('required', False)) is not bool):
            raise ValueError('unknown/invalid requirement schema')
        ids.add(requirement['id'])
        for name in ('paths', 'required_checks'):
            values = requirement.get(name, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values) or len(values) != len(set(values)):
                raise ValueError('invalid requirement paths/checks')
        ops = requirement.get('required_ops', {})
        if (not isinstance(ops, dict) or not ops.keys() <= set(requirement.get('required_checks', []))
                or any(op not in ('storage_equals_v1', 'sum_live_subnet_tao_v1') for op in ops.values())):
            raise ValueError('unknown required operation')
    changed = set(changed_paths)
    required = {r['id'] for r in requirements if r.get('required') is True or changed.intersection(r['paths'])}
    mapped = {p for r in requirements for p in r['paths']}
    unmapped = sorted(p for p in changed - mapped if re.search(r'migrat|governance|sudo|scheduler', p, re.I))
    if len(trusted_proofs) > max_reads:
        raise ValueError('proof read bound exceeded')
    rows = []
    for proof in trusted_proofs:
        base = {'obligation', 'evidence', 'block_hash'}
        optional = {'activation_hash', 'op', 'check_id'}
        op = proof.get('op', 'storage_equals_v1') if isinstance(proof, dict) else None
        if op not in ('storage_equals_v1', 'sum_live_subnet_tao_v1'):
            raise ValueError('unknown trusted proof operation')
        allowed = base | optional
        if op == 'storage_equals_v1':
            allowed |= {'key', 'expected_raw', 'expected_sha256'}
        if not base <= proof.keys() or proof.keys() - allowed or not isinstance(proof['evidence'], str) or not proof['evidence']:
            raise ValueError('unknown/invalid trusted proof schema')
        if 'activation_hash' in proof:
            _block(proof['activation_hash'])
        if proof['obligation'] not in required:
            continue
        _block(proof['block_hash'])
        if proof.get('op') == 'sum_live_subnet_tao_v1':
            rows.append(sum_live_subnet_tao(proof, rpc))
            continue
        key = proof['key']
        if not re.fullmatch(r'0x(?:[0-9a-f]{2}){1,512}', key) or not proof.get('evidence'):
            raise ValueError('bounded key and evidence citation required')
        if ('expected_raw' in proof) == ('expected_sha256' in proof):
            raise ValueError('exactly one expected raw value or sha256 required')
        raw = _read(rpc, key, proof['block_hash'])
        digest = hashlib.sha256(bytes.fromhex(raw[2:])).hexdigest() if raw is not None else None
        passed = raw == proof['expected_raw'] if 'expected_raw' in proof else digest == proof['expected_sha256']
        if 'expected_sha256' in proof and not re.fullmatch('[0-9a-f]{64}', proof['expected_sha256']):
            raise ValueError('invalid expected sha256')
        rows.append({**proof, 'raw': raw, 'raw_sha256': digest, 'passed': passed})
    required_checks = {r['id']: set(r.get('required_checks', [])) for r in requirements}
    required_ops = {r['id']: r.get('required_ops', {}) for r in requirements}
    for row in rows:
        expected_op = required_ops[row['obligation']].get(row.get('check_id'))
        if expected_op is not None and row.get('op', 'storage_equals_v1') != expected_op:
            row['passed'] = False
            row['error'] = 'required operation mismatch; marker cannot establish invariant'
    verified = {obligation for obligation in required
                if any(r['obligation'] == obligation for r in rows)
                and all(r['passed'] for r in rows if r['obligation'] == obligation)
                and required_checks[obligation] <= {r.get('check_id') for r in rows if r['obligation'] == obligation}}
    missing = sorted(required - verified)
    return {'passed': not unmapped and not missing and all(r['passed'] for r in rows),
            'checks': rows, 'unverified': missing, 'unmapped_changed_paths': unmapped,
            'count': len(rows)}


# Fixed trusted selectors: do not infer contracts from suite labels.
CONTRACT_NODES = (
    'knowledge/tests/test_server.py::ServerTests::test_handshake_and_tools_list',
    'knowledge/tests/test_server.py::ServerTests::test_search_is_source_bound',
    'knowledge/tests/test_server.py::ServerTests::test_status_reports_run_and_states',
    'knowledge/tests/test_server.py::NotActivatedTests::test_staged_only_store_fails_closed',
    'repotrack/tests/test_server.py::ServerTests::test_handshake_and_tools_list',
    'repotrack/tests/test_server.py::ServerTests::test_search_carries_sha_and_path_provenance',
    'repotrack/tests/test_server.py::ServerTests::test_status_answers_freshness_fields',
    'livedata/tests/test_server.py::ServerTests::test_handshake_and_tools',
    'livedata/tests/test_server.py::ServerTests::test_chain_head_enactment_watch',
    'fleet/tests/test_fleet_server.py::ToolListTests::test_lists_the_read_only_tool_set',
    'fleet/tests/test_mining_server.py::TestToolContract::test_three_mining_tools_are_advertised',
    'fleet/tests/test_mining_server.py::TestToolContract::test_schemas_reject_unknown_arguments',
)


def _node_checks(root, nodes):
    from maintenance.sandbox import run_tests, TEST_VENV
    # Separate modules prevent the repository's legacy test module names colliding.
    groups = {}
    for node in nodes:
        groups.setdefault(node.split('::')[0], []).append(node)
    suites = [{'name': path, 'argv': [TEST_VENV+'/bin/python', '-m', 'pytest',
                '-p', 'no:cacheprovider', '--color=no', '-q', *selected]}
              for path, selected in groups.items()]
    receipt = run_tests(root, suites)
    count = sum(s['counts']['passed'] for s in receipt['suites'])
    return {**receipt, 'passed': receipt['passed'] and count == len(nodes),
            'count': count, 'nodes': list(nodes)}


def mcp_contract_checks(root):
    return _node_checks(root, CONTRACT_NODES)


BENCHMARK_NODES = (
    'knowledge/tests/test_benchmark.py::CmdScoreTests::test_green_run_exit_0_schema_valid_closure_stated',
    'knowledge/tests/test_benchmark.py::ScoringTests::test_unevidenced_exchange_blocks_without_attestation',
    'knowledge/tests/test_server.py::ReadOnlySurfaceTests::test_store_opened_read_only',
)


def _connect(db):
    import sqlite3
    return sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro', uri=True)


def _active(db):
    with _connect(db) as conn:
        return sorted(r[0] for r in conn.execute('SELECT DISTINCT run_id FROM units WHERE active=1'))


def staged_kb_checks(db, report, expected_active, expected_sources, cases):
    """Run deterministic retrieval against the *staged* run, with production FTS
    tokenization/ranking and payload schema. No activation, writes or synthetic
    Hermes conversations. This is retrieval acceptance, not an LLM-answer score.
    cases is trusted policy: query, expected_unit_ids, optional max_results<=10.
    expected_sources is the reviewed corpus filename -> sha256 manifest.
    """
    from maintenance.deploy import validate_report
    from knowledge.atlas_kb_server import KnowledgeStore, _TOKEN
    validate_report(report, db)
    if not expected_sources or not cases or len(cases) > 64:
        raise ValueError('nonempty bounded reviewed benchmark and corpus required')
    run = report['run_id']
    active_before = _active(db)
    rows = []
    with _connect(db) as conn:
        source_rows = conn.execute('SELECT filename,sha256 FROM sources WHERE run_id=?', (run,)).fetchall()
        sources = dict(source_rows)
        members = dict(conn.execute('SELECT DISTINCT source_file,source_sha256 FROM units WHERE run_id=?', (run,)))
        inactive = conn.execute('SELECT count(*) FROM units WHERE run_id=? AND active!=0', (run,)).fetchone()[0] == 0
        for case in cases:
            tokens = _TOKEN.findall(case['query'])[:12]
            limit = case.get('max_results', 10)
            if not tokens or type(limit) is not int or not 1 <= limit <= 10 or not case['expected_unit_ids']:
                raise ValueError('invalid retrieval benchmark case')
            query = ' OR '.join('"'+t+'"' for t in tokens)
            found = conn.execute('SELECT '+KnowledgeStore._UNIT_COLUMNS_QUALIFIED+
                ' FROM units u JOIN units_fts f ON f.rowid=u.id WHERE units_fts MATCH ? '
                'AND u.run_id=? ORDER BY bm25(units_fts) LIMIT ?', (query, run, limit)).fetchall()
            payloads = [KnowledgeStore._unit_payload(row) for row in found]
            matched = {p['unit_id'] for p in payloads}
            rows.append({'query': case['query'], 'expected_unit_ids': case['expected_unit_ids'],
                         'results': payloads, 'passed': set(case['expected_unit_ids']) <= matched})
    active_after = _active(db)
    membership = sources == expected_sources and members == expected_sources and len(source_rows) == len(sources)
    unchanged = active_before == active_after == sorted(expected_active) and run not in active_after
    return {'passed': membership and unchanged and inactive and all(r['passed'] for r in rows),
            'run_id': run, 'corpus_membership': membership, 'sources': sources,
            'active_before': active_before, 'active_after': active_after, 'active_unchanged': unchanged,
            'staged_inactive': inactive, 'benchmark': {'count': len(rows), 'checks': rows},
            'scope': 'deterministic staged retrieval; not a conversational answer benchmark'}


def staged_kb_validator(root, db, expected_active, expected_sources, cases):
    """deploy(..., staged_validation=callback). Inspect callback.receipt after use.

    Trusted callback must be mandatory in the parent deploy controller. Exceptions
    are retained as failed receipts rather than allowing activation.
    """
    def callback(report):
        try:
            receipt = staged_kb_checks(db, report, expected_active, expected_sources, cases)
            receipt['schema_tests'] = _node_checks(root, BENCHMARK_NODES)
            receipt['passed'] = receipt['passed'] and receipt['schema_tests']['passed'] and _active(db) == sorted(expected_active)
            callback.receipt = receipt
        except Exception as exc:
            callback.receipt = {'passed': False, 'error': str(exc)}
        return callback.receipt['passed'] is True
    callback.receipt = {'passed': False, 'error': 'not executed'}
    return callback


def live_acceptance(root, kb_db, repo_config, expected_head, expected_run):
    """Read-only real MCP dispatch/status probe (not client reconnection proof).

    Calls the deployed server implementations with an in-memory audit sink;
    unlike launching their stdio CLI this writes no tool-audit.jsonl. root must
    be the checkout containing this imported acceptance module.
    """
    import os
    import subprocess
    import sys
    root = Path(root).resolve()
    if root != Path(__file__).resolve().parents[1]:
        raise ValueError('run the acceptance module from the exact deployed root')
    if not re.fullmatch('[0-9a-f]{40}', expected_head) or not expected_run:
        raise ValueError('expected deployed commit and KB run required')
    sys.path.insert(0, str(root/'repotrack'))
    from knowledge import atlas_kb_server as kb
    from repotrack import atlas_repo_server as repo
    class MemoryAudit:
        def record(self, *args):
            pass
    audit = MemoryAudit()
    def probe(module, store, tool):
        reply = module.handle_message(store, audit, {'jsonrpc': '2.0', 'id': 1,
            'method': 'tools/call', 'params': {'name': tool, 'arguments': {}}})
        return reply['result']
    # No git optional refresh/index writes while computing live freshness.
    previous = os.environ.get('GIT_OPTIONAL_LOCKS')
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    try:
        revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, timeout=30)
        head = revision.stdout.strip() if revision.returncode == 0 else None
        status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1', '--untracked-files=all'],
                                capture_output=True, text=True, timeout=30)
        clean = status.returncode == 0 and not status.stdout.strip()
        knowledge = probe(kb, kb.KnowledgeStore(str(kb_db)), 'knowledge_status')
        code = probe(repo, repo.RepoStore(str(repo_config)), 'repo_status')
    finally:
        if previous is None:
            os.environ.pop('GIT_OPTIONAL_LOCKS', None)
        else:
            os.environ['GIT_OPTIONAL_LOCKS'] = previous
        sys.path.remove(str(root/'repotrack'))
    k = json.loads(knowledge['content'][0]['text'])
    r = json.loads(code['content'][0]['text'])
    return {'passed': clean and head == expected_head and k.get('active_run') == expected_run
            and k.get('status') == 'ok' and r.get('status') == 'ok',
            'head': head, 'checkout_clean': clean, 'expected_head': expected_head, 'expected_run': expected_run,
            'knowledge': knowledge, 'repo': code,
            'scope': 'current MCP server dispatch/status; no client reconnect attestation'}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['live'])
    for name in ('root', 'kb-db', 'repo-config', 'expected-head', 'expected-run'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = live_acceptance(args.root, args.kb_db, args.repo_config, args.expected_head, args.expected_run)
    except Exception as exc:
        receipt = {'passed': False, 'error': str(exc)}
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt['passed'] is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
