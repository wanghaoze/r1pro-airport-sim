import importlib.util
from pathlib import Path


def test_inventory_resolves_nested_includes_and_flags_flex(tmp_path):
    spec = importlib.util.spec_from_file_location('scene_smoke',
        Path(__file__).resolve().parents[1] / 'scripts/isaacsim_scene_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'main.xml').write_text('<mujoco><include file="sub/body.xml"/></mujoco>')
    (tmp_path / 'sub/body.xml').write_text(
        '<mujoco><worldbody><body name="tray"/><flexcomp name="coat"/></worldbody></mujoco>')
    inventory = module.source_inventory(tmp_path / 'main.xml')
    assert len(inventory['files']) == 2
    assert inventory['tags']['flexcomp'] == 1
    assert inventory['names']['body'] == ['tray']


def test_import_copy_preserves_source_and_flex(tmp_path):
    spec = importlib.util.spec_from_file_location('scene_smoke',
        Path(__file__).resolve().parents[1] / 'scripts/isaacsim_scene_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'source.xml'
    raw = '<mujoco><option integrator="discrete"/><worldbody><flexcomp name="coat" file="coat.obj"/></worldbody></mujoco>'
    source.write_text(raw)
    output = tmp_path / 'out'
    output.mkdir()
    result = module.prepare_import_copy(source, output)
    assert source.read_text() == raw
    assert 'implicitfast' in result.read_text()
    assert 'flexcomp' in result.read_text()
    assert str(tmp_path / 'coat.obj') in result.read_text()
