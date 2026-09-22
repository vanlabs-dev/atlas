def test_metadata_projection_preserves_all_changes_without_repeating_unchanged_docs():
    from maintenance.metadata import compact_comparison
    before={'pallets':[{'name':'P','storage':{'items':[{'name':'Flag','default':'0x00','docs':['same']}]}}], 'types':{'types':[{'id':1,'type':{'def':{'primitive':'u8'},'docs':['same']}}]}}
    after={'pallets':[{'name':'P','storage':{'items':[{'name':'Flag','default':'0x01','docs':['same']}]}}], 'types':{'types':[{'id':1,'type':{'def':{'primitive':'u16'},'docs':['same']}}]}}
    result=compact_comparison(before,after)
    assert len(result['changes'])==2
    assert any(v['before']=='0x00' and v['after']=='0x01' for v in result['changes'])
    assert any(v['before']=='u8' and v['after']=='u16' for v in result['changes'])
    assert 'same' not in str(result['changes'])
    assert result['changed_pallets']==['P']
