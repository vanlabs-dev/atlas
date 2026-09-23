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


def _rebind_repo(tmp_path):
    import subprocess
    repo=tmp_path/'repo';repo.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
    git('init','-b','main');git('config','user.name','Test');git('config','user.email','test@example.invalid')
    (repo/'a').write_text('1');git('add','a');git('commit','-m','one')
    return repo,git


def _rebind_pipeline(tmp_path,repo,commit,rebuilt):
    import json
    from maintenance.pipeline import Pipeline
    p=Pipeline.__new__(Pipeline)
    p.repo=repo;p.root=tmp_path/'job';p.root.mkdir();p.job={'number':1}
    (p.root/'model-packet.json').write_text(json.dumps({'atlas_inventory':{'commit':commit}}))
    calls=[]
    def evidence(job):
        calls.append(job)
        (p.root/'model-packet.json').write_text(json.dumps({'atlas_inventory':{'commit':rebuilt}}))
        return {'model_packet_sha256':'f'*64}
    p.evidence=evidence
    return p,calls


def test_rebind_keeps_current_evidence(tmp_path):
    repo,git=_rebind_repo(tmp_path)
    head=git('rev-parse','HEAD')
    p,calls=_rebind_pipeline(tmp_path,repo,head,head)
    packet,rebound=p.rebind_evidence(head)
    assert rebound is None and calls==[]
    assert packet['atlas_inventory']['commit']==head


def test_rebind_rebuilds_evidence_after_fast_forward(tmp_path):
    repo,git=_rebind_repo(tmp_path)
    old=git('rev-parse','HEAD')
    (repo/'a').write_text('2');git('commit','-am','two')
    new=git('rev-parse','HEAD')
    p,calls=_rebind_pipeline(tmp_path,repo,old,new)
    packet,rebound=p.rebind_evidence(new)
    assert len(calls)==1
    assert rebound=={'from':old,'to':new,'model_packet_sha256':'f'*64}
    assert packet['atlas_inventory']['commit']==new


@pytest.mark.parametrize('case',['diverged','unknown','missing'])
def test_rebind_refuses_non_fast_forward(tmp_path,case):
    repo,git=_rebind_repo(tmp_path)
    base=git('rev-parse','HEAD')
    (repo/'a').write_text('2');git('commit','-am','two');head=git('rev-parse','HEAD')
    git('checkout','-q','-b','side',base);(repo/'a').write_text('3');git('commit','-am','side')
    side=git('rev-parse','HEAD');git('checkout','-q','main')
    collected={'diverged':side,'unknown':'0'*40,'missing':None}[case]
    p,calls=_rebind_pipeline(tmp_path,repo,collected,head)
    with pytest.raises(ValueError):
        p.rebind_evidence(head)
    assert calls==[]


def test_rebind_refuses_rebuild_that_misses_baseline(tmp_path):
    repo,git=_rebind_repo(tmp_path)
    old=git('rev-parse','HEAD')
    (repo/'a').write_text('2');git('commit','-am','two');new=git('rev-parse','HEAD')
    p,calls=_rebind_pipeline(tmp_path,repo,old,old)
    with pytest.raises(ValueError,match='rebuilt'):
        p.rebind_evidence(new)
