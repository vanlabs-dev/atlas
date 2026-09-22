"""Batch immutable finalized header reads; preserve Detector's per-block checks."""
import json
import urllib.request
from .detect import RPC, RPCError


def decode_batch(body, ids):
    records = json.loads(body)
    if not isinstance(records, list) or len(records) != len(ids):
        raise ValueError('incomplete RPC batch')
    by_id = {}
    for item in records:
        if (not isinstance(item, dict) or item.get('jsonrpc') != '2.0' or
            item.get('id') not in ids or item['id'] in by_id or
            'error' in item or item.get('result') is None):
            raise ValueError('invalid/error/null batch result')
        by_id[item['id']] = item['result']
    return [by_id[i] for i in ids]


class BatchRPC(RPC):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache = {}

    def batch(self, requests):
        if not requests or len(requests) > 100:
            raise ValueError('batch must contain 1..100 requests')
        ids = list(range(self.sequence + 1, self.sequence + 1 + len(requests)))
        self.sequence = ids[-1]
        payload = [{'jsonrpc':'2.0', 'id':i, 'method':method, 'params':params}
                   for i, (method, params) in zip(ids, requests)]
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise ValueError('batch response exceeds bound')
            return decode_batch(body, ids)
        except Exception as exc:
            raise RPCError('RPC batch failed (' + type(exc).__name__ + ')') from None

    def prime_range(self, first, last):
        if first < 0 or last < first or last-first >= 100:
            raise ValueError('invalid preload range')
        hashes = self.batch([('chain_getBlockHash', [n]) for n in range(first, last+1)])
        headers = self.batch([('chain_getHeader', [h]) for h in hashes])
        fresh = {}
        for n, h, header in zip(range(first, last+1), hashes, headers):
            if not isinstance(h, str) or len(h) != 66 or int(header['number'],16) != n:
                raise ValueError('inconsistent preload range')
            fresh[('chain_getBlockHash', (n,))] = h
            fresh[('chain_getHeader', (h,))] = header
        self.cache = fresh

    def call(self, method, params):
        key = (method, tuple(params))
        if key in self.cache:
            return self.cache[key]
        return super().call(method, params)


def scan_fast(detector, *, max_blocks=1000, batch_size=50):
    if not 1 <= batch_size <= 100 or not 1 <= max_blocks <= 10000:
        raise ValueError('invalid scan bounds')
    rpc = detector.rpc
    cursor = detector.store.cursor(detector.genesis)
    if cursor is None:
        raise ValueError('explicit pinned baseline required')
    head = rpc.call('chain_getFinalizedHead', [])
    target = int(rpc.call('chain_getHeader', [head])['number'], 16)
    end = min(target, cursor['number'] + max_blocks)
    cached = {}
    try:
        for first in range(cursor['number']+1, end+1, batch_size):
            rpc.prime_range(first, min(end, first+batch_size-1))
            cached.update(rpc.cache)
        rpc.cache = cached
        # Only the canonical detector commits; prefetch itself changes no cursor.
        return detector.scan(max_blocks=max(1, end-cursor['number']))
    finally:
        rpc.cache = {}
