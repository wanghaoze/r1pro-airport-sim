import json
from pathlib import Path
import h5py
import numpy as np
import pytest
from scripts.plan_complete_task_actions import plan_source,write_plans,sha


def fixture(tmp_path):
    root=tmp_path/'source';attempt=root/'attempts/s/a000';attempt.mkdir(parents=True)
    scene_dir=root/'scenes/s';scene_dir.mkdir(parents=True)
    scene=dict(scene_id='s',split='train');(scene_dir/'scene.json').write_text(json.dumps(scene))
    (scene_dir/'mobile.xml').write_text('<mujoco/>')
    result=dict(scene_id='s',split='train',frames=2,task_completed=True)
    (attempt/'result.json').write_text(json.dumps(result))
    phase=dict(start_frame=0,end_frame=2,state='ALIGN_BASE',phase='unknown',
        target_tray_id='tray_0',target_slot_id='slot_0',recovery=False)
    (attempt/'segments.json').write_text(json.dumps([phase]))
    event=dict(event='operation_selected',frame=0,operation_index=1,operation=dict(tray=0,slot=0,temporary=False))
    (attempt/'events.jsonl').write_text(json.dumps(event)+'\n');(attempt/'events.json').write_text('[]')
    with h5py.File(attempt/'trace.h5','w') as trace:
        trace.attrs['schema']='airport_fsm_raw/1';trace.attrs['num_frames']=2
        trace.attrs['metadata_json']=json.dumps(dict(scene=scene,fps=20,controller_source='program_generated',
            scene_xml_sha256=sha(scene_dir/'mobile.xml'),config=dict(criteria=dict(contact_n=.5,lifted_m=.02))))
        trace.attrs['terminal_snapshot_json']=json.dumps(dict(time=.1,qpos=[0.],qvel=[0.]))
        arrays=dict(transition_completed=[True,True],sim_time=[0.,.05],state=np.zeros((2,16)),
            action=np.zeros((2,16)),base_action=np.zeros((2,3)),fsm_state=np.array(['ALIGN_BASE']*2,dtype='S'),
            phase=np.array(['unknown']*2,dtype='S'),target_tray=[0,0],gripper_contact_force=np.zeros((2,1,2)),
            min_z=np.zeros((2,1)),support_contact=np.ones((2,1)),floor_contact=np.zeros((2,1)))
        for key,value in arrays.items():trace[key]=value
    paths=dict(trace=attempt/'trace.h5',result=attempt/'result.json',segments=attempt/'segments.json',
        events=attempt/'events.jsonl',physical_events=attempt/'events.json',scene_json=scene_dir/'scene.json',scene_xml=scene_dir/'mobile.xml')
    row=dict(collection=str(root),attempt=str(attempt),scene_id='s',split='train',frames=2,task_completed=True)
    for key,path in paths.items():row[key]=str(path);row[key+'_sha256']=sha(path)
    return row


def test_actual_h5_source_identity_and_complete_mask_produce_plan(tmp_path):
    row=fixture(tmp_path);before=Path(row['trace']).read_bytes();plan=plan_source(row)
    assert plan['segments'][0]['action_label']=='navigate_to_tray'
    assert plan['segments'][0]['scene_sha256']==row['scene_json_sha256']
    assert plan['raw_frames']==2 and plan['segments'][0]['frames']==2
    assert Path(row['trace']).read_bytes()==before


@pytest.mark.parametrize('change',['sha','mask','phase','terminal'])
def test_invalid_source_rejected_before_labeling(tmp_path,change):
    row=fixture(tmp_path)
    if change=='sha':Path(row['scene_xml']).write_text('changed')
    else:
        with h5py.File(row['trace'],'r+') as trace:
            if change=='mask':trace['transition_completed'][-1]=False
            if change=='phase':trace['phase'][0]=b'wrong'
            if change=='terminal':trace.attrs['terminal_snapshot_json']=json.dumps(dict(time=.09,qpos=[0.],qvel=[0.]))
        row['trace_sha256']=sha(row['trace'])
    with pytest.raises(ValueError):plan_source(row)


def test_every_inventory_row_emits_success_or_exclusion_and_no_overwrite(tmp_path):
    valid=fixture(tmp_path);invalid={**valid,'scene_xml_sha256':'bad'}
    inventory=tmp_path/'inventory.jsonl';inventory.write_text(json.dumps(valid)+'\n'+json.dumps(invalid)+'\n')
    output=tmp_path/'new/plans.jsonl';spec=tmp_path/'new/labels.json'
    summary=write_plans(inventory,output,spec)
    rows=[json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows)==2 and rows[0]['status']=='planned' and 'excluded_reason' in rows[1]
    assert summary['counts']['planned_sources']==1 and summary['counts']['excluded_sources']==1
    assert len(json.loads(spec.read_text())['action_vocabulary'])==8
    assert json.loads(spec.read_text())['mapping_status']=='user_confirmed'
    assert rows[0]['original_inventory']==valid
    with pytest.raises(FileExistsError):write_plans(inventory,output,spec)
