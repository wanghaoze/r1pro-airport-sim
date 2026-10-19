"""Strict conservative Bernstein certificates for the SAME additive candidate."""
import math
from fractions import Fraction
import numpy as np
from diagnostic_additive_suffix import AdditiveSuffix


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


def certified_range(power,cap=None,max_depth=18):
    """Exact rational Bernstein convex hull plus floating evaluation reserve.

    All polynomial conversion and subdivision arithmetic is exact for the
    supplied IEEE coefficients. Unresolved intervals fail certification.
    """
    power=list(map(exact,power))
    reserve=exact(1e-10)*(1+sum(map(abs,power)))
    cap=None if cap is None else exact(cap)
    stack=[(bernstein_coefficients(power),0)];lower=None;upper=None;nodes=0
    while stack:
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


class CertifiedAdditiveSuffix(AdditiveSuffix):
    def __init__(self,path,full_duration,start_fraction,endpoint,caps):
        super().__init__(path,full_duration,start_fraction,endpoint)
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
                original=compose_affine(path.spline.c[:,i,joint][::-1],a-exact(left),width)
                correction=compose_affine(self.correction.coef[:,joint],(a-exact(self.start))/remaining,width/remaining)
                count=max(len(original),len(correction))
                combined=[(original[k] if k<len(original) else 0)+(correction[k] if k<len(correction) else 0) for k in range(count)]
                b=bernstein_coefficients(combined)
                pad=exact(1e-10)*(1+sum(map(abs,combined)))
                position_low[joint]=min(position_low[joint],np.nextafter(float(min(b)-pad),-np.inf))
                position_high[joint]=max(position_high[joint],np.nextafter(float(max(b)+pad),np.inf))
                for order,(name,cap) in enumerate(zip(('velocity','acceleration','jerk'),caps),1):
                    power=[combined[k]*Fraction(math.factorial(k),math.factorial(k-order))/piece_seconds**order for k in range(order,len(combined))]
                    lo,hi,count,reserve=certified_range(power,float(cap[joint]))
                    bounds[name][joint]=max(bounds[name][joint],abs(lo),abs(hi));nodes+=count;largest_reserve=max(largest_reserve,reserve)
        self.reference_bounds=bounds
        self.extrema={0:(position_low,position_high)}
        self.certificate=dict(method='exact_rational_combined_piecewise_polynomial_bernstein_subdivision',pieces=pieces,nodes=nodes,max_depth=18,largest_float_reserve=largest_reserve,grid_sampling_used=False)
