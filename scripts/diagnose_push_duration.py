"""Read-only constructor audit of original zero-motion push path durations."""
import json,math,pathlib,sys,runpy
import numpy as np


def joint_name(index):
    return ('left_arm_joint'+str(index+1)) if index<7 else ('left_gripper' if index==7 else ('right_arm_joint'+str(index-7) if index<15 else 'right_gripper'))


def analyze(path,velocity,acceleration,jerk,minimum):
    limits=[np.broadcast_to(np.asarray(x,float),(path.points.shape[1],)) for x in (velocity,acceleration,jerk)]
    report=dict(path_type=type(path).__name__,native_duration_s=path.duration,rounded_duration_s=math.ceil(path.duration*20)/20,minimum_s=minimum,points=path.points.tolist(),knots=path.spline.x.tolist())
    records=[]
    if type(path).__name__=='BlendedJointPath':
        for order,cap in enumerate(limits,1):
            derivative=path.spline.derivative(order)
            for segment,width in enumerate(np.diff(path.spline.x)):
                for joint in range(len(cap)):
                    coef=derivative.c[:,segment,joint]
                    roots=np.roots(np.polyder(coef))
                    candidates=[0.,float(width)]+[float(z.real) for z in roots if abs(z.imag)<1e-9 and 0<z.real<width]
                    values=np.polyval(coef,candidates);which=int(np.argmax(abs(values)));peak=float(abs(values[which]))
                    records.append(dict(joint=joint_name(joint),column=joint,segment=segment,derivative_order=order,normalized_progress=float(path.spline.x[segment]+candidates[which]),peak_progress_derivative=peak,limit=float(cap[joint]),required_duration_s=(peak/float(cap[joint]))**(1/order),segment_start=path.points[segment,joint],segment_end=path.points[segment+1,joint]))
        records.sort(key=lambda x:x['required_duration_s'],reverse=True)
        report['limiting_extrema']=records[:12]
        report['per_order_max']={str(order):next(x for x in records if x['derivative_order']==order) for order in (1,2,3)}
    else:
        b1,b2,b3=path.path_derivative_bounds;r=path.ramp;peak=1/(1-r);acc=1.5*peak/r;jrk=6*peak/r**2
        bounds=(b1*peak,b2*peak**2+b1*acc,b3*peak**3+3*b2*peak*acc+b1*jrk)
        for order,(bound,cap) in enumerate(zip(bounds,limits),1):
            for joint in range(len(cap)):
                records.append(dict(joint=joint_name(joint),column=joint,derivative_order=order,required_duration_s=float((bound[joint]/cap[joint])**(1/order)),limit=float(cap[joint]),conservative_progress_derivative_bound=float(bound[joint])))
        report['ramp']=r;report['progress_scaled_minimum_s']=minimum*peak
        report['limiting_conservative_bounds']=sorted(records,key=lambda x:x['required_duration_s'],reverse=True)[:8]
    return report


def main():
    controller=sys.argv[sys.argv.index('--controller')+1];output=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);sys.path.insert(0,controller)
    from r1pro_teleop.airport_fsm import trajectory,primitives
    from r1pro_teleop.airport_fsm.contracts import Fault
    captured=[]
    for kind in (trajectory.BlendedJointPath,trajectory.CruiseJointPath):
        original=kind.__init__
        def wrap(self,points,v,a,j,minimum_seconds=.1,_original=original):
            _original(self,points,v,a,j,minimum_seconds)
            captured.append(analyze(self,v,a,j,minimum_seconds))
        kind.__init__=wrap
    def refuse_execution(*args,**kwargs):raise Fault('diagnostic_readonly_unexpected_feasible_path')
    primitives.execute=refuse_execution
    try:runpy.run_path(str(pathlib.Path(__file__).with_name('diagnose_push_from_trace.py')),run_name='__main__')
    finally:
        output.mkdir(exist_ok=True,parents=True)
        (output/'path_duration_audit.json').write_text(json.dumps(captured,indent=2))

if __name__=='__main__':main()
