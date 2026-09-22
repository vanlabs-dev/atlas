import pytest
from maintenance.detect import Detector,RPCError
from maintenance.store import Store
from maintenance.tests.test_detect import Chain,h


@pytest.mark.parametrize('log',['0x 08','0x09','0x04','0x0004','0x000100','0x0841','0x06415552412001'])
def test_malformed_digest_never_advances_cursor(log):
    rpc=Chain();original=rpc.call
    def call(method,params):
        value=original(method,params)
        if method=='chain_getHeader' and params==[h(2)]:
            value={**value,'digest':{'logs':[log]}}
        return value
    rpc.call=call
    with Store(':memory:') as store:
        detector=Detector(rpc,store,h(0));detector.initialize(1,h(1))
        with pytest.raises(RPCError):detector.scan(1)
        assert store.cursor(h(0))['number']==1
        assert store.jobs(h(0))==[]


@pytest.mark.parametrize('log',['0x08','0x0000','0x04415552410400','0x0641555241200000000000000000'])
def test_complete_digest_items_decode(log):
    from maintenance.detect import decode_digest_item
    assert decode_digest_item(log)==bytes.fromhex(log[2:])
