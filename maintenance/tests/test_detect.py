import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest


def test_real_http_transport_rejects_errors_ids_and_nulls():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            result = {'jsonrpc': '2.0', 'id': data['id'], 'result': 'ok'}
            if data['method'] == 'error': result['error'] = {'message': 'denied'}
            if data['method'] == 'id': result['id'] = -1
            if data['method'] == 'null': result['result'] = None
            body = json.dumps(result).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rpc = detect.RPC('http://127.0.0.1:' + str(server.server_port), timeout=1)
        assert rpc.call('ok', []) == 'ok'
        for method in ('error', 'id', 'null'):
            with pytest.raises(detect.RPCError): rpc.call(method, [])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

from maintenance import detect
from maintenance.store import Store


def h(n):
    return '0x' + format(n, '064x')


class Chain:
    def __init__(self):
        self.calls = []
        self.gap = None
    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'chain_getBlockHash': return h(params[0])
        if method == 'chain_getFinalizedHead': return h(5)
        n = int(params[-1], 16)
        if n == self.gap: raise detect.RPCError('archive gap')
        if method == 'chain_getHeader':
            return {'number': hex(n), 'parentHash': h(n-1), 'digest': {'logs': ['0x08'] if n in (2,4) else []}}
        if method == 'state_getRuntimeVersion': return {'specVersion': 9 if n < 4 else 8, 'specName': 'test'}
        if method == 'state_getStorageHash': return h(100 + (0 if n < 2 else 1 if n < 4 else 2))
        if method == 'state_getMetadata': return '0x6d657461' + format(n, '02x')
        raise AssertionError(method)


def test_missing_block_hash_never_queries_latest_or_moves_cursor(tmp_path):
    rpc = Chain()
    with Store(tmp_path / 'db') as db:
        detector = detect.Detector(rpc, db, h(0))
        detector.initialize(1, h(1))
        original = rpc.call
        def call(method, params):
            if method == 'chain_getBlockHash' and params == [2]: return None
            if method == 'chain_getHeader' and params == [None]:
                return {'number': '0x2', 'parentHash': h(1), 'digest': {'logs': []}}
            return original(method, params)
        rpc.call = call
        with pytest.raises(detect.RPCError): detector.scan(1)
        assert db.cursor(h(0))['number'] == 1


@pytest.mark.parametrize('fault', ['genesis', 'cursor', 'gap', 'parent', 'finalized'])
def test_provider_failures_preserve_accepted_prefix(tmp_path, fault):
    rpc = Chain()
    with Store(tmp_path / 'db') as db:
        detector = detect.Detector(rpc, db, h(0))
        detector.initialize(1, h(1))
        original = rpc.call
        def call(method, params):
            if fault == 'genesis' and method == 'chain_getBlockHash' and params == [0]: return h(999)
            if fault == 'cursor' and method == 'chain_getBlockHash' and params == [1]: return h(999)
            if fault == 'gap' and method == 'state_getMetadata' and params == [h(2)]: return None
            if fault == 'finalized' and method == 'chain_getBlockHash' and params == [5]: return h(999)
            result = original(method, params)
            if fault == 'parent' and method == 'chain_getHeader' and params == [h(2)]: result['parentHash'] = h(999)
            return result
        rpc.call = call
        with pytest.raises((ValueError, detect.RPCError)): detector.scan(5)
        assert db.cursor(h(0))['number'] == 1
        assert db.jobs(h(0)) == []


@pytest.mark.parametrize('logs', [['0x0800'], ['0xzz'], '0x08', ['0x']])
def test_malformed_digest_blocks_scan(tmp_path, logs):
    rpc = Chain()
    with Store(tmp_path / 'db') as db:
        detector = detect.Detector(rpc, db, h(0))
        detector.initialize(1, h(1))
        original = rpc.call
        def call(method, params):
            result = original(method, params)
            if method == 'chain_getHeader' and params == [h(2)]: result['digest']['logs'] = logs
            return result
        rpc.call = call
        with pytest.raises(detect.RPCError): detector.scan(1)
        assert db.cursor(h(0))['number'] == 1


def test_evidence_pin_fetches_code_only_on_explicit_worker_request(tmp_path):
    import hashlib
    rpc = Chain()
    original = rpc.call
    code = '0x0061736d'
    code_hash = '0x' + hashlib.blake2b(bytes.fromhex(code[2:]), digest_size=32).hexdigest()
    def call(method, params):
        if method == 'state_getStorage': return code
        if method == 'state_getStorageHash': return code_hash
        return original(method, params)
    rpc.call = call
    with Store(tmp_path / 'db') as db:
        detector = detect.Detector(rpc, db, h(0))
        pin = detector.evidence_pin(h(2))
        assert pin['code'] == code
        assert pin['runtime_version']['specVersion'] == 9
        assert pin['block_number'] == 2
        assert pin['genesis_hash'] == h(0)
        assert pin['code_hash'] == code_hash


def test_archive_gap_resumes_after_last_accepted_block(tmp_path):
    rpc = Chain()
    path = tmp_path / 'db'
    with Store(path) as db:
        detector = detect.Detector(rpc, db, h(0))
        detector.initialize(1, h(1))
        rpc.gap = 4
        with pytest.raises(detect.RPCError): detector.scan(4)
        assert db.cursor(h(0))['number'] == 3
        assert len(db.jobs(h(0))) == 1
    rpc.gap = None
    with Store(path) as db:
        result = detect.Detector(rpc, db, h(0)).scan(4)
        assert result['scanned'] == 2
        assert [j['number'] for j in db.jobs(h(0))] == [2, 4]


def test_bounded_finalized_scan_catches_same_spec_and_rollback(tmp_path):
    rpc = Chain()
    with Store(tmp_path / 'db') as db:
        detector = detect.Detector(rpc, db, h(0))
        with pytest.raises(ValueError, match='baseline'): detector.scan(2)
        detector.initialize(1, h(1))
        assert detector.scan(2)['scanned'] == 2
        assert db.cursor(h(0))['number'] == 3
        assert detector.scan(2)['scanned'] == 2
        jobs = db.jobs(h(0))
        assert [j['number'] for j in jobs] == [2,4]
        assert jobs[0]['evidence']['same_spec'] is True
        assert jobs[1]['evidence']['rollback'] is True
        assert jobs[0]['evidence']['parent']['block_hash'] == h(1)
        assert jobs[0]['evidence']['current']['block_hash'] == h(2)
        assert detector.scan(2)['scanned'] == 0
        assert not any(m == 'state_getStorage' for m,p in rpc.calls)
        assert len([m for m,p in rpc.calls if m == 'state_getRuntimeVersion']) == 5
