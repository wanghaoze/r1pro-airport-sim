"""Optional additive yaw suffix with exact-rational polynomial certificates."""
import math
from fractions import Fraction
import numpy as np


def exact(x):
    return x if isinstance(x,Fraction) else Fraction(float(x))


def compose_affine(coeff,offset,scale):
    offset,scale=exact(offset),exact(scale)
    result=[Fraction(0)]*len(coeff)
    for k,c in enumerate(coeff):
        for j in range(k+1):
            result[j]+=exact(c)*math.comb(k,j)*offset**(k-j)*scale**j
    return result


def bernstein_coefficients(power):
    power=list(map(exact,power));n=len(power)-1
    return [sum((power[k]*Fraction(math.comb(i,k),math.comb(n,k)) for k in range(i+1)),Fraction(0)) for i in range(n+1)]


def subdivide(coefficients):
    levels=[list(coefficients)]
    while len(levels[-1])>1:levels.append([(a+b)/2 for a,b in zip(levels[-1][:-1],levels[-1][1:])])
    return [level[0] for level in levels],[level[-1] for level in levels[::-1]]


def certified_range(power,cap=None,max_depth=18,*,max_nodes=8192,evaluation_scale=None):
    """Exact rational Bernstein convex hull plus floating evaluation reserve.

    All polynomial conversion and subdivision arithmetic is exact for the
    supplied IEEE coefficients. Unresolved intervals fail certification.
    """
    power=list(map(exact,power))
    if not isinstance(max_nodes,int) or isinstance(max_nodes,bool) or max_nodes<1:
        raise ValueError('Additive certificate node budget exhausted')
    source_scale=sum(map(abs,power)) if evaluation_scale is None else exact(evaluation_scale)
    reserve=exact(1e-10)*(1+max(sum(map(abs,power)),source_scale))
    cap=None if cap is None else exact(cap)
    stack=[(bernstein_coefficients(power),0)];lower=None;upper=None;nodes=0
    while stack:
        if nodes>=max_nodes:raise ValueError('Additive certificate node budget exhausted')
        b,depth=stack.pop();nodes+=1
        lo=min(b)-reserve;hi=max(b)+reserve
        certified=cap is not None and lo>=-cap and hi<=cap
        outside=cap is not None and (lo>cap or hi<-cap)
        if certified or outside or depth>=max_depth or hi-lo<=max(exact(1e-8),reserve*4):
            lower=lo if lower is None else min(lower,lo)
            upper=hi if upper is None else max(upper,hi)
        else:
            left,right=subdivide(b);stack.extend([(left,depth+1),(right,depth+1)])
    # Outward rounding when converting the rational enclosure back to floats.
    return np.nextafter(float(lower),-np.inf),np.nextafter(float(upper),np.inf),nodes,float(reserve)


