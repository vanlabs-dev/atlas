def test_metadata_diff_keeps_removed_item_and_default():
    from maintenance.metadata import compare_decoded
    before={'pallets':[{'name':'SubtensorModule','storage':{'items':[{'name':'Flag','modifier':'Default','default':'0x00'}]}}]}
    after={'pallets':[{'name':'SubtensorModule','storage':{'items':[]}}]}
    result=compare_decoded(before,after)
    assert result['changed_pallets']['SubtensorModule']['before']['storage']['items'][0]['default']=='0x00'
    assert result['changed_pallets']['SubtensorModule']['after']['storage']['items']==[]
    assert result['complete'] is True


def test_invalid_metadata_is_not_an_empty_success():
    from maintenance.metadata import decode_metadata
    import pytest
    with pytest.raises(ValueError):decode_metadata('0x0000')
