import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from r1pro_teleop.single_tray_3table.campaign import build_plan, execute, digest, case_commands
from r1pro_teleop.vla.data_three_table_single_tray import PROFILE, RULE_REVISION, LABELS
from r1pro_teleop.vla.three_table_single_tray_pipeline import campaign_gate


def inputs(tmp_path):
    manifest=tmp_path/'manifest.json';registry=tmp_path/'registry.json';inventory=tmp_path/'inventory.json'
    scenes=[];rows=[];splits={}
    for index,split in enumerate(('train','val','test')):
        name='parent_'+split;p=tmp_path/(name+'.json')
        # Resource annotation is deliberately different; registered split wins.
        p.write_text(json.dumps(dict(scene_id=name,split='train')))
        scenes.append(dict(scene_id=name,json=p.name));splits[name]=split
        rows.append(dict(parent_scene_id=name,registered_split=split,source_parent_json=str(p),source_parent_json_sha256=digest(p)))
    manifest.write_text(json.dumps(dict(scenes=scenes)));registry.write_text(json.dumps(splits))
    inventory.write_text(json.dumps(dict(schema='airport_registered_parent_split_inventory/1',parent_manifest_sha256=digest(manifest),canonical_split_registry_sha256=digest(registry),parent_rows=rows)))
    selection=dict(schema='airport_three_table_campaign_selection/1',variants=[dict(parent_scene_id='parent_'+s,variant_seed=100+i) for i,s in enumerate(('train','val','test'))])
    return selection,inventory,manifest,registry


def test_plan_inherits_canonical_parent_splits_and_never_randomizes_route(tmp_path):
    plan=build_plan(*inputs(tmp_path))
    assert [v['split'] for v in plan['variants']]==['train','val','test']
    assert [v['parent_resource_split'] for v in plan['variants']]==['train']*3
    assert plan['route_coverage']=='rear_to_front_left_only_not_all_three_table_routes'
    assert not plan['dataset_ready'] and not plan['training_started']
    assert not plan['push_axis_feedback_enabled']


@pytest.mark.parametrize('change',['duplicate','split_override','registry_changed','parent_changed','route_option','unknown_parent','bool_seed'])
def test_plan_rejects_parent_or_scope_mutations(tmp_path,change):
    selection,inventory,manifest,registry=inputs(tmp_path);options={}
    if change=='duplicate':selection['variants'].append(selection['variants'][0].copy())
    elif change=='split_override':selection['variants'][0]['split']='test'
    elif change=='registry_changed':registry.write_text('{}')
    elif change=='parent_changed':(tmp_path/'parent_train.json').write_text('{}')
    elif change=='route_option':options['target_table']='front_right'
    elif change=='unknown_parent':selection['variants'][0]['parent_scene_id']='unknown'
    else:selection['variants'][0]['variant_seed']=True
    with pytest.raises(ValueError):build_plan(selection,inventory,manifest,registry,scene_options=options)


def fake_source(argv,log):
    """Protocol fixture only, no MuJoCo, native media or claimed dataset ready."""
    destination=Path(argv[argv.index('--output')+1]);destination.mkdir(parents=True,exist_ok=False)
    if 'collect_three_table_full_source.py' not in argv[1]:return 0
    generated=Path(argv[argv.index('--scene')+1]).parent.parent
    index=int(generated.name.split('_')[-1]);split=('train','val','test')[index]
    source_path=destination/'source_proof/source.json';source_path.parent.mkdir()
    result=dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,task_completed=True,physics_success=True,training_eligible=True,split=split,frames=30,action_spans=[dict(action_label=label,start_frame=i*10,end_frame=(i+1)*10,measured_endpoint_frame=(i+1)*10-1,verified=True) for i,label in enumerate(LABELS)])
    result_path=destination/'result.json';result_path.write_text(json.dumps(result))
    source=dict(parent_scene_id='parent_'+split,variant_seed=100+index,split=split,parent_scene_json_sha256=digest(generated.parent.parent/('parent_'+split+'.json')))
    for key in ('trace','scene_xml','scene_json','events'):
        path=destination/(key+'.fixture');path.write_text('protocol fixture');source[key]=str(path);source[key+'_sha256']=digest(path)
    source.update(result=str(result_path),result_sha256=digest(result_path));source_path.write_text(json.dumps(source))
    (destination/'source_qualification_audit.json').write_text(json.dumps(dict(verified=True,action_spans=3,source_manifest=str(source_path))))
    return 0


