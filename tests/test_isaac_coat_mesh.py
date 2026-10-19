import importlib.util
from pathlib import Path
import pytest


def test_native_coat_source_mesh_is_not_replaced_by_box(tmp_path):
    spec = importlib.util.spec_from_file_location('coat',
        Path(__file__).resolve().parents[1] / 'scripts/isaacsim_deformable_coat.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    path = tmp_path / 'coat.obj'
    path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
    points, triangles = module.read_obj(path)
    assert len(points) == 3 and triangles == [[0, 1, 2]]
    path.write_text('v 0 0 0\nf 1 2 3\n')
    with pytest.raises(ValueError, match='invalid_coat_mesh'):
        module.read_obj(path)
