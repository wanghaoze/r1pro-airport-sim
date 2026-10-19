import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import numpy as np
from diagnostic_additive_certificate import certified_range,CertifiedAdditiveSuffix
from diagnostic_additive_suffix import AdditiveSuffix
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath

def test_polynomial_certificate_resolves_interior_peak_and_fails_closed():
 lo,hi,n,reserve=certified_range([0,4,-4],1.0001)
 assert lo<=0 and 1<=hi<=1.0001 and n>1 and reserve>0
 lo,hi,_,_=certified_range([0,4,-4],.9)
 assert hi>.9

def test_certificate_does_not_change_candidate_and_encloses_joint_derivatives():
 p=BlendedJointPath([[0.,.2],[.3,.1],[.5,.4]],np.ones(2),np.ones(2)*2,np.ones(2)*10)
 T=p.duration*1.1;end=p.evaluate(1,T)[0]+[.02,-.01];caps=(np.ones(2),np.ones(2)*2,np.ones(2)*10)
 exact=CertifiedAdditiveSuffix(p,T,.4,end,caps);old=AdditiveSuffix(p,T,.4,end)
 for u in np.linspace(0,1,701):
  for a,b in zip(exact.evaluate(u),old.evaluate(u)):np.testing.assert_array_equal(a,b)
  lo,hi=exact.extrema[0];assert np.all(exact.evaluate(u)[0]>=lo) and np.all(exact.evaluate(u)[0]<=hi)
  for order,name in enumerate(('velocity','acceleration','jerk'),1):assert np.all(abs(exact.evaluate(u)[order])<=exact.reference_bounds[name])
 assert not exact.certificate['grid_sampling_used']
