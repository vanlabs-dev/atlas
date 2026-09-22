import json
import pytest


def test_batch_response_reorders_ids_and_blocks_missing():
    from maintenance.fastscan import decode_batch
    body = json.dumps([{'jsonrpc':'2.0','id':2,'result':'b'}, {'jsonrpc':'2.0','id':1,'result':'a'}]).encode()
    assert decode_batch(body, [1,2]) == ['a','b']
    with pytest.raises(ValueError):
        decode_batch(body, [1,2,3])
    with pytest.raises(ValueError):
        decode_batch(json.dumps([{'jsonrpc':'2.0','id':1,'result':None}]).encode(), [1])


def test_batch_prime_does_not_cache_partial_header_range():
    from maintenance.fastscan import BatchRPC
    rpc = BatchRPC('https://example.invalid')
    calls=[]
    def batch(requests):
        calls.append(requests)
        if len(calls)==1:return ['0x'+'a'*64, '0x'+'b'*64]
        raise ValueError('archive gap')
    rpc.batch=batch
    with pytest.raises(ValueError):rpc.prime_range(1,2)
    assert rpc.cache == {}


def test_fast_scan_validates_one_contiguous_prefetched_window():
    from maintenance.fastscan import scan_fast
    class Store:
        def cursor(self,g):return {'number':0,'hash':'h0'}
    class RPC:
        cache={}
        def call(self,m,p):return 'h120' if m=='chain_getFinalizedHead' else {'number':'0x78'}
        def prime_range(self,a,b):self.cache={('block',n):n for n in range(a,b+1)}
    class Detector:
        store=Store();rpc=RPC();genesis='g';calls=0
        def scan(self,max_blocks):
            self.calls+=1
            assert len(self.rpc.cache)==120
            return {'scanned':max_blocks,'cursor':{'number':max_blocks},'remaining':120-max_blocks}
    d=Detector()
    assert scan_fast(d,max_blocks=120)['scanned']==120
    assert d.calls==1
    assert d.rpc.cache=={}
