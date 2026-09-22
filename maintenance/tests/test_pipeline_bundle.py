import pytest


def packet(old,new,label):
    return {'status':'ready','complete':True,'blocked_reasons':[], 'chunks':[{'id':'x:0','path':'x','text':label,'sha256':'d'}], 'chunk_ids':['x:0'], 'upstream_paths':['x'], 'deployments':{'old':{'code_hash':old},'new':{'code_hash':new}}, 'metadata':{'changes':[label]},'atlas_inventory':{'commit':'same'},'source_commits':{'old':old,'new':new},'provenance_level':'publisher'}


def test_bundle_keeps_intermediate_reverted_changes():
    from maintenance.pipeline import combine_packets
    result=combine_packets([packet('a','b','add'),packet('b','a','revert')])
    assert [c['text'] for c in result['chunks']]==['add','revert']
    assert len(set(result['chunk_ids']))==2
    assert result['upstream_paths']==['x']
    assert result['deployments']['old']['code_hash']==result['deployments']['new']['code_hash']
    assert len(result['audit_transitions'])==2


def test_bundle_rejects_a_gap_in_runtime_history():
    from maintenance.pipeline import combine_packets
    with pytest.raises(ValueError,match='contiguous'):
        combine_packets([packet('a','b','add'),packet('c','d','missing')])
