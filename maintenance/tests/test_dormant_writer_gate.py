"""A dormant installed writer must not escape deployment quiescence."""
import pytest
from maintenance.deploy import SystemdWindow, DeployBlocked


@pytest.mark.parametrize('fault', ['timer_enabled','timer_active','service_active','service_job'])
def test_dormant_chain_poller_blocks_before_mutation(monkeypatch, fault):
    def state(self,user,unit):
        row={'LoadState':'loaded','ActiveState':'inactive','UnitFileState':'disabled','Job':''}
        if user and unit == 'atlas-poll-chain-head.timer':
            if fault=='timer_enabled':row['UnitFileState']='enabled'
            if fault=='timer_active':row['ActiveState']='active'
        if user and unit == 'atlas-poll-chain-head.service':
            if fault=='service_active':row['ActiveState']='active'
            if fault=='service_job':row['Job']='123'
        return row
    monkeypatch.setattr(SystemdWindow,'_state',state)
    with pytest.raises(DeployBlocked,match='unmanaged'):
        SystemdWindow()._system_gate()


def test_absent_dormant_poller_is_allowed(monkeypatch):
    monkeypatch.setattr(SystemdWindow,'_state',lambda self,user,unit:
        {'LoadState':'not-found','ActiveState':'inactive','UnitFileState':'','Job':''} if user else
        {'LoadState':'loaded','ActiveState':'inactive','UnitFileState':'disabled','Job':''})
    SystemdWindow()._system_gate()
