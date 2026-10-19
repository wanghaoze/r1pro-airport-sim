from types import SimpleNamespace
import time,numpy as np,pytest
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.vla.contact_escape import RuntimeEscapeAdapter,pair_key


class CanonicalStageReached(Exception):pass


@pytest.mark.parametrize('mutate',['none','arm_ulp','base_ulp'])
def test_adapter_matches_real_Runtime_tick_float32_canonicalization_bitexact(mutate):
    r=Runtime.__new__(Runtime);r.cfg=Config();r.steps=0;r.wall_start=time.monotonic()
    r.d=SimpleNamespace(time=0.);r.check_retained_contact=lambda:None
    yaw0=.0408254457119768;start=np.array([0.,0.,2.517650842666626])
    r.m=SimpleNamespace(body_pos=np.zeros((1,3)),body_quat=np.array([[np.cos(yaw0/2),0.,0.,np.sin(yaw0/2)]]),body=lambda _:SimpleNamespace(id=0))
    r.sim=SimpleNamespace(base_target=np.array([0.,0.,start[2]-yaw0]),target=np.arange(16,dtype=float)*.0123456789)
    r.sim.base_state=lambda:np.r_[r.sim.base_target[:2],r.sim.base_target[2]+yaw0]
    r.sim.state=lambda:r.sim.target.copy()
    real_tick=Runtime.tick;canonical_calls=[]
    def observation():
        assert r.sim.target.dtype==r.sim.base_target.dtype==np.float32
        canonical_calls.append(r.sim.base_target.copy())
        raise CanonicalStageReached
    r.observation=observation
    def tick():
        # Invoke the actual production tick through its canonicalization stage.
        # The remaining physics/guards are mocked; no simulation success claim.
        with pytest.raises(CanonicalStageReached):real_tick(r)
        r.d.time+=.05;r.steps+=1
        if mutate=='arm_ulp':r.sim.target[0]=np.nextafter(r.sim.target[0],np.float32(1))
        if mutate=='base_ulp':r.sim.base_target[2]=np.nextafter(r.sim.base_target[2],np.float32(4))
    r.tick=tick
    adapter=RuntimeEscapeAdapter.__new__(RuntimeEscapeAdapter);adapter.r=r;adapter.margin=.001
    adapter.original={pair_key('robot','table'):-.0002};adapter.start=start;adapter.reference=r.sim.target.copy();adapter.measured_tracking=True
    adapter.screen=lambda _: {'source':'planning_shadow','status':'screened'}
    adapter.distances=lambda _: {pair_key('robot','table'):-.0002+float(r.sim.base_target[0])}
    audit={}
    if mutate!='none':
        with pytest.raises(ValueError,match='fixed_reference_changed'):adapter.execute(start+np.array([.005,0.,0.]),audit=audit)
        assert audit['status']=='private_prefix_rejected' and audit['failed_tick']==1
    else:
        adapter.execute(start+np.array([.005,0.,0.]),audit=audit)
        assert len(canonical_calls)==20
        canonical=audit['reference_canonicalization']
        assert canonical['canonical_local_yaw_reference']==float(np.float32(start[2]-yaw0))
        assert canonical['pre_local_yaw_reference']!=canonical['canonical_local_yaw_reference']
        assert canonical['actual_joint_dtype']==canonical['actual_base_dtype']=='float32'

