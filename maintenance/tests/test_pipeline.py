import pytest


def test_materialized_packet_rejects_partial_source_coverage(tmp_path):
    from maintenance.pipeline import model_packet
    packet={'status':'ready','complete':True,'source_diff':{'changed_paths':['a.rs'],'old_commit':'a'*40,'new_commit':'b'*40},'deployments':{},'atlas_inventory':{}}
    with pytest.raises(ValueError):model_packet(packet,tmp_path,tmp_path)


def test_pipeline_config_never_treats_empty_acceptance_as_pass(tmp_path):
    from maintenance.pipeline import acceptance_commands
    with pytest.raises(ValueError):acceptance_commands([],tmp_path)


def test_candidate_checkout_has_no_push_remote_or_production_state(tmp_path):
    from maintenance.pipeline import clone_candidate
    import subprocess
    src=tmp_path/'src';src.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(src),*args],stderr=subprocess.DEVNULL,text=True).strip()
    git('init','-b','main');git('config','user.name','Test');git('config','user.email','test@example.invalid')
    (src/'README.md').write_text('source')
    git('add','README.md');git('commit','-m','initial')
    (src/'.env').write_text('private')
    dst=tmp_path/'candidate'
    clone_candidate(src,dst,git('rev-parse','HEAD'))
    assert not (dst/'.env').exists()
    assert subprocess.check_output(['git','-C',str(dst),'remote'],text=True).strip()==''
