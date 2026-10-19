import pytest
from dataclasses import asdict
from r1pro_teleop.single_tray_lab.evaluation_population import population,adapted_profile,generate_protocol,workspace_scope,WORKSPACE_SCOPE_ID
from r1pro_teleop.single_tray_lab.control import ControlProfile

def test_stratified_fixed_front_new50():
 rows=population([1,2,3]);assert len(rows)==50 and len({r['scene_id'] for r in rows})==50
 assert all(r['robot_x']==.15 and r['robot_y']==r['tray_y'] and r['split']=='test' for r in rows)
 assert {y:sum(r['tray_y']==y for r in rows) for y in (-.05,0,.05,.10,.15)}==dict.fromkeys((-.05,0,.05,.10,.15),10)
 assert all(r['workspace_scope_id']==WORKSPACE_SCOPE_ID and r['stratum_index']==i//10 for i,r in enumerate(rows))
 with pytest.raises(ValueError,match='seed_overlap'):population([20261006049])

def test_new_workspace_identity_and_prepared_rows_do_not_claim_evaluation_success():
 from r1pro_teleop.vla.data_single_tray import canonical_hash
 scope=workspace_scope();assert scope['scene_generation_required'] and 'new_scenes_generated' not in scope and not scope['historical_negative_y_population_used']
 assert scope['reference_success_robot_y_m']==0 and scope['reference_handover_left_tangent_m']==.08
 current=canonical_hash(scope);scope['robot_and_initial_tray_y_strata_m']=[-.26,-.25,-.24,-.23,-.22]
 assert canonical_hash(scope)!=current
 assert all('task_completed' not in row and 'success' not in row for row in population())

def test_profile_geometry_rederived_not_copied():
 scene=dict(table=dict(body='table',yaw=0,size=[.6,1.2,.8],position=[.85,0,0],top_z=.8),tray=dict(body='tray',size=[.56,.43,.105],position=[.85,-.26,.801],goal_position=[.85,.295,.801],rim_grasp_z=.096),frame=dict(base_mode='fixed_front',robot_forward=[1,0,0],robot_left=[0,1,0]),payloads=[],config=dict(lift_clearance=.28))
 source=asdict(ControlProfile(rim_height=.07,held_tracking_tolerance_m=.015,soft_payload_penetration_m=.01,lift_distance=.28))
 adapted=adapted_profile(scene,source);assert adapted['empty_place_position']==(.85,-.26,.801)
 assert adapted['rim_height']==.07 and adapted['held_tracking_tolerance_m']==.015
 scene['control_profile']=adapted;ControlProfile.from_scene(scene)
 source.pop('fps')
 with pytest.raises(ValueError,match='complete_success_control_profile'):adapted_profile(scene,source)

def test_failed_source_no_formal_output(tmp_path):
 import json
 case=tmp_path/'failed';(case/'scene').mkdir(parents=True);(case/'result.json').write_text(json.dumps(dict(task_completed=False)));(case/'scene/scene.json').write_text('{}')
 out=tmp_path/'protocol'
 with pytest.raises(ValueError,match='complete_success_source'):generate_protocol(case,out,[])
 assert not out.exists()
