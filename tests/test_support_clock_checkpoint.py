"""Checkpoint/preview preservation of the opt-in retained-support integer clock."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from test_experiments import tiny_machine
from r1pro_teleop.experiments.checkpoint_tree import CheckpointTree

CLOCK_FIELDS = ('physics_step_count', 'physics_clock_origin_time',
                'physics_clock_timestep', 'retained_support_missing_step')


def clock_machine(tmp_path, label, *, enabled=True):
    m=tiny_machine(tmp_path,label);r=m.r
    r.cfg.retained_support_integer_clock_enabled=enabled
    r.cfg.fps=20;r.sim.nstep=5
    r.cfg.dump=lambda:{'primitive_seconds':3,'retained_support_integer_clock_enabled':enabled}
    r.physics_step_count=0;r.physics_clock_origin_time=float(r.d.time)
    r.physics_clock_timestep=float(r.m.opt.timestep)
    r.retained_support_missing_step=None
    return m


def step_physics(r, count):
    for _ in range(count):
        r.mj.mj_step(r.m,r.d);r.physics_step_count+=1


def test_checkpoint_keeps_active_grace_and_partial_tick_physics(tmp_path):
    a=clock_machine(tmp_path,'clock_a');b=clock_machine(tmp_path,'clock_b')
    try:
        step_physics(a.r,2)
        a.r.retained_support_missing_since=float(a.r.d.time)
        a.r.retained_support_missing_step=a.r.physics_step_count
        step_physics(a.r,5);a.r.steps=1  # seven completed physics steps, one control frame
        tree=CheckpointTree(a,tmp_path/'clock_cp');tree.plan(['settled'])
        cp=tree.save('settled',lambda _:True)
        CheckpointTree(b,tmp_path/'restored').restore(cp)
        for field in CLOCK_FIELDS:assert getattr(b.r,field)==getattr(a.r,field)
        assert b.r.retained_support_missing_since==a.r.retained_support_missing_since
        assert b.r.physics_step_count==7 and b.r.steps==1
        assert b.r.physics_step_count-b.r.retained_support_missing_step==5
        step_physics(a.r,1);step_physics(b.r,1)
        assert b.r.physics_step_count-b.r.retained_support_missing_step==6
        np.testing.assert_array_equal(a.r.d.qpos,b.r.d.qpos)
        np.testing.assert_array_equal(a.r.d.qvel,b.r.d.qvel)
        assert a.r.d.time==b.r.d.time
    finally:a.log.close();b.log.close()


@pytest.mark.parametrize('missing',CLOCK_FIELDS)
def test_enabled_checkpoint_missing_clock_field_rejected_before_mutation(tmp_path,missing):
    a=clock_machine(tmp_path,'old_a');b=clock_machine(tmp_path,'old_b')
    try:
        step_physics(a.r,2);a.r.retained_support_missing_since=float(a.r.d.time)
        a.r.retained_support_missing_step=2
        tree=CheckpointTree(a,tmp_path/'old_cp');tree.plan(['settled']);cp=tree.save('settled',lambda _:True)
        path=cp/'metadata.json';metadata=json.loads(path.read_text())
        del metadata['context']['runtime'][missing];path.write_text(json.dumps(metadata))
        before=b.r.d.time
        with pytest.raises(ValueError,match='checkpoint_integer_clock_context_missing'):
            CheckpointTree(b,tmp_path/'restore_old').restore(cp)
        assert b.r.d.time==before and b.r.physics_step_count==0
        assert not getattr(b,'checkpoint_restored',False)
    finally:a.log.close();b.log.close()


def test_disabled_legacy_checkpoint_preserves_float_timer_without_migration(tmp_path):
    a=clock_machine(tmp_path,'legacy_a',enabled=False);b=clock_machine(tmp_path,'legacy_b',enabled=False)
    try:
        a.r.retained_support_missing_since=12.345
        tree=CheckpointTree(a,tmp_path/'legacy_cp');tree.plan(['settled']);cp=tree.save('settled',lambda _:True)
        path=cp/'metadata.json';metadata=json.loads(path.read_text())
        for field in CLOCK_FIELDS:metadata['context']['runtime'].pop(field)
        path.write_text(json.dumps(metadata))
        CheckpointTree(b,tmp_path/'legacy_restore').restore(cp)
        assert b.r.retained_support_missing_since==12.345
        assert b.r.retained_support_missing_step is None
    finally:a.log.close();b.log.close()

@pytest.mark.parametrize('field,bad',[
    ('physics_step_count', -1), ('physics_clock_origin_time', 100.),
    ('physics_clock_timestep', .02), ('retained_support_missing_step', 99),
])
def test_corrupt_clock_rejected_before_checkpoint_destination_changes(tmp_path,field,bad):
    from r1pro_teleop.airport_fsm.contracts import Fault
    a=clock_machine(tmp_path,'bad_a');b=clock_machine(tmp_path,'bad_b')
    try:
        step_physics(a.r,2);a.r.retained_support_missing_since=float(a.r.d.time)
        a.r.retained_support_missing_step=2
        tree=CheckpointTree(a,tmp_path/'bad_cp');tree.plan(['settled']);cp=tree.save('settled',lambda _:True)
        path=cp/'metadata.json';metadata=json.loads(path.read_text())
        metadata['context']['runtime'][field]=bad;path.write_text(json.dumps(metadata))
        with pytest.raises(Fault,match='retained_support_clock_inconsistent'):
            CheckpointTree(b,tmp_path/'bad_restore').restore(cp)
        assert b.r.d.time==0 and b.r.physics_step_count==0
    finally:a.log.close();b.log.close()


# Reuse the independent real-model fixture; no production package is patched.
from test_physical_preview import machine


def test_physical_preview_preserves_active_integer_timer_and_independent_counter(machine,tmp_path):
    from dataclasses import replace
    from r1pro_teleop.airport_fsm import physical_preview as pp
    r=machine.r;r.cfg=replace(r.cfg,retained_support_integer_clock_enabled=True);machine.c=r.cfg
    r.physics_step_count=50;r.steps=2
    r.physics_clock_origin_time=0.
    r.d.time=50*r.physics_clock_timestep
    r.mj.mj_forward(r.m,r.d)
    r.retained_support_missing_step=0;r.retained_support_missing_since=r.physics_clock_origin_time
    r.retained_contact=(0,'right')
    digest=pp.context_digest(machine)
    probe=pp.clone_machine(machine,tmp_path/'active_clock_probe')
    try:
        p=probe.r
        for field in CLOCK_FIELDS:assert getattr(p,field)==getattr(r,field)
        assert p.retained_support_missing_since==r.retained_support_missing_since
        assert p.physics_step_count-p.retained_support_missing_step==50
        assert p.validate_retained_clock_state()==r.validate_retained_clock_state()
        p.physics_step_count+=1
        assert r.physics_step_count==50
        assert pp.context_digest(machine)==digest
    finally:probe.log.close();probe.r.close()


def test_physical_preview_rejects_incomplete_enabled_clock_before_allocating(machine,tmp_path):
    from dataclasses import replace
    from r1pro_teleop.airport_fsm import physical_preview as pp
    from r1pro_teleop.airport_fsm.contracts import Fault
    r=machine.r;r.cfg=replace(r.cfg,retained_support_integer_clock_enabled=True);machine.c=r.cfg
    r.retained_support_missing_since=float(r.d.time)
    r.retained_support_missing_step=None
    before=pp._integration(r).copy();directory=tmp_path/'invalid_clock_probe'
    with pytest.raises(Fault,match='retained_support_clock_inconsistent'):
        pp.clone_machine(machine,directory)
    assert not directory.exists()
    np.testing.assert_array_equal(before,pp._integration(r))
