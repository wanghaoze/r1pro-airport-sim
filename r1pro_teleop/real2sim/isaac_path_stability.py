"""Trajectory-wide diagnostics, deliberately separate from endpoint labels."""
import numpy as np
from scipy.spatial.transform import Rotation


def path_stability(trace, spans, mapping):
    if not spans:
        return dict(available=False,reason='no_complete_action_span')
    result={}
    for span in spans:
        lo,hi=span['start'],span['end']
        quat=trace['tray_pose'][lo:hi+1,0,3:]
        rotation=Rotation.from_quat(quat[:,[1,2,3,0]])
        tilt=np.degrees(np.arccos(np.clip(rotation.as_matrix()[:,2,2],-1,1)))
        angular=np.degrees((rotation[:-1].inv()*rotation[1:]).magnitude())*20
        force=trace['finger_contact_force'][lo:hi,:,0,:]
        result[span['prompt']]=dict(maximum_tilt_deg=float(tilt.max()),
            endpoint_tilt_deg=float(tilt[-1]),maximum_angular_speed_deg_s=float(angular.max()),
            angular_speed_p99_deg_s=float(np.quantile(angular,.99)),peak_finger_contact_force_n=float(force.max()))
    if len(spans)==2:
        lo=spans[0]['start']+28;hi=spans[1]['start']+28
        paths=mapping['sensor_paths'];relative={}
        for side in ('left','right'):
            index=next(i for i,p in enumerate(paths) if p.rsplit('/',1)[-1]==side+'_gripper_link')
            hand=trace['rigid_pose'][lo:hi+1,index];tray=trace['tray_pose'][lo:hi+1,0]
            r=Rotation.from_quat(hand[:,[4,5,6,3]])
            local=r.inv().apply(tray[:,:3]-hand[:,:3])
            relative[side]=float(np.linalg.norm(local-local[0],axis=1).max())
        result['held_tray_relative_to_gripper_link_maximum_change_m']=relative
        result['relative_change_is_slip_plus_contact_compliance_not_identified_material_slip']=True
    return dict(available=True,endpoint_success_does_not_prove_path_stability=True,
                user_defined_hard_stability_threshold=None,measurements=result)
