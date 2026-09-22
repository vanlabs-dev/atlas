import json
from pathlib import Path
from maintenance.store import Store


def test_notification_is_durable_and_deduplicated(tmp_path):
    from maintenance.atlas_maintenance import enqueue_notification
    with Store(tmp_path/'state.db') as store:
        job={'activation_hash':'0x'+'a'*64,'code_hash':'0x'+'b'*64,'number':42,
             'evidence':{'current':{'runtime':{'specVersion':999}}}}
        enqueue_notification(store,job,'detected',{})
        enqueue_notification(store,job,'detected',{})
        rows=store.db.execute('SELECT status,detail FROM maintenance_notifications').fetchall()
        assert len(rows)==1
        assert '42' in rows[0]['detail']


def test_status_reports_no_initialized_chain_without_guessing(tmp_path,capsys):
    from maintenance.atlas_maintenance import main
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'state_dir':str(tmp_path/'state'),'genesis':'test-genesis'}))
    assert main(['--config',str(config),'status'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['cursor'] is None
    assert result['jobs']==[]
