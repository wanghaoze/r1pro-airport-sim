import unittest
from types import SimpleNamespace
from pathlib import Path
import sys
import numpy as np
from diagnostic_force_suffix import ForceWindow,checked_replacement

class ForceWindowTest(unittest.TestCase):
    def initialize(self):
        window=ForceWindow(.8)
        for i in range(5):
            window.append([(12.,.8,4)]*25,.002)
            if i<4:self.assertIsNone(window.fref)
        self.assertAlmostEqual(window.fref,12)
        return window
    def test_units_sign_and_causal_window(self):
        w=self.initialize()
        w.append([(8.,.8,4)]*25,.002);w.append([(8.,.8,4)]*25,.002)
        request,reason=w.request();self.assertIsNone(reason)
        self.assertAlmostEqual(request['offset_m'],-.0001)
        self.assertAlmostEqual(w.fref,12)
    def test_upper_lower_caps_and_height_gate(self):
        w=self.initialize()
        for _ in range(2):w.append([(0.,.8,0)]*25,.002)
        self.assertAlmostEqual(w.request()[0]['offset_m'],-.00015)
        for _ in range(2):w.append([(30.,.8,4)]*25,.002)
        self.assertAlmostEqual(w.request()[0]['offset_m'],.00015)
        for _ in range(2):w.append([(0.,.79994,0)]*25,.002)
        self.assertEqual(w.request(),(None,'already_compressed_height_gate'))
    def test_zero_gain_keeps_observation_timing_but_has_no_normal_offset(self):
        w=ForceWindow(.8,force_gain=0.)
        for _ in range(5):w.append([(12.,.8,4)]*25,.002)
        for _ in range(2):w.append([(0.,.79994,0)]*25,.002)
        request,reason=w.request()
        self.assertIsNone(reason);self.assertEqual(request['offset_m'],0.)
        self.assertAlmostEqual(w.fref,12.)
    def test_incomplete_or_unsupported_reference_never_uses_future(self):
        w=ForceWindow(.8)
        self.assertEqual(w.request(),(None,'reference_not_initialized'))
        for _ in range(5):w.append([(12.,.8,0)]*25,.002)
        for _ in range(10):w.append([(12.,.8,4)]*25,.002)
        self.assertIsNone(w.fref)
    def test_rejection_keeps_latest_accepted_suffix(self):
        original=object();accepted=object()
        current,reason=checked_replacement(original,lambda:(accepted,None))
        self.assertIs(current,accepted)
        current,reason=checked_replacement(current,lambda:(None,{'reason':'normal_band'}))
        self.assertIs(current,accepted)
        def invalid():raise ValueError('bad endpoint')
        current,reason=checked_replacement(current,invalid)
        self.assertIs(current,accepted)
    def test_two_tables_opposite_geom_order_sum_real_upward_reactions(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from r1pro_teleop.airport_fsm.support_feedback import measure_support_force
        upward=np.array([[0,0,1],[1,0,0],[0,1,0]],float)
        downward=np.array([[0,0,-1],[1,0,0],[0,-1,0]],float)
        model=SimpleNamespace(nbody=4,geom_bodyid=np.array([0,2,1,3]))
        contacts=[SimpleNamespace(geom1=0,geom2=1,frame=upward.ravel()),
                  SimpleNamespace(geom1=1,geom2=2,frame=downward.ravel()),
                  SimpleNamespace(geom1=3,geom2=1,frame=upward.ravel())]
        data=SimpleNamespace(ncon=3,contact=contacts)
        def force(m,d,index,out):out[0]=[5.,7.,100.][index]
        result=measure_support_force(model,data,2,{0,1},contact_force=force)
        self.assertAlmostEqual(result.signed_normal_n,12.)
        self.assertEqual(result.pair_count,2)

if __name__=='__main__':unittest.main()
