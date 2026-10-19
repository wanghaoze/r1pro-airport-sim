"""Render saved observations at native camera sizes for diagnosis, without editing them."""
from pathlib import Path
import json
import h5py
import numpy as np

from .common import read, assert_campaign
from ..airport_fsm.contracts import atomic_json


def scene_view(root, trace, output, frame=-1):
    from PIL import Image
    from ..airport_fsm.registry import config_for
    from ..airport_fsm.runtime import Runtime
    root, trace, output = Path(root), Path(trace), Path(output)
    assert_campaign(root)
    trace.resolve().relative_to((root / "experiments").resolve())
    output.mkdir(parents=True, exist_ok=False)
    with h5py.File(trace) as f:
        meta = json.loads(f.attrs["metadata_json"])
        n = len(f["qpos"])
        index = frame if frame >= 0 else n + frame
        if not 0 <= index < n:
            raise ValueError("diagnostic_frame_out_of_range")
        directory = root / "collection/scenes" / meta["scene_id"]
        r = Runtime(read(directory / "scene.json"), directory / "mobile.xml",
                    config_for(root / "collection"), render=True)
        try:
            r.mj.mj_setState(r.m, r.d, f["integration_state"][index], r.integration_spec)
            r.mj.mj_forward(r.m, r.d)
            views = []
            for camera in r.sim.camera_shapes:
                path = output / (camera + ".png")
                pixels = r.sim.image(camera)
                Image.fromarray(pixels).save(path)
                views.append({"camera": camera, "path": str(path.resolve()), "shape": list(pixels.shape)})
            report = {"frame": index, "trace": str(trace.resolve()), "views": views,
                      "diagnostic_snapshot_only": True, "continuous_replay_verified": False}
            atomic_json(output / "view.json", report)
            return report
        finally:
            r.close()
