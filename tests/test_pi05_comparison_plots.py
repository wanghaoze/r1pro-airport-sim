import importlib.util
from pathlib import Path
import numpy as np
import pytest

s=importlib.util.spec_from_file_location('comparison',Path(__file__).parents[1]/'scripts/compare_pi05_real_mixed_plots.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def test_valid_horizons_and_outliers_are_not_hidden():
    truth=np.zeros((2,3,16));pred=truth.copy();pred[0,0,0]=10;pred[1,2,:]=1e6
    mask=np.array([[True,True,True],[True,True,False]])
    error=m.per_dimension_mse(pred,truth,mask)
    assert error[0]==20
    assert np.all(error[1:]==0)


def test_channel_order_keeps_grippers_separate():
    row=np.arange(19)[m.ORDER]
    np.testing.assert_array_equal(row[:14],[*range(7),*range(8,15)])
    np.testing.assert_array_equal(row[-2:],[7,15])
    assert len(m.NAMES)==16