class AdditiveYawSuffix:
    def __init__(self,path,full_duration,start_fraction,endpoint,caps,*,max_certificate_nodes=8192):
        from .yaw_feedback import FixedDurationQuintic
        from .trajectory import BlendedJointPath
        if type(path) is not BlendedJointPath:
            raise ValueError('Unsupported additive reference path type')
        if not isinstance(max_certificate_nodes,int) or isinstance(max_certificate_nodes,bool) or max_certificate_nodes<1:
            raise ValueError('Positive certificate node budget required')
        self.path=path;self.full_duration=float(full_duration);self.start=float(start_fraction)
        endpoint=np.asarray(endpoint,float)
        if not np.isfinite(self.full_duration) or self.full_duration<=0 or not 0<=self.start<1:
            raise ValueError('Invalid additive suffix timing')
        if endpoint.ndim!=1 or not np.isfinite(endpoint).all():raise ValueError('Finite endpoint required')
        if any(np.shape(cap)!=endpoint.shape or not np.isfinite(cap).all() or np.any(np.asarray(cap)<=0) for cap in caps):
            raise ValueError('Finite positive derivative caps required')
        if not np.isfinite(path.spline.c).all() or not np.isfinite(path.spline.x).all():raise ValueError('Nonfinite reference polynomial')
        self.duration=(1-self.start)*self.full_duration
        original_end=path.evaluate(1,self.full_duration)[0]
        delta=endpoint-original_end;zero=np.zeros_like(delta)
        self.correction=FixedDurationQuintic(zero,zero,zero,delta,self.duration)
        self.extremum_times=set(self.correction.extremum_times)
        # Original BlendedJointPath is piecewise quintic in global progress.
        # Restrict each piece to the remaining interval and express BOTH terms
        # in the same w in [0,1], then differentiate the combined polynomial.
        bounds={name:np.zeros_like(endpoint) for name in ('velocity','acceleration','jerk')}
        nodes=0;largest_reserve=0.;pieces=0
        position_low=np.full_like(endpoint,np.inf);position_high=np.full_like(endpoint,-np.inf)
        for i,(left,right) in enumerate(zip(path.spline.x[:-1],path.spline.x[1:])):
            if right<=self.start:continue
            a=max(exact(left),exact(self.start));width=exact(right)-a;pieces+=1
            remaining=1-exact(self.start)
            piece_seconds=width*exact(self.full_duration)
            for joint in range(len(endpoint)):
                # Critical locations supplement the unchanged inverse-dynamics
                # audit; they are not used as a derivative certificate.
                derivative=np.polyder(path.spline.c[:,i,joint])
                roots=np.roots(derivative)
                self.extremum_times.update(float((exact(left)+exact(z.real)-exact(self.start))/(1-exact(self.start)))
                    for z in roots if abs(z.imag)<1e-9 and float(a-exact(left))<z.real<float(exact(right)-exact(left)))
                self.extremum_times.update([float((a-exact(self.start))/remaining),float((exact(right)-exact(self.start))/remaining)])
                original=compose_affine(path.spline.c[:,i,joint][::-1],a-exact(left),width)
                correction=compose_affine(self.correction.coef[:,joint],(a-exact(self.start))/remaining,width/remaining)
                count=max(len(original),len(correction))
                combined=[(original[k] if k<len(original) else 0)+(correction[k] if k<len(correction) else 0) for k in range(count)]
                b=bernstein_coefficients(combined)
                pad=exact(1e-10)*(1+sum(map(abs,original))+sum(map(abs,correction)))
                position_low[joint]=min(position_low[joint],np.nextafter(float(min(b)-pad),-np.inf))
                position_high[joint]=max(position_high[joint],np.nextafter(float(max(b)+pad),np.inf))
                for order,(name,cap) in enumerate(zip(('velocity','acceleration','jerk'),caps),1):
                    power=[combined[k]*Fraction(math.factorial(k),math.factorial(k-order))/piece_seconds**order for k in range(order,len(combined))]
                    source_scale=sum(abs(coeff[k]*Fraction(math.factorial(k),math.factorial(k-order))/piece_seconds**order)
                        for coeff in (original,correction) for k in range(order,len(coeff)))
                    lo,hi,count,reserve=certified_range(power,float(cap[joint]),max_nodes=max_certificate_nodes-nodes,evaluation_scale=source_scale)
                    bounds[name][joint]=max(bounds[name][joint],abs(lo),abs(hi));nodes+=count;largest_reserve=max(largest_reserve,reserve)
        self.reference_bounds=bounds
        self.extrema={0:(position_low,position_high)}
        self.certificate=dict(method='exact_rational_combined_piecewise_polynomial_bernstein_subdivision',pieces=pieces,nodes=nodes,max_depth=18,max_nodes=max_certificate_nodes,largest_float_reserve=largest_reserve,grid_sampling_used=False)


    def evaluate(self,progress,duration=None):
        if duration is not None and abs(float(duration)-self.duration)>1e-10:
            raise ValueError('Additive suffix cannot be retimed')
        u=np.clip(np.asarray(progress,float),0,1)
        base=self.path.evaluate(self.start+(1-self.start)*u,self.full_duration)
        correction=self.correction.evaluate(u)
        return tuple(a+b for a,b in zip(base,correction))
