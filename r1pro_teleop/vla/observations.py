"""Optional policy-only renders. Native recording and camera poses stay intact."""
from __future__ import annotations
from math import gcd
import numpy as np
from .policy import PolicyError


def model_render_shape(native_shape, max_dim):
    """Return HWC with exactly the native aspect ratio, bounded by max_dim."""
    if type(max_dim) is not int or max_dim < 0:
        raise PolicyError('vla_invalid_model_render_max_dim')
    if len(native_shape) != 3 or native_shape[2] != 3 or any(type(x) is not int or x <= 0 for x in native_shape):
        raise PolicyError('vla_invalid_native_camera_shape')
    h, w, _ = native_shape
    if max_dim == 0 or max(h, w) <= max_dim:
        return h, w, 3
    divisor = gcd(h, w)
    rh, rw = h // divisor, w // divisor
    scale = max_dim // max(rh, rw)
    if scale < 1:
        raise PolicyError('vla_model_render_bound_too_small')
    return rh * scale, rw * scale, 3


def render_model_observation(sim, camera, max_dim=0, *, renderer_factory=None, render_flags=None):
    """Dedicated same-FOV renderer cached in the simulation's existing close owner.

    Zero follows the original native API exactly. Reduced observations require a
    rendering-enabled native camera simulation; they cannot silently create a
    render context for a render=False runtime or guess unknown camera geometry.
    """
    if type(max_dim) is not int or max_dim < 0:
        raise PolicyError('vla_invalid_model_render_max_dim')
    if max_dim == 0:
        return sim.image(camera)
    cache = getattr(sim, '_camera_renderers', None)
    shapes = getattr(sim, 'camera_shapes', {})
    if not isinstance(cache, dict):
        raise PolicyError('vla_model_render_requires_native_renderer')
    if camera not in shapes:
        raise PolicyError('vla_unknown_native_model_camera')
    h, w, _ = model_render_shape(shapes[camera], max_dim)
    if renderer_factory is None or render_flags is None:
        import mujoco
        renderer_factory = renderer_factory or mujoco.Renderer
        render_flags = render_flags or (mujoco.mjtRndFlag.mjRND_SHADOW, mujoco.mjtRndFlag.mjRND_REFLECTION)
    key = ('vla_model', camera, h, w)
    renderer = cache.get(key)
    if renderer is None:
        renderer = renderer_factory(sim.model, height=h, width=w)
        cache[key] = renderer
    renderer.update_scene(sim.data, camera=camera, scene_option=sim.options)
    for flag in render_flags:
        renderer.scene.flags[flag] = False
    image = renderer.render()
    if image.shape != (h, w, 3) or image.dtype != np.uint8:
        raise PolicyError('vla_invalid_model_render_rgb')
    return image.copy()
