import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import numpy as np
from diagnostic_additive_suffix import AdditiveSuffix
from r1pro_teleop.airport_fsm.trajectory import BlendedJointPath

def test_additive_suffix_keeps_boundary_and_original_shape():
 p=BlendedJointPath([[0,.2],[.3,.1],[.5,.4]],np.ones(2),np.ones(2)*2,np.ones(2)*10)
 duration=p.duration*1.1;start=.4;end=p.evaluate(1,duration)[0]+[.02,-.01]
 s=AdditiveSuffix(p,duration,start,end)
 for order in range(3):np.testing.assert_allclose(s.evaluate(0)[order],p.evaluate(start,duration)[order],atol=1e-12)
 np.testing.assert_allclose(s.evaluate(1)[0],end,atol=1e-12)
 for order in [1,2]:np.testing.assert_allclose(s.evaluate(1)[order],np.zeros(2),atol=1e-11)
 for u in np.linspace(0,1,701):
  values=s.evaluate(u);assert np.all(values[0]>=s.extrema[0][0]-1e-12) and np.all(values[0]<=s.extrema[0][1]+1e-12)
  for order,name in enumerate(('velocity','acceleration','jerk'),1):assert np.all(abs(values[order])<=s.reference_bounds[name]+1e-10)
 zero=AdditiveSuffix(p,duration,start,p.evaluate(1,duration)[0])
 for u in [.1,.3,.7]:
  for x,y in zip(zero.evaluate(u),p.evaluate(start+(1-start)*u,duration)):np.testing.assert_allclose(x,y,atol=1e-12)
