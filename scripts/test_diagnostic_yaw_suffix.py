"""Standalone mathematical checks; no MuJoCo controller changes."""
import unittest
import numpy as np
from diagnostic_yaw_suffix import FixedDurationQuintic

class SuffixTest(unittest.TestCase):
    def test_c2_boundary_and_rest_endpoint(self):
        q=np.array([.1,-.2]);v=np.array([.3,-.4]);a=np.array([-.6,.2]);end=np.array([.7,.1])
        p=FixedDurationQuintic(q,v,a,end,1.25)
        for actual,expected in zip(p.evaluate(0)[:3],(q,v,a)):np.testing.assert_allclose(actual,expected,atol=1e-13)
        for actual,expected in zip(p.evaluate(1)[:3],(end,np.zeros(2),np.zeros(2))):np.testing.assert_allclose(actual,expected,atol=1e-12)

    def test_analytic_extrema_bound_dense_samples(self):
        p=FixedDurationQuintic([.1,.2],[1.,-.5],[2.,3.],[-.3,.4],1.25)
        values=np.array([p.evaluate(u) for u in np.linspace(0,1,10001)])
        for order in range(4):
            low,high=p.extrema[order]
            self.assertTrue(np.all(values[:,order]>=low-1e-12));self.assertTrue(np.all(values[:,order]<=high+1e-12))
            np.testing.assert_allclose(values[:,order].min(0),low,atol=1e-6)
            np.testing.assert_allclose(values[:,order].max(0),high,atol=1e-6)

    def test_no_silent_retiming(self):
        p=FixedDurationQuintic([0],[0],[0],[1],1)
        with self.assertRaises(ValueError):p.evaluate(.5,2)

if __name__=='__main__':unittest.main()
