from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.vla.observations import model_render_shape, render_model_observation
from r1pro_teleop.vla.policy import PolicyError
from r1pro_teleop.airport_fsm.contracts import Config


def test_exact_native_aspect_without_fov_crop():
    assert model_render_shape((1536,1920,3),320)==(256,320,3)
    assert model_render_shape((720,1280,3),320)==(180,320,3)
    assert model_render_shape((1536,1920,3),224)==(176,220,3)
    assert model_render_shape((720,1280,3),0)==(720,1280,3)


@pytest.mark.parametrize('value',[-1,True,3.5])
def test_invalid_bound_rejected(value):
    with pytest.raises(PolicyError):model_render_shape((720,1280,3),value)
    with pytest.raises(ValueError):Config(vla_model_render_max_dim=value).validate()


def test_native_default_delegates_original_api():
    value=object()
    sim=SimpleNamespace(image=lambda name:value)
    assert render_model_observation(sim,'head_left') is value


def test_low_render_requires_known_enabled_native_camera():
    with pytest.raises(PolicyError):render_model_observation(SimpleNamespace(camera_shapes={'head_left':(1536,1920,3)}),'head_left',320)
    with pytest.raises(PolicyError):render_model_observation(SimpleNamespace(_camera_renderers={},camera_shapes={}), 'invented',320)


def test_cache_is_distinct_owned_and_does_not_alias_frame():
    class Renderer:
        def __init__(self,model,*,height,width):
            self.scene=SimpleNamespace(flags={});self.pixels=np.ones((height,width,3),dtype=np.uint8);self.calls=[]
        def update_scene(self,data,**kw):self.calls.append((data,kw))
        def render(self):return self.pixels
    native=object()
    sim=SimpleNamespace(_camera_renderers={'head_left':native},camera_shapes={'head_left':(1536,1920,3)},model=object(),data=object(),options=object())
    first=render_model_observation(sim,'head_left',320,renderer_factory=Renderer,render_flags=(0,1))
    second=render_model_observation(sim,'head_left',320,renderer_factory=Renderer,render_flags=(0,1))
    assert sim._camera_renderers['head_left'] is native
    renderer=sim._camera_renderers[('vla_model','head_left',256,320)]
    assert len(renderer.calls)==2 and renderer.scene.flags=={0:False,1:False}
    assert renderer.calls[0][1]=={'camera':'head_left','scene_option':sim.options}
    first[:]=0
    assert second.all() and renderer.pixels.all()
    assert len(sim._camera_renderers)==2  # existing simulation.close owns both


def test_too_small_aspect_bound_is_rejected():
    with pytest.raises(PolicyError):model_render_shape((720,1280,3),8)
