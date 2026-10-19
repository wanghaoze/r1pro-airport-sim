import pytest
from scripts.probe_single_tray_front_workspace import candidates


def test_lateral_candidates_are_relative_to_tray_and_no_duplicates():
    rows=candidates([.1,.2],[-.24],[-.08,0,.08])
    assert len(rows)==6
    assert rows[1]==dict(robot_x=.1,robot_y=-.24,tray_y=-.24)
    assert rows[0]['robot_y']==pytest.approx(-.32)


@pytest.mark.parametrize('xs', [[],[float('nan')],[float('inf')]])
def test_bad_grid_rejected(xs):
    with pytest.raises(ValueError):candidates(xs,[-.24],[0])
