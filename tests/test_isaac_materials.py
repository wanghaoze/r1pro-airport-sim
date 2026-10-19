import importlib.util
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest


def test_source_nominal_friction_is_not_an_arbitrary_boost():
    spec = importlib.util.spec_from_file_location('materials',
        Path(__file__).resolve().parents[1] / 'scripts/isaacsim_materials.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    model = SimpleNamespace(npair=0, ngeom=2, geom_contype=[1, 0], geom_conaffinity=[1, 0],
        geom_priority=[0, 0], geom_friction=np.array([[1.2, .005, .0001], [8, 0, 0]]),
        geom=lambda index: SimpleNamespace(name=['finger', 'visual'][index]))
    assert module.source_friction_plan(model) == {'finger': 1.2}
    model.geom_priority[0] = 1
    with pytest.raises(ValueError, match='priority'):
        module.source_friction_plan(model)