def test_fresh_case_dirs_full_collector_and_campaign_gate_protocol(tmp_path):
    plan=build_plan(*inputs(tmp_path));out=tmp_path/'campaign';seen=[]
    def run(argv,log):seen.append(argv);return fake_source(argv,log)
    status=execute(plan,out,release=tmp_path,sim_python=sys.executable,config='cfg',reference='ref',workers=8,runner=run)
    assert status['completed']==status['selected']==status['successful']==3
    assert campaign_gate(out)['ready'] and not status['dataset_ready']
    assert len(seen)==6
    assert status['workers']==8 and status['resource_worker_cap']==64 and status['child_cpu_threads']==1
    assert not status['child_process_receipts_are_actual']  # Mock child protocol is not physical evidence.
    for argv in seen:
        if 'collect_three_table_full_source.py' in argv[1]:
            assert '--no-axis-feedback' in argv
            assert Path(argv[argv.index('--output')+1]).name=='observed_source'
    with pytest.raises(FileExistsError):execute(plan,out,release=tmp_path,sim_python=sys.executable,config='cfg',reference='ref')


def test_child_failure_is_preserved_and_does_not_fill_successful_split(tmp_path):
    plan=build_plan(*inputs(tmp_path));out=tmp_path/'campaign'
    def run(argv,log):
        if 'case_0001' in str(log):return 2
        return fake_source(argv,log)
    status=execute(plan,out,release=tmp_path,sim_python=sys.executable,config='cfg',reference='ref',runner=run)
    assert status['completed']==3 and status['successful']==2
    assert not campaign_gate(out)['ready']
    row=status['results'][1];assert row['returncode']==2 and not row['source_qualified']
    assert json.loads(Path(row['result']).read_text())['training_eligible'] is False


def test_success_claim_without_complete_windows_or_qualification_is_not_accepted(tmp_path):
    plan=build_plan(*inputs(tmp_path));out=tmp_path/'campaign'
    def run(argv,log):
        code=fake_source(argv,log)
        if 'collect_three_table_full_source.py' in argv[1]:
            p=Path(argv[argv.index('--output')+1])/'result.json';r=json.loads(p.read_text());r['action_spans']=r['action_spans'][:2];p.write_text(json.dumps(r))
        return code
    status=execute(plan,out,release=tmp_path,sim_python=sys.executable,config='cfg',reference='ref',runner=run)
    assert status['successful']==0 and not campaign_gate(out)['ready']
    assert all(r['error'] and r['returncode']==-1 for r in status['results'])


def test_cli_import_and_plan_only_never_spawn_physics(tmp_path,monkeypatch):
    script=Path(__file__).resolve().parents[1]/'scripts/collect_three_table_campaign.py'
    spec=importlib.util.spec_from_file_location('campaign_cli',script);module=importlib.util.module_from_spec(spec)
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:pytest.fail('plan/import must not spawn'))
    spec.loader.exec_module(module)
    selection,inventory,manifest,registry=inputs(tmp_path);selected=tmp_path/'selection.json';selected.write_text(json.dumps(selection));out=tmp_path/'plan_only'
    monkeypatch.setattr(sys,'argv',[str(script),'--selection',str(selected),'--inventory',str(inventory),'--parent-manifest',str(manifest),'--split-registry',str(registry),'--output',str(out)])
    module.main()
    receipt=json.loads((out/'planning_receipt.json').read_text())
    assert receipt['physical_jobs_started']==0 and not (out/'status.json').exists()
    assert campaign_gate(out) is None


def test_actual_cpu_child_receipts_env_exit_and_peak_are_not_physical_success(tmp_path,monkeypatch):
    from r1pro_teleop.single_tray_3table import campaign
    plan=build_plan(*inputs(tmp_path))
    def fixture_commands(*args):
        # Real subprocesses only print their environment; no scene/physics call.
        text="import os; print('threads='+os.environ['OMP_NUM_THREADS']); print('cuda='+os.environ['CUDA_VISIBLE_DEVICES'])"
        return [sys.executable,'-c',text],[sys.executable,'-c',text+'; raise SystemExit(2)']
    monkeypatch.setattr(campaign,'case_commands',fixture_commands)
    out=tmp_path/'cpu_children'
    state=execute(plan,out,release=tmp_path,sim_python=sys.executable,config='cfg',reference='ref',workers=8)
    assert state['child_process_receipts_are_actual'] and 1<=state['peak_active_child_processes']<=3
    assert state['successful']==0 and state['completed']==3 and not campaign_gate(out)['ready']
    receipts=list(out.glob('case_*/*.process.json'));assert len(receipts)==6
    assert {json.loads(p.read_text())['returncode'] for p in receipts}=={0,2}
    assert all(json.loads(p.read_text())['status']=='exited' for p in receipts)
    for log in out.glob('case_*/*.log'):
        assert 'threads=1' in log.read_text() and 'cuda=\n' in log.read_text()

def test_atomic_json_stale_partial_does_not_block_or_replace_good_target(tmp_path):
    from r1pro_teleop.single_tray_3table.campaign import atomic_json
    target=tmp_path/'status.json';target.write_text('{"old": true}')
    stale=tmp_path/'status.json.writing';stale.write_text('{partial')
    atomic_json(target,dict(complete=True))
    assert json.loads(target.read_text())==dict(complete=True)
    assert stale.read_text()=='{partial'
    with pytest.raises(ValueError):atomic_json(target,dict(value=float('nan')))
    assert json.loads(target.read_text())==dict(complete=True)
