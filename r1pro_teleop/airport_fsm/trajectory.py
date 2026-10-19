"""C2 multi-waypoint motion with conservative analytical derivative bounds."""
from __future__ import annotations
import numpy as np
from scipy.interpolate import CubicSpline
from .contracts import quintic


def entry_limit_envelope(points, low, high, margin):
    """Permit a physical starting state to retreat into the planning margin.

    All subsequent knots must satisfy the margin. This is not permission to
    command further toward a hard stop from a measured near-limit start.
    """
    points=np.asarray(points,float);low=np.asarray(low,float);high=np.asarray(high,float)
    if np.any(points[0]<low-1e-6) or np.any(points[0]>high+1e-6):
        raise ValueError('Starting reference outside physical joint limits')
    if np.any(points[1:]<low+margin-1e-6) or np.any(points[1:]>high-margin+1e-6):
        raise ValueError('Subsequent reference outside planning joint margin')
    return np.minimum(points[0],low+margin)-1e-6,np.maximum(points[0],high-margin)+1e-6


class BlendedJointPath:
    """C2 quintic Hermite path, no joint overshoot and no mandatory knot stops.

    Interior slopes are shared by adjacent pieces; accelerations are zero at
    knots. Bernstein control points stay inside each joint's endpoint interval.
    Exact polynomial derivative extrema determine one uniform time scale.
    Collision and payload constraints must still be checked by the caller.
    """
    def __init__(self, points, velocity, acceleration, jerk, minimum_seconds=.1):
        from scipy.interpolate import BPoly, PPoly
        p = np.asarray(points, dtype=float)
        if p.ndim != 2 or len(p) < 2 or not np.isfinite(p).all():
            raise ValueError('Need finite joint waypoints')
        p = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-9]]
        if len(p) == 1:
            p = np.r_[p, p]
        limits = [np.broadcast_to(np.asarray(x, float), (p.shape[1],)) for x in (velocity, acceleration, jerk)]
        if any(not np.isfinite(x).all() or np.any(x <= 0) for x in limits):
            raise ValueError('Finite positive limits required')
        # Balance short intervals by acceleration/jerk as well as velocity.
        # Velocity-only parameterization gives tiny intervals near an IK plateau,
        # whose curvature then slows the ENTIRE path by orders of magnitude.
        delta=abs(np.diff(p,axis=0))
        widths=np.maximum.reduce([
            np.max(1.875*delta/limits[0],axis=1),
            np.max(np.sqrt((10/np.sqrt(3))*delta/limits[1]),axis=1),
            np.max(np.cbrt(60*delta/limits[2]),axis=1),
            np.full(len(p)-1,1e-4)])
        u = np.r_[0., np.cumsum(widths)]; u /= u[-1]
        slopes = np.diff(p, axis=0)/np.diff(u)[:, None]
        tangent = np.zeros_like(p)
        same = slopes[:-1]*slopes[1:] > 0
        tangent[1:-1] = np.where(same, np.sign(slopes[:-1])*np.minimum(abs(slopes[:-1]), abs(slopes[1:])), 0.)
        self.points, self.knots = p, u
        self.spline = PPoly.from_bernstein_basis(BPoly.from_derivatives(
            u, [[q, v, np.zeros_like(q)] for q, v in zip(p, tangent)]))
        maxima = []
        for order in (1, 2, 3):
            derivative = self.spline.derivative(order)
            bound = np.zeros(p.shape[1])
            for i, width in enumerate(np.diff(u)):
                for joint in range(p.shape[1]):
                    coef = derivative.c[:, i, joint]
                    roots = np.roots(np.polyder(coef))
                    candidates = [0., width] + [float(z.real) for z in roots if abs(z.imag) < 1e-9 and 0 < z.real < width]
                    bound[joint] = max(bound[joint], float(np.max(abs(np.polyval(coef, candidates)))))
            maxima.append(bound)
        self.duration = float(max(minimum_seconds, *(np.max(b/cap)**(1/order) for order, (b, cap) in enumerate(zip(maxima, limits), 1))))*1.000001
        self.reference_bounds = {name: b/self.duration**order for order, (name, b) in enumerate(zip(('velocity','acceleration','jerk'), maxima), 1)}

    def evaluate(self, progress, duration=None):
        T = self.duration if duration is None else float(duration)
        u = np.clip(progress, 0., 1.)
        return tuple(self.spline(u, order)/T**order for order in range(4))


