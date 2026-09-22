import fcntl,json


def test_status_remains_available_while_worker_holds_lock(tmp_path,capsys):
    from maintenance.atlas_maintenance import main
    state=tmp_path/'state';state.mkdir()
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'state_dir':str(state),'genesis':'0x'+'0'*64}))
    with (state/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert main(['--config',str(config),'status'])==0
    result=json.loads(capsys.readouterr().out)
    assert 'jobs' in result and 'progress' in result
    assert result.get('state')!='busy'
