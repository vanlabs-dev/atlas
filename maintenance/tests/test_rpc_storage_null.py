import io,json
import pytest
from maintenance.detect import RPC,RPCError


def test_explicit_null_storage_is_not_an_archive_gap(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":null}'))
    assert RPC('https://fixture.invalid').call('state_getStorage',['0x00','0x01']) is None


@pytest.mark.parametrize('method,payload',[
 ('state_getStorage',{'jsonrpc':'2.0','id':1}),
 ('chain_getBlockHash',{'jsonrpc':'2.0','id':1,'result':None}),
 ('state_getRuntimeVersion',{'jsonrpc':'2.0','id':1,'result':None}),
 ('state_getStorage',{'jsonrpc':'2.0','id':1,'error':{'message':'State already discarded'}})])
def test_missing_storage_result_and_archive_errors_still_fail(monkeypatch,method,payload):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RPCError):RPC('https://fixture.invalid').call(method,[])
