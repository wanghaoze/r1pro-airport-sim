"""Audit contact chatter by exact private replay of recorded raw/1 or raw/2 controls.

Never writes a collection or changes labels. Every replayed completed interval
must match the next recorded qpos/qvel. Raw/2 uses its actual per-substep ctrl journal; no constant-control fallback.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import h5py
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation


def estimator(path):
    spec=importlib.util.spec_from_file_location('support_substep_estimator',path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module.measure_support_force


def collision_vertices(model,data,bid):
    body=data.body(bid);vertices=[]
    for geom in range(model.ngeom):
        if model.geom_bodyid[geom]!=bid or not model.geom_contype[geom]:continue
        mesh=int(model.geom_dataid[geom])
        if mesh<0:continue
        first=int(model.mesh_vertadr[mesh]);count=int(model.mesh_vertnum[mesh])
        world=model.mesh_vert[first:first+count]@data.geom_xmat[geom].reshape(3,3).T+data.geom_xpos[geom]
        vertices.extend((world-body.xpos)@body.xmat.reshape(3,3))
    if not vertices:raise ValueError('No tray collision vertices')
    return np.asarray(vertices)


def audit(root,attempt,output,measure):
    scene=attempt.parent.name;scene_root=root/'scenes'/scene;xml=scene_root/'mobile.xml'
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines() if line.strip()]
    segments=[];active=None
    for event in events:
        if event.get('event')=='primitive_start' and event.get('primitive')=='push':active=int(event['frame'])
        elif active is not None and event.get('event') in ('primitive_complete','primitive_failed') and event.get('primitive')=='push':
            segments.append((active,int(event['frame'])));active=None
    xml_hash=hashlib.sha256(xml.read_bytes()).hexdigest()
    summaries=[];maximum_qpos_error=maximum_qvel_error=0.
    with h5py.File(attempt/'trace.h5','r') as trace:
        schema=str(trace.attrs['schema'])
        if schema not in ('airport_fsm_raw/1', 'airport_fsm_raw/2'):
            raise ValueError(f'Unsupported raw schema: {schema}')
        raw2 = schema == 'airport_fsm_raw/2'
        if raw2 and ('ctrl_substeps' not in trace or 'executed_substeps' not in trace):
            raise ValueError('Raw/2 requires its actual substep control journal')
        metadata=json.loads(trace.attrs['metadata_json'])
        if xml_hash!=metadata['scene_xml_sha256']:raise ValueError('Frozen XML hash mismatch')
        model=mujoco.MjModel.from_xml_path(str(xml));data=mujoco.MjData(model)
        model.actuator_forcerange[:]=metadata['limits']['actuator_forcerange']
        dt=float(model.opt.timestep);period=1/float(metadata['fps']);steps=round(period/dt)
        if not np.isclose(steps*dt,period,atol=1e-10,rtol=0):raise ValueError('Nonintegral frame/substep ratio')
        tables={model.body(name).id for name in ('front_left','front_right','rear')}
        fingers={bid for bid in range(model.nbody) if 'gripper_finger' in model.body(bid).name}
        state_spec=mujoco.mjtState.mjSTATE_INTEGRATION
        if trace['integration_state'].shape[1]!=mujoco.mj_stateSize(model,state_spec):raise ValueError('Integration schema mismatch')
        mujoco.mj_setState(model,data,trace['integration_state'][0],state_spec);mujoco.mj_forward(model,data)
        tray_ids=[model.body('tray_'+str(i)).id for i in range(3)]
        vertices={bid:collision_vertices(model,data,bid) for bid in tray_ids}
        csv_path=output/f'{scene}_{attempt.name}_push_substeps.csv'
        with csv_path.open('x',newline='',encoding='utf-8') as stream:
            fields=['scene_id','primitive_start_frame','frame','substep','simulation_time_s','tray',
                    'table_contact_count','table_normal_n','gripper_vertical_n','min_z_m','roll_deg','pitch_deg']
            writer=csv.writer(stream);writer.writerow(fields)
            for start,end in segments:
                tray=int(trace['target_tray'][start]);bid=tray_ids[tray]
                row=dict(start_frame=start,end_frame=end,tray=tray,accepted_intervals=0,skipped_incomplete_intervals=0,
                         skipped_no_endpoint_intervals=0,
                         sampled_substeps=0,supported_substeps=0,table_load_peak_n=0.,table_load_impulse_ns=0.,
                         longest_missing_substeps=0,recorded_endpoint_missing_intervals=0)
                missing_run=0
                for frame in range(start,min(end,len(trace['timestamp']))):
                    if not bool(trace['transition_completed'][frame]):
                        row['skipped_incomplete_intervals']+=1;continue
                    if frame+1>=len(trace['timestamp']):
                        row['skipped_no_endpoint_intervals']+=1;continue
                    mujoco.mj_setState(model,data,trace['integration_state'][frame],state_spec)
                    mujoco.mj_forward(model,data)
                    data.qacc_warmstart[:]=trace['qacc_warmstart'][frame]
                    # At the next frame's observation, ctrl still contains the
                    # previous interval's applied command. This is exact raw/1.
                    if raw2:
                        controls=trace['ctrl_substeps'][frame]
                        if int(trace['executed_substeps'][frame]) != steps or controls.shape != (steps, model.nu):
                            raise ValueError('Completed raw/2 interval has an incomplete ctrl journal')
                    else:
                        data.ctrl[:]=trace['ctrl'][frame+1]
                    for substep in range(1,steps+1):
                        if raw2:data.ctrl[:]=controls[substep-1]
                        mujoco.mj_step(model,data);mujoco.mj_forward(model,data)
                        table=measure(model,data,bid,tables);gripper=measure(model,data,bid,fingers)
                        supported=table.qualifying_contact_count>0
                        missing_run=0 if supported else missing_run+1
                        row['sampled_substeps']+=1;row['supported_substeps']+=int(supported)
                        row['longest_missing_substeps']=max(row['longest_missing_substeps'],missing_run)
                        row['table_load_peak_n']=max(row['table_load_peak_n'],table.load_n)
                        row['table_load_impulse_ns']+=table.load_n*dt
                        body=data.body(bid);rotation=body.xmat.reshape(3,3)
                        bottom=float((vertices[bid]@rotation.T+body.xpos)[:,2].min())
                        rpy=Rotation.from_matrix(rotation).as_euler('xyz',degrees=True)
                        writer.writerow([scene,start,frame,substep,float(data.time),tray,table.qualifying_contact_count,
                                         table.signed_normal_n,gripper.signed_normal_n,bottom,float(rpy[0]),float(rpy[1])])
                    ep=float(np.max(np.abs(data.qpos-trace['qpos'][frame+1])))
                    ev=float(np.max(np.abs(data.qvel-trace['qvel'][frame+1])))
                    maximum_qpos_error=max(maximum_qpos_error,ep);maximum_qvel_error=max(maximum_qvel_error,ev)
                    if ep>1e-9 or ev>1e-8:raise ValueError(f'{scene}/{frame}: private replay diverges: qpos={ep}, qvel={ev}')
                    row['accepted_intervals']+=1
                    row['recorded_endpoint_missing_intervals']+=int(trace['table_contact'][frame+1,tray]<=0)
                count=row['sampled_substeps']
                row['support_fraction']=row['supported_substeps']/count if count else None
                row['longest_physics_missing_s']=row['longest_missing_substeps']*dt
                row['mean_table_load_n']=row['table_load_impulse_ns']/(count*dt) if count else None
                summaries.append(row)
    return {'scene_id':scene,'source_xml_sha256':xml_hash,'source_trace':str(attempt/'trace.h5'),
            'maximum_qpos_endpoint_error':maximum_qpos_error,'maximum_qvel_endpoint_error':maximum_qvel_error,
            'physics_timestep_s':dt,'push_segments':summaries}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--cases',type=int,nargs='+',required=True)
    parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--estimator',type=Path)
    args=parser.parse_args();root=args.root.resolve();output=args.output_directory.resolve()
    if output==root or root in output.parents:raise ValueError('Output must be outside the frozen collection')
    path=args.estimator or Path(__file__).with_name('support_feedback.py')
    if not path.exists():path=Path(__file__).resolve().parents[1]/'r1pro_teleop/airport_fsm/support_feedback.py'
    measure=estimator(path);attempts=[]
    for case in args.cases:
        matches=[p for p in (root/'attempts').glob(f'airport_{case:04d}_*/a*') if p.is_dir()]
        if not matches:raise ValueError(f'Missing case {case}')
        attempts.extend(sorted(matches))
    output.mkdir(parents=True,exist_ok=False)
    report={'qualification':'private_exact_recorded_controls_replay_diagnostic_only_no_label_changes',
            'mujoco_version':mujoco.__version__,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'estimator_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'root':str(root),'cases':[]}
    for attempt in attempts:
        result=audit(root,attempt,output,measure);report['cases'].append(result);print(json.dumps(result),flush=True)
    with (output/'summary.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)


if __name__=='__main__':main()
