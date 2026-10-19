"""One private withdrawal structure candidate; no production file edits."""
import json,pathlib,sys,runpy
import numpy as np
from diagnose_push_duration import analyze


def main():
    controller=sys.argv[sys.argv.index('--controller')+1];output=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);sys.path.insert(0,controller)
    from r1pro_teleop.airport_fsm import trajectory,primitives
    from r1pro_teleop.airport_fsm.contracts import Fault
    captured=[];candidate_started=[False]
    for kind in (trajectory.BlendedJointPath,trajectory.CruiseJointPath):
        original=kind.__init__
        def wrap(self,points,v,a,j,minimum_seconds=.1,_original=original):
            _original(self,points,v,a,j,minimum_seconds)
            report=analyze(self,v,a,j,minimum_seconds);report['structural_candidate']=candidate_started[0];captured.append(report)
        kind.__init__=wrap
    original_withdraw=primitives.plan_withdraw_path
    def structural(r,points,free_midpoint,held_endpoint,held_columns,*,available,extra_path_check=None):
        try:return original_withdraw(r,points,free_midpoint,held_endpoint,held_columns,available=available,extra_path_check=extra_path_check)
        except Fault as error:
            if error.code!='primitive_path_infeasible' or any(x.get('reason')!='duration' for x in error.detail.get('candidates',[])):raise
            original_rejection=error.detail
        points=np.array(points,copy=True);held_columns=np.asarray(held_columns);free_columns=np.array([i for i in range(points.shape[1]) if i not in held_columns])
        if points.shape[0]!=4 or not np.array_equal(points[1,free_columns],points[2,free_columns]):
            raise ValueError('Cannot retain exact free-hand clearance in merged waypoint')
        # Point2 already has exactly the same free-hand clearance target and
        # the real held-hand mid-trajectory IK solution. Remove only the
        # artificial held-joint blend, without moving any remaining waypoint.
        candidate=points[[0,2,3]].copy();candidate_started[0]=True
        r.trace.event('diagnostic_withdraw_merge',original_rejection=original_rejection,original_points=points,candidate_points=candidate,
            free_clearance_exactly_preserved=True,endpoint_exactly_preserved=True,available_s=available)
        return primitives.plan(r,candidate,available=available,minimum=min(2.4,available-.05),allow_shortcut=False,extra_path_check=extra_path_check)
    primitives.plan_withdraw_path=structural
    try:runpy.run_path(str(pathlib.Path(__file__).with_name('diagnose_push_from_trace.py')),run_name='__main__')
    finally:
        output.mkdir(exist_ok=True,parents=True);(output/'path_duration_audit.json').write_text(json.dumps(captured,indent=2))

if __name__=='__main__':main()