class TimedJointPath:
    def __init__(self, points, velocity, acceleration, jerk, minimum_seconds=.1):
        p = np.asarray(points, float)
        if p.ndim != 2 or len(p) < 2 or not np.isfinite(p).all():
            raise ValueError('Need two or more finite joint vectors')
        d = np.linalg.norm(np.diff(p, axis=0), axis=1)
        # Keep stationary beginning/end as one configuration rather than tiny
        # artificial knots that would amplify curvature and slow the path.
        keep = np.r_[True, d > 1e-9]
        p = p[keep]
        if len(p) == 1:
            p = np.r_[p, p]
        distances = np.maximum(np.linalg.norm(np.diff(p, axis=0), axis=1), 1e-9)
        u = np.r_[0., np.cumsum(distances)]; u /= u[-1]
        self.spline = CubicSpline(u, p, axis=0)
        self.points = p
        self.knots = u
        # Coefficients describe q(s) = c0*x^3+c1*x^2+c2*x+c3 on each piece.
        coefficients = self.spline.c
        b1 = np.zeros(p.shape[1]); b2 = b1.copy(); b3 = b1.copy()
        for i, width in enumerate(np.diff(u)):
            a, b, c, _ = coefficients[:, i]
            b1 = np.maximum(b1, np.maximum(np.abs(c), np.abs(3*a*width**2+2*b*width+c)))
            nonzero = np.abs(a) > 1e-14
            vertex = np.divide(-b, 3*a, out=np.zeros_like(a), where=nonzero)
            inside = nonzero & (vertex > 0) & (vertex < width)
            b1 = np.maximum(b1, np.where(inside, np.abs(3*a*vertex**2+2*b*vertex+c), 0))
            b2 = np.maximum(b2, np.maximum(np.abs(2*b), np.abs(6*a*width+2*b)))
            b3 = np.maximum(b3, np.abs(6*a))
        v, a, j = np.broadcast_arrays(velocity, acceleration, jerk)
        self.path_derivative_bounds = (b1, b2, b3)
        if np.any(v <= 0) or np.any(a <= 0) or np.any(j <= 0) or not np.isfinite(np.r_[v, a, j]).all():
            raise ValueError('Finite positive limits required')
        s1, s2, s3 = 1.875, 10/np.sqrt(3), 60.
        self.duration = float(max(minimum_seconds, np.max(b1*s1/v),
                                  np.max(np.sqrt((b2*s1**2+b1*s2)/a)),
                                  np.max(np.cbrt((b3*s1**3+3*b2*s1*s2+b1*s3)/j))))
        self.reference_bounds = {'velocity': b1*s1/self.duration,
                                 'acceleration': (b2*s1**2+b1*s2)/self.duration**2,
                                 'jerk': (b3*s1**3+3*b2*s1*s2+b1*s3)/self.duration**3}

    def evaluate(self, progress, duration=None):
        T = self.duration if duration is None else float(duration)
        u = np.clip(progress, 0., 1.)
        s = quintic(u)
        s1 = 30*u**2-60*u**3+30*u**4
        s2 = 60*u-180*u**2+120*u**3
        s3 = 60-360*u+360*u**2
        q = self.spline(s)
        if np.ndim(s1):
            s1, s2, s3 = s1[...,None], s2[...,None], s3[...,None]
        dq, ddq, dddq = self.spline(s, 1), self.spline(s, 2), self.spline(s, 3)
        return q, dq*s1/T, (ddq*s1*s1+dq*s2)/T**2, (dddq*s1**3+3*ddq*s1*s2+dq*s3)/T**3


class CruiseJointPath(TimedJointPath):
    """Bounded C2 speed ramps with a cruise interval on the unchanged path.

    minimum_seconds is the unit-progress duration at the allowed path speed.
    Each ramp candidate accounts for its peak progress speed explicitly.
    Joint derivative bounds are analytical, including path curvature terms.
    """
    def __init__(self, points, velocity, acceleration, jerk, minimum_seconds=.1):
        super().__init__(points, velocity, acceleration, jerk, minimum_seconds)
        b1,b2,b3=self.path_derivative_bounds
        v,a,j=np.broadcast_arrays(velocity,acceleration,jerk)
        choices=[]
        for ramp in (.08,.1,.15,.2,.25,.3,.4):
            peak=1/(1-ramp);acc=1.5*peak/ramp;jrk=6*peak/ramp**2
            bounds=(b1*peak,b2*peak**2+b1*acc,
                    b3*peak**3+3*b2*peak*acc+b1*jrk)
            duration=float(max(minimum_seconds*peak,np.max(bounds[0]/v),
                np.max(np.sqrt(bounds[1]/a)),np.max(np.cbrt(bounds[2]/j))))*1.000001
            choices.append((duration,ramp,bounds))
        self.duration,self.ramp,bounds=min(choices,key=lambda x:x[0])
        self.reference_bounds={k:b/self.duration**n for n,(k,b) in enumerate(
            zip(('velocity','acceleration','jerk'),bounds),1)}

    def evaluate(self, progress, duration=None):
        T=self.duration if duration is None else float(duration)
        u=np.clip(np.asarray(progress),0.,1.);r=self.ramp;peak=1/(1-r)
        w=np.clip(np.minimum(u,1-u)/r,0.,1.)
        ramp_s=peak*r*(w**3-.5*w**4)
        s=np.where(u<r,ramp_s,np.where(u>1-r,1-ramp_s,peak*(u-.5*r)))
        s1=np.where((u<r)|(u>1-r),peak*(3*w*w-2*w**3),peak)
        s2=np.where(u<r,1.,np.where(u>1-r,-1.,0.))*peak/r*(6*w-6*w*w)
        s3=np.where((u<r)|(u>1-r),peak/r**2*(6-12*w),0.)
        if u.ndim:s1,s2,s3=s1[...,None],s2[...,None],s3[...,None]
        q=self.spline(s);dq=self.spline(s,1);ddq=self.spline(s,2);dddq=self.spline(s,3)
        return q,dq*s1/T,(ddq*s1*s1+dq*s2)/T**2,(dddq*s1**3+3*ddq*s1*s2+dq*s3)/T**3
