"""Finalized per-block runtime digest detector (no endpoint-spec inference).

Detector(rpc, store, genesis): rpc exposes call(method, params).
initialize(number, block_hash) requires an operator-selected pinned baseline.
scan(max_blocks=100) resumes after the durable cursor; returns progress dict.
An update is recorded at the block whose post-state changes runtime; execution
under the new runtime begins at its child. Metadata/code-hash/runtime reads
are pinned to parent and update block. No WASM bytes are downloaded.
"""
import hashlib

FINNEY_GENESIS = '0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03'
CODE_KEY = '0x3a636f6465'


class RPCError(RuntimeError):
    pass


class RPC:
    """Bounded stdlib JSON-RPC transport; no retries or credential logging.

    timeout bounds network operations; max_response_bytes bounds each response.
    Null block/runtime results block cursor advancement. Explicit raw storage
    null is preserved for metadata-default interpretation; RPC errors still fail.
    """
    def __init__(self, url, timeout=20, max_response_bytes=32 * 1024 * 1024):
        from urllib.parse import urlsplit
        if urlsplit(url).scheme not in ('http', 'https') or timeout <= 0 or max_response_bytes <= 0:
            raise ValueError('invalid RPC transport bounds/URL')
        self.url, self.timeout, self.max_response_bytes = url, timeout, max_response_bytes
        self.sequence = 0

    def call(self, method, params):
        import json
        import urllib.request
        self.sequence += 1
        request = urllib.request.Request(self.url, data=json.dumps(
            {'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise RPCError('RPC response exceeds bound')
            data = json.loads(body)
            if (not isinstance(data, dict) or data.get('jsonrpc') != '2.0'
                    or data.get('id') != self.sequence or 'error' in data or 'result' not in data
                    or (data['result'] is None and method != 'state_getStorage')):
                raise RPCError('invalid/error/null RPC response: ' + method)
            return data['result']
        except RPCError:
            raise
        except Exception as exc:
            raise RPCError('RPC transport failed: ' + method + ' (' + type(exc).__name__ + ')') from None


def decode_digest_item(log):
    """Validate complete canonical SCALE DigestItem, including vector length."""
    import re
    if not isinstance(log,str) or re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+',log) is None:
        raise RPCError('malformed digest hex')
    raw=bytes.fromhex(log[2:])
    if raw==b'\x08':return raw
    if raw[0] not in (0,4,5,6):raise RPCError('unknown/malformed digest variant')
    offset=1 if raw[0]==0 else 5
    if len(raw)<=offset:raise RPCError('truncated digest payload')
    first=raw[offset];mode=first & 3
    width=(1,2,4,1+(first >> 2)+4)[mode]
    if len(raw)<offset+width:raise RPCError('truncated SCALE vector length')
    encoded=raw[offset:offset+width]
    length=(int.from_bytes(encoded,'little') >> 2) if mode<3 else int.from_bytes(encoded[1:],'little')
    minimum=(0,64,16384,1073741824)[mode]
    if length<minimum or (mode==3 and encoded[-1]==0) or len(raw)!=offset+width+length:
        raise RPCError('noncanonical or inconsistent SCALE vector length')
    return raw


class Detector:
    def __init__(self, rpc, store, genesis=FINNEY_GENESIS):
        self.rpc, self.store, self.genesis = rpc, store, genesis

    def _identity(self):
        if self.rpc.call('chain_getBlockHash', [0]) != self.genesis:
            raise ValueError('wrong genesis')

    def _header(self, block_hash):
        if not isinstance(block_hash, str) or len(block_hash) != 66 or not block_hash.startswith('0x'):
            raise RPCError('missing or malformed block hash')
        header = self.rpc.call('chain_getHeader', [block_hash])
        if not header:
            raise RPCError('missing archive header')
        return header

    def snapshot(self, block_hash):
        """Pinned evidence dictionary; metadata hex retained for evidence worker."""
        runtime = self.rpc.call('state_getRuntimeVersion', [block_hash])
        code_hash = self.rpc.call('state_getStorageHash', [CODE_KEY, block_hash])
        metadata = self.rpc.call('state_getMetadata', [block_hash])
        if not runtime or not code_hash or not metadata:
            raise RPCError('missing archive runtime/code/metadata')
        return {'block_hash': block_hash, 'runtime': runtime, 'code_hash': code_hash,
                'metadata': metadata, 'metadata_sha256': hashlib.sha256(bytes.fromhex(metadata[2:])).hexdigest()}

    def evidence_pin(self, block_hash):
        """Explicit worker-only full pin accepted by evidence.build_evidence.

        Downloads WASM once for this pin, never called by the scanner.
        """
        self._identity()
        header = self._header(block_hash)
        pin = self.snapshot(block_hash)
        code = self.rpc.call('state_getStorage', [CODE_KEY, block_hash])
        return {'genesis_hash': self.genesis, 'block_hash': block_hash,
                'block_number': int(header['number'], 16),
                'runtime_version': pin['runtime'], 'metadata': pin['metadata'],
                'code_hash': pin['code_hash'], 'code': code}

    def initialize(self, number, block_hash):
        self._identity()
        head = self.rpc.call('chain_getFinalizedHead', [])
        if number < 0 or number > int(self._header(head)['number'], 16):
            raise ValueError('baseline must be finalized')
        if self.rpc.call('chain_getBlockHash', [number]) != block_hash:
            raise ValueError('baseline pin mismatch')
        if int(self._header(block_hash)['number'], 16) != number:
            raise ValueError('baseline header mismatch')
        self.store.initialize(self.genesis, number, block_hash, self.snapshot(block_hash))

    def scan(self, max_blocks=100):
        if not 1 <= max_blocks <= 10000:
            raise ValueError('max_blocks must be 1..10000')
        self._identity()
        cursor = self.store.cursor(self.genesis)
        if cursor is None:
            raise ValueError('explicit pinned baseline required')
        head = self.rpc.call('chain_getFinalizedHead', [])
        final = int(self._header(head)['number'], 16)
        if self.rpc.call('chain_getBlockHash', [final]) != head:
            raise ValueError('provider disagrees with finalized head')
        if final < cursor['number'] or self.rpc.call('chain_getBlockHash', [cursor['number']]) != cursor['hash']:
            raise ValueError('provider disagrees with finalized cursor')
        count = 0
        for number in range(cursor['number'] + 1, min(final, cursor['number'] + max_blocks) + 1):
            block_hash = self.rpc.call('chain_getBlockHash', [number])
            header = self._header(block_hash)
            if int(header['number'], 16) != number or header['parentHash'] != cursor['hash']:
                raise ValueError('noncontiguous finalized header')
            event = None
            logs = header['digest']['logs']
            if not isinstance(logs, list):
                raise RPCError('malformed digest logs')
            decoded=[decode_digest_item(log) for log in logs]
            if b'\x08' in decoded:
                parent, current = self.snapshot(cursor['hash']), self.snapshot(block_hash)
                before, after = parent['runtime']['specVersion'], current['runtime']['specVersion']
                event = {'genesis': self.genesis, 'activation_number': number,
                         'activation_hash': block_hash, 'code_hash': current['code_hash'],
                         'parent': parent, 'current': current,
                         'same_spec': before == after, 'rollback': after < before}
            self.store.accept_block(self.genesis, number, block_hash, cursor['hash'], event)
            cursor = {'number': number, 'hash': block_hash}
            count += 1
        return {'scanned': count, 'cursor': cursor, 'finalized_number': final,
                'finalized_hash': head, 'remaining': final - cursor['number']}
