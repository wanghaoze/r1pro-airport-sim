"""Private additive yaw correction over an existing validated blended curve."""
import numpy as np
from diagnostic_yaw_suffix import FixedDurationQuintic

class AdditiveSuffix:
    def __init__(self,path,full_duration,start_fraction,endpoint):
        if type(path).__name__!='BlendedJointPath' or not hasattr(path,'spline'):
            raise ValueError('Only original piecewise-polynomial BlendedJointPath supported')
        self.path=path;self.full_duration=float(full_duration);self.start=float(start_fraction)
        self.duration=(1-self.start)*self.full_duration
        original_end=path.evaluate(1,self.full_duration)[0]
        delta=np.asarray(endpoint)-original_end;zero=np.zeros_like(delta)
        self.correction=FixedDurationQuintic(zero,zero,zero,delta,self.duration)
        self.reference_bounds={name:np.asarray(path.reference_bounds[name])*(path.duration/self.full_duration)**order+self.correction.reference_bounds[name] for order,name in enumerate(('velocity','acceleration','jerk'),1)}
        # Exact extrema of the ORIGINAL suffix on each polynomial piece; add
        # monotone quintic correction interval conservatively (not samples).
        low=np.full_like(delta,np.inf);high=np.full_like(delta,-np.inf)
        self.extremum_times=set(self.correction.extremum_times)
        for i,(left,right) in enumerate(zip(path.spline.x[:-1],path.spline.x[1:])):
            if right<self.start:continue
            a=max(left,self.start)-left;b=right-left
            for joint in range(len(delta)):
                coef=path.spline.c[:,i,joint]
                roots=np.roots(np.polyder(coef));times=[a,b]+[float(z.real) for z in roots if abs(z.imag)<1e-9 and a<z.real<b]
                values=np.polyval(coef,times);low[joint]=min(low[joint],min(values));high[joint]=max(high[joint],max(values))
                self.extremum_times.update((left+t-self.start)/(1-self.start) for t in times)
        self.extrema={0:(low+np.minimum(delta,0),high+np.maximum(delta,0))}
    def evaluate(self,progress,duration=None):
        if duration is not None and abs(duration-self.duration)>1e-10:raise ValueError('Additive suffix cannot be retimed')
        u=float(np.clip(progress,0,1));base=self.path.evaluate(self.start+(1-self.start)*u,self.full_duration);correction=self.correction.evaluate(u)
        return tuple(a+b for a,b in zip(base,correction))
