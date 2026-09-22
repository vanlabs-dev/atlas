import pytest
from maintenance.worker import sha256,canonical,verify_manifest


def test_trusted_report_is_bound_to_review_manifest(tmp_path):
    from maintenance.pipeline import attach_report
    proposal={'edits':[],'manifest':{},'before_files':{},'manifest_sha256':sha256(canonical({}))}
    attach_report(tmp_path,proposal,'docs/runtime-upgrades/1-abcd.md','audit evidence')
    assert verify_manifest(proposal)==proposal['manifest']
    assert proposal['before_files']['docs/runtime-upgrades/1-abcd.md']['content'] is None
    assert (tmp_path/'docs/runtime-upgrades/1-abcd.md').read_text()=='audit evidence'
    with pytest.raises(ValueError):attach_report(tmp_path,proposal,'docs/runtime-upgrades/1-abcd.md','overwrite')
