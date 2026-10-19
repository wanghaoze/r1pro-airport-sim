"""Independently verify a completed replay's clocks, pose, trace and videos."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import h5py
import mujoco
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim import Trajectory, r1pro_map
from r1pro_teleop.real2sim.trajectory import sha256, write_json


def validate(run,output=None):
    run=Path(run); output=Path(output) if output else run/'delivery_validation.json'
    if output.exists():raise FileExistsError(output)
    assert json.loads((run/'exit.json').read_text())['exit_code']==0
    cases=[]
    for case in sorted(run.glob('case_*')):
        result=json.loads((case/'result.json').read_text());source=Trajectory.load(case/'source')
        model_path=case/'registered_model.xml' if (case/'registered_model.xml').exists() else run/'model.xml'
        model=mujoco.MjModel.from_xml_path(str(model_path));data=mujoco.MjData(model);dt=model.opt.timestep
        with h5py.File(case/'physics.h5') as h, np.load(case/'comparison.npz') as comparison:
            steps=len(h['time']);assert steps==result['physics_steps']
            for dataset in h.values():assert np.isfinite(dataset[:]).all()
            assert h.attrs['model_sha256']==sha256(model_path)
            assert np.allclose(h['time'][:],np.arange(steps)*dt,atol=1e-9,rtol=0)
            assert abs(h.attrs['terminal_time']-steps*dt)<1e-8
            expected=np.searchsorted(source.seconds,np.arange(steps)*dt+1e-12,side='right')-1
            assert np.array_equal(expected,h['source_index'][:])
            mapping=r1pro_map()
            targets=source.commands[expected][:,mapping.indices]*mapping.scale+mapping.offset
            assert np.allclose(h['target'][:],targets,atol=1e-12,rtol=0)
            for i,binding in enumerate(mapping.bindings):
                if binding.actuator:assert np.allclose(h['ctrl'][:,model.actuator(binding.actuator).id],targets[:,i])
            ticks=np.rint(comparison['actual_times']/dt).astype(int)
            assert np.array_equal(comparison['source_times'],source.seconds)
            reference=np.column_stack([np.interp(comparison['actual_times'],source.seconds,source.feedback[:,i])
                                       for i in range(len(source.channels))])
            assert np.allclose(reference,comparison['feedback_at_actual_time'],atol=1e-12,rtol=0)
            qids=[model.jnt_qposadr[model.joint(name).id] for name in mapping.joints]
            observations=np.array([mapping.decode((h['terminal_qpos'][:] if tick==steps else h['qpos'][tick])[qids]) for tick in ticks])
            assert np.allclose(observations,comparison['actual'],atol=1e-12,rtol=0)
            actual_indices=np.array([-1 if tick==0 else expected[tick-1] for tick in ticks])
            assert np.array_equal(actual_indices,comparison['source_command_indices'])
            error=((observations-reference)**2).mean(0)
            assert np.allclose(error,result['per_channel_mse'],atol=1e-12,rtol=0)
            assert result['online_state_resets']==0 and result['replay_completed']
            data.qpos[:]=h['qpos'][0];mujoco.mj_forward(model,data)
            if (case/'registration.json').exists():
                registration=json.loads((case/'registration.json').read_text())
                for body,key in [('base_link','base_pose'),('tray','tray_pose')]:
                    assert np.allclose(data.body(body).xpos,registration[key]['xyz'],atol=1e-8)
                    assert abs(abs(np.dot(data.body(body).xquat,registration[key]['quaternion_wxyz']))-1)<1e-8
            max_penetration=float(np.max(h['max_penetration_m'][:]))
        videos=[]
        for video in result['videos']:
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
                '-show_entries','stream=nb_read_frames,r_frame_rate,width,height','-of','json',video['path']]))['streams'][0]
            assert int(probe['nb_read_frames'])==len(source.seconds)==video['frames']
            assert (probe['width'],probe['height'],probe['r_frame_rate'])==(640,360,'30/1')
            assert sha256(video['path'])==video['sha256'];videos.append(video)
        contacts=json.loads((case/'contacts.json').read_text())
        tail=[c for c in contacts if c['time']>=contacts[-1]['time']-1.]
        evidence=dict(final_second_samples=len(tail),
            table_support_frames=sum(c['table_tray_n']>0 for c in tail),
            bilateral_finger_contact_frames=sum(c['left_tray_n']>0 and c['right_tray_n']>0 for c in tail),
            max_physics_penetration_m=max_penetration,
            final_tray_xyz=contacts[-1]['tray_xyz'],task_success=None)
        cases.append(dict(case=case.name,steps=steps,trace_sha256=sha256(case/'physics.h5'),videos=videos,
                          clocks_commands_metrics_and_initial_world_pose_verified=True,contact_evidence=evidence))
    report=dict(verified=True,checked_unix=time.time(),cases=cases,
        scope='artifact_integrity_and_raw_contact_evidence_not_task_acceptance')
    write_json(output,report);print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True)
    parser.add_argument('--output');args=parser.parse_args();validate(args.run,args.output)
