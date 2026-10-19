"""Experiment isolation and real MuJoCo checkpoint restoration regression tests."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

from r1pro_teleop.experiments.common import candidate, read
from r1pro_teleop.experiments.campaign import rank
from r1pro_teleop.experiments.checkpoint_tree import CheckpointTree, encode, decode
from r1pro_teleop.experiments.assessment import assess, history, diagnose
from r1pro_teleop.airport_fsm.contracts import State, atomic_json


@pytest.mark.parametrize("params", [{"primitive_seconds": 8}, {"criteria": {}},
                                      {"base_distance_delta_m": .2}, {"rim_x_delta_m": float("nan")},
                                      {"base_yaw_delta_rad": True}])
def test_search_cannot_weaken_contract(params):
    with pytest.raises(ValueError):
        candidate({"name": "probe", "params": params})


def test_failed_or_recovered_progress_never_beats_clean_episode():
    clean = [{"complete_episode_verified": True, "simulation_seconds": 590}]
    fail = [{"complete_episode_verified": False, "simulation_seconds": 599}]
    recovered = [{"complete_episode_verified": True, "recovery_used": True, "simulation_seconds": 1}]
    assert rank(clean) < rank(fail)
    assert rank(clean) < rank(recovered)
    assert rank(fail) == rank([{"complete_episode_verified": False, "simulation_seconds": 1}])


def test_assessments_and_nested_failure_evidence(tmp_path):
    with pytest.raises(ValueError):
        assess(tmp_path, observation="", evidence="x", hypothesis="h", next_action="n", outcome="failed")
    assess(tmp_path, observation="contact missing", evidence="trace.h5", hypothesis="lost support",
           next_action="inspect table forces", outcome="failed")
    assert history(tmp_path)[0]["hypothesis"] == "lost support"
    d = tmp_path / "source/attempts/s1/a000"; d.mkdir(parents=True)
    atomic_json(d / "result.json", {"scene_id": "s1", "physics_success": False,
                                     "failure_code": "contact_handoff_aborted"})
    (d / "events.jsonl").write_text(json.dumps({"event": "operation_failed", "detail": {"reason": "retained_contact_lost"}}) + '\n{"partial":', encoding="utf-8")
    result = diagnose(tmp_path / "source", tmp_path / "audit.json")
    assert result["rows"][0]["last_events"][0]["detail"]["reason"] == "retained_contact_lost"
    assert result['underlying_failures'] == {'retained_contact_lost':1}
    with pytest.raises(FileExistsError):
        diagnose(tmp_path / "source", tmp_path / "audit.json")


def test_handoff_wrapper_does_not_turn_planning_rejection_into_lost_contact():
    from r1pro_teleop.experiments.assessment import failure_chain
    events=[{'event':'operation_failed','reason':'contact_handoff_aborted',
             'detail':{'reason':'primitive_path_infeasible','detail':{'candidates':[]}}}]
    assert failure_chain('contact_handoff_aborted',events)==[
        'contact_handoff_aborted','primitive_path_infeasible']
    assert failure_chain(None,events)==[]
    assert failure_chain('new_failure',events)==['new_failure']


def test_diagnosis_keeps_attempt_yield_and_clean_scene_coverage_separate(tmp_path):
    for scene,attempt,recovered,diagnostic in [('s1','a000',False,False),
            ('s1','a001',False,False),('s2','a000',True,False),('s3','a000',False,True)]:
        directory=tmp_path/'source/attempts'/scene/attempt
        directory.mkdir(parents=True)
        atomic_json(directory/'result.json',dict(scene_id=scene,physics_success=True,
                    recovery_used=recovered,diagnostic_only=diagnostic,failure_code=None))
    report=diagnose(tmp_path/'source',tmp_path/'audit.json')
    assert report['attempts']==4 and report['attempted_scenes']==3
    assert report['successes']==4 and report['clean_complete_successes']==2
    assert report['clean_successful_scenes']==1


def tiny_machine(tmp_path, label):
    import mujoco
    from r1pro_teleop.airport_fsm.trace import Trace
    xml = tmp_path / "model.xml"
    xml.write_text('''<mujoco><option timestep="0.01" gravity="0 0 0"/>
      <worldbody><body name="base_link"><joint name="slide" type="slide" axis="1 0 0"/>
      <geom type="sphere" size=".1" mass="1"/></body></worldbody>
      <actuator><motor joint="slide"/></actuator></mujoco>''')
    model = mujoco.MjModel.from_xml_path(str(xml)); data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    kind = mujoco.mjtState.mjSTATE_INTEGRATION
    runtime = SimpleNamespace(mj=mujoco, m=model, d=data, integration_spec=kind,
        integration_size=mujoco.mj_stateSize(model, kind), spec={"scene_id": "tiny"},
        cfg=SimpleNamespace(dump=lambda: {"primitive_seconds": 3}),
        sim=SimpleNamespace(scene=xml, target=np.array([.02]), base_target=np.zeros(3)),
        steps=0, previous_warning=np.zeros(len(data.warning), dtype=int),
        fsm_state=State.APPROACH_TRAY, phase="pregrasp", allowed_tray=0, holding=None,
        retained_contact={"side": "left", "tray": 0}, retained_support_missing_since=None,
        lost_time=0., wall_start=0., guard=lambda: None, experiment_dependencies="assets")
    import time
    runtime.wall_start = time.monotonic()
    directory = tmp_path / label
    machine = SimpleNamespace(r=runtime, directory=directory, log=Trace(directory, {}),
         rng=np.random.default_rng(42), scheduler=SimpleNamespace(mapping=(2, 0, 1)),
         reach_pull_used={1}, pending_grasp_contact={"side": "left"}, stage_context={"tray": 1},
         experiment_origin="fresh", experiment={"name": "baseline", "params": {}, "strategy": "baseline"})
    return machine


def test_real_mujoco_checkpoint_restores_targets_context_and_next_step(tmp_path):
    a = tiny_machine(tmp_path, "a")
    tree = CheckpointTree(a, tmp_path / "checkpoints"); tree.plan(["settled"])
    a.r.d.ctrl[:] = .03; a.r.steps = 40
    a.verified_final_trays = {0, 2}
    from r1pro_teleop.airport_fsm.rim_affordances import RimPair
    a.grasp_rim_pair = RimPair('length', .3, .27, .205)
    checkpoint = tree.save("settled", lambda _: True)
    b = tiny_machine(tmp_path, "b")
    other = CheckpointTree(b, tmp_path / "new_checkpoints")
    other.restore(checkpoint)
    assert b.r.steps == 40 and b.reach_pull_used == {1}
    assert b.verified_final_trays == {0, 2}
    assert b.grasp_rim_pair == a.grasp_rim_pair
    assert b.r.retained_contact == a.r.retained_contact
    assert b.scheduler.mapping == (2, 0, 1)
    assert b.rng.random() == a.rng.random()
    np.testing.assert_array_equal(b.r.sim.target, a.r.sim.target)
    for m in (a, b):
        m.r.mj.mj_step(m.r.m, m.r.d)
    np.testing.assert_array_equal(a.r.d.qpos, b.r.d.qpos)
    np.testing.assert_array_equal(a.r.d.qvel, b.r.d.qvel)
    with pytest.raises(ValueError, match="fresh"):
        other.restore(checkpoint)
    for m in (a, b): m.log.close()


def test_checkpoint_rejects_unsettled_unchecked_and_changed_identity(tmp_path):
    a = tiny_machine(tmp_path, "a")
    tree = CheckpointTree(a, tmp_path / "cp"); tree.plan(["settled"])
    with pytest.raises(ValueError, match="check_failed"):
        tree.save("settled", lambda _: False)
    a.r.d.qvel[:] = 1
    with pytest.raises(ValueError, match="not_settled"):
        tree.save("settled", lambda _: True)
    a.r.d.qvel[:] = 0
    cp = tree.save("settled", lambda _: True)
    b = tiny_machine(tmp_path, "b"); b.r.spec = {"scene_id": "other"}
    with pytest.raises(ValueError, match="identity_mismatch"):
        CheckpointTree(b, tmp_path / "other").restore(cp)
    for m in (a, b): m.log.close()


def test_checkpoint_serialization_preserves_arrays_tuples_sets():
    original = {"pose": np.array([1., 2.]), "hands": (np.eye(2), None), "used": {1, 2}}
    restored = decode(json.loads(json.dumps(encode(original))))
    np.testing.assert_array_equal(restored["pose"], original["pose"])
    assert isinstance(restored["hands"], tuple) and restored["used"] == {1, 2}


def test_adapter_baseline_and_bounds_keep_input_unchanged(monkeypatch):
    from r1pro_teleop.experiments.adapter import ExperimentMachine
    from r1pro_teleop.airport_fsm.machine import Machine
    original = [(np.array([1., 2., 0.]), .2, .01)]
    monkeypatch.setattr(Machine, "_candidate_list", lambda self, tray: original)
    machine = object.__new__(ExperimentMachine)
    machine.experiment = candidate({"name": "baseline"})
    baseline = machine._candidate_list(0)
    np.testing.assert_array_equal(baseline[0][0], original[0][0])
    machine.experiment = candidate({"name": "closer", "params": {"base_distance_delta_m": -.02}})
    actual = machine._candidate_list(0)
    assert actual[0][0][0] == pytest.approx(1.02)
    assert original[0][0][0] == 1.


def test_cma_search_requires_viable_fresh_seed(tmp_path, monkeypatch):
    from r1pro_teleop.experiments import parameter_search as module
    monkeypatch.setattr(module, "assert_campaign", lambda root: {})
    path = tmp_path / "experiments/test/summary.json"
    atomic_json(path, {"group": "development", "origin": "fresh", "winner": None})
    with pytest.raises(ValueError, match="viable_seed"):
        module.search(tmp_path, path, {"rim_x_delta_m": [-.01, .01]})


def test_cma_evaluates_incumbent_each_generation(tmp_path, monkeypatch):
    from r1pro_teleop.experiments import parameter_search as module
    monkeypatch.setattr(module, "assert_campaign", lambda root: {})
    path = tmp_path / "experiments/test/summary.json"
    seed = candidate({"name": "seed"})
    atomic_json(path, {"group": "development", "origin": "fresh", "winner": seed})
    calls = []
    def fake_evaluate(root, specs, **kwargs):
        calls.append(specs)
        entries = [{"candidate": s, "ranking_key": [-1, 100], "rows": [{}]} for s in specs]
        return {"run": kwargs["run"], "ranking": entries, "winner": specs[0]}
    monkeypatch.setattr(module, "evaluate", fake_evaluate)
    result = module.search(tmp_path, path, {"rim_x_delta_m": [-.01, .01]}, generations=2)
    assert len(calls) == 2 and all(s[0]["name"] == "incumbent" for s in calls)
    assert result["requires_fresh_verification"]


def test_verification_protects_known_success_and_is_one_shot(tmp_path, monkeypatch):
    from r1pro_teleop.experiments import campaign as module
    import r1pro_teleop.airport_fsm.registry as registry
    monkeypatch.setattr(module, "require_conda", lambda: None)
    monkeypatch.setattr(module, "assert_campaign", lambda root: {
        "groups": {"development": ["dev"], "regression": ["old_success"], "holdout": ["unseen"]}})
    monkeypatch.setattr(registry, "config_for", lambda root: SimpleNamespace(max_attempts_per_scene=6))
    origins = []
    def trial(root, run, scene, spec, attempt, timeout, checkpoint=None, stage=None):
        origins.append((scene, checkpoint, stage))
        success = spec["name"] == "baseline" or scene == "unseen"
        return {"scene_id": scene, "attempt": attempt, "complete_episode_verified": success}
    monkeypatch.setattr(module, "_trial", trial)
    report = module.verify(tmp_path, {"name": "new"})
    assert not report["passed"] and report["regressions"] == [("old_success", 0)]
    assert all(cp is None and stage is None and scene != "dev" for scene, cp, stage in origins)
    with pytest.raises(FileExistsError):
        module.verify(tmp_path, {"name": "new"})


def test_checkpoint_detects_corrupted_state_before_restore(tmp_path):
    a = tiny_machine(tmp_path, "a")
    tree = CheckpointTree(a, tmp_path / "cp"); tree.plan(["settled"])
    cp = tree.save("settled", lambda _: True)
    (cp / "state.npz").write_bytes(b"corrupted")
    b = tiny_machine(tmp_path, "b")
    with pytest.raises(ValueError, match="state_changed"):
        CheckpointTree(b, tmp_path / "other").restore(cp)
    assert b.r.steps == 0 and not getattr(b, "checkpoint_restored", False)
    for m in (a, b): m.log.close()


def test_training_export_rejects_diagnostic_even_if_marked_physics_success(tmp_path, monkeypatch):
    from r1pro_teleop.airport_fsm import exporter
    monkeypatch.setattr(exporter, "config_for", lambda root: SimpleNamespace(successes_per_scene=1))
    monkeypatch.setattr(exporter, "scene_rows", lambda root: [{"scene_id": "s", "split": "train"}])
    directory = tmp_path / "attempts/s/a000"
    atomic_json(directory / "result.json", {"physics_success": True, "recovery_used": False,
                                             "diagnostic_only": True})
    (directory / "trace.h5").write_bytes(b"not needed for selection")
    assert exporter.choose_attempts(tmp_path) == []


@pytest.mark.parametrize('strategy',['baseline','full_approach_preview'])
def test_experiment_align_forwards_push_alternate_restriction(monkeypatch,strategy):
    from r1pro_teleop.experiments.adapter import ExperimentMachine
    from r1pro_teleop.airport_fsm.machine import Machine
    calls=[]
    monkeypatch.setattr(Machine,'align',lambda self,*args,**kw:calls.append(kw))
    m=object.__new__(ExperimentMachine)
    m.experiment=candidate({'name':'probe','strategy':strategy})
    original=lambda *a,**k:None
    m.r=SimpleNamespace(cartesian=original)
    m.align(0,0,allow_alternate=False)
    assert calls[0]['allow_alternate'] is False
    assert m.r.cartesian is original


def test_checkpoint_preserves_lift_escape_context(tmp_path):
    a=tiny_machine(tmp_path,'a');a.r.primitive_lift_xy_shift_m=.06
    tree=CheckpointTree(a,tmp_path/'cp');tree.plan(['settled'])
    saved=tree.save('settled',lambda _:True)
    b=tiny_machine(tmp_path,'b')
    CheckpointTree(b,tmp_path/'other').restore(saved)
    assert b.r.primitive_lift_xy_shift_m==.06
    for m in (a,b):m.log.close()


def test_checkpoint_preserves_preview_sequence_but_never_active_preview(tmp_path):
    a=tiny_machine(tmp_path,'a');a._physical_preview_sequence=4
    tree=CheckpointTree(a,tmp_path/'cp');tree.plan(['settled'])
    a._physical_preview_active=True
    with pytest.raises(ValueError,match='inside_physical_preview'):
        tree.save('settled',lambda _:True)
    a._physical_preview_active=False
    saved=tree.save('settled',lambda _:True)
    metadata=json.loads((saved/'metadata.json').read_text())
    assert '_physical_preview_active' not in metadata['context']['machine']
    b=tiny_machine(tmp_path,'b')
    CheckpointTree(b,tmp_path/'other').restore(saved)
    assert b._physical_preview_sequence==4 and b._physical_preview_active is False
    for m in (a,b):m.log.close()
